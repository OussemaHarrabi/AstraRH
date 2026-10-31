"""Contract tests for the seed corpus. The data must match DEMO_WORLD and the pack rules."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = REPO_ROOT / "seed" / "journey"

POSITIONS = {
    "POS-BE",
    "POS-FE",
    "POS-DATA",
    "POS-PM",
    "POS-DES",
    "POS-AE",
    "POS-SUP",
    "POS-REC",
    "POS-HRBP",
    "POS-ACC",
    "POS-MGR",
    "POS-CEO",
}
SKILLS = {
    "SKILL-PY",
    "SKILL-SQL",
    "SKILL-FASTAPI",
    "SKILL-K8S",
    "SKILL-DOCKER",
    "SKILL-OBS",
    "SKILL-REACT",
    "SKILL-TS",
    "SKILL-DATA",
    "SKILL-PM",
    "SKILL-UX",
    "SKILL-NEG",
    "SKILL-CRM",
    "SKILL-SUPPORT",
    "SKILL-RECRUIT",
    "SKILL-LABOR",
    "SKILL-ACCT",
    "SKILL-LEAD",
    "SKILL-COMM",
}
KPIS = {"KPI-MTTR", "KPI-RAMP", "KPI-90D", "KPI-TTH", "KPI-COST", "KPI-OVERTIME"}
OWNER_ROLES = {"hr", "manager", "admin", "employee"}
PHASES = {"preboarding", "day1", "week1", "day30", "day60", "day90"}
TASK_KINDS = {"preboarding", "standard", "first_win", "manager_prep"}
FORBIDDEN_SENTIMENT = {
    "feel",
    "feeling",
    "mood",
    "happy",
    "happiness",
    "stress",
    "stressed",
    "sentiment",
    "engagement",
    "burnout",
    "attitude",
}


def read_csv(name: str) -> list[dict[str, str]]:
    with (SEED / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_seed_files_exist():
    for name in (
        "skill_requirements.csv",
        "courses.csv",
        "onboarding_templates.json",
        "pulse_survey.json",
        "scenarios.md",
    ):
        assert (SEED / name).is_file(), name


def test_every_position_has_a_complete_requirement_profile():
    rows = read_csv("skill_requirements.csv")
    covered = {row["position_id"] for row in rows}
    assert covered == POSITIONS
    for position in POSITIONS:
        own = [row for row in rows if row["position_id"] == position]
        assert len(own) >= 2, position
        for row in own:
            assert row["skill_id"] in SKILLS
            assert 1 <= int(row["level_required"]) <= 4
            assert row["is_mandatory"] in {"true", "false"}
            assert Decimal(row["weight"]) > 0
            assert row["source"] == "role-profile-v1"


def test_hero_role_requires_kubernetes_and_observability():
    rows = [row for row in read_csv("skill_requirements.csv") if row["position_id"] == "POS-BE"]
    required = {row["skill_id"]: int(row["level_required"]) for row in rows}
    assert required["SKILL-K8S"] == 3
    assert required["SKILL-OBS"] == 3


def test_courses_are_fictional_and_cover_the_hero_path():
    rows = read_csv("courses.csv")
    ids = {row["course_id"] for row in rows}
    assert len(ids) == len(rows)
    assert "CRS-K8S-01" in ids
    assert "CRS-K8S-02" in ids
    for row in rows:
        assert row["skill_id"] in SKILLS
        assert row["kpi_id"] in KPIS
        assert int(row["hours"]) > 0
        assert 1 <= int(row["level_gained"]) <= 2
        assert Decimal(row["cost_tnd"]) >= 0
        assert row["format"] in {"self_paced", "workshop", "course"}
        assert "cds.example.test" in row["url"]


def test_templates_are_consistent_and_long_enough():
    payload = json.loads((SEED / "onboarding_templates.json").read_text(encoding="utf-8"))
    templates = payload["templates"]
    assert {template["position_id"] for template in templates} == {"POS-BE", "POS-AE", "GENERIC"}
    for template in templates:
        tasks = template["tasks"]
        assert len(tasks) >= 15, template["id"]
        ids = [task["id"] for task in tasks]
        assert len(ids) == len(set(ids)), template["id"]
        phases = set()
        kinds = set()
        for task in tasks:
            assert task["title"]
            assert task["phase"] in PHASES
            assert task["task_kind"] in TASK_KINDS
            assert task["owner_role"] in OWNER_ROLES
            assert isinstance(task["due_day"], int)
            assert isinstance(task["mandatory"], bool)
            assert task["evidence_required"]
            phases.add(task["phase"])
            kinds.add(task["task_kind"])
        assert phases == PHASES, template["id"]
        assert "first_win" in kinds
        assert "manager_prep" in kinds


def test_pulse_survey_is_structured_and_never_asks_for_sentiment():
    payload = json.loads((SEED / "pulse_survey.json").read_text(encoding="utf-8"))
    assert "no sentiment" in payload["note"].lower()
    assert payload["scale"] == {
        "min": 1,
        "max": 5,
        "labels": ["1 - not yet", "2 - partially", "3 - mostly", "4 - yes", "5 - fully"],
    }
    assert {survey["kind"] for survey in payload["surveys"]} == {"day7", "day30", "day60", "day90"}
    for survey in payload["surveys"]:
        assert len(survey["questions"]) >= 4
        for question in survey["questions"]:
            text = question["text"].lower()
            assert not any(word in text for word in FORBIDDEN_SENTIMENT), (survey["kind"], text)
            assert "sentiment" not in question["id"].lower()
            assert question["type"] in {"scale", "text"}
            if question["type"] == "text":
                assert question.get("required") is False


def test_scenarios_cover_the_pack_contract():
    text = (SEED / "scenarios.md").read_text(encoding="utf-8")
    for token in ("J1", "J2", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "D1", "D3"):
        assert token in text, token
    for token in ("payload", "audit", "no evidence", "cross-tenant", "fail closed"):
        assert token.lower() in text.lower(), token

