"""Architecture rules enforced by tests, so they hold as the team adds code."""

import ast
from pathlib import Path

from conftest import as_role
from sqlalchemy import text

from kernel.db import global_session
from kernel.registry import active_packs, load_manifests

ROOT = Path(__file__).resolve().parents[1]
OUTBOUND_MODULES = {"kernel.adapters", "smtplib"}
LLM_MODULES = {"anthropic", "openai", "groq"}
OUTBOUND_ALLOWED = ("apps/executor/", "packages/kernel/adapters/", "tests/")
LLM_ALLOWED = ("packages/kernel/ai/", "tests/")
EXEMPT_FROM_RLS = {
    "core.tenant",
    "core.alembic_version",
    "trust.action_type",
    "trust.policy_version",
}
APP_SCHEMAS = (
    "core",
    "trust",
    "ai",
    "knowledge",
    "comms",
    "calendar",
    "talent",
    "journey",
    "finance",
    "workforce",
)


def python_files():
    for folder in ("apps", "packages"):
        yield from (ROOT / folder).rglob("*.py")


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def uses(found: set[str], modules: set[str]) -> bool:
    return any(name == m or name.startswith(f"{m}.") for name in found for m in modules)


def test_only_the_executor_can_send():
    for path in python_files():
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(OUTBOUND_ALLOWED):
            assert not uses(imports(path), OUTBOUND_MODULES), f"{relative} imports outbound code"


def test_only_the_gateway_calls_model_providers():
    for path in python_files():
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(LLM_ALLOWED):
            assert not uses(imports(path), LLM_MODULES), f"{relative} imports an LLM SDK"


def test_every_tenant_table_has_rls_forced():
    with as_role("superuser"), global_session() as session:
        rows = session.execute(
            text(
                "SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid "
                "        AND a.attname = 'tenant_id' AND NOT a.attisdropped) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' AND n.nspname = ANY(:schemas)"
            ),
            {"schemas": list(APP_SCHEMAS)},
        ).all()
    assert rows
    for name, rls, forced, has_tenant in rows:
        if name in EXEMPT_FROM_RLS:
            continue
        assert has_tenant, f"{name} has no tenant_id"
        assert rls and forced, f"{name} does not have row-level security forced"


def test_no_application_role_can_bypass_rls():
    with as_role("superuser"), global_session() as session:
        rows = session.execute(
            text(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'astra\\_%' "
                "AND (rolsuper OR rolbypassrls OR rolcreaterole)"
            )
        ).all()
    assert rows == []


def test_manifests_are_valid():
    manifests = load_manifests()
    ids = [manifest.id for manifest in manifests]
    assert "kernel" in ids
    assert len(ids) == len(set(ids))
    action_ids = [action.id for manifest in manifests for action in manifest.actions]
    assert len(action_ids) == len(set(action_ids))
    for manifest in active_packs():
        for action in manifest.actions:
            assert action.id.startswith(f"{manifest.id}."), f"{action.id} is outside its pack"
