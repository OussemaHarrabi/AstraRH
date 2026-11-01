"""Overload-scorer tests. Runs under pytest in the container (kernel importable),
or standalone inside a container: `python test_scoring.py`.

Proves the factor-sum is exact (the kernel's explain layer rejects it otherwise)
and that, on the real seed, Engineering is overloaded in week 4 while a normal
team is not. The score is purely team-level — no per-person input exists.
"""

import csv
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from packs.workforce import scoring  # noqa: E402

SEED = pathlib.Path(__file__).resolve().parents[4] / "data" / "workforce"


def test_weights_sum_to_one():
    assert scoring.W_OVERTIME + scoring.W_COVERAGE + scoring.W_OPEN == Decimal("1")


def test_factors_sum_to_score():
    result = scoring.score(scoring.team_inputs(10, "570", on_leave_count=1, open_reqs=1))
    assert sum((f.contribution for f in result.factors), Decimal(0)) == result.score


def test_contribution_is_weight_times_value():
    result = scoring.score(scoring.team_inputs(10, "570", on_leave_count=1, open_reqs=1))
    for factor in result.factors:
        assert factor.weight * factor.value == factor.contribution


def test_clearly_overloaded_team_triggers_alert():
    result = scoring.score(scoring.team_inputs(17, "971", on_leave_count=1, open_reqs=1))
    assert scoring.is_overloaded(result)
    overtime = next(f for f in result.factors if f.key == "overtime")
    assert overtime.value == Decimal("1.0000")


def test_normal_team_does_not_trigger():
    result = scoring.score(scoring.team_inputs(6, "240"))
    assert not scoring.is_overloaded(result)
    assert result.score == Decimal("0")


def test_zero_headcount_is_safe():
    assert scoring.score(scoring.team_inputs(0, "0")).score == Decimal("0")


def _team_week(org_unit_id, week):
    hours = Decimal(0)
    heads = set()
    for r in csv.DictReader(open(SEED / "time_entries.csv", encoding="utf-8")):
        if r["org_unit_id"] == org_unit_id and r["week"] == week:
            hours += Decimal(r["hours"])
            heads.add(r["employee_id"])
    return scoring.team_inputs(len(heads), hours, on_leave_count=1, open_reqs=1)


def test_seed_engineering_overloaded_in_week4():
    result = scoring.score(_team_week("ORG-ENG", "2026-W43"))
    assert scoring.is_overloaded(result), result.score


def test_seed_product_team_not_overloaded_in_week4():
    result = scoring.score(_team_week("ORG-PRD", "2026-W43"))
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
