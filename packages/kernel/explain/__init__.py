"""Explainability: explain the real computation, not an approximation of it.

Register a deterministic scorer, then record decisions. The kernel recomputes the score at
record time and again on verify, so what is displayed is provably what was calculated.

    @register_scorer("talent.rubric", "1")
    def score(inputs: dict) -> ScoreResult: ...

    record_id = record(session, tenant_id, DecisionDraft(...)).id
"""

import copy
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.authz import require_role
from kernel.canonical import payload_hash
from kernel.errors import NotFound, ValidationFailed
from kernel.events import event_type, publish
from kernel.explain.models import (
    DecisionCounterfactual,
    DecisionEvidence,
    DecisionFactor,
    DecisionRecord,
)
from kernel.identity import Actor
from kernel.trust.audit import current_trace_id
from kernel.trust.models import Approval, Proposal

DEFAULT_VIEW_ROLES = ["admin", "hr", "recruiter", "auditor"]
CITATION = re.compile(r"\[(E\d+)\]")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

tracer = trace.get_tracer("astra.explain")


class NarrativeRejected(ValidationFailed):
    code = "narrative_rejected"


class Factor(BaseModel):
    key: str
    label: str
    weight: Decimal
    value: Decimal
    contribution: Decimal


class Evidence(BaseModel):
    ref: str
    factor_key: str | None = None
    source_type: str
    source_id: str
    quote: str
    locator: dict[str, Any] = Field(default_factory=dict)


class Counterfactual(BaseModel):
    description: str
    change: dict[str, Any]
    outcome: dict[str, Any]


class ScoreResult(BaseModel):
    score: Decimal
    factors: list[Factor]


class DecisionDraft(BaseModel):
    kind: str
    question: str
    outcome: dict[str, Any]
    subject: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    narrative: str | None = None
    score: Decimal | None = None
    factors: list[Factor] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    counterfactuals: list[Counterfactual] = Field(default_factory=list)
    not_considered: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    scorer: str | None = None
    scorer_version: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    versions: dict[str, Any] = Field(default_factory=dict)
    view_roles: list[str] = Field(default_factory=lambda: list(DEFAULT_VIEW_ROLES))
    agent_run_id: UUID | None = None


@event_type("explain.decision.recorded.v1")
class DecisionRecorded(BaseModel):
    """Labels and IDs only: this feeds the graph, so it carries no quotes or inputs."""

    decision_id: UUID
    kind: str
    agent_run_id: UUID | None = None
    factors: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    prompt_hash: str | None = None
    model: str | None = None


_scorers: dict[tuple[str, str], Callable[[dict[str, Any]], ScoreResult]] = {}


def register_scorer(name: str, version: str) -> Callable:
    def register(fn: Callable[[dict[str, Any]], ScoreResult]) -> Callable:
        _scorers[(name, version)] = fn
        return fn

    return register


def rescore(name: str, version: str, inputs: dict[str, Any]) -> ScoreResult:
    scorer = _scorers.get((name, version))
    if scorer is None:
        raise ValidationFailed(f"Scorer {name}@{version} is not registered")
    return scorer(copy.deepcopy(inputs))


def counterfactual(
    name: str,
    version: str,
    inputs: dict[str, Any],
    description: str,
    change: dict[str, Any],
    rank_of: Callable[[Decimal], int] | None = None,
) -> Counterfactual:
    """Computed by actually re-scoring with the change applied, never estimated."""
    changed = copy.deepcopy(inputs)
    _deep_merge(changed, change)
    result = rescore(name, version, changed)
    outcome: dict[str, Any] = {"score": str(result.score)}
    if rank_of is not None:
        outcome["rank"] = rank_of(result.score)
    return Counterfactual(description=description, change=change, outcome=outcome)


