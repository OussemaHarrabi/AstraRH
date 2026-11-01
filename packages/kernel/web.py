"""HTTP layer for the kernel: request context, auth routes, trust, explain, graph and registry."""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, graph, registry, trust
from kernel.ai.models import AgentRun, AgentStep
from kernel.authz import has_role, require_role
from kernel.db import tenant_session
from kernel.errors import KernelError, NotAuthenticated, NotFound, PermissionDenied
from kernel.identity import (
    SESSION_HOURS,
    STEP_UP_MINUTES,
    Actor,
    authenticate,
    decode_session,
    issue_session,
    load_actor,
    new_csrf_token,
    tenant_by_slug,
    verify_password,
)
from kernel.identity.models import UserAccount
from kernel.people.models import Employee, KpiDefinition, OrgUnit, Position, Skill
from kernel.trust.models import ActionType, AuditEvent, Proposal

SESSION_COOKIE = "astra_session"
CSRF_COOKIE = "astra_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUDIT_ROLES = {"admin", "auditor", "hr"}
RUN_ROLES = {"admin", "auditor", "hr", "recruiter"}
PEOPLE_ROLES = {"admin", "hr", "recruiter", "manager", "finance", "auditor"}
GRAPH_VIEWS = {
    "agent_mesh": {"admin", "hr", "recruiter", "auditor"},
    "skills_graph": {"admin", "hr", "manager"},
    "bus_factor": {"admin", "hr", "manager"},
}


@dataclass(frozen=True)
class RequestContext:
    session: Session
    actor: Actor


def _check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise PermissionDenied("Missing or invalid CSRF token")


