"""Event bus: transactional outbox, versioned catalogue, isolated consumer deliveries.

@event_type("journey.training.completed.v1")
class TrainingCompleted(BaseModel): ...

publish(session, tenant_id, TrainingCompleted(...))

@subscribe("journey.training.completed.v1", "finance.training_cost")
def on_training(session, event): ...
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kernel.db import tenant_session, utcnow
from kernel.errors import ValidationFailed
from kernel.events.models import EventDelivery, EventOutbox

MAX_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 30
BATCH_SIZE = 100
WILDCARD = "*"

log = logging.getLogger("astra.events")
tracer = trace.get_tracer("astra.events")

_catalogue: dict[str, type[BaseModel]] = {}


@dataclass(frozen=True)
class Consumer:
    name: str
    handler: Callable[[Session, EventOutbox], None]
    retry_forever: bool = False


_consumers: dict[str, list[Consumer]] = {}


def event_type(name: str) -> Callable[[type[BaseModel]], type[BaseModel]]:
    def register(model: type[BaseModel]) -> type[BaseModel]:
        model.__event_type__ = name
        _catalogue[name] = model
        return model

    return register


def catalogue() -> dict[str, type[BaseModel]]:
    return dict(_catalogue)


def subscribe(event: str, name: str, retry_forever: bool = False) -> Callable[[Callable], Callable]:
    def register(handler: Callable) -> Callable:
        add_consumer(event, Consumer(name, handler, retry_forever))
        return handler

    return register


def add_consumer(event: str, consumer: Consumer) -> None:
    consumers = _consumers.setdefault(event, [])
    if not any(existing.name == consumer.name for existing in consumers):
        consumers.append(consumer)


def consumers_for(event: str) -> list[Consumer]:
    return [*_consumers.get(event, []), *_consumers.get(WILDCARD, [])]


def publish(session: Session, tenant_id: UUID, event: BaseModel) -> EventOutbox:
    """Only catalogued events can be published. Commits or rolls back with the caller's change."""
    name = getattr(type(event), "__event_type__", None)
    if name is None or name not in _catalogue:
        raise ValidationFailed(f"Event {type(event).__name__} is not in the catalogue")
    carrier: dict[str, str] = {}
    inject(carrier)
    row = EventOutbox(
        tenant_id=tenant_id,
        type=name,
        payload=event.model_dump(mode="json"),
        traceparent=carrier.get("traceparent"),
    )
    session.add(row)
    session.flush()
    return row


def _route(tenant_id: UUID) -> int:
    with tenant_session(tenant_id) as session:
        events = session.scalars(
            select(EventOutbox)
            .where(EventOutbox.routed_at.is_(None))
            .order_by(EventOutbox.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            for consumer in consumers_for(event.type):
                session.add(
                    EventDelivery(tenant_id=tenant_id, event_id=event.id, consumer=consumer.name)
                )
            event.routed_at = utcnow()
    return len(events)


def _find_consumer(event_type_name: str, name: str) -> Consumer | None:
    return next((c for c in consumers_for(event_type_name) if c.name == name), None)


def _process_one(tenant_id: UUID, delivery_id: UUID) -> None:
    retry_forever = False
    try:
        with tenant_session(tenant_id) as session:
            delivery = session.get(
                EventDelivery, delivery_id, with_for_update={"skip_locked": True}
            )
            if delivery is None or delivery.status != "pending":
                return
            event = session.get(EventOutbox, delivery.event_id)
            consumer = _find_consumer(event.type, delivery.consumer)
            if consumer is None:
                raise LookupError(f"Consumer {delivery.consumer} is not registered in this process")
            retry_forever = consumer.retry_forever
            context = extract({"traceparent": event.traceparent} if event.traceparent else {})
            with tracer.start_as_current_span(
                f"event {event.type}",
                context=context,
                attributes={"astra.consumer": consumer.name, "astra.event_id": str(event.id)},
            ):
                consumer.handler(session, event)
            delivery.status = "done"
            delivery.last_error = None
    except Exception as exc:  # noqa: BLE001 - one consumer's failure must not stop the relay
        log.warning("Delivery %s failed: %s", delivery_id, type(exc).__name__)
        _record_failure(tenant_id, delivery_id, exc, retry_forever)


def _record_failure(tenant_id: UUID, delivery_id: UUID, exc: Exception, forever: bool) -> None:
    with tenant_session(tenant_id) as session:
        delivery = session.get(EventDelivery, delivery_id)
        delivery.attempts += 1
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:500]
        delivery.next_attempt_at = utcnow() + timedelta(
            seconds=min(2**delivery.attempts, MAX_BACKOFF_SECONDS)
        )
        if delivery.attempts >= MAX_ATTEMPTS and not forever:
            delivery.status = "dead"


def relay_once(tenant_id: UUID) -> int:
    """Route new events to consumers, then run every delivery that is due."""
    routed = _route(tenant_id)
    with tenant_session(tenant_id) as session:
        due = session.scalars(
            select(EventDelivery.id)
            .where(EventDelivery.status == "pending", EventDelivery.next_attempt_at <= utcnow())
            .order_by(EventDelivery.id)
            .limit(BATCH_SIZE)
        ).all()
    for delivery_id in due:
        _process_one(tenant_id, delivery_id)
    return routed + len(due)


def redeliver(session: Session, consumer: str) -> None:
    """Make a consumer retry now, for example after a dependency returns."""
    session.execute(
        update(EventDelivery)
        .where(EventDelivery.consumer == consumer, EventDelivery.status == "pending")
        .values(next_attempt_at=utcnow())
    )
