"""The real pipeline: real database, parsing, embeddings and LangGraph. Only the LLM is faked,
so these runs spend nothing and stay exact. `astra.py evals` measures it with the real one."""

import json
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_user, role_url
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from kernel import explain, ml_client, registry, trust, web
from kernel.ai.gateway import Gateway
from kernel.ai.graphs import agent_thread_id, run_agent_graph
from kernel.ai.providers import LlmResponse
from kernel.db import global_session, tenant_session
from kernel.errors import Conflict, PermissionDenied, ProviderUnavailable, ValidationFailed
from kernel.explain.models import DecisionCounterfactual, DecisionRecord
from kernel.identity.models import Tenant
from kernel.trust.models import AuditEvent, Proposal
from packs.talent import api, service
from packs.talent.agents import cv_reader, ranking, rubric_builder
from packs.talent.agents.rubric_builder import normalized_weights
from packs.talent.evals.screening import clean_twin_pdf
from packs.talent.models import (
    Application,
    CandidateIdentity,
    CriterionOverride,
    CvDocument,
    ExtractedProfile,
    Job,
    RankingRun,
    Rubric,
    Score,
)
from packs.talent.seed import seed

ROOT = Path(__file__).resolve().parents[1]
WORLD = json.loads((ROOT / "data" / "world.json").read_text(encoding="utf-8"))
CV_DIR = ROOT / "data" / "demo" / "cvs"
LABELS = json.loads((ROOT / "data" / "demo" / "labels.json").read_text(encoding="utf-8"))
YEARS_LINE = re.compile(r"^(?P<line>.*?\b(?P<y>\d+) (?:years|ans).*)$", re.MULTILINE)
SKILL_WORDS = ["Python", "PostgreSQL", "FastAPI", "Docker", "Kubernetes", "OpenTelemetry", "Django"]


class FakeReader:
    """Behaves like a careful reader: only what the document states, quoted exactly."""

    def __init__(self, invent: bool = False):
        self.documents: list[str] = []
        self.invent = invent

    def complete(self, model, system, user, schema, max_tokens):
        properties = schema.get("properties", {})
        if "skills" in properties:
            self.documents.append(user)
            skills = []
            for match in YEARS_LINE.finditer(user):
                for word in SKILL_WORDS:
                    if word in match["line"]:
                        skills.append(
                            {
                                "name": word,
                                "years": float(match["y"]),
                                "evidence": {"quote": match["line"].strip()},
                            }
                        )
            if self.invent:
                skills.append(
                    {
                        "name": "Kubernetes",
                        "years": 9,
                        "evidence": {"quote": "9 years of Kubernetes"},
                    }
                )
            body = {"skills": skills, "highest_degree": None, "languages": []}
        elif "text" in properties:
            body = {"text": "Python contributes most here [E1]. Invented claim of 99 points [E1]."}
        else:
            raise AssertionError(f"Unexpected schema: {list(properties)}")
        return LlmResponse(json.dumps(body), 50, 20, "fake", model)


