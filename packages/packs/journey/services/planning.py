"""Deterministic scheduling and attention rules for the journey pack.

Dates, phases, "today's three things", support flags and the dossier are Python.
No LLM, no kernel imports. Holidays are data; the demo list must be replaced with
the official calendar before a real deployment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

# Demo list for the fictional company. Replace with the official Tunisian
# calendar before any real deployment; the function takes holidays as data.
DEMO_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2026, 1, 1),  # New Year
        date(2026, 3, 20),  # Independence Day
        date(2026, 5, 1),  # Labour Day
        date(2026, 7, 25),  # Republic Day
        date(2026, 8, 13),  # Women's Day
        date(2026, 10, 15),  # Evacuation Day
        date(2026, 12, 17),  # Revolution Day
    }
)

OPEN_STATUSES = frozenset({"pending", "in_progress", "blocked"})
LOW_ANSWER_KEYS = ("access_ready", "role_clarity", "manager_support")
CHECKIN_DAYS = (("day7", 7), ("day30", 30), ("day60", 60), ("day90", 90))


def is_working_day(day: date, holidays: Iterable[date] = DEMO_HOLIDAYS) -> bool:
    return day.weekday() < 5 and day not in set(holidays)


def add_working_days(
    start: date,
    days: int,
    holidays: Iterable[date] = DEMO_HOLIDAYS,
) -> date:
    """Move `days` working days from `start`. Zero keeps the anchor date."""
    if days == 0:
        return start
    holiday_set = set(holidays)
    step = 1 if days > 0 else -1
    remaining = abs(days)
    current = start
    while remaining:
        current += timedelta(days=step)
        if current.weekday() < 5 and current not in holiday_set:
            remaining -= 1
    return current


def due_at(
    start: date,
    due_day: int,
    holidays: Iterable[date] = DEMO_HOLIDAYS,
    at: time = time(9, 0),
) -> datetime:
    """A task due on a working day at 09:00. Day 0 is the start anchor."""
    return datetime.combine(add_working_days(start, due_day, holidays), at)


def checkin_schedule(
    start: date,
    holidays: Iterable[date] = DEMO_HOLIDAYS,
) -> list[tuple[str, datetime]]:
    """The four check-in milestones, anchored on working days from the start date."""
    return [(kind, due_at(start, day, holidays)) for kind, day in CHECKIN_DAYS]


def phase_for_day(day: int) -> str:
    """The plan phase for a day offset from the start date."""
    if day < 0:
        return "preboarding"
    if day == 0:
        return "day1"
    if day <= 7:
        return "week1"
    if day <= 30:
        return "day30"
    if day <= 60:
        return "day60"
    if day <= 90:
        return "day90"
    return "completed"


def working_days_between(
    start: date,
    end: date,
    holidays: Iterable[date] = DEMO_HOLIDAYS,
) -> int:
    """Signed number of working days between two dates. Used for the plan phase."""
    if end < start:
        return -working_days_between(end, start, holidays)
    holiday_set = set(holidays)
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holiday_set:
            count += 1
    return count


def expand_template(
    template: Mapping[str, Any],
    start: date,
    holidays: Iterable[date] = DEMO_HOLIDAYS,
) -> list[dict[str, Any]]:
    """Instantiate a template's tasks with working-day due dates and phases."""
    tasks: list[dict[str, Any]] = []
    for position, task in enumerate(template.get("tasks", []), start=1):
        due_day = int(task["due_day"])
        row = dict(task)
        row.setdefault("position", position)
        row["due_day"] = due_day
        row["due_at"] = due_at(start, due_day, holidays)
        row.setdefault("phase", phase_for_day(due_day))
        row["status"] = row.get("status", "pending")
        tasks.append(row)
    return tasks


