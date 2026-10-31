"""Connects events to agents. Agents run as durable jobs, so many can run at once and a crash
retries. The manifest's `entry` is "module:build", a function returning a LangGraph StateGraph.

An event that hands work to several agents is routed by the relay, without holding it up.
"""

import logging
import os
from importlib import import_module
from uuid import UUID

import procrastinate
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.ai.models import AgentRun
from kernel.db import tenant_session
from kernel.events import Consumer, EventOutbox, add_consumer
from kernel.jobs import get_job_app

AGENT_TASK = "agents.run"
AGENT_QUEUE = "agents"
AGENT_MAX_ATTEMPTS = 3

log = logging.getLogger("astra.runner")


def _inline() -> bool:
    return os.environ.get("AGENTS_INLINE") == "1"


def execute_agent(agent: str, pack: str, entry: str, tenant_id: str, event_id: str) -> None:
    from kernel.ai.graphs import run_agent_graph

    module_name, function_name = entry.split(":", 1)
    builder = getattr(import_module(module_name), function_name)()
    with tenant_session(tenant_id) as session:
        done = session.scalar(
            select(AgentRun.id).where(
                AgentRun.agent == agent,
                AgentRun.trigger_event_id == UUID(event_id),
                AgentRun.status == "succeeded",
            )
        )
        if done:
            return
        event = session.get(EventOutbox, UUID(event_id))
        payload, event_type = event.payload, event.type
    run = run_agent_graph(
        agent,
        pack,
        builder,
        UUID(tenant_id),
        event=payload,
        event_id=UUID(event_id),
        event_type=event_type,
    )
    if run.status != "succeeded":
        raise RuntimeError(f"Agent {pack}.{agent} failed: {run.error}")


def register_agent(agent: str, pack: str, entry: str, events: list[str]) -> None:
    def handler(_session: Session, event: EventOutbox) -> None:
        args = {
            "agent": agent,
            "pack": pack,
            "entry": entry,
            "tenant_id": str(event.tenant_id),
            "event_id": str(event.id),
        }
        if _inline():
            execute_agent(**args)
            return
        get_job_app().configure_task(
            AGENT_TASK,
            queue=AGENT_QUEUE,
            queueing_lock=f"{agent}:{event.id}",
        ).defer(**args)

    for name in events:
        add_consumer(name, Consumer(f"agent:{pack}.{agent}", handler))


def install_agent_task(app: procrastinate.App) -> None:
    @app.task(
        name=AGENT_TASK,
        queue=AGENT_QUEUE,
        retry=procrastinate.RetryStrategy(max_attempts=AGENT_MAX_ATTEMPTS, exponential_wait=4),
    )
    def run(agent: str, pack: str, entry: str, tenant_id: str, event_id: str) -> None:
        execute_agent(agent, pack, entry, tenant_id, event_id)