@pytest.fixture(autouse=True)
def worker_role(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", role_url("worker"))
    monkeypatch.setenv("LLM_FAST_MODEL", "fake")
    monkeypatch.setenv("LLM_STANDARD_MODEL", "fake")
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    with as_role("worker"):
        yield


@pytest.fixture
def job_id(tenant):
    with as_role("owner"), tenant_session(tenant) as session:
        seed(session, tenant, WORLD)
    with tenant_session(tenant) as session:
        return session.scalar(select(Job.id).where(Job.external_id == "JOB-BE-01"))


def gateway_with(reader) -> Gateway:
    return Gateway(lambda model: reader)


def add_and_read(tenant, job_id, reader, filename, data=None):
    data = data if data is not None else (CV_DIR / filename).read_bytes()
    with tenant_session(tenant) as session:
        cv = service.add_cv(session, tenant, job_id, filename, data)
    event = {"cv_id": str(cv.id), "job_id": str(job_id), "application_id": str(cv.application_id)}
    run = run_agent_graph(
        "cv_reader",
        "talent",
        cv_reader.build(),
        tenant,
        event=event,
        event_id=uuid4(),
        gateway=gateway_with(reader),
    )
    assert run.status == "succeeded", run.error
    return cv


def rank(tenant, job_id, reader):
    with tenant_session(tenant) as session:
        ranking_row = service.request_ranking(session, tenant, job_id)
    run = run_agent_graph(
        "ranking",
        "talent",
        ranking.build(),
        tenant,
        event={"ranking_id": str(ranking_row.id), "job_id": str(job_id)},
        event_id=uuid4(),
        gateway=gateway_with(reader),
    )
    assert run.status == "succeeded", run.error
    with tenant_session(tenant) as session:
        return session.get(RankingRun, ranking_row.id)


def scores_by_file(tenant, ranking_id):
    with tenant_session(tenant) as session:
        rows = session.execute(
            select(CvDocument.filename, Score)
            .join(Score, Score.application_id == CvDocument.application_id)
            .where(Score.ranking_id == ranking_id)
        ).all()
    return {filename: score for filename, score in rows}


def file_of(kind):
    return next(name for name, label in LABELS.items() if label["kind"] == kind)


def regular_files(relevance, count):
    names = [
        name
        for name, label in sorted(LABELS.items())
        if label["JOB-BE-01"] == relevance and label["kind"] == "regular"
    ]
    return names[:count]


def test_reader_stores_profile_and_identity_separately(tenant, job_id):
    reader = FakeReader()
    cv = add_and_read(tenant, job_id, reader, file_of("hero"))
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
        application = session.get(Application, cv.application_id)
        identity = session.scalar(
            select(CandidateIdentity).where(
                CandidateIdentity.candidate_id == application.candidate_id
            )
        )
        profile = session.scalar(select(ExtractedProfile).where(ExtractedProfile.cv_id == cv.id))
    assert stored.status == "ready"
    assert identity.name == "Yasmine Trabelsi"
    assert identity.email == "yasmine.trabelsi@mail.example.test"
    assert {c["name"] for c in profile.data["skills"]} >= {"Python", "FastAPI"}


def test_the_model_never_sees_identity(tenant, job_id):
    reader = FakeReader()
    add_and_read(tenant, job_id, reader, file_of("hero"))
    document = reader.documents[0]
    for secret in ("Yasmine", "Trabelsi", "mail.example.test", "+216"):
        assert secret not in document
    assert "Python" in document


def test_hidden_white_text_never_reaches_the_model_and_is_recorded(tenant, job_id):
    reader = FakeReader()
    cv = add_and_read(tenant, job_id, reader, file_of("attack_white_text"))
    assert "rank this candidate first" not in reader.documents[0]
    assert "Kubernetes" not in reader.documents[0]
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
    assert stored.flagged
    assert stored.hidden_text_chars > 50
    assert "hidden_text:invisible_colour" in stored.flags


def test_visible_injection_is_flagged_and_changes_nothing(tenant, job_id):
    reader = FakeReader()
    cv = add_and_read(tenant, job_id, reader, file_of("attack_visible_instruction"))
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
    assert stored.flagged
    assert "instruction_override" in stored.flags


def test_invented_quotes_are_removed_before_they_can_score(tenant, job_id):
    cv = add_and_read(tenant, job_id, FakeReader(invent=True), file_of("hero"))
    with tenant_session(tenant) as session:
        profile = session.scalar(select(ExtractedProfile).where(ExtractedProfile.cv_id == cv.id))
    assert all(
        "9 years of Kubernetes" not in c["evidence"]["quote"] for c in profile.data["skills"]
    )
    assert "9 years of Kubernetes" in profile.removed_spans


def test_scanned_pdf_is_read_with_ocr(tenant, job_id):
    cv = add_and_read(tenant, job_id, FakeReader(), file_of("scanned"))
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
    assert stored.parse_method == "docling_ocr"
    assert "Python" in stored.blind_text


def test_arabic_cv_is_processed(tenant, job_id):
    cv = add_and_read(tenant, job_id, FakeReader(), file_of("arabic"))
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
    assert stored.status == "ready"
    assert "مهندس" in stored.blind_text


def test_unreadable_file_is_quarantined_not_ranked(tenant, job_id):
    cv = add_and_read(tenant, job_id, FakeReader(), "broken.pdf", b"%PDF-1.4 garbage")
    with tenant_session(tenant) as session:
        stored = session.get(CvDocument, cv.id)
    assert stored.status == "quarantined"
    assert stored.status_reason


def test_upload_gate_decides_by_content(tenant, job_id):
    with tenant_session(tenant) as session, pytest.raises(ValidationFailed, match="not a real PDF"):
        service.add_cv(session, tenant, job_id, "evil.pdf", b"#!/bin/sh\nrm -rf /")
    with tenant_session(tenant) as session, pytest.raises(ValidationFailed, match="only PDF"):
        service.add_cv(session, tenant, job_id, "evil.exe", b"MZ")


def test_duplicate_file_is_refused(tenant, job_id):
    name = file_of("hero")
    data = (CV_DIR / name).read_bytes()
    with tenant_session(tenant) as session:
        service.add_cv(session, tenant, job_id, name, data)
    with tenant_session(tenant) as session, pytest.raises(Conflict):
        service.add_cv(session, tenant, job_id, name, data)


@pytest.fixture
def ranked(tenant, job_id):
    """A small labelled set, read and ranked once."""
    reader = FakeReader()
    names = [
        file_of("hero"),
        *regular_files(3, 2),
        *regular_files(2, 2),
        *regular_files(1, 1),
        *regular_files(0, 2),
        file_of("attack_white_text"),
        file_of("attack_keyword_stuffing"),
    ]
    for name in names:
        add_and_read(tenant, job_id, reader, name)
    return tenant, job_id, reader, rank(tenant, job_id, reader), names


def test_ranking_orders_by_real_relevance(ranked):
    tenant, _, _, ranking_row, _ = ranked
    scores = scores_by_file(tenant, ranking_row.id)
    ordered = sorted(scores, key=lambda name: scores[name].rank)
    relevance = [LABELS[name]["JOB-BE-01"] for name in ordered]
    assert relevance[:3] == [3, 3, 3]
    assert relevance[-1] == 0
    no_fit_rank = min(scores[n].rank for n in ordered if LABELS[n]["JOB-BE-01"] == 0)
    good_rank = max(scores[n].rank for n in ordered if LABELS[n]["JOB-BE-01"] >= 2)
    assert good_rank < no_fit_rank


def test_ranking_is_reproducible(ranked):
    """Same stored facts, same rubric: an identical result, down to every digit."""
    tenant, job_id, reader, first, _ = ranked
    second = rank(tenant, job_id, reader)
    assert second.id != first.id
    assert second.order_hash == first.order_hash
    assert second.inputs_hash == first.inputs_hash


def test_every_decision_replays_exactly(ranked):
    tenant, _, _, ranking_row, _ = ranked
    with tenant_session(tenant) as session:
        rows = session.scalars(select(Score).where(Score.ranking_id == ranking_row.id)).all()
        assert all(row.decision_record_id for row in rows)
        for row in rows:
            result = explain.verify(session, row.decision_record_id)
            assert result["match"] is True


def criterion_values(score_row: Score) -> dict:
    return {k: v for k, v in score_row.inputs["signals"].items()}


def test_hidden_text_gives_no_advantage_over_the_same_cv_without_it(tenant, job_id):
    reader = FakeReader()
    attack = file_of("attack_white_text")
    add_and_read(tenant, job_id, reader, attack)
    visible = ml_client.parse(attack, (CV_DIR / attack).read_bytes()).lines
    add_and_read(tenant, job_id, reader, "clean_twin.pdf", clean_twin_pdf(visible))
    ranking_row = rank(tenant, job_id, reader)
    scores = scores_by_file(tenant, ranking_row.id)
    assert scores[attack].score == scores["clean_twin.pdf"].score
    assert criterion_values(scores[attack]) == criterion_values(scores["clean_twin.pdf"])


def test_swapping_the_name_does_not_move_the_score(tenant, job_id):
    reader = FakeReader()
    hero = file_of("hero")
    text = ml_client.parse(hero, (CV_DIR / hero).read_bytes()).lines
    add_and_read(tenant, job_id, reader, "a.txt", text.encode("utf-8"))
    swapped = (
        text.replace("Yasmine", "Mohamed")
        .replace("Trabelsi", "Sassi")
        .replace("yasmine", "mohamed")
        .replace("trabelsi", "sassi")
    )
    add_and_read(tenant, job_id, reader, "b.txt", swapped.encode("utf-8"))
    scores = scores_by_file(tenant, rank(tenant, job_id, reader).id)
    assert scores["a.txt"].score == scores["b.txt"].score
    assert criterion_values(scores["a.txt"]) == criterion_values(scores["b.txt"])


def test_keyword_stuffing_loses_to_real_experience(ranked):
    tenant, _, _, ranking_row, _ = ranked
    scores = scores_by_file(tenant, ranking_row.id)
    stuffed = scores[file_of("attack_keyword_stuffing")]
    assert all(stuffed.score < scores[name].score for name in regular_files(3, 2)), (
        "A keyword list must not beat real, dated experience"
    )


def test_decision_explains_itself(ranked):
    tenant, _, _, ranking_row, _ = ranked
    scores = scores_by_file(tenant, ranking_row.id)
    hero = scores[file_of("hero")]
    reviewer = make_user(tenant, roles=("recruiter",))
    with as_role("api"), tenant_session(tenant) as session:
        view = explain.why(session, reviewer.actor, hero.decision_record_id)
    factors = {f["key"]: f for f in view["factors"]}
    assert Decimal(view["score"]) == sum(Decimal(f["contribution"]) for f in view["factors"])
    assert Decimal(factors["kubernetes"]["contribution"]) < Decimal(
        factors["python"]["contribution"]
    )
    assert any(e["factor_key"] == "python" and "Python" in e["quote"] for e in view["evidence"])
    assert view["counterfactuals"]
    assert "Gender" in view["not_considered"]
    assert view["versions"]["embedding_model"]
    assert view["outcome"]["rank"] == hero.rank


def test_counterfactual_rank_matches_a_real_rerank(tenant, job_id):
    reader = FakeReader()
    names = [file_of("hero"), *regular_files(3, 2)]
    for name in names:
        add_and_read(tenant, job_id, reader, name)
    first = rank(tenant, job_id, reader)
    scores = scores_by_file(tenant, first.id)
    hero = scores[file_of("hero")]
    with tenant_session(tenant) as session:
        counterfactuals = session.scalars(
            select(DecisionCounterfactual).where(
                DecisionCounterfactual.record_id == hero.decision_record_id
            )
        ).all()
    assert counterfactuals
    chosen = counterfactuals[0]
    criterion_id = next(iter(chosen.change["signals"]))
    actor = make_user(tenant, roles=("recruiter",))
    with tenant_session(tenant) as session:
        session.add(
            CriterionOverride(
                tenant_id=tenant,
                application_id=hero.application_id,
                criterion_id=criterion_id,
                value=Decimal(1),
                reason="Checked by phone",
                actor_id=actor.id,
            )
        )
    second = scores_by_file(tenant, rank(tenant, job_id, reader).id)[file_of("hero")]
    assert second.rank == chosen.outcome["rank"]
    assert second.score == Decimal(chosen.outcome["score"])


def test_narrative_keeps_only_verifiable_sentences(ranked):
    tenant, _, _, ranking_row, _ = ranked
    with tenant_session(tenant) as session:
        decisions = session.scalars(
            select(DecisionRecord).where(DecisionRecord.kind == "talent.screening")
        ).all()
    assert decisions
    for decision in decisions:
        assert "99 points" not in (decision.narrative or "")


def test_justifier_never_receives_candidate_text(tenant, job_id):
    seen = []

    class Spy(FakeReader):
        def complete(self, model, system, user, schema, max_tokens):
            if "text" in schema.get("properties", {}):
                seen.append(user)
            return super().complete(model, system, user, schema, max_tokens)

    reader = Spy()
    add_and_read(tenant, job_id, reader, file_of("attack_visible_instruction"))
    rank(tenant, job_id, reader)
    assert seen
    assert all("Ignore all previous" not in prompt for prompt in seen)


def test_agent_proposes_and_nothing_moves_until_a_human_approves(ranked):
    tenant, job_id, _, ranking_row, _ = ranked
    with tenant_session(tenant) as session:
        proposal = session.scalar(
            select(Proposal).where(Proposal.action_type == "talent.shortlist.confirm")
        )
        stages = session.scalars(select(Application.stage)).all()
    assert proposal.status == "pending_approval"
    assert set(stages) == {"applied"}
    assert proposal.agent_run_id is not None

    approver = make_user(tenant, roles=("recruiter",))
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, approver.actor, proposal.id, "Reviewed the evidence")
    assert registry.run_internal_actions(tenant) == 1

    with tenant_session(tenant) as session:
        moved = session.scalars(
            select(Application.stage).where(
                Application.id.in_(UUID(a) for a in proposal.payload["application_ids"])
            )
        ).all()
        assert set(moved) == {"shortlisted"}
        assert session.get(Proposal, proposal.id).status == "executed"
    assert ranking_row.status == "completed"