def _deep_merge(base: dict[str, Any], change: dict[str, Any]) -> None:
    for key, value in change.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _validate(draft: DecisionDraft) -> None:
    if not draft.factors and not draft.evidence and not draft.rationale:
        raise ValidationFailed("A decision needs factors, evidence or a rationale")
    if not draft.view_roles:
        raise ValidationFailed("A decision needs at least one role allowed to view it")
    for factor in draft.factors:
        if factor.weight * factor.value != factor.contribution:
            raise ValidationFailed(f"Factor {factor.key}: contribution is not weight x value")
    if draft.score is not None and draft.factors:
        total = sum((factor.contribution for factor in draft.factors), Decimal(0))
        if total != draft.score:
            raise ValidationFailed(f"Factors sum to {total}, but the score is {draft.score}")
    factor_keys = {factor.key for factor in draft.factors}
    for item in draft.evidence:
        if item.factor_key is not None and item.factor_key not in factor_keys:
            raise ValidationFailed(f"Evidence {item.ref} cites unknown factor {item.factor_key}")
    if draft.scorer:
        if not draft.scorer_version:
            raise ValidationFailed("A scorer needs a version")
        result = rescore(draft.scorer, draft.scorer_version, draft.inputs)
        if result.score != draft.score:
            raise ValidationFailed("The recorded score does not match the scorer")
    if draft.narrative:
        validate_narrative(draft.narrative, draft)


def _allowed_numbers(draft: DecisionDraft) -> set[Decimal]:
    allowed: set[Decimal] = set()

    def add(value: Any) -> None:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return
        allowed.update({number.normalize(), (number * 100).normalize()})

    if draft.score is not None:
        add(draft.score)
    for factor in draft.factors:
        add(factor.weight)
        add(factor.value)
        add(factor.contribution)
    for value in draft.outcome.values():
        add(value)
    for item in draft.counterfactuals:
        for value in item.outcome.values():
            add(value)
    for item in draft.evidence:
        for number in NUMBER.findall(item.quote):
            add(number.replace(",", "."))
    return allowed


def validate_narrative(narrative: str, draft: DecisionDraft) -> None:
    """Reject text that states a number or cites evidence the record does not contain."""
    refs = {item.ref for item in draft.evidence}
    for ref in CITATION.findall(narrative):
        if ref not in refs:
            raise NarrativeRejected(f"Narrative cites {ref}, which is not in the evidence")
    allowed = _allowed_numbers(draft)
    without_refs = CITATION.sub("", narrative)
    for match in NUMBER.findall(without_refs):
        if Decimal(match.replace(",", ".")).normalize() not in allowed:
            raise NarrativeRejected(f"Narrative states {match}, which is not in the record")


def keep_cited_sentences(narrative: str, draft: DecisionDraft) -> str:
    """Drop sentences with no valid citation or with unsupported numbers."""
    kept = []
    for sentence in SENTENCE_END.split(narrative.strip()):
        if not CITATION.search(sentence):
            continue
        try:
            validate_narrative(sentence, draft)
        except NarrativeRejected:
            continue
        kept.append(sentence)
    return " ".join(kept)


def record(session: Session, tenant_id: UUID, draft: DecisionDraft) -> DecisionRecord:
    with tracer.start_as_current_span("explain.record", attributes={"astra.kind": draft.kind}):
        _validate(draft)
        row = DecisionRecord(
            tenant_id=tenant_id,
            kind=draft.kind,
            question=draft.question,
            subject=draft.subject,
            outcome=draft.outcome,
            score=draft.score,
            rationale=draft.rationale,
            narrative=draft.narrative,
            scorer=draft.scorer,
            scorer_version=draft.scorer_version,
            inputs=draft.inputs,
            not_considered=draft.not_considered,
            limits=draft.limits,
            versions=draft.versions,
            view_roles=draft.view_roles,
            input_hash=payload_hash(draft.inputs),
            output_hash=payload_hash(
                {"outcome": draft.outcome, "score": draft.score, "narrative": draft.narrative}
            ),
            agent_run_id=draft.agent_run_id,
            trace_id=current_trace_id(),
        )
        session.add(row)
        session.flush()
        for position, factor in enumerate(draft.factors):
            session.add(
                DecisionFactor(
                    tenant_id=tenant_id,
                    record_id=row.id,
                    key=factor.key,
                    label=factor.label,
                    weight=factor.weight,
                    value=factor.value,
                    contribution=factor.contribution,
                    position=position,
                )
            )
        for item in draft.evidence:
            session.add(
                DecisionEvidence(
                    tenant_id=tenant_id,
                    record_id=row.id,
                    ref=item.ref,
                    factor_key=item.factor_key,
                    source_type=item.source_type,
                    source_id=item.source_id,
                    locator=item.locator,
                    quote=item.quote,
                )
            )
        for item in draft.counterfactuals:
            session.add(
                DecisionCounterfactual(
                    tenant_id=tenant_id,
                    record_id=row.id,
                    description=item.description,
                    change=item.change,
                    outcome=item.outcome,
                )
            )
        publish(
            session,
            tenant_id,
            DecisionRecorded(
                decision_id=row.id,
                kind=draft.kind,
                agent_run_id=draft.agent_run_id,
                factors=[
                    {"decision_id": str(row.id), "key": f.key, "label": f.label}
                    for f in draft.factors
                ],
                evidence=[
                    {
                        "decision_id": str(row.id),
                        "ref": f"{row.id}:{e.ref}",
                        "source_type": e.source_type,
                        "source_id": e.source_id,
                        "factor_key": e.factor_key,
                    }
                    for e in draft.evidence
                ],
                prompt_hash=draft.versions.get("prompt_hash"),
                model=draft.versions.get("model"),
            ),
        )
        return row


