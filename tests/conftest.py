"""Shared fixtures. Integration tests run against the real Postgres, using each process's real
database role, in throwaway tenants that background processes ignore (active=false)."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from kernel import explain, graph, trust
from kernel.db import global_session, tenant_session, use_database
from kernel.explain import DecisionDraft
from kernel.identity import Actor, RoleGrant, hash_password
from kernel.identity.models import RoleAssignment, Tenant, UserAccount
from kernel.registry import import_all_models
from kernel.trust.models import ActionType, Proposal

import_all_models()

ROLE_ENV = {
    "api": "TEST_API_URL",
    "worker": "TEST_WORKER_URL",
    "executor": "TEST_EXECUTOR_URL",
    "owner": "TEST_OWNER_URL",
    "superuser": "TEST_SUPERUSER_URL",
}
TEST_PASSWORD = "correct horse battery staple"


def role_url(role: str) -> str:
    return os.environ[ROLE_ENV[role]]


def as_role(role: str):
    return use_database(role_url(role))


def superuser_sql(sql: str, **params) -> None:
    """Simulates an attacker with database access, bypassing triggers and RLS."""
    engine = create_engine(role_url("superuser").replace("postgresql://", "postgresql+psycopg://"))
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text(sql), params)
    engine.dispose()


def _delete_tenant(tenant_id: UUID) -> None:
    engine = create_engine(role_url("superuser").replace("postgresql://", "postgresql+psycopg://"))
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        tables = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.columns "
                "WHERE column_name = 'tenant_id' "
                "AND table_schema NOT IN ('pg_catalog','information_schema')"
            )
        ).all()
        for schema, table in tables:
            conn.execute(
                text(f'DELETE FROM "{schema}"."{table}" WHERE tenant_id = :t'), {"t": tenant_id}
            )
        conn.execute(text("DELETE FROM core.tenant WHERE id = :t"), {"t": tenant_id})
    engine.dispose()


def make_tenant() -> UUID:
    with as_role("owner"), global_session() as session:
        tenant = Tenant(slug=f"test-{uuid4().hex[:12]}", name="Test", active=False)
        session.add(tenant)
        session.flush()
        return tenant.id


@pytest.fixture(scope="session", autouse=True)
def close_graph_driver() -> Iterator[None]:
    yield
    graph.close_driver()


@pytest.fixture
def tenant() -> Iterator[UUID]:
    tenant_id = make_tenant()
    yield tenant_id
    _delete_tenant(tenant_id)


@pytest.fixture
def other_tenant() -> Iterator[UUID]:
    tenant_id = make_tenant()
    yield tenant_id
    _delete_tenant(tenant_id)


def declare_action(
    action_id: str,
    risk: str = "R2",
    channel: str = "external",
    approver_roles: tuple[str, ...] = ("hr",),
    view_roles: tuple[str, ...] = ("hr", "auditor", "manager"),
) -> str:
    with as_role("owner"), global_session() as session:
        if session.get(ActionType, action_id) is None:
            session.add(
                ActionType(
                    id=action_id,
                    pack="test",
                    risk=risk,
                    channel=channel,
                    adapter="test.adapter",
                    approver_roles=list(approver_roles),
                    view_roles=list(view_roles),
                    description="Test action",
                )
            )
    return action_id


@dataclass
class TestUser:
    actor: Actor
    email: str

    @property
    def id(self) -> UUID:
        return self.actor.user_id


def make_user(
    tenant_id: UUID,
    roles: tuple[str, ...] = ("hr",),
    step_up: bool = False,
    scope: tuple[str, str] | None = None,
) -> TestUser:
    email = f"{uuid4().hex[:10]}@example.test"
    scope_type, scope_id = scope or (None, None)
    with as_role("owner"), tenant_session(tenant_id) as session:
        user = UserAccount(
            tenant_id=tenant_id,
            email=email,
            password_hash=hash_password(TEST_PASSWORD),
            display_name="Test User",
        )
        session.add(user)
        session.flush()
        for role in roles:
            session.add(
                RoleAssignment(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    role=role,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
        user_id = user.id
    grants = tuple(RoleGrant(role, scope_type, scope_id) for role in roles)
    return TestUser(Actor(user_id, tenant_id, grants, step_up_fresh=step_up), email)


def make_decision(tenant_id: UUID) -> UUID:
    with as_role("worker"), tenant_session(tenant_id) as session:
        row = explain.record(
            session,
            tenant_id,
            DecisionDraft(
                kind="test",
                question="Should this go out?",
                outcome={"label": "draft"},
                rationale="Test rationale",
            ),
        )
        return row.id


def make_proposal(
    tenant_id: UUID,
    action_id: str | None = None,
    payload: dict | None = None,
    requested_by: UUID | None = None,
    target: dict | None = None,
) -> Proposal:
    action_id = action_id or declare_action("test.email.r2")
    decision_id = make_decision(tenant_id)
    with as_role("worker"), tenant_session(tenant_id) as session:
        return trust.propose(
            session,
            tenant_id,
            action_id,
            payload or {"to": "a@example.test", "subject": "Hi", "body": "Hello"},
            "Send a test email",
            decision_id,
            idempotency_key=f"test:{uuid4().hex}",
            requested_by=requested_by,
            target=target,
        )