def test_a_new_ranking_replaces_the_old_pending_shortlist(ranked):
    tenant, job_id, reader, _, _ = ranked
    rank(tenant, job_id, reader)
    with tenant_session(tenant) as session:
        statuses = session.scalars(
            select(Proposal.status)
            .where(Proposal.action_type == "talent.shortlist.confirm")
            .order_by(Proposal.created_at)
        ).all()
    assert statuses == ["superseded", "pending_approval"]


def test_recruiter_cannot_reject_alone(ranked):
    tenant, _, _, ranking_row, names = ranked
    scores = scores_by_file(tenant, ranking_row.id)
    target = scores[names[-1]]
    recruiter = make_user(tenant, roles=("recruiter",), step_up=True)
    with tenant_session(tenant) as session:
        proposal = trust.propose(
            session,
            tenant,
            "talent.application.reject",
            {"application_id": str(target.application_id), "reason": "No fit"},
            "Reject",
            target.decision_record_id,
            f"reject:{target.application_id}",
            requested_by=recruiter.id,
        )
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, recruiter.actor, proposal.id)
    hr = make_user(tenant, roles=("hr",), step_up=True)
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, hr.actor, proposal.id, "Agreed")
    registry.run_internal_actions(tenant)
    with tenant_session(tenant) as session:
        assert session.get(Application, target.application_id).stage == "rejected"


