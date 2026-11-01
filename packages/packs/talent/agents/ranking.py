"""Ranking agent, a LangGraph graph:
    collect signals -> score and rank -> explain (loop in batches) -> propose shortlist

Models don't rank. The order comes only from scoring.py. A model writes justifications from the
numbers, sees no CV text, and is checked against the record. A crash resumes at the last batch.
"""

from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy import select

from kernel import ml_client, trust
from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.canonical import canonical_json, sha256_hex
from kernel.db import utcnow
from kernel.events import publish
from kernel.explain import (
    DecisionDraft,
    Evidence,
    counterfactual,
    keep_cited_sentences,
    rescore,
)
from kernel.people import skill_relations
from kernel.people.models import Skill
from kernel.trust.models import Proposal
from packs.talent import scoring
from packs.talent.events import RankingCompleted
from packs.talent.models import (
    CriterionOverride,
    CvDocument,
    ExtractedProfile,
    Job,
    RankingRun,
    Rubric,
    Score,
)
from packs.talent.signals import (
    best_similarities,
    bm25_scores,
    compute_signal,
    criterion_text,
    lexical_document,
    weighted_dense_match,
)

EXPLAIN_BATCH = 8
JUSTIFY_TOP = 15
SHORTLIST_SIZE = 5
NOT_CONSIDERED = [
    "Name",
    "Photo",
    "Contact details",
    "Age or date of birth",
    "Gender",
    "Nationality or origin",
    "Marital status",
    "Address",
    "Name of school or university",
]


class State(AgentState, total=False):
    ranking_id: str
    pending: int


class Justification(BaseModel):
    text: str


def _ranking(ctx: AgentContext, state: dict) -> RankingRun:
    return ctx.session.get(RankingRun, UUID(state["event"]["ranking_id"]))


def _related_keywords(ctx: AgentContext, criteria: list[dict]) -> dict[str, list[dict[str, Any]]]:
    """Adjacent skills from the authoritative table in Postgres, never from the graph database."""
    relations = skill_relations(ctx.session)
    skills = {s.external_id: s for s in ctx.session.scalars(select(Skill))}
    names = {s.id: s.name for s in skills.values()}
    result: dict[str, list[dict[str, Any]]] = {}
    for criterion in criteria:
        skill = skills.get(criterion.get("skill") or "")
        if skill is None:
            continue
        result[criterion["id"]] = [
            {"name": names[other], "strength": str(strength), "keywords": [names[other]]}
            for other, strength in relations.get(skill.id, {}).items()
            if other in names
        ]
    return result


@agent_node
def collect_signals(ctx: AgentContext, state: dict) -> dict:
    """Gather evidence per criterion and store it, so scoring is pure arithmetic on stored facts."""
    ranking = _ranking(ctx, state)
    ranking.status = "running"
    session = ctx.session
    rubric = session.get(Rubric, ranking.rubric_id)
    criteria = rubric.criteria
    cvs = session.scalars(
        select(CvDocument).where(CvDocument.job_id == ranking.job_id, CvDocument.status == "ready")
    ).all()
    profiles = {
        p.cv_id: p.data
        for p in session.scalars(
            select(ExtractedProfile).where(ExtractedProfile.cv_id.in_([c.id for c in cvs]))
        )
    }
    overrides = {
        (o.application_id, o.criterion_id): o.value
        for o in session.scalars(select(CriterionOverride).order_by(CriterionOverride.created_at))
    }
    related = _related_keywords(ctx, criteria)
    all_keywords = sorted({k for c in criteria for k in c.get("keywords", [])})
    vectors = ml_client.embed([criterion_text(c) for c in criteria])
    similarities = {
        c["id"]: best_similarities(session, ranking.job_id, vector)
        for c, vector in zip(criteria, vectors, strict=True)
    }
    ranking.embedding_model = str(ml_client.model_info()["model"])

    public_criteria = [
        {
            "id": c["id"],
            "label": c["label"],
            "weight": c["weight"],
            "must_have": bool(c.get("must_have")),
            "required_years": c.get("required_years", 0),
        }
        for c in criteria
    ]
    job = session.get(Job, ranking.job_id)
    query = " ".join(
        [job.title, job.description]
        + [
            f"{c['label']} {c.get('description', '')} {' '.join(c.get('keywords', []))}"
            for c in criteria
        ]
    )
    lexical = bm25_scores(
        query, {cv.id: lexical_document(cv.blind_text or "", all_keywords) for cv in cvs}
    )
    for cv in cvs:
        signals, evidence = {}, []
        for criterion in criteria:
            outcome = compute_signal(
                criterion,
                profiles.get(cv.id, {}),
                cv.blind_text or "",
                similarities[criterion["id"]].get(cv.id),
                related.get(criterion["id"], []),
                overrides.get((cv.application_id, criterion["id"])),
                str(cv.id),
                all_keywords,
            )
            signals[criterion["id"]] = outcome.signal
            evidence.extend(outcome.evidence)
        session.add(
            Score(
                tenant_id=ctx.tenant_id,
                ranking_id=ranking.id,
                application_id=cv.application_id,
                inputs={
                    "criteria": public_criteria,
                    "signals": signals,
                    "match": {
                        "dense": str(
                            weighted_dense_match(
                                public_criteria,
                                {k: v.get("similarity") for k, v in signals.items()},
                            )
                        ),
                        "lexical": str(lexical.get(cv.id, 0)),
                    },
                },
                evidence=evidence,
                tiebreak=cv.sha256,
            )
        )
    session.flush()
    return {}


