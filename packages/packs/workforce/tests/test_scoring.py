"""Overload-scorer tests. Runs under pytest, or standalone: `python test_scoring.py`.

Proves the factor-sum is exact and that, on the real seed, Engineering is
overloaded in week 4 while a normal team is not (scenario S5) — and that the
score is purely team-level (no per-person input exists).
"""

import csv
import pathlib
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import scoring  # noqa: E402

SEED = pathlib.Path(__file__).resolve().parents[4] / "seed" / "workforce"


# --- unit tests -----------------------------------------------------------

def test_weights_sum_to_one():
    assert scoring.W_OVERTIME + scoring.W_COVERAGE + scoring.W_OPEN == Decimal("1")


def test_factors_sum_to_score():
    tw = scoring.TeamWeek("ORG-ENG", "W", headcount=10, actual_hours=Decimal("570"), on_leave_count=1, open_reqs=1)
    result = scoring.score_overload(tw)
    assert sum((f.contribution for f in result.factors), Decimal(0)) == result.score


def test_clearly_overloaded_team_triggers_alert():
    tw = scoring.TeamWeek("ORG-ENG", "W", headcount=10, actual_hours=Decimal("570"), on_leave_count=1, open_reqs=1)
    result = scoring.score_overload(tw)
    assert scoring.is_overloaded(result)
    overtime = next(f for f in result.factors if f.key == "overtime")
    assert overtime.value == Decimal("1.0000")  # 57h avg is >= 15h over the 40h baseline


def test_normal_team_does_not_trigger():
    tw = scoring.TeamWeek("ORG-FIN", "W", headcount=6, actual_hours=Decimal("240"), on_leave_count=0, open_reqs=0)
    result = scoring.score_overload(tw)
    assert not scoring.is_overloaded(result)
    assert result.score == Decimal("0.0000")


def test_zero_headcount_is_safe():
    tw = scoring.TeamWeek("ORG-X", "W", headcount=0, actual_hours=Decimal("0"))
    assert scoring.score_overload(tw).score == Decimal("0.0000")


# --- against the real seed ------------------------------------------------

def _team_week(org_unit_id, week):
    hours = Decimal(0)
    heads = set()
    for r in csv.DictReader(open(SEED / "time_entries.csv", encoding="utf-8")):
        if r["org_unit_id"] == org_unit_id and r["week"] == week:
            hours += Decimal(r["hours"])
            heads.add(r["employee_id"])
    return scoring.TeamWeek(org_unit_id, week, headcount=len(heads), actual_hours=hours, on_leave_count=1, open_reqs=1)


def test_seed_engineering_overloaded_in_week4():
    result = scoring.score_overload(_team_week("ORG-ENG", "2026-W43"))
    assert scoring.is_overloaded(result), result.score


def test_seed_finance_not_overloaded_in_week4():
    result = scoring.score_overload(_team_week("ORG-FIN", "2026-W43"))
    assert not scoring.is_overloaded(result), result.score


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