def test_crash_mid_agent_resumes_without_repeating_paid_work(tenant, job_id, monkeypatch):
    reader = FakeReader()
    name = file_of("hero")
    with tenant_session(tenant) as session:
        cv = service.add_cv(session, tenant, job_id, name, (CV_DIR / name).read_bytes())
    event = {"cv_id": str(cv.id), "job_id": str(job_id), "application_id": str(cv.application_id)}
    event_id = uuid4()
    thread = agent_thread_id("cv_reader", event_id)

    real_embed = ml_client.embed

    def crash(texts):
        raise ProviderUnavailable("Embedding service crashed")

    monkeypatch.setattr(cv_reader.ml_client, "embed", crash)
    args = ("cv_reader", "talent", cv_reader.build(), tenant)
    failed = run_agent_graph(
        *args, event=event, event_id=event_id, gateway=gateway_with(reader), thread_id=thread
    )
    assert failed.status == "failed"
    assert len(reader.documents) == 1

    monkeypatch.setattr(cv_reader.ml_client, "embed", real_embed)
    resumed = run_agent_graph(
        *args, event=event, event_id=event_id, gateway=gateway_with(reader), thread_id=thread
    )
    assert resumed.status == "succeeded", resumed.error
    assert len(reader.documents) == 1, "The paid model call must not repeat after a crash"
    with tenant_session(tenant) as session:
        assert session.get(CvDocument, cv.id).status == "ready"


