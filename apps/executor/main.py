"""AstraRH executor process: the only holder of outbound credentials.

It runs approved external proposals after re-validating them. Its database role sees only
proposals that reached approval. It never reads CVs and never calls LLMs.
"""

import logging
import time

from opentelemetry import trace
from sqlalchemy import select

from kernel import adapters, trust
from kernel.db import active_tenant_ids, tenant_session
from kernel.heartbeat import beat
from kernel.obs import setup_telemetry
from kernel.trust.models import Proposal

POLL_SECONDS = 1
RECONCILE_EVERY_SECONDS = 30

log = logging.getLogger("astra.executor")
tracer = trace.get_tracer("astra.executor")


def run_pass(tenant_id) -> int:
    with tenant_session(tenant_id) as session:
        ids = session.scalars(
            select(Proposal.id).where(Proposal.status == "approved", Proposal.channel == "external")
        ).all()
    for proposal_id in ids:
        status = trust.execute(tenant_id, proposal_id, adapters.run, channel="external")
        log.info("Proposal %s: %s", proposal_id, status)
    return len(ids)


def main() -> None:
    setup_telemetry()
    log.info("executor started")
    last_reconcile = 0.0
    while True:
        beat()
        try:
            tenants = active_tenant_ids()
            for tenant_id in tenants:
                run_pass(tenant_id)
            if time.monotonic() - last_reconcile > RECONCILE_EVERY_SECONDS:
                last_reconcile = time.monotonic()
                with tracer.start_as_current_span("executor.reconcile"):
                    for tenant_id in tenants:
                        trust.reconcile_stale(tenant_id, adapters.lookup)
        except Exception:
            log.exception("Executor pass failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
