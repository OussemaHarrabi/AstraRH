"""AstraRH worker process: runs agents, the event relay and durable jobs.

It can propose and apply approved internal actions. It can never send or approve: the database
role can't write approvals, and this process holds no mail credentials.
"""

import logging
import os
import threading
import time

import httpx
from opentelemetry import trace

from kernel import registry
from kernel.ai.graphs import setup_checkpoints
from kernel.ai.runner import install_agent_task
from kernel.db import active_tenant_ids
from kernel.events import relay_once
from kernel.heartbeat import beat
from kernel.jobs import WORKER_QUEUES, get_job_app
from kernel.obs import setup_telemetry

HEARTBEAT_SECONDS = 30
RELAY_IDLE_SECONDS = 1
AGENT_CONCURRENCY = 4

log = logging.getLogger("astra.worker")
tracer = trace.get_tracer("astra.worker")


def relay_loop() -> None:
    """Every tenant in turn, each under its own RLS scope."""
    while True:
        worked = 0
        try:
            for tenant_id in active_tenant_ids():
                worked += relay_once(tenant_id)
                worked += registry.run_internal_actions(tenant_id)
        except Exception:
            log.exception("Relay pass failed")
        if not worked:
            time.sleep(RELAY_IDLE_SECONDS)


def heartbeat_loop() -> None:
    while True:
        beat()
        with tracer.start_as_current_span("worker.heartbeat") as span:
            try:
                status = httpx.get(f"{os.environ['ML_URL']}/v0/ping", timeout=5).status_code
                span.set_attribute("astra.ml.status", status)
            except httpx.HTTPError as exc:
                span.record_exception(exc)
                log.warning("ml service unreachable")
        time.sleep(HEARTBEAT_SECONDS)


def main() -> None:
    setup_telemetry()
    registry.install_graph_projections()
    registry.wire_agents()
    setup_checkpoints()
    threading.Thread(target=heartbeat_loop, daemon=True, name="heartbeat").start()
    threading.Thread(target=relay_loop, daemon=True, name="relay").start()
    log.info("worker started")
    app = get_job_app()
    install_agent_task(app)
    # The relay defers jobs synchronously while the worker below runs them on its own connection.
    app.open()
    app.run_worker(
        queues=WORKER_QUEUES, concurrency=AGENT_CONCURRENCY, install_signal_handlers=True
    )


if __name__ == "__main__":
    main()
