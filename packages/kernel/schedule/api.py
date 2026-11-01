"""Calendar API: a person's busy time, calendar file import, free time and bookings.

Recruiters manage their own calendar. HR and admins can manage anyone's, because they
set up interview panels. Everyone sees only busy or free, never what an event is about.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from kernel import schedule, trust
from kernel.authz import has_role, require_role
from kernel.db import utcnow
from kernel.errors import NotFound, PermissionDenied, ValidationFailed
from kernel.identity.models import UserAccount
from kernel.schedule.ics_import import MAX_BYTES, CalendarFileInvalid, read_busy
from kernel.schedule.models import Booking, BookingSeat, BusyBlock, Hold
from kernel.web import request_context

CALENDAR_ROLES = {"admin", "hr", "recruiter"}
MANAGE_ANYONE = {"admin", "hr"}
IMPORT_PAST = timedelta(days=1)
IMPORT_AHEAD = timedelta(days=90)
LONGEST_VIEW = timedelta(days=62)

router = APIRouter(prefix="/calendar", tags=["calendar"])


class BusyBody(BaseModel):
    participant: str | None = Field(default=None, max_length=320)
    starts_at: datetime
    ends_at: datetime
    label: str = Field(default="Busy", min_length=1, max_length=120)

    @model_validator(mode="after")
    def _sensible(self) -> "BusyBody":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Times need a time zone")
        if self.ends_at <= self.starts_at:
            raise ValueError("The end must be after the start")
        if self.ends_at - self.starts_at > timedelta(days=14):
            raise ValueError("Busy time can be at most 14 days long")
        return self


def _own_email(ctx) -> str:
    email = ctx.session.scalar(select(UserAccount.email).where(UserAccount.id == ctx.actor.user_id))
    if email is None:
        raise NotFound("Your account was not found")
    return email.lower()


def _whose(ctx, participant: str | None) -> str:
    """The calendar this request is about. Only HR and admins may name someone else."""
    require_role(ctx.actor, CALENDAR_ROLES)
    own = _own_email(ctx)
    wanted = (participant or own).strip().lower()
    if wanted != own and not has_role(ctx.actor, MANAGE_ANYONE):
        raise PermissionDenied("You can only manage your own calendar")
    return wanted


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    start = start or utcnow()
    end = end or start + timedelta(days=14)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationFailed("Times need a time zone")
    if end <= start or end - start > LONGEST_VIEW:
        raise ValidationFailed("Pick a window of up to 62 days")
    return start, end


def _log(ctx, data: dict[str, Any]) -> None:
    trust.log_action(
        ctx.session,
        ctx.actor.tenant_id,
        "kernel.calendar.change",
        "human",
        str(ctx.actor.user_id),
        data=data,
    )


@router.get("/busy")
def busy(
    request: Request,
    participant: str | None = Query(default=None, max_length=320),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """Everything that makes someone unavailable: busy time, bookings and held offers."""
    with request_context(request) as ctx:
        who = _whose(ctx, participant)
        start, end = _window(start, end)
        items: list[dict[str, Any]] = []
        for block in ctx.session.scalars(
            select(BusyBlock).where(
                BusyBlock.participant == who,
                BusyBlock.starts_at < end,
                BusyBlock.ends_at > start,
            )
        ):
            items.append(
                {
                    "id": str(block.id),
                    "kind": "busy",
                    "source": block.source,
                    "label": block.label,
                    "starts_at": block.starts_at.isoformat(),
                    "ends_at": block.ends_at.isoformat(),
                }
            )
        for seat, booking in ctx.session.execute(
            select(BookingSeat, Booking)
            .join(Booking, Booking.id == BookingSeat.booking_id)
            .where(
                BookingSeat.participant == who,
                BookingSeat.starts_at < end,
                BookingSeat.ends_at > start,
            )
        ):
            items.append(
                {
                    "id": str(booking.id),
                    "kind": "booking",
                    "label": booking.title,
                    "starts_at": seat.starts_at.isoformat(),
                    "ends_at": seat.ends_at.isoformat(),
                }
            )
        for held in ctx.session.scalars(
            select(Hold).where(
                Hold.participant == who,
                Hold.expires_at > utcnow(),
                Hold.starts_at < end,
                Hold.ends_at > start,
            )
        ):
            items.append(
                {
                    "id": str(held.id),
                    "kind": "hold",
                    "label": "Offered to a candidate",
                    "starts_at": held.starts_at.isoformat(),
                    "ends_at": held.ends_at.isoformat(),
                    "expires_at": held.expires_at.isoformat(),
                }
            )
        items.sort(key=lambda item: item["starts_at"])
        return {
            "participant": who,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "items": items,
        }


@router.post("/busy", status_code=201)
def add_busy(request: Request, body: BusyBody) -> dict[str, Any]:
    with request_context(request) as ctx:
        who = _whose(ctx, body.participant)
        block = BusyBlock(
            tenant_id=ctx.actor.tenant_id,
            participant=who,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            label=body.label,
            source="manual",
        )
        ctx.session.add(block)
        ctx.session.flush()
        _log(ctx, {"participant": who, "change": "added", "busy_id": str(block.id)})
        return {"id": str(block.id), "participant": who}


@router.delete("/busy/{busy_id}", status_code=204)
def remove_busy(request: Request, busy_id: UUID) -> None:
    with request_context(request) as ctx:
        require_role(ctx.actor, CALENDAR_ROLES)
        block = ctx.session.get(BusyBlock, busy_id)
        if block is None:
            raise NotFound("This busy time was not found")
        _whose(ctx, block.participant)
        ctx.session.delete(block)
        _log(ctx, {"participant": block.participant, "change": "removed", "busy_id": str(busy_id)})


@router.post("/import")
async def import_calendar(
    request: Request,
    file: UploadFile = File(...),
    participant: str | None = Form(default=None, max_length=320),
) -> dict[str, Any]:
    """Import an .ics export. It replaces the previous import; hand-entered time stays."""
    data = await file.read(MAX_BYTES + 1)
    with request_context(request) as ctx:
        who = _whose(ctx, participant)
        now = utcnow()
        try:
            found = read_busy(data, now - IMPORT_PAST, now + IMPORT_AHEAD)
        except CalendarFileInvalid as exc:
            raise ValidationFailed(str(exc)) from exc
        count = schedule.replace_imported(
            ctx.session,
            ctx.actor.tenant_id,
            who,
            [(block.starts_at, block.ends_at) for block in found],
        )
        _log(ctx, {"participant": who, "change": "imported", "busy_blocks": count})
        return {"participant": who, "imported": count}


@router.get("/free")
def free(
    request: Request,
    participants: list[str] = Query(default=[], max_length=10),
    minutes: int = Query(default=45, ge=15, le=240),
    count: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    """Times everyone named is free: working hours, weekdays, with notice. Nothing is held."""
    with request_context(request) as ctx:
        require_role(ctx.actor, CALENDAR_ROLES)
        people = sorted({p.strip().lower() for p in participants if p.strip()}) or [_own_email(ctx)]
        slots = schedule.find_slots(ctx.session, people, timedelta(minutes=minutes), count=count)
        return {
            "participants": people,
            "minutes": minutes,
            "slots": [
                {"starts_at": s.starts_at.isoformat(), "ends_at": s.ends_at.isoformat()}
                for s in slots
            ],
        }


@router.get("/bookings")
def bookings(
    request: Request,
    participant: str | None = Query(default=None, max_length=320),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    include_cancelled: bool = False,
) -> dict[str, Any]:
    """Booked meetings. Without a participant, HR sees everyone's; recruiters see their own."""
    with request_context(request) as ctx:
        require_role(ctx.actor, CALENDAR_ROLES)
        start, end = _window(start, end)
        query = select(Booking).where(Booking.starts_at < end, Booking.ends_at > start)
        if not include_cancelled:
            query = query.where(Booking.status == "confirmed")
        if participant or not has_role(ctx.actor, MANAGE_ANYONE):
            who = _whose(ctx, participant)
            query = query.where(
                Booking.id.in_(select(BookingSeat.booking_id).where(BookingSeat.participant == who))
            )
        found = ctx.session.scalars(query.order_by(Booking.starts_at)).all()
        seats: dict[Any, list[str]] = {}
        if found:
            for seat in ctx.session.scalars(
                select(BookingSeat).where(BookingSeat.booking_id.in_([b.id for b in found]))
            ):
                seats.setdefault(seat.booking_id, []).append(seat.participant)
        return {
            "items": [
                {
                    "id": str(b.id),
                    "title": b.title,
                    "status": b.status,
                    "starts_at": b.starts_at.isoformat(),
                    "ends_at": b.ends_at.isoformat(),
                    "participants": sorted(seats.get(b.id, [])),
                    "ref": b.ref,
                }
                for b in found
            ]
        }
