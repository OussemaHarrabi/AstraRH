"""Loads the fictional demo company. Idempotent. Run with the owner role by `astra.py seed`.

Each pack with a `seed.py` adds its own data: seed(session, tenant_id, world).
"""

import json
import logging
import os
from datetime import date
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.db import global_session, tenant_session
from kernel.identity import hash_password
from kernel.identity.models import RoleAssignment, Tenant, UserAccount
from kernel.people.models import (
    Employee,
    KpiDefinition,
    OrgUnit,
    Person,
    Position,
    Skill,
    SkillRelation,
)
from kernel.registry import active_packs, import_all_models

ROOT = Path(__file__).resolve().parents[2]
WORLD_FILE = ROOT / "data" / "world.json"

log = logging.getLogger("astra.seed")


def _get_or_add(session: Session, model, lookup: dict, **values):
    row = session.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup, **values)
        session.add(row)
        session.flush()
    return row


def seed_people(session: Session, tenant_id, world: dict) -> None:
    common = {"tenant_id": tenant_id}
    org = {
        o["id"]: _get_or_add(session, OrgUnit, {"external_id": o["id"]}, name=o["name"], **common)
        for o in world["org_units"]
    }
    positions = {
        p["id"]: _get_or_add(
            session, Position, {"external_id": p["id"]}, title=p["title"], **common
        )
        for p in world["positions"]
    }
    skills = {
        s["id"]: _get_or_add(session, Skill, {"external_id": s["id"]}, name=s["name"], **common)
        for s in world["skills"]
    }
    for relation in world["skill_relations"]:
        _get_or_add(
            session,
            SkillRelation,
            {
                "skill_id": skills[relation["skill"]].id,
                "related_skill_id": skills[relation["related"]].id,
            },
            strength=Decimal(relation["strength"]),
            **common,
        )
    for kpi in world["kpis"]:
        _get_or_add(
            session,
            KpiDefinition,
            {"external_id": kpi["id"]},
            name=kpi["name"],
            unit=kpi["unit"],
            owner_pack=kpi["owner"],
            direction=kpi["direction"],
            **common,
        )
    employees = {}
    for employee in world["employees"]:
        person = _get_or_add(
            session, Person, {"external_id": employee["id"]}, lifecycle="employee", **common
        )
        employees[employee["id"]] = _get_or_add(
            session,
            Employee,
            {"external_id": employee["id"]},
            person_id=person.id,
            display_name=employee["name"],
            email=employee["email"],
            org_unit_id=org[employee["org_unit"]].id,
            position_id=positions[employee["position"]].id,
            start_date=date.fromisoformat(employee["start_date"]),
            **common,
        )
    for employee in world["employees"]:
        if employee["manager"]:
            employees[employee["id"]].manager_id = employees[employee["manager"]].id
    session.flush()


def seed_users(session: Session, tenant_id, world: dict) -> None:
    password = os.environ["DEMO_PASSWORD"]
    for spec in world["users"]:
        if session.scalar(select(UserAccount).where(UserAccount.email == spec["email"])):
            continue
        person_id = None
        if spec.get("employee"):
            person_id = session.scalar(
                select(Person.id).where(Person.external_id == spec["employee"])
            )
        user = UserAccount(
            tenant_id=tenant_id,
            email=spec["email"],
            password_hash=hash_password(password),
            display_name=spec["name"],
            person_id=person_id,
        )
        session.add(user)
        session.flush()
        scope_type, scope_id = spec.get("scope", (None, None))
        for role in spec["roles"]:
            session.add(
                RoleAssignment(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    role=role,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
    session.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    import_all_models()
    world = json.loads(WORLD_FILE.read_text(encoding="utf-8"))
    with global_session() as session:
        tenant = _get_or_add(
            session, Tenant, {"slug": world["tenant"]["slug"]}, name=world["tenant"]["name"]
        )
        tenant_id = tenant.id
    with tenant_session(tenant_id) as session:
        seed_people(session, tenant_id, world)
        seed_users(session, tenant_id, world)
    for manifest in active_packs():
        if manifest.id == "kernel":
            continue
        try:
            module = import_module(f"packs.{manifest.id}.seed")
        except ModuleNotFoundError:
            continue
        with tenant_session(tenant_id) as session:
            module.seed(session, tenant_id, world)
    name, slug = world["tenant"]["name"], world["tenant"]["slug"]
    print(f"Seeded {name}. Sign in with tenant '{slug}'.")


if __name__ == "__main__":
    main()
