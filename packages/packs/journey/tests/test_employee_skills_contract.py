"""Contract tests for the journey roster and employee skill evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = REPO_ROOT / "seed" / "journey"
HERO = "EMP-041"
SOURCES = {"manager", "applied_evidence", "assessment", "self"}


def read_csv(name: str) -> list[dict[str, str]]:
    with (SEED / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def roster() -> list[dict[str, object]]:
    payload = json.loads((SEED / "roster.json").read_text(encoding="utf-8"))
    return list(payload["employees"])


def engineering_ids() -> set[str]:
    return {
        str(row["employee_id"])
        for row in roster()
        if row["org_unit_id"] == "ORG-ENG" and row["employee_id"] != HERO
    }


def test_roster_matches_the_demo_world_ids():
    employees = roster()
    ids = [str(row["employee_id"]) for row in employees]
    assert len(ids) == 41
    assert len(ids) == len(set(ids))
    assert ids[:9] == [f"EMP-{number:03d}" for number in range(1, 10)]
    assert HERO in ids
    assert len(engineering_ids()) == 14


def test_employee_skills_cover_every_employee_except_the_hero():
    rows = read_csv("employee_skills.csv")
    assert rows
    employees = {row["employee_id"] for row in rows}
    assert employees == {f"EMP-{number:03d}" for number in range(1, 41)}
    assert HERO not in employees
    for row in rows:
        assert row["skill_id"].startswith("SKILL-")
        assert 1 <= int(row["level"]) <= 4
        assert row["source"] in SOURCES
        assert row["evidence"]


def test_no_duplicate_employee_skill_pairs():
    rows = read_csv("employee_skills.csv")
    pairs = [(row["employee_id"], row["skill_id"]) for row in rows]
    assert len(pairs) == len(set(pairs))


def test_nine_engineering_kubernetes_gaps_power_the_heatmap():
    rows = read_csv("employee_skills.csv")
    engineering = engineering_ids()
    gaps = {
        row["employee_id"]
        for row in rows
        if row["skill_id"] == "SKILL-K8S"
        and row["employee_id"] in engineering
        and int(row["level"]) < 3
    }
    assert gaps == {f"EMP-{number:03d}" for number in range(16, 25)}
    non_gaps = {
        row["employee_id"]
        for row in rows
        if row["skill_id"] == "SKILL-K8S"
        and row["employee_id"] in engineering
        and int(row["level"]) >= 3
    }
    assert non_gaps == {"EMP-009", "EMP-025", "EMP-026"}


def test_emp_009_is_the_only_observability_holder_in_engineering():
    rows = read_csv("employee_skills.csv")
    engineering = engineering_ids()
    holders = {
        row["employee_id"]
        for row in rows
        if row["skill_id"] == "SKILL-OBS" and row["employee_id"] in engineering
    }
    assert holders == {"EMP-009"}
    emp_009 = next(
        row
        for row in rows
        if row["employee_id"] == "EMP-009" and row["skill_id"] == "SKILL-OBS"
    )
    assert int(emp_009["level"]) == 4
    assert emp_009["source"] == "applied_evidence"


def test_every_employee_has_at_least_two_evidence_rows():
    rows = read_csv("employee_skills.csv")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["employee_id"]] = counts.get(row["employee_id"], 0) + 1
    assert set(counts) == {f"EMP-{number:03d}" for number in range(1, 41)}
    assert all(count >= 2 for count in counts.values())


def test_employee_skills_header_is_stable():
    with (SEED / "employee_skills.csv").open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == ["employee_id", "skill_id", "level", "source", "evidence"]