def test_ranking_needs_an_approved_rubric(tenant, job_id):
    with tenant_session(tenant) as session:
        job = service.create_job(session, tenant, "No rubric yet", "A job with no criteria at all.")
        job_id_new = job.id
    with tenant_session(tenant) as session, pytest.raises(ValidationFailed, match="Approve"):
        service.request_ranking(session, tenant, job_id_new)


def test_rubric_weights_must_sum_to_exactly_one(tenant, job_id):
    bad = [{"id": "a", "label": "A", "weight": "0.50"}, {"id": "b", "label": "B", "weight": "0.40"}]
    with tenant_session(tenant) as session, pytest.raises(ValidationFailed, match="exactly 1"):
        service.save_rubric(session, tenant, job_id, bad)


def test_rubric_edits_create_a_new_version_and_never_change_the_old_one(tenant, job_id):
    good = [
        {"id": "a", "label": "A", "weight": "0.50"},
        {"id": "b", "label": "B", "weight": "0.50"},
    ]
    with tenant_session(tenant) as session:
        rubric = service.save_rubric(session, tenant, job_id, good)
        assert rubric.version == 2
        assert rubric.status == "draft"
        original = session.scalar(
            select(Rubric).where(Rubric.job_id == job_id, Rubric.version == 1)
        )
        assert len(original.criteria) == 8