def verify(session: Session, record_id: UUID) -> dict[str, Any]:
    """Replay: recompute the score from stored inputs and compare it with what was recorded."""
    row = session.get(DecisionRecord, record_id)
    if row is None:
        raise NotFound("Decision not found")
    inputs_ok = payload_hash(row.inputs) == row.input_hash
    if not row.scorer:
        return {"verifiable": False, "inputs_intact": inputs_ok, "match": None}
    result = rescore(row.scorer, row.scorer_version, row.inputs)
    stored = session.scalars(
        select(DecisionFactor)
        .where(DecisionFactor.record_id == record_id)
        .order_by(DecisionFactor.position)
    ).all()
    factors_match = len(stored) == len(result.factors) and all(
        a.key == b.key and a.contribution == b.contribution
        for a, b in zip(stored, result.factors, strict=True)
    )
    match = inputs_ok and factors_match and result.score == row.score
    return {
        "verifiable": True,
        "inputs_intact": inputs_ok,
        "match": match,
        "recorded_score": str(row.score),
        "recomputed_score": str(result.score),
    }


def why(session: Session, actor: Actor, record_id: UUID) -> dict[str, Any]:
    """Everything the "Why?" panel shows, including the human decision."""
    row = session.get(DecisionRecord, record_id)
    if row is None:
        raise NotFound("Decision not found")
    require_role(actor, row.view_roles, row.subject)
    factors = session.scalars(
        select(DecisionFactor)
        .where(DecisionFactor.record_id == record_id)
        .order_by(DecisionFactor.position)
    ).all()
    evidence = session.scalars(
        select(DecisionEvidence).where(DecisionEvidence.record_id == record_id)
    ).all()
    counterfactuals = session.scalars(
        select(DecisionCounterfactual).where(DecisionCounterfactual.record_id == record_id)
    ).all()
    proposal = session.scalar(select(Proposal).where(Proposal.decision_record_id == record_id))
    decisions = []
    if proposal is not None:
        rows = session.scalars(
            select(Approval)
            .where(Approval.proposal_id == proposal.id)
            .order_by(Approval.created_at)
        ).all()
        decisions = [
            {
                "decision": a.decision,
                "status": a.status,
                "approver_id": str(a.approver_id),
                "reason": a.reason,
                "at": a.created_at.isoformat(),
            }
            for a in rows
        ]
    return {
        "id": str(row.id),
        "kind": row.kind,
        "question": row.question,
        "outcome": row.outcome,
        "score": str(row.score) if row.score is not None else None,
        "rationale": row.rationale,
        "narrative": row.narrative,
        "factors": [
            {
                "key": f.key,
                "label": f.label,
                "weight": str(f.weight),
                "value": str(f.value),
                "contribution": str(f.contribution),
            }
            for f in factors
        ],
        "evidence": [
            {
                "ref": e.ref,
                "factor_key": e.factor_key,
                "source_type": e.source_type,
                "source_id": e.source_id,
                "locator": e.locator,
                "quote": e.quote,
            }
            for e in evidence
        ],
        "counterfactuals": [
            {"description": c.description, "change": c.change, "outcome": c.outcome}
            for c in counterfactuals
        ],
        "not_considered": row.not_considered,
        "limits": row.limits,
        "versions": row.versions,
        "scorer": row.scorer,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat(),
        "proposal": {"id": str(proposal.id), "status": proposal.status} if proposal else None,
        "human_decisions": decisions,
    }
