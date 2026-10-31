"""Agent runtime. Events start agents; no LLM decides what runs.

Declare an agent in the pack manifest, then write its entry point:

    def run(ctx: AgentContext, event: EventOutbox) -> None:
        result = ctx.read_untrusted(text, prompt, Schema, "cv", cv_id)
        draft = ctx.llm("fast", prompt, facts, Schema)
        decision = ctx.record_decision(DecisionDraft(...))
        ctx.propose("talent.email.send", payload, "Reply to candidate", decision.id, key)

An agent run ends by creating proposals. It never waits for approval and never acts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.ai.gateway import Gateway, PromptRef, default_gateway
from kernel.ai.models import AgentRun, AgentStep, EvalResult, LlmCache, PromptVersion, SecurityEvent
from kernel.ai.reader import EvidenceSpan, ReaderResult, read_untrusted
from kernel.db import utcnow
from kernel.events import EventOutbox, event_type, publish
from kernel.explain import DecisionDraft
from kernel.explain.models import DecisionRecord
from kernel.trust.audit import append as audit_append
from kernel.trust.audit import current_trace_id
from kernel.trust.models import Proposal

__all__ = [
    "AgentContext",
    "AgentRun",
    "AgentStep",
    "EvalResult",
    "EvidenceSpan",
    "LlmCache",
    "PromptRef",
    "PromptVersion",
    "ReaderResult",
    "SecurityEvent",
    "load_prompt",
    "register_agent",
    "run_agent",
]

T = TypeVar("T", bound=BaseModel)

tracer = trace.get_tracer("astra.agents")


@event_type("ai.agent_run.completed.v1")
class AgentRunCompleted(BaseModel):
    run_id: UUID
    agent: str
    pack: str
    status: str
    trigger_event_id: UUID | None = None
    trigger_event_type: str | None = None


def load_prompt(pack_file: str, name: str) -> PromptRef:
    """Prompts are files beside the agent, versioned by content hash: load_prompt(__file__, "x")."""
    path = Path(pack_file).resolve().parent / "prompts" / f"{name}.md"
    return PromptRef(name=name, text=path.read_text(encoding="utf-8").strip())


@dataclass
class AgentContext:
    session: Session
    tenant_id: UUID
    run: AgentRun
    gateway: Gateway = default_gateway
    proposals: list[Proposal] = field(default_factory=list)

    @property
    def model_used(self) -> str | None:
        """The model behind this run's latest call, recorded in decision records."""
        return self.session.scalar(
            select(AgentStep.model)
            .where(AgentStep.run_id == self.run.id, AgentStep.model.is_not(None))
            .order_by(AgentStep.created_at.desc())
            .limit(1)
        )

    def _remember(self, prompt: PromptRef) -> None:
        # Agents run in parallel, so two may record the same prompt at once.
        self.session.execute(
            insert(PromptVersion)
            .values(tenant_id=self.tenant_id, name=prompt.name, hash=prompt.hash, text=prompt.text)
            .on_conflict_do_nothing(index_elements=["tenant_id", "name", "hash"])
        )

    def llm(self, tier: str, prompt: PromptRef, facts: str, schema: type[T]) -> T:
        """For trusted, already-validated facts. Untrusted text must use read_untrusted."""
        self._remember(prompt)
        return self.gateway.structured(
            self.session, self.tenant_id, tier, prompt, facts, schema, run_id=self.run.id
        )

    def read_untrusted(
        self,
        raw_text: str,
        prompt: PromptRef,
        schema: type[T],
        source_type: str,
        source_id: str,
        tier: str = "standard",
    ) -> ReaderResult[T]:
        self._remember(prompt)
        return read_untrusted(
            self.session,
            self.tenant_id,
            raw_text,
            prompt,
            schema,
            source_type,
            source_id,
            tier=tier,
            run_id=self.run.id,
            gateway=self.gateway,
        )

    def record_decision(self, draft: DecisionDraft) -> DecisionRecord:
        draft.agent_run_id = self.run.id
        return explain.record(self.session, self.tenant_id, draft)

    def propose(
        self,
        action_id: str,
        payload: dict[str, Any],
        summary: str,
        decision_record_id: UUID | None,
        idempotency_key: str,
        target: dict[str, Any] | None = None,
        expires_in: timedelta = trust.PROPOSAL_TTL,
    ) -> Proposal:
        proposal = trust.propose(
            self.session,
            self.tenant_id,
            action_id,
            payload,
            summary,
            decision_record_id,
            idempotency_key,
            target=target,
            agent_run_id=self.run.id,
            expires_in=expires_in,
        )
        self.proposals.append(proposal)
        return proposal


def run_agent(
    session: Session,
    agent: str,
    pack: str,
    entry: Callable[[AgentContext, EventOutbox | None], None],
    tenant_id: UUID,
    event: EventOutbox | None = None,
    gateway: Gateway = default_gateway,
) -> AgentRun:
    run = AgentRun(
        tenant_id=tenant_id,
        agent=agent,
        pack=pack,
        trigger_event_id=event.id if event else None,
        status="running",
        trace_id=current_trace_id(),
    )
    session.add(run)
    session.flush()
    ctx = AgentContext(session=session, tenant_id=tenant_id, run=run, gateway=gateway)
    with tracer.start_as_current_span(
        f"agent {agent}", attributes={"astra.agent": agent, "astra.pack": pack}
    ) as span:
        run.trace_id = current_trace_id()
        savepoint = session.begin_nested()
        try:
            entry(ctx, event)
            savepoint.commit()
            run.status = "succeeded"
        except Exception as exc:
            savepoint.rollback()
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:500]
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR)
        run.finished_at = utcnow()
        audit_append(
            session,
            tenant_id,
            "agent",
            f"{pack}.{agent}",
            f"agent.run.{run.status}",
            "success" if run.status == "succeeded" else "failure",
            reason=run.error,
            data={
                "run_id": str(run.id),
                "proposals": [str(p.id) for p in ctx.proposals if run.status == "succeeded"],
            },
        )
        publish(
            session,
            tenant_id,
            AgentRunCompleted(
                run_id=run.id,
                agent=agent,
                pack=pack,
                status=run.status,
                trigger_event_id=event.id if event else None,
                trigger_event_type=event.type if event else None,
            ),
        )
    return run