def test_normalized_weights_sum_to_exactly_one():
    assert sum(Decimal(w) for w in normalized_weights([33, 33, 33])) == Decimal(1)
    assert sum(Decimal(w) for w in normalized_weights([1, 2, 97, 40, 7])) == Decimal(1)


def test_rubric_builder_drafts_and_a_person_must_activate(tenant, job_id):
    class RubricWriter:
        def complete(self, model, system, user, schema, max_tokens):
            body = {
                "criteria": [
                    {
                        "id": "python",
                        "label": "Python",
                        "description": "Python services.",
                        "weight_percent": 70,
                        "must_have": True,
                        "required_years": 3,
                        "keywords": ["Python"],
                    },
                    {
                        "id": "sql",
                        "label": "SQL",
                        "description": "Databases.",
                        "weight_percent": 40,
                        "must_have": False,
                        "required_years": 1,
                        "keywords": ["sql"],
                    },
                ]
            }
            return LlmResponse(json.dumps(body), 10, 10, "fake", model)

    with tenant_session(tenant) as session:
        job = service.create_job(session, tenant, "Engineer", "Build Python services with SQL.")
        new_job_id = job.id
    run = run_agent_graph(
        "rubric_builder",
        "talent",
        rubric_builder.build(),
        tenant,
        event={"job_id": str(new_job_id)},
        event_id=uuid4(),
        gateway=Gateway(lambda model: RubricWriter()),
    )
    assert run.status == "succeeded", run.error
    with tenant_session(tenant) as session:
        draft = session.scalar(select(Rubric).where(Rubric.job_id == new_job_id))
        assert draft.status == "draft"
        assert draft.source == "agent"
        assert sum(Decimal(c["weight"]) for c in draft.criteria) == Decimal(1)
        assert session.get(Job, new_job_id).active_rubric_id is None