@agent_node
def score_and_rank(ctx: AgentContext, state: dict) -> dict:
    ranking = _ranking(ctx, state)
    rows = ctx.session.scalars(select(Score).where(Score.ranking_id == ranking.id)).all()
    items = []
    for row in rows:
        result = rescore(scoring.SCORER, scoring.SCORER_VERSION, row.inputs)
        row.score = result.score
        row.meets_must_haves = not scoring.missing_must_haves(row.inputs)
        items.append(scoring.Ranked(str(row.id), result.score, row.meets_must_haves, row.tiebreak))
    ranked = {item.key: item.rank for item in scoring.rank_all(items)}
    for row in rows:
        row.rank = ranked[str(row.id)]
    ordered = sorted(rows, key=lambda r: r.rank)
    ranking.inputs_hash = sha256_hex(canonical_json([r.inputs for r in ordered]))
    ranking.order_hash = sha256_hex(
        canonical_json([[r.tiebreak, str(r.score), r.rank] for r in ordered])
    )
    return {"pending": len(rows)}


def _template_narrative(row: Score, factors: list, refs: dict[str, str]) -> str:
    """Always available, and always true, because it is generated from the record itself."""
    strongest = sorted(factors, key=lambda f: (-f.contribution, -f.weight, f.key))
    supported = [f for f in strongest[:2] if f.contribution > 0 and f.key in refs]
    if not supported:
        return "No evidence found for any criterion in this job."
    labels = " and ".join(f.label for f in supported)
    citations = "".join(f"[{refs[f.key]}]" for f in supported)
    unproven = [f.label for f in sorted(factors, key=lambda f: -f.weight) if f.contribution == 0]
    note = f" No evidence found for {unproven[0]}." if unproven else ""
    return f"Best supported by {labels} {citations}.{note}"


def _justify(ctx: AgentContext, draft: DecisionDraft, row: Score, refs: dict[str, str]) -> str:
    """The model sees criteria, numbers and reference labels: no text written by the candidate."""
    lines = [f"Rank: {row.rank}. Score: {draft.score}."]
    for factor in draft.factors:
        ref = f" [{refs[factor.key]}]" if factor.key in refs else " (no evidence found)"
        lines.append(f"- {factor.label}: earned {factor.value} of 1, weight {factor.weight}{ref}")
    if row.inputs and scoring.missing_must_haves(row.inputs):
        lines.append("Missing must-haves: " + ", ".join(scoring.missing_must_haves(row.inputs)))
    result = ctx.llm("fast", load_prompt(__file__, "justifier"), "\n".join(lines), Justification)
    return keep_cited_sentences(result.text, draft)


