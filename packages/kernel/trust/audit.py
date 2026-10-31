"""Append-only, hash-chained audit log. A failed audit write fails the whole action."""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from kernel.canonical import canonical_json, sha256_hex
from kernel.db import tenant_session, utcnow
from kernel.ids import uuid7
from kernel.trust.models import AuditEvent

GENESIS_HASH = "0" * 64
HASHED_FIELDS = (
    "id",
    "seq",
    "tenant_id",
    "actor_type",
    "actor_id",
    "action",
    "result",
    "reason",
    "proposal_id",
    "approval_id",
    "policy_version",
    "model_version",
    "prompt_hash",
    "input_hash",
    "output_hash",
    "trace_id",
    "data",
    "created_at",
)

log = logging.getLogger("astra.audit")


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def event_hash(fields: dict[str, Any], prev_hash: str) -> str:
    body = {name: fields[name] for name in HASHED_FIELDS}
    return sha256_hex(prev_hash + canonical_json(body))


def append(
    session: Session,
    tenant_id: UUID,
    actor_type: str,
    actor_id: str,
    action: str,
    result: str = "success",
    **details: Any,
) -> AuditEvent:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"audit:{tenant_id}"},
    )
    last = session.execute(
        select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
    ).first()
    seq, prev_hash = (last.seq + 1, last.hash) if last else (1, GENESIS_HASH)

    fields: dict[str, Any] = {
        "id": uuid7(),
        "seq": seq,
        "tenant_id": tenant_id,
        "actor_type": actor_type,
        "actor_id": str(actor_id),
        "action": action,
        "result": result,
        "reason": details.get("reason"),
        "proposal_id": details.get("proposal_id"),
        "approval_id": details.get("approval_id"),
        "policy_version": details.get("policy_version"),
        "model_version": details.get("model_version"),
        "prompt_hash": details.get("prompt_hash"),
        "input_hash": details.get("input_hash"),
        "output_hash": details.get("output_hash"),
        "trace_id": details.get("trace_id") or current_trace_id(),
        "data": details.get("data") or {},
        "created_at": utcnow(),
    }
    row = AuditEvent(**fields, prev_hash=prev_hash, hash=event_hash(fields, prev_hash))
    session.add(row)
    session.flush()
    return row


def record_denial(
    tenant_id: UUID, actor_type: str, actor_id: str, action: str, reason: str, **details: Any
) -> None:
    """Persist a denial in its own transaction, since the caller's will roll back."""
    try:
        with tenant_session(tenant_id) as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            append(
                session, tenant_id, actor_type, actor_id, action, "denied", reason=reason, **details
            )
    except Exception:  # noqa: BLE001 - the caller is denying anyway; never turn that into an allow
        log.exception("Could not record denial for %s", action)


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    length: int
    first_bad_seq: int | None = None


def verify_chain(session: Session) -> ChainStatus:
    """Recompute every hash. Editing, removing or reordering any row is detected."""
    prev_hash = GENESIS_HASH
    expected_seq = 1
    length = 0
    for row in session.scalars(select(AuditEvent).order_by(AuditEvent.seq)).yield_per(500):
        fields = {name: getattr(row, name) for name in HASHED_FIELDS}
        valid = (
            row.seq == expected_seq
            and row.prev_hash == prev_hash
            and row.hash == event_hash(fields, prev_hash)
        )
        if not valid:
            return ChainStatus(False, length, row.seq)
        prev_hash = row.hash
        expected_seq += 1
        length += 1
    return ChainStatus(True, length)