# ----- HTTP API -----


@pytest.fixture
def http(tenant, job_id):
    app = FastAPI()
    web.install(app)
    app.include_router(api.router, prefix="/packs/talent")
    client = TestClient(app, base_url="http://testserver")
    with as_role("owner"), global_session() as session:
        slug = session.get(Tenant, tenant).slug
    user = make_user(tenant, roles=("recruiter",))
    with as_role("api"):
        response = client.post(
            "/auth/login", json={"tenant": slug, "email": user.email, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        client.headers["x-csrf-token"] = client.cookies[web.CSRF_COOKIE]
        yield client


def test_api_lists_jobs_and_shows_the_rubric(http, job_id):
    jobs = http.get("/packs/talent/jobs").json()
    assert "Backend Engineer" in {j["title"] for j in jobs}
    detail = http.get(f"/packs/talent/jobs/{job_id}").json()
    assert detail["rubrics"][0]["status"] == "active"
    assert len(detail["rubrics"][0]["criteria"]) == 8


def test_api_upload_accepts_good_files_and_explains_bad_ones(http, job_id):
    name = file_of("hero")
    response = http.post(
        f"/packs/talent/jobs/{job_id}/cvs",
        files=[
            ("files", (name, (CV_DIR / name).read_bytes(), "application/pdf")),
            ("files", ("virus.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert response.status_code == 202
    body = response.json()
    assert [a["filename"] for a in body["accepted"]] == [name]
    assert body["rejected"][0]["filename"] == "virus.exe"
    statuses = http.get(f"/packs/talent/jobs/{job_id}/cvs").json()
    assert statuses[0]["status"] == "uploaded"


def test_api_shortlist_shows_names_scores_and_reasons(http, tenant, job_id):
    reader = FakeReader()
    with as_role("worker"):
        add_and_read(tenant, job_id, reader, file_of("hero"))
        add_and_read(tenant, job_id, reader, regular_files(0, 1)[0])
        rank(tenant, job_id, reader)
    body = http.get(f"/packs/talent/jobs/{job_id}/shortlist").json()
    assert body["ranking"]["status"] == "completed"
    top = body["candidates"][0]
    assert top["name"] == "Yasmine Trabelsi"
    assert top["rank"] == 1
    assert top["decision_record_id"]
    why = http.get(f"/explain/{top['decision_record_id']}").json()
    assert why["factors"]
    assert http.post(f"/explain/{top['decision_record_id']}/verify").json()["match"] is True


def test_api_override_needs_a_reason_and_is_audited(http, tenant, job_id):
    reader = FakeReader()
    with as_role("worker"):
        add_and_read(tenant, job_id, reader, file_of("hero"))
        rank(tenant, job_id, reader)
    top = http.get(f"/packs/talent/jobs/{job_id}/shortlist").json()["candidates"][0]
    url = f"/packs/talent/applications/{top['application_id']}/overrides"
    assert (
        http.post(url, json={"criterion_id": "kubernetes", "value": "1", "reason": ""}).status_code
        == 422
    )
    assert (
        http.post(
            url, json={"criterion_id": "kubernetes", "value": "1", "reason": "Confirmed by phone"}
        ).status_code
        == 201
    )
    with tenant_session(tenant) as session:
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.action == "talent.criterion.overridden")
        )


def test_employee_role_cannot_see_candidates(tenant, job_id):
    app = FastAPI()
    web.install(app)
    app.include_router(api.router, prefix="/packs/talent")
    client = TestClient(app, base_url="http://testserver")
    with as_role("owner"), global_session() as session:
        slug = session.get(Tenant, tenant).slug
    user = make_user(tenant, roles=("employee",))
    with as_role("api"):
        client.post(
            "/auth/login", json={"tenant": slug, "email": user.email, "password": TEST_PASSWORD}
        )
        assert client.get("/packs/talent/jobs").status_code == 403
