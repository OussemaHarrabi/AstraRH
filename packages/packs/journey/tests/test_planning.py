"""Hand-checked tests for dates, phases, attention and the dossier."""

from datetime import date, datetime

from packs.journey.services.planning import (
    add_working_days,
    attention,
    dossier,
    due_at,
    expand_template,
    is_working_day,
    next_three,
    phase_for_day,
    working_days_between,
)

MONDAY = date(2026, 11, 9)
FRIDAY = date(2026, 11, 6)
HOLIDAY = date(2026, 11, 9)


def test_weekend_and_holiday_rules():
    assert is_working_day(MONDAY, holidays=())
    assert not is_working_day(date(2026, 11, 7), holidays=())  # Saturday
    assert not is_working_day(MONDAY, holidays={HOLIDAY})


def test_add_working_days_moves_over_the_weekend():
    assert add_working_days(FRIDAY, 1, holidays=()) == MONDAY
    assert add_working_days(MONDAY, 5, holidays=()) == date(2026, 11, 16)
    assert add_working_days(MONDAY, -1, holidays=()) == FRIDAY


def test_add_working_days_skips_a_holiday():
    assert add_working_days(FRIDAY, 1, holidays={HOLIDAY}) == date(2026, 11, 10)


def test_due_at_is_nine_am_on_a_working_day():
    assert due_at(MONDAY, 7, holidays=()) == datetime(2026, 11, 18, 9, 0)
    assert due_at(MONDAY, 0, holidays=()) == datetime(2026, 11, 9, 9, 0)


def test_phase_boundaries():
    assert phase_for_day(-1) == "preboarding"
    assert phase_for_day(0) == "day1"
    assert phase_for_day(1) == "week1"
    assert phase_for_day(7) == "week1"
    assert phase_for_day(8) == "day30"
    assert phase_for_day(30) == "day30"
    assert phase_for_day(31) == "day60"
    assert phase_for_day(60) == "day60"
    assert phase_for_day(61) == "day90"
    assert phase_for_day(90) == "day90"
    assert phase_for_day(91) == "completed"


def test_working_days_between_is_signed_and_skips_weekends():
    assert working_days_between(MONDAY, MONDAY, holidays=()) == 0
    assert working_days_between(MONDAY, date(2026, 11, 13), holidays=()) == 4
    assert working_days_between(MONDAY, date(2026, 11, 16), holidays=()) == 5
    assert working_days_between(date(2026, 11, 6), MONDAY, holidays=()) == 1
    assert working_days_between(MONDAY, date(2026, 11, 6), holidays=()) == -1


def test_expand_template_sets_due_dates_and_phases():
    template = {
        "tasks": [
            {"title": "Contract", "due_day": -7, "owner_role": "hr", "evidence_required": "signed"},
            {
                "title": "First win",
                "due_day": 3,
                "owner_role": "employee",
                "evidence_required": "PR",
            },
            {
                "title": "Day 30 review",
                "due_day": 30,
                "owner_role": "manager",
                "evidence_required": "notes",
            },
        ]
    }
    tasks = expand_template(template, MONDAY, holidays=())
    assert [task["phase"] for task in tasks] == ["preboarding", "week1", "day30"]
    assert tasks[0]["due_at"] == datetime(2026, 10, 29, 9, 0)
    assert all(task["status"] == "pending" for task in tasks)


def test_next_three_prefers_mandatory_then_due_date():
    tasks = [
        {
            "title": "Optional",
            "due_at": datetime(2026, 11, 10, 9),
            "status": "pending",
            "mandatory": False,
        },
        {
            "title": "Mandatory",
            "due_at": datetime(2026, 11, 12, 9),
            "status": "pending",
            "mandatory": True,
        },
        {
            "title": "Done",
            "due_at": datetime(2026, 11, 9, 9),
            "status": "completed",
            "mandatory": True,
        },
        {
            "title": "Later",
            "due_at": datetime(2026, 11, 20, 9),
            "status": "pending",
            "mandatory": False,
        },
    ]
    assert [task["title"] for task in next_three(tasks, datetime(2026, 11, 8, 12))] == [
        "Optional",
        "Mandatory",
        "Later",
    ]


def test_attention_reports_facts_not_a_score():
    now = datetime(2026, 11, 20, 12)
    tasks = [
        {
            "title": "Staging access",
            "due_at": datetime(2026, 11, 10, 9),
            "status": "in_progress",
            "mandatory": True,
        }
    ]
    checkins = [
        {
            "kind": "day7",
            "scheduled_at": datetime(2026, 11, 10, 9),
            "status": "pending",
            "answers": {"access_ready": 2},
        }
    ]
    result = attention(tasks, checkins, now)
    assert result.level == "needs_attention"
    assert "mandatory_task_overdue" in result.codes
    assert "checkin_missed" in result.codes
    assert "low_structured_answer" in result.codes
    assert any("Staging access" in fact for fact in result.facts)
    assert not hasattr(result, "score")


def test_attention_is_empty_when_nothing_is_wrong():
    result = attention([], [], datetime(2026, 11, 20, 12))
    assert result.level == "none"
    assert result.facts == ()


def test_dossier_counts_evidence_and_missing_items_without_salary():
    tasks = [
        {"title": "Contract", "status": "completed", "evidence": {"ref": "doc-1"}},
        {"title": "First PR", "status": "completed", "evidence": None},
        {"title": "Day 30 review", "status": "pending", "evidence": None},
    ]
    checkins = [{"status": "completed"}, {"status": "pending"}]
    gaps = [
        {"skill_id": "SKILL-K8S", "current_level": 2, "status": "verified"},
        {"skill_id": "SKILL-OBS", "current_level": 1, "status": "proposed"},
    ]
    result = dossier(tasks, checkins, gaps)
    assert result["tasks_total"] == 3
    assert result["tasks_completed"] == 2
    assert result["tasks_with_evidence"] == 1
    assert result["missing"] == ["First PR", "Day 30 review"]
    assert result["checkins_completed"] == 1
    assert result["verified_skills"] == [{"skill_id": "SKILL-K8S", "level": 2}]
    assert "salary" not in result
    assert "rating" not in result
