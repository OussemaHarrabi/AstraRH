"""No explanation, no proposal. What is displayed is provably what was computed."""

from decimal import Decimal

import pytest
from conftest import as_role, make_proposal, make_user, superuser_sql
from sqlalchemy.exc import DBAPIError

from kernel import explain, trust
from kernel.db import tenant_session
from kernel.errors import PermissionDenied, ValidationFailed
from kernel.explain import (
    DecisionDraft,
    Evidence,
    Factor,
    NarrativeRejected,
    ScoreResult,
    keep_cited_sentences,
    register_scorer,
    validate_narrative,
)

WEIGHTS = {"python": Decimal("0.6"), "sql": Decimal("0.4")}


@register_scorer("test.rubric", "1")
def score(inputs: dict) -> ScoreResult:
    factors = []
    for key, weight in WEIGHTS.items():
        value = Decimal(str(inputs["levels"][key]))
        factors.append(
            Factor(
                key=key, label=key.title(), weight=weight, value=value, contribution=weight * value
            )
        )
    return ScoreResult(score=sum((f.contribution for f in factors), Decimal(0)), factors=factors)


def scored_draft(levels=None, **overrides) -> DecisionDraft:
    inputs = {"levels": levels or {"python": 4, "sql": 2}}
    result = score(inputs)
    fields = {
        "kind": "test.rank",
        "question": "Rank for Backend Engineer",
        "outcome": {"rank": 3, "score": str(result.score)},
        "score": result.score,
        "factors": result.factors,
        "scorer": "test.rubric",
        "scorer_version": "1",
        "inputs": inputs,
        "evidence": [
            Evidence(
                ref="E1",
                factor_key="python",
                source_type="cv",
                source_id="cv-1",
                quote="5 years of Python",
            )
        ],
        "not_considered": ["name", "photo", "gender", "age", "address"],
        "limits": ["No evidence found for Kubernetes"],
    }
    return DecisionDraft(**{**fields, **overrides})


def record(tenant, draft):
    with as_role("worker"), tenant_session(tenant) as session:
        return explain.record(session, tenant, draft)


def test_factors_must_sum_exactly_to_the_score(tenant):
    draft = scored_draft(score=Decimal("9"), scorer=None, scorer_version=None)
    with pytest.raises(ValidationFailed, match="sum"):
        record(tenant, draft)


def test_contribution_must_equal_weight_times_value(tenant):
    bad = Factor(
        key="python",
        label="Python",
        weight=Decimal("0.5"),
        value=Decimal(4),
        contribution=Decimal(3),
    )
    draft = scored_draft(factors=[bad], score=Decimal(3), scorer=None, scorer_version=None)
    with pytest.raises(ValidationFailed, match="weight"):
        record(tenant, draft)


def test_score_that_does_not_match_the_scorer_is_refused(tenant):
    good = score({"levels": {"python": 1, "sql": 1}})
    draft = scored_draft(score=good.score, factors=good.factors)
    with pytest.raises(ValidationFailed, match="does not match"):
        record(tenant, draft)


def test_evidence_must_cite_a_real_factor(tenant):
    evidence = [
        Evidence(ref="E1", factor_key="rust", source_type="cv", source_id="1", quote="Rust")
    ]
    with pytest.raises(ValidationFailed, match="unknown factor"):
        record(tenant, scored_draft(evidence=evidence))


def test_a_decision_with_nothing_behind_it_is_refused(tenant):
    with pytest.raises(ValidationFailed, match="factors, evidence or a rationale"):
        record(tenant, DecisionDraft(kind="x", question="?", outcome={"a": "b"}))


def test_replay_reproduces_the_score(tenant):
    row = record(tenant, scored_draft())
    with as_role("api"), tenant_session(tenant) as session:
        result = explain.verify(session, row.id)
    assert result["match"] is True
    assert Decimal(result["recomputed_score"]) == Decimal(result["recorded_score"])


def test_replay_detects_changed_inputs(tenant):
    row = record(tenant, scored_draft())
    superuser_sql(
        """UPDATE trust.decision_record
           SET inputs = '{"levels": {"python": 1, "sql": 1}}' WHERE id = :id""",
        id=row.id,
    )
    with as_role("api"), tenant_session(tenant) as session:
        result = explain.verify(session, row.id)
    assert result["match"] is False
    assert result["inputs_intact"] is False


def test_narrative_with_a_wrong_number_is_rejected(tenant):
    draft = scored_draft(narrative="Scored 9.9 overall [E1].")
    with pytest.raises(NarrativeRejected, match="9.9"):
        record(tenant, draft)


def test_narrative_with_correct_numbers_is_accepted(tenant):
    draft = scored_draft(narrative="Scored 3.2 and ranks 3 on Python with level 4 [E1].")
    row = record(tenant, draft)
    assert row.narrative


def test_narrative_citing_missing_evidence_is_rejected():
    with pytest.raises(NarrativeRejected, match="E7"):
        validate_narrative("Strong in Rust [E7].", scored_draft())


def test_uncited_sentences_are_dropped():
    text = "Strong Python background [E1]. Probably a great culture fit. Scored 99 points [E1]."
    assert keep_cited_sentences(text, scored_draft()) == "Strong Python background [E1]."


def test_counterfactual_matches_a_real_rescore(tenant):
    inputs = {"levels": {"python": 4, "sql": 2}}
    item = explain.counterfactual(
        "test.rubric",
        "1",
        inputs,
        "With SQL at level 4",
        {"levels": {"sql": 4}},
        rank_of=lambda s: 1 if s >= Decimal("4") else 3,
    )
    expected = score({"levels": {"python": 4, "sql": 4}})
    assert Decimal(item.outcome["score"]) == expected.score
    assert item.outcome["rank"] == 1
    assert inputs["levels"]["sql"] == 2


def test_why_returns_everything_including_the_human_decision(tenant):
    row = record(tenant, scored_draft())
    action = "test.why"
    from conftest import declare_action

    declare_action(action)
    reader = make_user(tenant, roles=("hr",))
    with as_role("worker"), tenant_session(tenant) as session:
        proposal = trust.propose(session, tenant, action, {"a": 1}, "x", row.id, "key:why")
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, reader.actor, proposal.id, "Evidence is solid")
    with as_role("api"), tenant_session(tenant) as session:
        view = explain.why(session, reader.actor, row.id)
    assert {f["key"] for f in view["factors"]} == {"python", "sql"}
    assert view["evidence"][0]["quote"] == "5 years of Python"
    assert "gender" in view["not_considered"]
    assert view["limits"] == ["No evidence found for Kubernetes"]
    assert view["human_decisions"][0]["reason"] == "Evidence is solid"
    assert view["human_decisions"][0]["decision"] == "approved"


def test_why_is_restricted_by_role(tenant):
    row = record(tenant, scored_draft(view_roles=["hr"]))
    outsider = make_user(tenant, roles=("employee",))
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        explain.why(session, outsider.actor, row.id)


def test_decision_records_are_immutable(tenant):
    row = record(tenant, scored_draft())
    from sqlalchemy import text

    for role in ("api", "worker", "owner"):
        with as_role(role), pytest.raises(DBAPIError), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE trust.decision_record SET question = 'x' WHERE id = :id"),
                {"id": row.id},
            )


def test_full_flow_proposal_carries_its_explanation(tenant):
    proposal = make_proposal(tenant)
    assert proposal.decision_record_id is not None
