"""CV Reader agent, a LangGraph graph: parse -> separate identity -> read -> embed -> finish.

Each step is durable. The model only meets text that is already sanitized and identity-blind,
and it can only return data. Its output is frozen, so later rankings never re-read the CV.
"""

from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from kernel import files, ml_client, trust
from kernel.ai import AgentContext, EvidenceSpan, SecurityEvent, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.db import utcnow
from kernel.errors import ValidationFailed
from kernel.events import publish
from kernel.trust.audit import current_trace_id
from packs.talent.blind import blind
from packs.talent.events import CvProcessed
from packs.talent.models import (
    Application,
    CandidateIdentity,
    CvChunk,
    CvDocument,
    ExtractedProfile,
)
from packs.talent.signals import chunk_text

MODEL_TIER = "standard"


class SkillClaim(BaseModel):
    name: str
    years: float | None
    evidence: EvidenceSpan


class Degree(BaseModel):
    level: str
    field: str


class RoleClaim(BaseModel):
    title: str
    start_year: int | None
    end_year: int | None
    skills: list[str] = Field(default_factory=list)
    evidence: EvidenceSpan


class CvProfile(BaseModel):
    skills: list[SkillClaim] = Field(default_factory=list)
    roles: list[RoleClaim] = Field(default_factory=list)
    highest_degree: Degree | None
    languages: list[str] = Field(default_factory=list)


class State(AgentState, total=False):
    cv_id: str
    quarantined: bool


def _cv(ctx: AgentContext, state: dict) -> CvDocument:
    return ctx.session.get(CvDocument, UUID(state["event"]["cv_id"]), with_for_update=True)


def _quarantine(ctx: AgentContext, cv: CvDocument, reason: str) -> dict:
    cv.status = "quarantined"
    cv.status_reason = reason
    ctx.session.add(
        SecurityEvent(
            tenant_id=ctx.tenant_id,
            kind="cv_quarantined",
            severity="medium",
            source_type="cv",
            source_id=str(cv.id),
            detail={"reason": reason},
            trace_id=current_trace_id(),
        )
    )
    publish(
        ctx.session, ctx.tenant_id, CvProcessed(cv_id=cv.id, job_id=cv.job_id, status=cv.status)
    )
    return {"quarantined": True}


@agent_node
def parse_and_blind(ctx: AgentContext, state: dict) -> dict:
    """In the sandbox: extract visible text. Then take identity out before any model is involved."""
    cv = _cv(ctx, state)
    data = files.get(ctx.tenant_id, cv.file_key)
    try:
        parsed = ml_client.parse(cv.filename, data)
    except ValidationFailed as exc:
        return _quarantine(ctx, cv, exc.message)

    blinded = blind(parsed.text, parsed.lines)
    application = ctx.session.get(Application, cv.application_id)
    identity = ctx.session.scalar(
        select(CandidateIdentity).where(CandidateIdentity.candidate_id == application.candidate_id)
    )
    if identity is None:
        identity = CandidateIdentity(tenant_id=ctx.tenant_id, candidate_id=application.candidate_id)
        ctx.session.add(identity)
    identity.name = blinded.name or cv.filename
    identity.email = blinded.email
    identity.phone = blinded.phone

    cv.blind_text = blinded.text
    cv.parse_method = parsed.method
    cv.pages = parsed.pages
    cv.hidden_text_chars = len(parsed.hidden_text)
    cv.flags = list(parsed.findings)
    if parsed.hidden_text:
        cv.flagged = True
        ctx.session.add(
            SecurityEvent(
                tenant_id=ctx.tenant_id,
                kind="hidden_text_removed",
                severity="high",
                source_type="cv",
                source_id=str(cv.id),
                detail={"findings": parsed.findings, "characters": len(parsed.hidden_text)},
                trace_id=current_trace_id(),
            )
        )
    return {"quarantined": False}


@agent_node
def read_profile(ctx: AgentContext, state: dict) -> dict:
    """The quarantined model: no tools, strict schema, and quotes checked against the source."""
    cv = _cv(ctx, state)
    prompt = load_prompt(__file__, "cv_reader")
    result = ctx.read_untrusted(cv.blind_text, prompt, CvProfile, "cv", str(cv.id), tier=MODEL_TIER)
    profile = result.data.model_dump(mode="json")
    profile["skills"] = [c for c in profile["skills"] if c["evidence"]["quote"]]
    profile["roles"] = [r for r in profile["roles"] if r["evidence"]["quote"]]
    # Fixes what "present" means, so computed durations never drift with the calendar.
    profile["as_of_year"] = utcnow().year

    existing = ctx.session.scalar(select(ExtractedProfile).where(ExtractedProfile.cv_id == cv.id))
    if existing is None:
        ctx.session.add(
            ExtractedProfile(
                tenant_id=ctx.tenant_id,
                cv_id=cv.id,
                data=profile,
                prompt_hash=prompt.hash,
                removed_spans=result.removed_spans,
            )
        )
    cv.flagged = cv.flagged or result.flagged
    cv.flags = sorted({*cv.flags, *result.reasons, *result.findings})
    trust.log_action(
        ctx.session,
        ctx.tenant_id,
        "talent.cv.read",
        "agent",
        "talent.cv_reader",
        prompt_hash=prompt.hash,
        data={"cv_id": str(cv.id), "flagged": cv.flagged, "skills": len(profile["skills"])},
    )
    return {}


@agent_node
def embed_passages(ctx: AgentContext, state: dict) -> dict:
    cv = _cv(ctx, state)
    passages = chunk_text(cv.blind_text)
    existing = ctx.session.scalar(select(CvChunk.id).where(CvChunk.cv_id == cv.id).limit(1))
    if existing is None and passages:
        for position, (passage, vector) in enumerate(
            zip(passages, ml_client.embed(passages), strict=True)
        ):
            ctx.session.add(
                CvChunk(
                    tenant_id=ctx.tenant_id,
                    cv_id=cv.id,
                    job_id=cv.job_id,
                    position=position,
                    text=passage,
                    embedding=vector,
                )
            )
    cv.status = "ready"
    publish(
        ctx.session, ctx.tenant_id, CvProcessed(cv_id=cv.id, job_id=cv.job_id, status=cv.status)
    )
    return {}


def _after_parse(state: dict) -> str:
    return END if state.get("quarantined") else "read_profile"


def build() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("parse_and_blind", parse_and_blind)
    graph.add_node("read_profile", read_profile)
    graph.add_node("embed_passages", embed_passages)
    graph.add_edge(START, "parse_and_blind")
    graph.add_conditional_edges("parse_and_blind", _after_parse, ["read_profile", END])
    graph.add_edge("read_profile", "embed_passages")
    graph.add_edge("embed_passages", END)
    return graph
