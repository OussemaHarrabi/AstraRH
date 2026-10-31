"""Deterministic conflict detection for the workforce pack.

Pure functions: no database, no model, no randomness. Clash detection is
fully unit-testable offline, before platform-v0 exists (invariant 5: the
LLM never computes decisions). Detection never changes any record — at
platform-v0 a clash feeds the agent that drafts a fix for a manager to
approve (R2).

Two kinds (brief: "operational conflict"):
  * leave_overlap        — two people on the same team on leave at once
  * shift_double_booking — one person booked on two overlapping shifts
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LeaveInterval:
    request_id: str
    employee_id: str
    org_unit_id: str
    start: date
    end: date


@dataclass(frozen=True)
class ShiftInterval:
    shift_id: str
    employee_id: str
    day: date
    start_min: int  # minutes from midnight
    end_min: int


@dataclass(frozen=True)
class Clash:
    kind: str  # "leave_overlap" | "shift_double_booking"
    org_unit_id: str
    a: str  # first id (request_id or shift_id)
    b: str  # second id
    employee_a: str
    employee_b: str
    detail: str


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Inclusive date-range overlap."""
    return a_start <= b_end and b_start <= a_end


def minutes(hhmm: str) -> int:
    """'16:00' -> 960. Helper for building ShiftInterval from seed data."""
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def detect_leave_clashes(intervals: list[LeaveInterval]) -> list[Clash]:
    """Same-team leave requests whose date ranges overlap.

    Deterministic order (by team, then date, then id) so output never
    depends on input order. Two requests by the same person are not a
    coverage clash and are skipped here.
    """
    items = sorted(intervals, key=lambda i: (i.org_unit_id, i.start, i.request_id))
    clashes: list[Clash] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.org_unit_id != b.org_unit_id:
                continue
            if a.employee_id == b.employee_id:
                continue
            if _overlaps(a.start, a.end, b.start, b.end):
                clashes.append(
                    Clash(
                        kind="leave_overlap",
                        org_unit_id=a.org_unit_id,
                        a=a.request_id,
                        b=b.request_id,
                        employee_a=a.employee_id,
                        employee_b=b.employee_id,
                        detail=(
                            f"{a.employee_id} ({a.start}..{a.end}) overlaps "
                            f"{b.employee_id} ({b.start}..{b.end}) in {a.org_unit_id}"
                        ),
                    )
                )
    return clashes


def detect_shift_clashes(shifts: list[ShiftInterval]) -> list[Clash]:
    """One employee booked on two overlapping shifts on the same day."""
    items = sorted(shifts, key=lambda s: (s.employee_id, s.day, s.start_min, s.shift_id))
    clashes: list[Clash] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.employee_id != b.employee_id or a.day != b.day:
                continue
            if a.start_min < b.end_min and b.start_min < a.end_min:
                clashes.append(
                    Clash(
                        kind="shift_double_booking",
                        org_unit_id="",
                        a=a.shift_id,
                        b=b.shift_id,
                        employee_a=a.employee_id,
                        employee_b=b.employee_id,
                        detail=f"{a.employee_id} double-booked on {a.day}: {a.shift_id} and {b.shift_id}",
                    )
                )
    return clashes
