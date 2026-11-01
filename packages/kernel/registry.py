"""Pack registry: manifests drive the action catalogue, agents, graph, routes and dashboard.

A pack that fails to load degrades to "unavailable" and never takes the platform down.
"""

import logging
from importlib import import_module
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from kernel.canonical import payload_hash
from kernel.db import global_session, tenant_session
from kernel.graph import Projection, install_projector, register_projection
from kernel.trust.models import ActionType, PolicyVersion, Proposal

ROOT = Path(__file__).resolve().parents[2]
KERNEL_MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"
PACKS_DIR = ROOT / "packages" / "packs"

log = logging.getLogger("astra.registry")

_load_errors: dict[str, str] = {}


class ActionSpec(BaseModel):
    id: str
    risk: Literal["R0", "R1", "R2", "R3"]
    channel: Literal["external", "internal", "none"] = "none"
    adapter: str | None = None
    handler: str | None = None
    approver_roles: list[str] = Field(default_factory=list)
    view_roles: list[str] = Field(default_factory=list)
    description: str

    @model_validator(mode="after")
    def _approvals_are_complete(self) -> "ActionSpec":
        if self.risk in {"R2", "R3"}:
            if not self.approver_roles or not self.view_roles:
                raise ValueError(f"{self.id}: {self.risk} needs approver_roles and view_roles")
            if self.channel == "none":
                raise ValueError(f"{self.id}: {self.risk} needs a channel")
            if self.channel == "external" and not self.adapter:
                raise ValueError(f"{self.id}: an external action needs an adapter")
            if self.channel == "internal" and not self.handler:
                raise ValueError(f"{self.id}: an internal action needs a handler")
        return self


class AgentSpec(BaseModel):
    id: str
    title: str = ""
    events: list[str]
    entry: str
    description: str = ""


class UiSpec(BaseModel):
    route: str | None = None
    nav_label: str | None = None
    roles: list[str] = Field(default_factory=list)


class Manifest(BaseModel):
    id: str
    name: str
    owner: str
    status: Literal["live", "preview", "off"] = "preview"
    description: str = ""
    actions: list[ActionSpec] = Field(default_factory=list)
    agents: list[AgentSpec] = Field(default_factory=list)
    graph: list[Projection] = Field(default_factory=list)
    ui: UiSpec = Field(default_factory=UiSpec)
    api: str | None = None
    models: str | None = None
    publishes: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)


def load_manifests() -> list[Manifest]:
    manifests = []
    paths = [KERNEL_MANIFEST]
    if PACKS_DIR.exists():
        paths += sorted(PACKS_DIR.glob("*/manifest.yaml"))
    for path in paths:
        manifests.append(Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
    return manifests


def active_packs() -> list[Manifest]:
    return [manifest for manifest in load_manifests() if manifest.status != "off"]


def import_all_models() -> None:
    """Every model module, so Alembic sees the full metadata."""
    for module in (
        "kernel.identity.models",
        "kernel.people.models",
        "kernel.events.models",
        "kernel.trust.models",
        "kernel.explain.models",
        "kernel.ai.models",
        "kernel.comms.models",
        "kernel.schedule.models",
        "kernel.knowledge.models",
    ):
        import_module(module)
    for manifest in load_manifests():
        if manifest.models:
            import_module(manifest.models)


def catalogue_hash(manifests: list[Manifest]) -> str:
    actions = sorted(
        (
            action.model_dump(exclude={"description"})
            for manifest in manifests
            for action in manifest.actions
        ),
        key=lambda item: item["id"],
    )
    return payload_hash(actions)


def sync_catalogue() -> None:
    """Run by migrate with the owner role, the only role allowed to change the catalogue."""
    manifests = [manifest for manifest in load_manifests() if manifest.status != "off"]
    version = catalogue_hash(manifests)
    with global_session() as session:
        for manifest in manifests:
            for action in manifest.actions:
                values = {
                    "pack": manifest.id,
                    "risk": action.risk,
                    "channel": action.channel,
                    "adapter": action.adapter or action.handler,
                    "approver_roles": action.approver_roles,
                    "view_roles": action.view_roles,
                    "description": action.description,
                }
                session.execute(
                    insert(ActionType)
                    .values(id=action.id, **values)
                    .on_conflict_do_update(index_elements=["id"], set_=values)
                )
        session.execute(
            update(PolicyVersion).where(PolicyVersion.version != version).values(is_current=False)
        )
        session.execute(
            insert(PolicyVersion)
            .values(version=version, is_current=True)
            .on_conflict_do_update(index_elements=["version"], set_={"is_current": True})
        )
    log.info("Action catalogue synced, policy version %s", version[:12])


def install_kernel_consumers() -> None:
    """Importing registers the consumers."""
    import_module("kernel.comms")
    import_module("kernel.comms.inbound")
    import_module("kernel.knowledge")


def install_graph_projections() -> None:
    for manifest in active_packs():
        for projection in manifest.graph:
            register_projection(projection)
    install_projector()


def wire_agents() -> None:
    """Worker only. A broken pack's agents are skipped and reported."""
    from kernel.ai.runner import register_agent

    for manifest in active_packs():
        for agent in manifest.agents:
            try:
                register_agent(agent.id, manifest.id, agent.entry, agent.events)
            except Exception as exc:  # noqa: BLE001 - one pack must not stop the platform
                _load_errors[manifest.id] = f"{type(exc).__name__}: {exc}"
                log.exception("Agent %s.%s failed to load", manifest.id, agent.id)


def mount_pack_routers(app: FastAPI) -> None:
    for manifest in active_packs():
        if not manifest.api:
            continue
        try:
            module_name, attribute = manifest.api.split(":", 1)
            router: APIRouter = getattr(import_module(module_name), attribute)
            app.include_router(router, prefix=f"/packs/{manifest.id}", tags=[manifest.id])
        except Exception as exc:  # noqa: BLE001 - one pack must not stop the platform
            _load_errors[manifest.id] = f"{type(exc).__name__}: {exc}"
            log.exception("Pack %s failed to load", manifest.id)


def pack_listing() -> list[dict[str, Any]]:
    """What the dashboard shows: the features of the solution, driven by the manifests."""
    return [
        {
            "id": manifest.id,
            "name": manifest.name,
            "owner": manifest.owner,
            "status": "unavailable" if manifest.id in _load_errors else manifest.status,
            "description": manifest.description,
            "route": manifest.ui.route,
            "nav_label": manifest.ui.nav_label,
            "roles": manifest.ui.roles,
            "actions": [
                {"id": a.id, "risk": a.risk, "description": a.description} for a in manifest.actions
            ],
            "agents": [
                {"id": a.id, "title": a.title or a.id, "description": a.description}
                for a in manifest.agents
            ],
        }
        for manifest in active_packs()
    ]


def run_internal_actions(tenant_id: UUID) -> int:
    """Worker only: apply approved internal actions, through the same gate as external ones.

    The handler is "module:function", read from the catalogue that only migrations can write.
    """
    from kernel import trust

    with tenant_session(tenant_id) as session:
        ids = session.scalars(
            select(Proposal.id).where(Proposal.status == "approved", Proposal.channel == "internal")
        ).all()

    def runner(handler: str | None, payload: dict[str, Any], key: str) -> str | None:
        module_name, function_name = (handler or "").split(":", 1)
        function = getattr(import_module(module_name), function_name)
        with tenant_session(tenant_id) as session:
            return function(session, tenant_id, payload, key)

    for proposal_id in ids:
        trust.execute(tenant_id, proposal_id, runner, channel="internal")
    return len(ids)