@agent_node
def explain_batch(ctx: AgentContext, state: dict) -> dict:
    """Record a full decision for a batch of candidates, then loop until none remain."""
    ranking = _ranking(ctx, state)
    session = ctx.session
    job = session.get(Job, ranking.job_id)
    rubric = session.get(Rubric, ranking.rubric_id)
    rows = session.scalars(
        select(Score).where(Score.ranking_id == ranking.id).order_by(Score.rank)
    ).all()
    items = [
        scoring.Ranked(str(r.id), r.score, r.meets_must_haves, r.tiebreak, r.rank) for r in rows
    ]
    todo = [r for r in rows if r.decision_record_id is None]
    prompt = load_prompt(__file__, "justifier")

    for row in todo[:EXPLAIN_BATCH]:
        result = rescore(scoring.SCORER, scoring.SCORER_VERSION, row.inputs)
        evidence, refs = [], {}
        for index, item in enumerate(row.evidence, start=1):
            ref = f"E{index}"
            refs.setdefault(item["factor_key"], ref)
            evidence.append(
                Evidence(
                    ref=ref,
                    factor_key=item["factor_key"],
                    source_type="cv",
                    source_id=item["source_id"],
                    quote=item["quote"],
                    locator={"kind": item["kind"], "years": item.get("years")},
                )
            )
        missing = [f for f in result.factors if f.contribution == 0 and f.weight > 0]
        limits = [f"No evidence found for {f.label}" for f in missing]
        limits += [
            f"{f.label} is only listed as a keyword, with no experience shown"
            for f in result.factors
            if row.inputs["signals"].get(f.key, {}).get("listed")
        ]
        counterfactuals = []
        # The biggest gain available: what full proof of one criterion would do to the rank.
        gaps = sorted(result.factors, key=lambda f: f.weight * (1 - f.value), reverse=True)
        for factor in gaps[:2]:
            if factor.value >= 1 or factor.key == scoring.MATCH_KEY:
                continue
            change = {"signals": {factor.key: {"override": "1"}}}
            changed_inputs = {
                **row.inputs,
                "signals": {
                    **row.inputs["signals"],
                    factor.key: {**row.inputs["signals"].get(factor.key, {}), "override": "1"},
                },
            }
            meets = not scoring.missing_must_haves(changed_inputs)
            key = str(row.id)
            counterfactuals.append(
                counterfactual(
                    scoring.SCORER,
                    scoring.SCORER_VERSION,
                    row.inputs,
                    f"With full evidence for {factor.label}",
                    change,
                    rank_of=lambda s, key=key, meets=meets: scoring.rank_if(items, key, s, meets),
                )
            )

        draft = DecisionDraft(
            kind="talent.screening",
            question=f"Rank for {job.title}",
            subject={"job_id": str(job.id), "application_id": str(row.application_id)},
            outcome={
                "rank": row.rank,
                "score": str(result.score),
                "meets_must_haves": row.meets_must_haves,
                "candidates": len(rows),
            },
            score=result.score,
            factors=result.factors,
            evidence=evidence,
            counterfactuals=counterfactuals,
            not_considered=NOT_CONSIDERED,
            limits=limits,
            scorer=scoring.SCORER,
            scorer_version=scoring.SCORER_VERSION,
            inputs=row.inputs,
            versions={
                "rubric_id": str(rubric.id),
                "rubric_version": rubric.version,
                "embedding_model": ranking.embedding_model,
                "prompt_hash": prompt.hash,
                "model": ctx.model_used or "none",
            },
        )
        narrative = ""
        if row.rank <= JUSTIFY_TOP:
            narrative = _justify(ctx, draft, row, refs)
        draft.narrative = narrative or _template_narrative(row, result.factors, refs) or None
        decision = ctx.record_decision(draft)
        row.decision_record_id = decision.id
    return {"pending": max(0, len(todo) - EXPLAIN_BATCH)}


def _more_to_explain(state: dict) -> str:
    return "explain_batch" if state.get("pending", 0) > 0 else "propose_shortlist"


@agent_node
def propose_shortlist(ctx: AgentContext, state: dict) -> dict:
    """The agent ends here: a proposal a person must approve. Nothing changes until they do."""
    ranking = _ranking(ctx, state)
    session = ctx.session
    job = session.get(Job, ranking.job_id)
    rows = session.scalars(
        select(Score).where(Score.ranking_id == ranking.id).order_by(Score.rank)
    ).all()
    top = [r for r in rows if r.meets_must_haves][:SHORTLIST_SIZE]
    ranking.status = "completed"
    ranking.finished_at = utcnow()
    stale = session.scalars(
        select(Proposal).where(
            Proposal.action_type == "talent.shortlist.confirm",
            Proposal.status == "pending_approval",
            Proposal.target["job_id"].astext == str(job.id),
        )
    ).all()
    for proposal in stale:
        trust.supersede(session, proposal, "talent.ranking", "A newer ranking replaced this")
    publish(
        session,
        ctx.tenant_id,
        RankingCompleted(ranking_id=ranking.id, job_id=ranking.job_id, candidates=len(rows)),
    )
    if not top:
        return {}
    decision = ctx.record_decision(
        DecisionDraft(
            kind="talent.shortlist",
            question=f"Who should move forward for {job.title}?",
            subject={"job_id": str(job.id), "ranking_id": str(ranking.id)},
            outcome={"proposed": len(top), "candidates": len(rows)},
            rationale=(
                f"The top {len(top)} candidates who meet every must-have, out of {len(rows)}, "
                "by rubric score. Each has its own decision record."
            ),
            not_considered=NOT_CONSIDERED,
            versions={"ranking_id": str(ranking.id), "order_hash": ranking.order_hash},
        )
    )
    ctx.propose(
        "talent.shortlist.confirm",
        {
            "job_id": str(job.id),
            "ranking_id": str(ranking.id),
            "application_ids": [str(r.application_id) for r in top],
        },
        f"Move {len(top)} candidates to the shortlist for {job.title}",
        decision.id,
        f"shortlist:{ranking.id}",
        target={"job_id": str(job.id), "org_unit": job.org_unit},
    )
    return {}


def build() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("collect_signals", collect_signals)
    graph.add_node("score_and_rank", score_and_rank)
    graph.add_node("explain_batch", explain_batch)
    graph.add_node("propose_shortlist", propose_shortlist)
    graph.add_edge(START, "collect_signals")
    graph.add_edge("collect_signals", "score_and_rank")
    graph.add_edge("score_and_rank", "explain_batch")
    graph.add_conditional_edges(
        "explain_batch", _more_to_explain, ["explain_batch", "propose_shortlist"]
    )
    graph.add_edge("propose_shortlist", END)
    return graph