def next_three(
    tasks: Sequence[Mapping[str, Any]],
    now: datetime,
    limit: int = 3,
) -> list[Mapping[str, Any]]:
    """The portal's "today: 3 things". Mandatory and soonest first; completed excluded."""
    open_tasks = [
        task
        for task in tasks
        if str(task.get("status", "pending")) in OPEN_STATUSES and task.get("due_at") is not None
    ]
    open_tasks.sort(
        key=lambda task: (
            task["due_at"],
            0 if task.get("mandatory") else 1,
            int(task.get("position", 0)),
            str(task.get("title", "")),
        )
    )
    return open_tasks[:limit]


@dataclass(frozen=True)
class Attention:
    """Facts, not a score. The UI may say "needs attention"; it never predicts attrition."""

    level: str
    facts: tuple[str, ...]
    codes: tuple[str, ...]


def attention(
    tasks: Sequence[Mapping[str, Any]],
    checkins: Sequence[Mapping[str, Any]],
    now: datetime,
    *,
    overdue_after_days: int = 3,
    missed_after_days: int = 5,
    low_threshold: int = 2,
) -> Attention:
    """Derive support flags from facts: overdue tasks, missed check-ins, low structured answers."""
    facts: list[str] = []
    codes: list[str] = []

    overdue_cutoff = now - timedelta(days=overdue_after_days)
    overdue = [
        task
        for task in tasks
        if str(task.get("status", "pending")) in OPEN_STATUSES
        and task.get("due_at") is not None
        and task["due_at"] < overdue_cutoff
        and bool(task.get("mandatory"))
    ]
    if overdue:
        codes.append("mandatory_task_overdue")
        titles = ", ".join(str(task.get("title", "task")) for task in overdue[:3])
        facts.append(
            f"{len(overdue)} mandatory task(s) overdue by more than "
            f"{overdue_after_days} days: {titles}"
        )

    missed_cutoff = now - timedelta(days=missed_after_days)
    missed = [
        checkin
        for checkin in checkins
        if str(checkin.get("status", "pending")) == "pending"
        and checkin.get("scheduled_at") is not None
        and checkin["scheduled_at"] < missed_cutoff
    ]
    if missed:
        codes.append("checkin_missed")
        kinds = ", ".join(str(item.get("kind", "check-in")) for item in missed)
        facts.append(f"{len(missed)} check-in(s) more than {missed_after_days} days late: {kinds}")

    low: list[str] = []
    for checkin in checkins:
        answers = checkin.get("answers") or {}
        for key in LOW_ANSWER_KEYS:
            value = answers.get(key)
            if isinstance(value, int) and value <= low_threshold:
                low.append(f"{key}={value}")
    if low:
        codes.append("low_structured_answer")
        facts.append("Low self-reported answers: " + ", ".join(low))

    if not facts:
        return Attention(level="none", facts=(), codes=())
    return Attention(level="needs_attention", facts=tuple(facts), codes=tuple(codes))


def dossier(
    tasks: Sequence[Mapping[str, Any]],
    checkins: Sequence[Mapping[str, Any]],
    gaps: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The Day-90 review pack. Evidence and missing items only; no salary, rating or ranking."""
    completed = [
        task for task in tasks if str(task.get("status")) in {"completed", "verified"}
    ]
    with_evidence = [task for task in completed if task.get("evidence") not in (None, "", {}, [])]
    missing = [
        str(task.get("title", "task"))
        for task in tasks
        if str(task.get("status")) not in {"completed", "verified"}
        or task.get("evidence") in (None, "", {}, [])
    ]
    verified = [
        {
            "skill_id": gap.get("skill_id"),
            "level": gap.get("current_level"),
        }
        for gap in gaps
        if str(gap.get("status")) in {"verified", "closed"}
    ]
    return {
        "tasks_total": len(tasks),
        "tasks_completed": len(completed),
        "tasks_with_evidence": len(with_evidence),
        "missing": missing,
        "checkins_completed": sum(
            1 for checkin in checkins if str(checkin.get("status")) == "completed"
        ),
        "verified_skills": verified,
        "note": "Assembled for a human decision. No salary, rating or recommendation is included.",
    }

