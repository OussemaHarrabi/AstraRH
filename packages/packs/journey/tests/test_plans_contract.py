"""Contract tests for the generated plan corpus and the hero story."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = REPO_ROOT / "seed" / "journey"
HERO = "EMP-041"


def payload() -> dict:
    return json.loads((SEED / "plans.json").read_text(encoding="utf-8"))


def plans() -> list[dict]:
    return payload()["plans"]


def plan(employee_id: str) -> dict:
    return next(item for item in plans() if item["employee_id"] == employee_id)


def test_eight_plans_with_unique_ids_and_a_hero():
    items = plans()
    assert len(items) == 8
    assert len({item["plan_id"] for item in items}) == 8
    hero = plan(HERO)
    assert hero["display_name"] == "Yasmine Trabelsi"
    assert hero["position_id"] == "POS-BE"
    assert hero["org_unit_id"] == "ORG-ENG"
    assert hero["manager_id"] == "EMP-002"
    assert hero["buddy_id"] == "EMP-009"


def test_every_plan_has_a_consistent_task_and_checkin_shape():
    for item in plans():
        assert item["phase"] in {
            "preboarding",
            "day1",
            "week1",
            "day30",
            "day60",
            "day90",
            "completed",
        }
        assert item["status"] in {"approved", "in_progress", "completed"}
        assert len(item["tasks"]) >= 15
        task_ids = [task["task_id"] for task in item["tasks"]]
        assert len(task_ids) == len(set(task_ids))
        assert {checkin["kind"] for checkin in item["checkins"]} == {
            "day7",
            "day30",
            "day60",
            "day90",
        }
        for task in item["tasks"]:
            assert task["status"] in {"pending", "in_progress", "completed"}
            assert task["owner_role"] in {"hr", "manager", "admin", "employee"}
            assert task["evidence_required"]
        for checkin in item["checkins"]:
            assert checkin["status"] in {"pending", "completed"}


def test_hero_is_in_week_one_with_a_factual_attention_story():
    hero = plan(HERO)
    assert hero["phase"] == "week1"
    assert hero["status"] == "in_progress"
    be_12 = next(task for task in hero["tasks"] if task["task_id"] == "BE-12")
    assert be_12["status"] == "in_progress"
    assert be_12["evidence"] is None
    d7 = next(checkin for checkin in hero["checkins"] if checkin["kind"] == "day7")
    assert d7["status"] == "completed"
    assert d7["answers"]["access_ready"] == 2
    open_flags = [flag for flag in hero["support_flags"] if flag["status"] == "open"]
    assert len(open_flags) == 2
    assert {flag["kind"] for flag in open_flags} == {"milestone_slip", "low_answer"}
    doc_flag = next(flag for flag in hero["support_flags"] if flag["kind"] == "doc_feedback")
    assert doc_flag["status"] == "resolved"


def test_hero_gap_and_training_are_evidence_first():
    hero = plan(HERO)
    gaps = {gap["skill_id"]: gap for gap in hero["gaps"]}
    assert gaps["SKILL-K8S"]["status"] == "confirmed"
    assert gaps["SKILL-K8S"]["gap"] == 2
    assert gaps["SKILL-K8S"]["severity"] == "high"
    assert gaps["SKILL-OBS"]["status"] == "proposed"
    recommendation = hero["recommendations"][0]
    assert recommendation["status"] == "proposed"
    assert recommendation["course_id"] == "CRS-K8S-01"
    assert recommendation["mentor_employee_id"] == "EMP-009"
    assert Decimal(recommendation["cost_tnd"]) == Decimal("0")
    assert recommendation["kpi_id"] == "KPI-MTTR"


def test_gap_factors_sum_exactly_to_the_severity_score():
    gaps = list(payload()["background_gaps"])
    for item in plans():
        gaps.extend(item["gaps"])
    assert gaps
    for gap in gaps:
        total = sum((Decimal(factor["contribution"]) for factor in gap["factors"]), Decimal("0"))
        assert total == Decimal(gap["severity_score"]), gap["gap_id"]
        for factor in gap["factors"]:
            assert Decimal(factor["weight"]) * Decimal(factor["value"]) == Decimal(
                factor["contribution"]
            )


def test_nine_background_gaps_power_the_heatmap():
    gaps = payload()["background_gaps"]
    assert len(gaps) == 9
    assert {gap["employee_id"] for gap in gaps} == {
        f"EMP-{number:03d}" for number in range(16, 25)
    }
    for gap in gaps:
        assert gap["skill_id"] == "SKILL-K8S"
        assert gap["status"] == "confirmed"
        assert gap["gap"] == 1
        assert gap["severity"] == "medium"
        assert Decimal(gap["confidence"]) == Decimal("0.85")


def test_missed_checkin_flag_is_factual():
    plan_015 = plan("EMP-015")
    day30 = next(checkin for checkin in plan_015["checkins"] if checkin["kind"] == "day30")
    assert day30["status"] == "pending"
    flag = plan_015["support_flags"][0]
    assert flag["kind"] == "missed_checkin"
    assert flag["status"] == "open"
    assert flag["facts"]


def test_completed_training_has_verification_and_observed_impact():
    plan_014 = plan("EMP-014")
    assert plan_014["status"] == "completed"
    recommendation = plan_014["recommendations"][0]
    assert recommendation["status"] == "completed"
    enrollment = plan_014["enrollments"][0]
    assert enrollment["status"] == "completed"
    assert enrollment["score"] == 88
    assert enrollment["verified_by"] == "EMP-003"
    impact = plan_014["impact_measures"][0]
    assert Decimal(impact["observed_delta"]) == Decimal("-0.6")
    assert impact["label"] == "observed"
    assert "not causal" in impact["caveat"].lower()
    dossier = plan_014["dossier"]
    assert dossier["tasks_completed"] == dossier["tasks_total"]
    assert dossier["tasks_with_evidence"] == dossier["tasks_total"] - 1
    assert dossier["missing"] == ["Independent work review"]
    assert dossier["verified_skills"] == [{"skill_id": "SKILL-K8S", "level": 3}]
    assert "salary" not in dossier
    assert "rating" not in dossier


def test_no_sentiment_or_individual_risk_field_exists():
    text = json.dumps(payload()).lower()
    for forbidden in ("sentiment", "flight_risk", "flight risk", "performance_rating"):
        assert forbidden not in text