@contextmanager
def request_context(request: Request) -> Iterator[RequestContext]:
    """Authenticated, CSRF-checked, tenant-scoped. Commits before the response is sent."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotAuthenticated("Please sign in")
    claims = decode_session(token)
    _check_csrf(request)
    with tenant_session(claims["tid"]) as session:
        yield RequestContext(session, load_actor(session, claims))


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    secure = os.environ.get("ASTRA_ENV", "dev") != "dev"
    max_age = SESSION_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=max_age,
        path="/",
    )
    # Readable by the page, which sends it back as a header: the double-submit CSRF pattern.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="strict",
        max_age=max_age,
        path="/",
    )


class LoginBody(BaseModel):
    tenant: str
    email: str
    password: str


class PasswordBody(BaseModel):
    password: str


class ReasonBody(BaseModel):
    reason: str | None = None


class RejectBody(BaseModel):
    reason: str


class EditBody(BaseModel):
    payload: dict[str, Any]
    reason: str | None = None


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    tenant = tenant_by_slug(body.tenant)
    client_ip = request.client.host if request.client else "unknown"
    with tenant_session(tenant.id) as session:
        user = authenticate(session, body.email, body.password, client_ip)
        if user is not None:
            trust.audit.append(session, tenant.id, "human", user.id, "auth.login")
    if user is None:
        raise NotAuthenticated("Invalid credentials")
    _set_session_cookies(response, issue_session(user.id, tenant.id), new_csrf_token())
    return {"user_id": str(user.id), "display_name": user.display_name}


@auth_router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"status": "signed_out"}


@auth_router.get("/me")
def me(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        user = ctx.session.get(UserAccount, ctx.actor.user_id)
        return {
            "user_id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "roles": sorted(ctx.actor.roles),
            "step_up_fresh": ctx.actor.step_up_fresh,
        }


@auth_router.post("/step-up")
def step_up(body: PasswordBody, request: Request, response: Response) -> dict[str, Any]:
    """Re-enter the password before an R3 approval. Lasts a few minutes."""
    with request_context(request) as ctx:
        user = ctx.session.get(UserAccount, ctx.actor.user_id)
        if not verify_password(user.password_hash, body.password):
            trust.audit.record_denial(
                ctx.actor.tenant_id, "human", user.id, "auth.step_up", "wrong_password"
            )
            raise PermissionDenied("Incorrect password")
        trust.audit.append(ctx.session, ctx.actor.tenant_id, "human", user.id, "auth.step_up")
    token = issue_session(ctx.actor.user_id, ctx.actor.tenant_id, step_up=True)
    _set_session_cookies(response, token, request.cookies[CSRF_COOKIE])
    return {"valid_for_minutes": STEP_UP_MINUTES}


trust_router = APIRouter(prefix="/trust", tags=["trust"])


def _proposal_json(proposal: Proposal) -> dict[str, Any]:
    return {
        "id": str(proposal.id),
        "action_type": proposal.action_type,
        "status": proposal.status,
        "risk": proposal.risk,
        "summary": proposal.summary,
        "payload": proposal.payload,
        "payload_hash": proposal.payload_hash,
        "target": proposal.target,
        "decision_record_id": str(proposal.decision_record_id),
        "revision": proposal.revision,
        "agent_run_id": str(proposal.agent_run_id) if proposal.agent_run_id else None,
        "expires_at": proposal.expires_at.isoformat(),
        "created_at": proposal.created_at.isoformat(),
    }


def _visible(session: Session, actor: Actor, proposal: Proposal) -> bool:
    action = session.get(ActionType, proposal.action_type)
    return action is not None and has_role(actor, action.view_roles, proposal.target)


@trust_router.get("/proposals")
def list_proposals(
    request: Request,
    status: str | None = None,
    limit: int = Query(default=100, le=500),
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        statement = select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)
        if status:
            statement = statement.where(Proposal.status == status)
        rows = ctx.session.scalars(statement).all()
        return [_proposal_json(p) for p in rows if _visible(ctx.session, ctx.actor, p)]


@trust_router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        proposal = ctx.session.get(Proposal, proposal_id)
        if proposal is None or not _visible(ctx.session, ctx.actor, proposal):
            raise NotFound("Proposal not found")
        return _proposal_json(proposal)


@trust_router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: UUID, body: ReasonBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        approval = trust.approve(ctx.session, ctx.actor, proposal_id, body.reason)
        return {"approval_id": str(approval.id), "status": "approved"}


@trust_router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: UUID, body: RejectBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        trust.reject(ctx.session, ctx.actor, proposal_id, body.reason)
        return {"status": "rejected"}


@trust_router.post("/proposals/{proposal_id}/edit")
def edit_proposal(proposal_id: UUID, body: EditBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        return _proposal_json(
            trust.edit(ctx.session, ctx.actor, proposal_id, body.payload, body.reason)
        )


@trust_router.get("/audit")
def audit_timeline(
    request: Request,
    proposal_id: UUID | None = None,
    limit: int = Query(default=100, le=1000),
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, AUDIT_ROLES)
        statement = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
        if proposal_id:
            statement = statement.where(AuditEvent.proposal_id == proposal_id)
        return [
            {
                "seq": e.seq,
                "at": e.created_at.isoformat(),
                "actor_type": e.actor_type,
                "actor_id": e.actor_id,
                "action": e.action,
                "result": e.result,
                "reason": e.reason,
                "proposal_id": str(e.proposal_id) if e.proposal_id else None,
                "trace_id": e.trace_id,
                "hash": e.hash,
                "prev_hash": e.prev_hash,
            }
            for e in ctx.session.scalars(statement)
        ]


@trust_router.post("/audit/verify")
def audit_verify(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, AUDIT_ROLES)
        status = trust.audit.verify_chain(ctx.session)
        return {"ok": status.ok, "length": status.length, "first_bad_seq": status.first_bad_seq}


explain_router = APIRouter(prefix="/explain", tags=["explain"])


@explain_router.get("/{record_id}")
def why(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        return explain.why(ctx.session, ctx.actor, record_id)


@explain_router.post("/{record_id}/verify")
def verify_decision(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        explain.why(ctx.session, ctx.actor, record_id)
        return explain.verify(ctx.session, record_id)


graph_router = APIRouter(prefix="/graph", tags=["graph"])


@graph_router.get("/decision/{decision_id}")
def graph_decision(decision_id: UUID, request: Request) -> dict[str, Any]:
    """Authorization is decided by Postgres first; the graph only holds IDs and labels."""
    with request_context(request) as ctx:
        explain.why(ctx.session, ctx.actor, decision_id)
        tenant_id = ctx.actor.tenant_id
    return graph.query(tenant_id, "decision_chain", id=str(decision_id))


@graph_router.get("/{view}")
def graph_view(view: str, request: Request) -> dict[str, Any]:
    roles = GRAPH_VIEWS.get(view)
    if roles is None:
        raise NotFound("Unknown graph view")
    with request_context(request) as ctx:
        require_role(ctx.actor, roles)
        tenant_id = ctx.actor.tenant_id
    return graph.query(tenant_id, view)


ai_router = APIRouter(prefix="/ai", tags=["ai"])


def _run_json(run: AgentRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "agent": run.agent,
        "pack": run.pack,
        "status": run.status,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": str(run.cost_usd),
        "error": run.error,
        "trace_id": run.trace_id,
        "started_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@ai_router.get("/runs")
def list_runs(request: Request, limit: int = Query(default=50, le=200)) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_ROLES)
        rows = ctx.session.scalars(
            select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        )
        return [_run_json(run) for run in rows]


@ai_router.get("/runs/{run_id}")
def get_run(run_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_ROLES)
        run = ctx.session.get(AgentRun, run_id)
        if run is None:
            raise NotFound("Run not found")
        steps = ctx.session.scalars(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.created_at)
        )
        return {
            **_run_json(run),
            "steps": [
                {
                    "name": step.name,
                    "tier": step.tier,
                    "provider": step.provider,
                    "model": step.model,
                    "prompt_hash": step.prompt_hash,
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "cost_usd": str(step.cost_usd),
                    "latency_ms": step.latency_ms,
                    "cached": step.cached,
                    "fallback": step.fallback,
                }
                for step in steps
            ],
        }


people_router = APIRouter(prefix="/people", tags=["people"])


@people_router.get("/employees")
def list_employees(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, PEOPLE_ROLES)
        return [
            {
                "id": str(e.id),
                "external_id": e.external_id,
                "person_id": str(e.person_id),
                "display_name": e.display_name,
                "email": e.email,
                "org_unit_id": str(e.org_unit_id),
                "position_id": str(e.position_id),
                "manager_id": str(e.manager_id) if e.manager_id else None,
                "start_date": e.start_date.isoformat(),
                "status": e.status,
            }
            for e in ctx.session.scalars(select(Employee).order_by(Employee.external_id))
        ]


@people_router.get("/org")
def org_reference(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, PEOPLE_ROLES)
        session = ctx.session
        return {
            "org_units": [
                {"id": str(o.id), "external_id": o.external_id, "name": o.name}
                for o in session.scalars(select(OrgUnit).order_by(OrgUnit.name))
            ],
            "positions": [
                {"id": str(p.id), "external_id": p.external_id, "title": p.title}
                for p in session.scalars(select(Position).order_by(Position.title))
            ],
            "skills": [
                {"id": str(s.id), "external_id": s.external_id, "name": s.name}
                for s in session.scalars(select(Skill).order_by(Skill.name))
            ],
            "kpis": [
                {
                    "id": str(k.id),
                    "external_id": k.external_id,
                    "name": k.name,
                    "unit": k.unit,
                    "owner_pack": k.owner_pack,
                }
                for k in session.scalars(select(KpiDefinition).order_by(KpiDefinition.name))
            ],
        }


registry_router = APIRouter(prefix="/registry", tags=["registry"])


@registry_router.get("/packs")
def list_packs(request: Request) -> list[dict[str, Any]]:
    with request_context(request):
        return registry.pack_listing()


def install(app: FastAPI) -> None:
    from kernel.comms.api import router as comms_router
    from kernel.knowledge.api import router as knowledge_router

    @app.exception_handler(KernelError)
    def handle_kernel_error(_: Request, exc: KernelError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": exc.code, "message": exc.message}
        )

    for router in (
        auth_router,
        trust_router,
        explain_router,
        graph_router,
        ai_router,
        people_router,
        registry_router,
        comms_router,
        knowledge_router,
    ):
        app.include_router(router)
