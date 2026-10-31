"""Transactional outbox, isolated consumers, durable jobs."""

from uuid import uuid4

import pytest
from conftest import as_role, role_url
from pydantic import BaseModel
from sqlalchemy import select, text

from kernel import events
from kernel.db import tenant_session
from kernel.errors import ValidationFailed
from kernel.events.models import EventDelivery, EventOutbox


def unique_event() -> tuple[str, type[BaseModel]]:
    name = f"test.{uuid4().hex[:8]}.happened.v1"

    @events.event_type(name)
    class Happened(BaseModel):
        value: int

    return name, Happened


def test_uncatalogued_event_is_refused(tenant):
    class Stray(BaseModel):
        value: int

    with as_role("worker"), tenant_session(tenant) as session, pytest.raises(ValidationFailed):
        events.publish(session, tenant, Stray(value=1))


def test_event_rolls_back_with_its_transaction(tenant):
    _, Happened = unique_event()

    class Boom(Exception):
        pass

    with as_role("worker"), pytest.raises(Boom), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
        raise Boom
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.scalars(select(EventOutbox)).all() == []


def test_consumers_receive_the_event(tenant):
    name, Happened = unique_event()
    seen = []
    events.subscribe(name, f"test.ok.{name}")(lambda s, e: seen.append(e.payload["value"]))
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=7))
    with as_role("worker"):
        events.relay_once(tenant)
    assert seen == [7]


def test_a_failing_consumer_does_not_block_the_others(tenant):
    name, Happened = unique_event()
    seen = []

    def explode(session, event):
        raise RuntimeError("Consumer down")

    events.subscribe(name, f"test.bad.{name}")(explode)
    events.subscribe(name, f"test.good.{name}")(lambda s, e: seen.append(1))
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(tenant)
    assert seen == [1]
    with as_role("worker"), tenant_session(tenant) as session:
        rows = {d.consumer: d for d in session.scalars(select(EventDelivery))}
    assert rows[f"test.good.{name}"].status == "done"
    bad = rows[f"test.bad.{name}"]
    assert bad.status == "pending"
    assert bad.attempts == 1
    assert "Consumer down" in bad.last_error


def test_consumer_changes_roll_back_on_failure(tenant):
    name, Happened = unique_event()

    def half_done(session, event):
        session.execute(
            text(
                "INSERT INTO core.person (id, tenant_id, external_id, lifecycle, created_at) "
                "VALUES (gen_random_uuid(), :t, 'half', 'candidate', now())"
            ),
            {"t": tenant},
        )
        raise RuntimeError("Then failed")

    events.subscribe(name, f"test.half.{name}")(half_done)
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.execute(text("SELECT count(*) FROM core.person")).scalar() == 0


def test_delivery_goes_dead_after_max_attempts(tenant):
    name, Happened = unique_event()

    def explode(session, event):
        raise RuntimeError("Always")

    events.subscribe(name, f"test.dead.{name}")(explode)
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(tenant)
        for _ in range(events.MAX_ATTEMPTS):
            with tenant_session(tenant) as session:
                session.execute(text("UPDATE core.event_delivery SET next_attempt_at = now()"))
            events.relay_once(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        statuses = session.scalars(
            select(EventDelivery.status).where(EventDelivery.consumer == f"test.dead.{name}")
        ).all()
    assert statuses == ["dead"]


def test_retry_forever_consumer_never_goes_dead(tenant):
    name, Happened = unique_event()

    def explode(session, event):
        raise RuntimeError("Dependency down")

    events.subscribe(name, f"test.forever.{name}", retry_forever=True)(explode)
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(tenant)
        for _ in range(events.MAX_ATTEMPTS + 1):
            with tenant_session(tenant) as session:
                session.execute(text("UPDATE core.event_delivery SET next_attempt_at = now()"))
            events.relay_once(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        statuses = session.scalars(
            select(EventDelivery.status).where(EventDelivery.consumer == f"test.forever.{name}")
        ).all()
    assert statuses == ["pending"]


def test_rls_scopes_the_relay_to_one_tenant(tenant, other_tenant):
    name, Happened = unique_event()
    seen = []
    events.subscribe(name, f"test.scope.{name}")(lambda s, e: seen.append(e.tenant_id))
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(other_tenant)
    assert seen == []
    with as_role("worker"):
        events.relay_once(tenant)
    assert seen == [tenant]


def test_durable_job_runs_from_postgres(monkeypatch):
    import procrastinate

    from kernel import jobs

    monkeypatch.setenv("DATABASE_URL", role_url("worker"))
    monkeypatch.setattr(jobs, "_app", None)
    app = jobs.get_job_app()
    results = []
    queue = f"test_{uuid4().hex[:8]}"

    @app.task(name=f"test.job.{queue}", queue=queue)
    def job(value: int) -> None:
        results.append(value)

    with app.open():
        job.defer(value=42)
    app.run_worker(queues=[queue], wait=False, install_signal_handlers=False)
    assert results == [42]
    assert isinstance(app, procrastinate.App)
