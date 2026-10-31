"""LangGraph agents with durable steps.

Every agent is a StateGraph. Each node runs in its own committed transaction, and LangGraph
checkpoints to Postgres between nodes, so a crash resumes after the last finished node and
never repeats finished work or its spend.

    class State(AgentState):
        cv_id: str

    @agent_node
    def parse(ctx: AgentContext, state: State) -> dict: ...

    def build() -> StateGraph:
        graph = StateGraph(State)
        graph.add_node("parse", parse)
        ...

State must hold IDs and small values: checkpoints are not the place for CV text.
Worker image only: LangGraph is not installed in the API or executor images.
"""

import os
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, TypedDict
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from opentelemetry import trace

from kernel.ai import AgentContext, AgentRun, AgentRunCompleted, AgentStep
from kernel.ai.gateway import Gateway, default_gateway
from kernel.db import tenant_session, utcnow
from kernel.events import publish
from kernel.trust.audit import append as audit_append
from kernel.trust.audit import current_trace_id

CHECKPOINT_SEARCH_PATH = "agent_ckpt"

tracer = trace.get_tracer("astra.agents")
_gateway: ContextVar[Gateway] = ContextVar("astra_gateway", default=default_gateway)


class AgentState(TypedDict, total=False):
    tenant_id: str
    run_id: str
    event_id: str | None
    event: dict[str, Any]


def _conn_string() -> str:
    url = os.environ["DATABASE_URL"]
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options={quote(f'-csearch_path={CHECKPOINT_SEARCH_PATH}')}"


def setup_checkpoints() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        saver.setup()


def run_graph(builder: Any, state: dict[str, Any] | None, thread_id: UUID | str) -> dict[str, Any]:
    """Run a StateGraph. With state=None, resume from the last checkpoint."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        graph = builder.compile(checkpointer=saver)
        return graph.invoke(state, {"configurable": {"thread_id": str(thread_id)}})


def has_pending_checkpoint(builder: Any, thread_id: UUID | str) -> bool:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        graph = builder.compile(checkpointer=saver)
        snapshot = graph.get_state({"configurable": {"thread_id": str(thread_id)}})
        return bool(snapshot.next)


def agent_node(fn: Callable[[AgentContext, dict], dict | None]) -> Callable[[dict], dict]:
    """One durable step: its own transaction, trace span and entry in the run's step log."""

    # Not functools.wraps: LangGraph reads the signature and would build the state from `ctx`.
    def wrapper(state: dict) -> dict:
        tenant_id = UUID(state["tenant_id"])
        run_id = UUID(state["run_id"])
        with tracer.start_as_current_span(f"node {fn.__name__}") as span:
            started = time.monotonic()
            try:
                with tenant_session(tenant_id) as session:
                    run = session.get(AgentRun, run_id)
                    ctx = AgentContext(session, tenant_id, run, gateway=_gateway.get())
                    updates = fn(ctx, state) or {}
                    session.add(
                        AgentStep(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            name=fn.__name__,
                            latency_ms=int((time.monotonic() - started) * 1000),
                        )
                    )
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR)
                raise
        return updates

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def agent_thread_id(agent: str, event_id: UUID | str) -> UUID:
    """Stable per agent and event, so a redelivered event resumes and doesn't start over."""
    return uuid5(NAMESPACE_URL, f"astra:{agent}:{event_id}")


def run_agent_graph(
    agent: str,
    pack: str,
    builder: Any,
    tenant_id: UUID,
    event: dict[str, Any] | None = None,
    event_id: UUID | None = None,
    event_type: str | None = None,
    gateway: Gateway = default_gateway,
    extra_state: dict[str, Any] | None = None,
    thread_id: UUID | str | None = None,
) -> AgentRun:
    """Create the run, execute or resume the graph, then record the outcome."""
    thread = thread_id or agent_thread_id(
        agent, event_id or uuid5(NAMESPACE_URL, str(time.time_ns()))
    )
    with tracer.start_as_current_span(
        f"agent {agent}", attributes={"astra.agent": agent, "astra.pack": pack}
    ) as span:
        with tenant_session(tenant_id) as session:
            run = AgentRun(
                tenant_id=tenant_id,
                agent=agent,
                pack=pack,
                trigger_event_id=event_id,
                status="running",
                trace_id=current_trace_id(),
            )
            session.add(run)
            session.flush()
            run_id = run.id

        state: dict[str, Any] | None = {
            "tenant_id": str(tenant_id),
            "run_id": str(run_id),
            "event_id": str(event_id) if event_id else None,
            "event": event or {},
            **(extra_state or {}),
        }
        resuming = has_pending_checkpoint(builder, thread)
        token = _gateway.set(gateway)
        status, error = "succeeded", None
        try:
            if resuming:
                _point_checkpoint_at_run(builder, thread, run_id)
                state = None
            run_graph(builder, state, thread)
        except Exception as exc:  # noqa: BLE001 - recorded on the run, and the job layer retries
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR)
        finally:
            _gateway.reset(token)

        with tenant_session(tenant_id) as session:
            run = session.get(AgentRun, run_id)
            run.status = status
            run.error = error
            run.finished_at = utcnow()
            audit_append(
                session,
                tenant_id,
                "agent",
                f"{pack}.{agent}",
                f"agent.run.{status}",
                "success" if status == "succeeded" else "failure",
                reason=error,
                data={"run_id": str(run_id), "resumed": resuming},
            )
            publish(
                session,
                tenant_id,
                AgentRunCompleted(
                    run_id=run_id,
                    agent=agent,
                    pack=pack,
                    status=status,
                    trigger_event_id=event_id,
                    trigger_event_type=event_type,
                ),
            )
        return run


def _point_checkpoint_at_run(builder: Any, thread: UUID | str, run_id: UUID) -> None:
    """A resumed graph logs its remaining steps against the new run."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        graph = builder.compile(checkpointer=saver)
        graph.update_state({"configurable": {"thread_id": str(thread)}}, {"run_id": str(run_id)})
