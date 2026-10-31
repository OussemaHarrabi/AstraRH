"""Finance API."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from kernel.authz import require_role
from kernel.web import request_context
from packs.finance import service
from packs.finance.models import RuleSetRecord
from packs.finance.payroll import calc

READ_ROLES = {"admin", "finance", "hr", "auditor"}
WRITE_ROLES = {"admin", "finance"}
MAX_SCENARIOS = 6

router = APIRouter()


class NetBody(BaseModel):
    gross: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    head_of_family: bool = False
    children: list[Literal["child", "student", "disabled"]] = Field(
        default_factory=list, max_length=20
    )
    on: date | None = None


class CompareBody(BaseModel):
    on: date | None = None
    scenarios: list[NetBody] = Field(min_length=1, max_length=MAX_SCENARIOS)


class RuleSetBody(BaseModel):
    definition: dict[str, Any]


def _input(body: NetBody) -> calc.PayslipInput:
    return calc.PayslipInput(body.gross, body.head_of_family, tuple(body.children))


def _summary(record: RuleSetRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "rule_id": record.rule_id,
        "version": record.version,
        "jurisdiction": record.jurisdiction,
        "status": record.status,
        "valid_from": record.valid_from.isoformat(),
        "valid_to": record.valid_to.isoformat() if record.valid_to else None,
        "is_demo": record.is_demo,
        "source_ref": record.source_ref,
        "definition_hash": record.definition_hash,
    }


@router.post("/calculator/net", summary="Gross to net, line by line. Nothing is stored.")
def calculate_net(body: NetBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        return service.calculate_net(ctx.session, _input(body), body.on or service.today_in_tunis())


@router.post("/calculator/compare", summary="Several gross-to-net scenarios side by side")
def compare(body: CompareBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        return {
            "scenarios": [
                service.calculate_net(
                    ctx.session, _input(item), item.on or body.on or service.today_in_tunis()
                )
                for item in body.scenarios
            ]
        }


@router.get("/rule-sets", summary="Rule sets, without their full definitions")
def list_rule_sets(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        rows = ctx.session.scalars(
            select(RuleSetRecord).order_by(RuleSetRecord.valid_from, RuleSetRecord.rule_id)
        ).all()
        return [_summary(row) for row in rows]


@router.get("/rule-sets/{record_id}", summary="One rule set with its full definition")
def get_rule_set(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        record = service.get_rule_set(ctx.session, record_id)
        return {**_summary(record), "definition": record.definition}


@router.post("/rule-sets", status_code=201, summary="Save a new rule set as a draft")
def create_rule_set(body: RuleSetBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        record = service.create_rule_set(ctx.session, ctx.actor.tenant_id, body.definition)
        return _summary(record)


@router.post("/rule-sets/{record_id}/test", summary="Run the rule set's hand-checked examples")
def test_rule_set(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        record = service.get_rule_set(ctx.session, record_id)
        return service.example_report(service.parse_definition(record.definition))


@router.post(
    "/rule-sets/{record_id}/activate",
    status_code=202,
    summary="Propose activating a rule set. A different person must approve it.",
)
def activate_rule_set(record_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        proposal = service.request_activation(
            ctx.session, ctx.actor.tenant_id, ctx.actor, record_id
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}
