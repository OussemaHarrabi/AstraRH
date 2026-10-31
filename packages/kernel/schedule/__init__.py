"""Calendars: real free slots, and booking with no double booking possible.

Slots are found by arithmetic on calendar data. No model is involved, so a slot can't be invented.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.schedule.models import Booking, BookingSeat, BusyBlock
from kernel.trust import AdapterRejected

__all__ = ["Booking", "BookingSeat", "BusyBlock", "Slot", "book", "find_slots", "free_slots"]

TIMEZONE = ZoneInfo("Africa/Tunis")
WORK_START = time(9, 0)
WORK_END = time(17, 0)
SLOT_STEP = timedelta(minutes=30)
DEFAULT_DURATION = timedelta(minutes=45)
SEARCH_DAYS = 14
MINIMUM_NOTICE = timedelta(hours=24)


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


def _busy_for(session: Session, participants: list[str]) -> list[tuple[datetime, datetime]]:
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
    return [(row[0], row[1]) for row in [*blocks, *seats]]


def find_slots(
    session: Session, participants: list[str], duration: timedelta = DEFAULT_DURATION
) -> list[Slot]:
    return free_slots(_busy_for(session, participants), utcnow(), duration)


def book(
    session: Session,
    tenant_id: UUID,
    participants: list[str],
    starts_at: datetime,
    ends_at: datetime,
    title: str,
    ref: dict[str, Any] | None = None,
) -> Booking:
    """Re-checks at the last moment, because calendars change after slots are proposed."""
    for busy_start, busy_end in _busy_for(session, participants):
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
    return booking
