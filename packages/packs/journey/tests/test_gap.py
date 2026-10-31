"""Hand-checked tests for the gap math. Every expected number is computed by hand."""

from decimal import Decimal

import pytest
from journey.services.gap import (
    Assessment,
    Evidence,
    InvalidLevel,
    assess,
    compute_gap,
    confidence,
    cost_per_closed_gap,
    course_path,
    mentor_candidates,
    observed_delta,
    priority,
    severity,
)


def test_gap_is_required_minus_current_floored_at_zero():
    assert compute_gap(3, 1) == 2
    assert compute_gap(4, 1) == 3
    assert compute_gap(2, 4) == 0
    assert compute_gap(1, 1) == 0


@pytest.mark.parametrize("level", [0, 5, -1])
def test_level_outside_one_to_four_is_rejected(level):
    with pytest.raises(InvalidLevel):
        compute_gap(level, 1)
    with pytest.raises(InvalidLevel):
        compute_gap(1, level)


def test_severity_high_for_mandatory_two_level_gap():
    result = severity(3, 1, mandatory=True, weight=1, max_weight=1)
    assert result.label == "high"
    assert result.score == Decimal("0.8")
    assert sum((factor.contribution for factor in result.factors), Decimal("0")) == result.score
    for factor in result.factors:
        assert factor.weight * factor.value == factor.contribution


def test_severity_medium_for_mandatory_one_level_gap():
    result = severity(3, 2, mandatory=True, weight=1, max_weight=1)
    assert result.label == "medium"
    assert result.score == Decimal("0.6")


def test_severity_low_for_optional_one_level_gap():
    result = severity(3, 2, mandatory=False, weight=1, max_weight=1)
    assert result.label == "low"
    assert result.score == Decimal("0.35")


def test_severity_none_when_meeting_the_requirement():
    result = severity(3, 4, mandatory=True, weight=1, max_weight=1)
    assert result.label == "none"
    assert result.score == Decimal("0")
    assert result.factors == ()


def test_severity_uses_the_role_profile_weight():
    result = severity(3, 1, mandatory=True, weight=Decimal("0.8"), max_weight=1)
    assert result.score == Decimal("0.77")


def test_priority_multiplies_by_kpi_weight():
    assert priority(Decimal("0.8"), Decimal("2")) == Decimal("1.6")


def test_confidence_is_a_weighted_average_of_source_trust():
    signals = [
        Evidence("assessment", Decimal("0.5"), "practical task passed", "assess-1"),
        Evidence("manager", Decimal("0.3"), "day-60 review", "review-1"),
    ]
    assert confidence(signals) == Decimal("0.8875")


def test_self_declaration_alone_is_low_confidence():
    assert confidence([Evidence("self", Decimal("1"), "profile claim")]) == Decimal("0.2")


def test_no_evidence_is_zero_confidence_and_says_no_evidence_found():
    result = assess("Kubernetes", 3, 1, mandatory=True, evidence=[])
    assert isinstance(result, Assessment)
    assert result.confidence == Decimal("0")
    assert result.message.startswith("No evidence found for Kubernetes")
    assert "lacks" not in result.message.lower()


def test_met_requirement_is_not_a_gap():
    result = assess(
        "Docker",
        3,
        3,
        mandatory=False,
        evidence=[Evidence("applied_evidence", Decimal("1"), "12 merged PRs", "pr-1")],
    )
    assert result.gap == 0
    assert result.severity.label == "none"
    assert "meets the role requirement" in result.message


def test_course_path_orders_by_level_then_hours_and_closes_the_gap():
    courses = [
        {
            "course_id": "CRS-K8S-02",
            "skill_id": "SKILL-K8S",
            "level_gained": 1,
            "hours": 12,
            "cost_tnd": "450",
        },
        {
            "course_id": "CRS-K8S-01",
            "skill_id": "SKILL-K8S",
            "level_gained": 1,
            "hours": 6,
            "cost_tnd": "0",
        },
        {
            "course_id": "CRS-K8S-03",
            "skill_id": "SKILL-K8S",
            "level_gained": 2,
            "hours": 20,
            "cost_tnd": "900",
        },
        {
            "course_id": "CRS-OTHER",
            "skill_id": "SKILL-PY",
            "level_gained": 1,
            "hours": 1,
            "cost_tnd": "0",
        },
    ]
    path = course_path(courses, skill_id="SKILL-K8S", required_level=3, current_level=1)
    assert [item["course_id"] for item in path.items] == ["CRS-K8S-01", "CRS-K8S-02"]
    assert path.total_hours == Decimal("18")
    assert path.total_cost_tnd == Decimal("450")
    assert path.closes_gap is True


def test_course_path_does_not_claim_to_close_when_it_cannot():
    courses = [
        {
            "course_id": "CRS-K8S-01",
            "skill_id": "SKILL-K8S",
            "level_gained": 1,
            "hours": 6,
            "cost_tnd": "0",
        }
    ]
    path = course_path(courses, skill_id="SKILL-K8S", required_level=4, current_level=1)
    assert path.closes_gap is False
    assert len(path.items) == 1


def test_mentor_candidates_exclude_the_learner_and_manager():
    holders = [
        {"employee_id": "EMP-041", "level": 4},
        {"employee_id": "EMP-002", "level": 4},
        {"employee_id": "EMP-009", "level": 4},
        {"employee_id": "EMP-010", "level": 2},
    ]
    result = mentor_candidates(
        holders,
        required_level=3,
        learner_id="EMP-041",
        manager_id="EMP-002",
    )
    assert [row["employee_id"] for row in result] == ["EMP-009"]


def test_cost_per_closed_gap_and_zero_division():
    assert cost_per_closed_gap("450", 2) == Decimal("225")
    assert cost_per_closed_gap("0", 2) == Decimal("0")
    assert cost_per_closed_gap("900", 0) is None


def test_observed_delta_refuses_a_small_comparison_group():
    result = observed_delta(
        treated_baseline="8",
        treated_post="6",
        comparison_baseline="8",
        comparison_post="7",
        comparison_n=4,
    )
    assert result.value is None
    assert result.label == "insufficient_comparison_group"


def test_observed_delta_is_difference_in_differences():
    result = observed_delta(
        treated_baseline="8",
        treated_post="6",
        comparison_baseline="8",
        comparison_post="7",
        comparison_n=5,
    )
    assert result.value == Decimal("-1")
    assert result.label == "observed"
