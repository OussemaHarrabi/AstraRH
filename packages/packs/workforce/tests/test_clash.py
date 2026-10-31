"""Clash-detection tests. Runs under pytest, or standalone: `python test_clash.py`.

Includes checks against the real seed in seed/workforce/, proving the planted
clashes (scenarios S2 and S4) and that there are no accidental ones.
"""

import csv
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import clash  # noqa: E402

SEED = pathlib.Path(__file__).resolve().parents[4] / "seed" / "workforce"


# --- unit tests -----------------------------------------------------------

def test_same_team_overlap_is_a_clash():
    items = [
        clash.LeaveInterval("A", "E1", "ORG-ENG", date(2026, 11, 16), date(2026, 11, 20)),
        clash.LeaveInterval("B", "E2", "ORG-ENG", date(2026, 11, 18), date(2026, 11, 24)),
    ]
    assert len(clash.detect_leave_clashes(items)) == 1


def test_different_teams_do_not_clash():
    items = [
        clash.LeaveInterval("A", "E1", "ORG-ENG", date(2026, 11, 16), date(2026, 11, 20)),
        clash.LeaveInterval("B", "E2", "ORG-SAL", date(2026, 11, 16), date(2026, 11, 20)),
    ]
    assert clash.detect_leave_clashes(items) == []


def test_non_overlapping_dates_do_not_clash():
    items = [
        clash.LeaveInterval("A", "E1", "ORG-ENG", date(2026, 11, 16), date(2026, 11, 20)),
        clash.LeaveInterval("B", "E2", "ORG-ENG", date(2026, 11, 21), date(2026, 11, 24)),
    ]
    assert clash.detect_leave_clashes(items) == []


def test_order_independent():
    a = clash.LeaveInterval("A", "E1", "ORG-ENG", date(2026, 11, 16), date(2026, 11, 20))
    b = clash.LeaveInterval("B", "E2", "ORG-ENG", date(2026, 11, 18), date(2026, 11, 24))
    assert clash.detect_leave_clashes([a, b]) == clash.detect_leave_clashes([b, a])


def test_shift_overlap_same_person_is_a_clash():
    shifts = [
        clash.ShiftInterval("S1", "E1", date(2026, 11, 6), clash.minutes("08:00"), clash.minutes("16:00")),
        clash.ShiftInterval("S2", "E1", date(2026, 11, 6), clash.minutes("12:00"), clash.minutes("20:00")),
    ]
    assert len(clash.detect_shift_clashes(shifts)) == 1


def test_adjacent_shifts_do_not_clash():
    shifts = [
        clash.ShiftInterval("S1", "E1", date(2026, 11, 6), clash.minutes("08:00"), clash.minutes("16:00")),
        clash.ShiftInterval("S2", "E1", date(2026, 11, 6), clash.minutes("16:00"), clash.minutes("23:00")),
    ]
    assert clash.detect_shift_clashes(shifts) == []


# --- against the real seed ------------------------------------------------

def _leave_intervals_from_seed():
    org = {r["employee_id"]: r["org_unit_id"] for r in csv.DictReader(open(SEED / "employees.csv", encoding="utf-8"))}
    out = []
    for r in csv.DictReader(open(SEED / "leave_requests.csv", encoding="utf-8")):
        out.append(
            clash.LeaveInterval(
                r["leave_request_id"], r["employee_id"], org[r["employee_id"]],
                date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]),
            )
        )
    return out


def test_seed_has_exactly_two_leave_clashes():
    clashes = clash.detect_leave_clashes(_leave_intervals_from_seed())
    assert len(clashes) == 2, [c.detail for c in clashes]
    pairs = {frozenset((c.a, c.b)) for c in clashes}
    assert pairs == {frozenset(("LR-001", "LR-002")), frozenset(("LR-003", "LR-004"))}
    assert all(c.org_unit_id == "ORG-ENG" for c in clashes)


def test_seed_has_exactly_one_shift_clash():
    shifts = [
        clash.ShiftInterval(
            r["shift_id"], r["employee_id"], date.fromisoformat(r["date"]),
            clash.minutes(r["start"]), clash.minutes(r["end"]),
        )
        for r in csv.DictReader(open(SEED / "shifts.csv", encoding="utf-8"))
    ]
    clashes = clash.detect_shift_clashes(shifts)
    assert len(clashes) == 1, [c.detail for c in clashes]
    assert clashes[0].employee_a == "EMP-029"
    assert {clashes[0].a, clashes[0].b} == {"SH-010", "SH-011"}


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"ok   {_name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {_name}: {exc}")
    sys.exit(1 if failures else 0)
