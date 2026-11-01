"""AstraRH executor process: the only holder of outbound credentials.

It runs approved external proposals after re-validating them. Its database role sees only
proposals that reached approval. It never reads CVs and never calls LLMs.
"""

import logging
import os
import time
from decimal import Decimal, InvalidOperation

from opentelemetry import trace
from sqlalchemy import select

from kernel import adapters, trust
from kernel.db import active_tenant_ids, tenant_session
from kernel.events import publish
from kernel.heartbeat import beat
from kernel.obs import setup_telemetry
from kernel.payments import PaymentStatusReported
from kernel.trust.models import Proposal

POLL_SECONDS = 1
RECONCILE_EVERY_SECONDS = 30
BANK_POLL_EVERY_SECONDS = 5

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


def poll_bank(cursor: int) -> int:
    """Turn the bank's statuses into events. The executor holds the approved payload, so it checks
    each reported amount against what was approved and publishes only whether they matched.

    Safe to repeat: the consumer ignores a status it has already applied, so a restart that
    starts from 0 again duplicates nothing."""
    new_cursor, records = adapters.poll(cursor)
    for record in records:
        with tenant_session(record["tenant_id"]) as session:
            proposal = session.scalar(
                select(Proposal).where(Proposal.idempotency_key == record["key"])
            )
            if proposal is None:
                log.warning("Bank status for an unknown release %s ignored", record["key"])
                continue
            expected = next(
                (
                    line["amount"]
                    for line in proposal.payload["lines"]
                    if line["line_id"] == record["line_id"]
                ),
                None,
            )
            matches = True
            if record["status"] == "paid":
                try:
                    matches = expected is not None and Decimal(record["paid_amount"]) == Decimal(
                        expected
                    )
                except InvalidOperation:
                    matches = False
            publish(
                session,
                proposal.tenant_id,
                PaymentStatusReported(
                    provider_ref=record["reference"],
                    key=record["key"],
                    line_id=record["line_id"],
                    status=record["status"],
                    status_seq=record["seq"],
                    amount_matches=matches,
                    reason_code=record.get("reason"),
                ),
            )
    return new_cursor


def main() -> None:
    setup_telemetry()
    log.info("executor started")
    last_reconcile = 0.0
    last_bank_poll = 0.0
    bank_cursor = 0
    while True:
        beat()
        try:
            tenants = active_tenant_ids()
            for tenant_id in tenants:
                run_pass(tenant_id)
            if (
                os.environ.get("BANK_URL")
                and time.monotonic() - last_bank_poll > BANK_POLL_EVERY_SECONDS
            ):
                last_bank_poll = time.monotonic()
                with tracer.start_as_current_span("executor.bank_poll"):
                    bank_cursor = poll_bank(bank_cursor)
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
