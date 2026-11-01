"""Calendars: real free slots, holds on offered slots, and booking with no double booking possible.

Slots are found by arithmetic on calendar data. No model is involved, so a slot can't be invented.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.schedule.models import Booking, BookingSeat, BusyBlock, Hold
from kernel.trust import AdapterRejected

__all__ = [
    "replace_imported",
    "Booking",
    "BookingSeat",
    "BusyBlock",
    "Hold",
    "Slot",
    "book",
    "cancel",
    "find_slots",
    "free_slots",
    "hold",
    "release",
]

TIMEZONE = ZoneInfo("Africa/Tunis")
WORK_START = time(9, 0)
WORK_END = time(17, 0)
SLOT_STEP = timedelta(minutes=30)
DEFAULT_DURATION = timedelta(minutes=45)
SEARCH_DAYS = 14
MINIMUM_NOTICE = timedelta(hours=24)
# Long enough for a candidate to answer, short enough that a silent one doesn't block a calendar.
HOLD_TTL = timedelta(hours=72)


@dataclass(frozen=True)
class Slot:
    starts_at: datetime
    ends_at: datetime

    def as_json(self) -> dict[str, str]:
        return {"starts_at": self.starts_at.isoformat(), "ends_at": self.ends_at.isoformat()}


def free_slots(
    busy: list[tuple[datetime, datetime]],
    now: datetime,
    duration: timedelta = DEFAULT_DURATION,
    count: int = 3,
    timezone: ZoneInfo = TIMEZONE,
) -> list[Slot]:
    """Earliest free slots in working hours on weekdays, at most one per day, for real choice."""
    earliest = now + MINIMUM_NOTICE
    found: list[Slot] = []
    local_day = earliest.astimezone(timezone).date()
    for _ in range(SEARCH_DAYS):
        if local_day.weekday() < 5:
            start = datetime.combine(local_day, WORK_START, tzinfo=timezone)
            day_end = datetime.combine(local_day, WORK_END, tzinfo=timezone)
            while start + duration <= day_end:
                end = start + duration
                clash = any(start < busy_end and busy_start < end for busy_start, busy_end in busy)
                if start >= earliest and not clash:
                    found.append(Slot(start, end))
                    break
                start += SLOT_STEP
        if len(found) == count:
            break
        local_day += timedelta(days=1)
    return found


def _busy_for(
    session: Session, participants: list[str], ignore_owner: str | None = None
) -> list[tuple[datetime, datetime]]:
    """Busy time, bookings, and live holds. A holder's own holds don't block its own booking."""
    blocks = session.execute(
        select(BusyBlock.starts_at, BusyBlock.ends_at).where(
            BusyBlock.participant.in_(participants)
        )
    ).all()
    seats = session.execute(
        select(BookingSeat.starts_at, BookingSeat.ends_at).where(
            BookingSeat.participant.in_(participants)
        )
    ).all()
    holds_query = select(Hold.starts_at, Hold.ends_at).where(
        Hold.participant.in_(participants), Hold.expires_at > utcnow()
    )
    if ignore_owner:
        holds_query = holds_query.where(Hold.owner != ignore_owner)
    holds = session.execute(holds_query).all()
    return [(row[0], row[1]) for row in [*blocks, *seats, *holds]]


def lock_calendars(session: Session, participants: list[str]) -> None:
    """Until commit, nobody else can offer these people's time. Sorted, so two callers can't deadlock."""
    for participant in sorted(set(participants)):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"calendar:{participant}"},
        )


def find_slots(
    session: Session,
    participants: list[str],
    duration: timedelta = DEFAULT_DURATION,
    ignore_owner: str | None = None,
    count: int = 3,
) -> list[Slot]:
    return free_slots(_busy_for(session, participants, ignore_owner), utcnow(), duration, count)


def replace_imported(
    session: Session,
    tenant_id: UUID,
    participant: str,
    blocks: list[tuple[datetime, datetime]],
) -> int:
    """A new calendar file replaces the last one. Hand-entered busy time is kept."""
    session.execute(
        delete(BusyBlock).where(BusyBlock.participant == participant, BusyBlock.source == "ics")
    )
    for starts_at, ends_at in blocks:
        session.add(
            BusyBlock(
                tenant_id=tenant_id,
                participant=participant,
                starts_at=starts_at,
                ends_at=ends_at,
                label="Busy",
                source="ics",
            )
        )
    session.flush()
    return len(blocks)


def hold(
    session: Session,
    tenant_id: UUID,
    participants: list[str],
    slots: list[Slot],
    owner: str,
    ttl: timedelta = HOLD_TTL,
) -> datetime:
    """Keep offered slots from being offered to someone else. Replaces the owner's older holds."""
    release(session, owner)
    expires_at = utcnow() + ttl
    for slot in slots:
        for participant in participants:
            session.add(
                Hold(
                    tenant_id=tenant_id,
                    owner=owner,
                    participant=participant,
                    starts_at=slot.starts_at,
                    ends_at=slot.ends_at,
                    expires_at=expires_at,
                )
            )
    session.flush()
    return expires_at


def release(session: Session, owner: str) -> int:
    return session.execute(delete(Hold).where(Hold.owner == owner)).rowcount


def book(
    session: Session,
    tenant_id: UUID,
    participants: list[str],
    starts_at: datetime,
    ends_at: datetime,
    title: str,
    ref: dict[str, Any] | None = None,
    owner: str | None = None,
) -> Booking:
    """Re-checks at the last moment, because calendars change after slots are proposed."""
    for busy_start, busy_end in _busy_for(session, participants, ignore_owner=owner):
        if starts_at < busy_end and busy_start < ends_at:
            raise AdapterRejected("This slot is no longer free. Propose new slots.")
    booking = Booking(
        tenant_id=tenant_id, title=title, starts_at=starts_at, ends_at=ends_at, ref=ref or {}
    )
    session.add(booking)
    session.flush()
    for participant in participants:
        session.add(
            BookingSeat(
                tenant_id=tenant_id,
                booking_id=booking.id,
                participant=participant,
                starts_at=starts_at,
                ends_at=ends_at,
            )
        )
    try:
        session.flush()
    except IntegrityError as exc:
        raise AdapterRejected("Someone booked this slot at the same moment.") from exc
    if owner:
        release(session, owner)
    return booking


def cancel(session: Session, booking_id: UUID) -> Booking:
    """Frees everyone's time but keeps the booking, so the history stays complete."""
    booking = session.get(Booking, booking_id, with_for_update=True)
    if booking is None:
        raise AdapterRejected("Booking not found")
    if booking.status == "cancelled":
        return booking
    session.execute(delete(BookingSeat).where(BookingSeat.booking_id == booking_id))
    booking.status = "cancelled"
    booking.cancelled_at = utcnow()
    session.flush()
    return booking
