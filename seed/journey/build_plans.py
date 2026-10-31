"""Generate the journey plan corpus from the templates and role profiles.

Deterministic: run `python seed/journey/build_plans.py` and commit `plans.json`.
No database, no LLM, no network. The output is a seed, not a runtime dependency.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed" / "journey"
sys.path.insert(0, str(ROOT / "packages"))

from packs.journey.services import gap as gap_math  # noqa: E402
from packs.journey.services import planning  # noqa: E402

AS_OF = datetime(2026, 11, 18, 9, 0)
HERO = "EMP-041"
MISSING_EVIDENCE_TASK = "GEN-17"

PLAN_CONFIG = [
    {"employee_id": "EMP-010", "template": "GENERIC", "start": "2026-12-01", "status": "draft"},
    {
        "employee_id": "EMP-011",
        "template": "GENERIC",
        "start": "2026-11-16",
        "status": "in_progress",
    },
    {
        "employee_id": "EMP-012",
        "template": "POS-AE",
        "start": "2026-11-02",
        "status": "in_progress",
    },
    {
        "employee_id": "EMP-013",
        "template": "GENERIC",
        "start": "2026-10-01",
        "status": "in_progress",
    },
    {"employee_id": "EMP-014", "template": "GENERIC", "start": "2026-07-01", "status": "completed"},
    {
        "employee_id": "EMP-015",
        "template": "GENERIC",
        "start": "2026-09-01",
        "status": "in_progress",
    },
    {
        "employee_id": "EMP-016",
        "template": "POS-BE",
        "start": "2026-10-15",
        "status": "in_progress",
    },
    {"employee_id": HERO, "template": "POS-BE", "start": "2026-11-09", "status": "in_progress"},
]

CHECKIN_DAYS = (("day7", 7), ("day30", 30), ("day60", 60), ("day90", 90))
BASE_ANSWERS = {
    "day7": {"role_clarity": 4, "access_ready": 4, "buddy_contact": 5, "first_week_tasks": 4},
    "day30": {
        "role_clarity": 4,
        "first_contribution": 4,
        "manager_feedback": 4,
        "team_context": 4,
    },
    "day60": {
        "independent_work": 4,
        "wider_context": 4,
        "learning_progress": 4,
        "manager_support": 4,
    },
    "day90": {
        "role_readiness": 4,
        "contribution": 4,
        "training_application": 4,
        "team_integration": 4,
    },
}


def read_json(name: str) -> dict[str, Any]:
    return json.loads((SEED / name).read_text(encoding="utf-8"))


def read_roster() -> dict[str, dict[str, Any]]:
    return {str(row["employee_id"]): row for row in read_json("roster.json")["employees"]}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def task_owner(employee: dict[str, Any], owner_role: str) -> str | None:
    if owner_role == "employee":
        return str(employee["employee_id"])
    if owner_role == "manager":
        return str(employee["manager_id"]) if employee.get("manager_id") else None
    return None


def task_status(employee: dict[str, Any], task: dict[str, Any], plan_status: str) -> str:
    task_id = str(task["id"])
    if plan_status == "completed":
        return "completed"
    if plan_status == "draft":
        return "pending"
    if plan_status == "approved":
        return "completed" if task_id in {"GEN-01", "GEN-02"} else "pending"
    if employee["employee_id"] == HERO and task_id == "BE-12":
        return "in_progress"
    due = task["due_at"]
    assert isinstance(due, datetime)
    return "completed" if due.date() <= AS_OF.date() else "pending"


def build_tasks(
    employee: dict[str, Any],
    template: dict[str, Any],
    plan_status: str,
) -> list[dict[str, Any]]:
    expanded = planning.expand_template(template, date.fromisoformat(employee["start_date"]))
    rows: list[dict[str, Any]] = []
    for task in expanded:
        due = task["due_at"]
        assert isinstance(due, datetime)
        status = task_status(employee, task, plan_status)
        task_id = str(task["id"])
        evidence = None
        if status == "completed":
            evidence = {"ref": f"EVID-{task_id}", "summary": task["evidence_required"]}
            if employee["employee_id"] == "EMP-014" and task_id == MISSING_EVIDENCE_TASK:
                evidence = None
        owner_role = str(task["owner_role"])
        approved_by = None
        if status == "completed" and owner_role in {"manager", "hr"}:
            approved_by = str(employee["manager_id"]) if owner_role == "manager" else "EMP-006"
        rows.append(
            {
                "task_id": task_id,
                "title": task["title"],
                "phase": task["phase"],
                "task_kind": task["task_kind"],
                "owner_role": owner_role,
                "owner_employee_id": task_owner(employee, owner_role),
                "due_at": iso(due),
                "status": status,
                "mandatory": bool(task["mandatory"]),
                "evidence_required": task["evidence_required"],
                "evidence": evidence,
                "completed_at": iso(due + timedelta(hours=6)) if status == "completed" else None,
                "approved_by": approved_by,
            }
        )
    return rows


def build_checkins(employee: dict[str, Any]) -> list[dict[str, Any]]:
    start = date.fromisoformat(employee["start_date"])
    rows: list[dict[str, Any]] = []
    for kind, day in CHECKIN_DAYS:
        scheduled = planning.due_at(start, day)
        due = scheduled.date() <= AS_OF.date()
        status = "completed" if due else "pending"
        answers: dict[str, Any] = dict(BASE_ANSWERS[kind]) if status == "completed" else {}
        if employee["employee_id"] == HERO and kind == "day7":
            answers["access_ready"] = 2
            answers["blockers_text"] = "Staging DB access is still pending."
        if employee["employee_id"] == "EMP-015" and kind == "day30":
            status = "pending"
            answers = {}
        rows.append(
            {
                "checkin_id": f"CHK-{employee['employee_id']}-{kind}",
                "kind": kind,
                "scheduled_at": iso(scheduled),
                "completed_at": iso(scheduled + timedelta(hours=2))
                if status == "completed"
                else None,
                "status": status,
                "answers": answers,
                "escalation": False,
            }
        )
    return rows


def build_flags(employee: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if employee["employee_id"] == HERO:
        return [
            {
                "flag_id": "FLAG-EMP-041-1",
                "kind": "milestone_slip",
                "reason_code": "staging_access_missing",
                "facts": [
                    "BE-12 Run the local development stack is in progress; "
                    "staging DB access has not been provisioned."
                ],
                "status": "open",
                "raised_at": iso(AS_OF),
                "resolved_at": None,
                "resolved_by": None,
            },
            {
                "flag_id": "FLAG-EMP-041-2",
                "kind": "low_answer",
                "reason_code": "access_ready_low",
                "facts": ["D7 pulse: access_ready=2; blockers_text recorded for a human to read."],
                "status": "open",
                "raised_at": iso(AS_OF),
                "resolved_at": None,
                "resolved_by": None,
            },
            {
                "flag_id": "FLAG-EMP-041-3",
                "kind": "doc_feedback",
                "reason_code": "doc_outdated",
                "facts": [
                    "New hire flagged 'Engineering Runbook v4 section 3.2 Access' as outdated."
                ],
                "status": "resolved",
                "raised_at": iso(AS_OF - timedelta(days=1)),
                "resolved_at": iso(AS_OF),
                "resolved_by": "EMP-006",
            },
        ]
    if employee["employee_id"] == "EMP-015":
        return [
            {
                "flag_id": "FLAG-EMP-015-1",
                "kind": "missed_checkin",
                "reason_code": "day30_not_submitted",
                "facts": ["D30 check-in was scheduled and is still pending."],
                "status": "open",
                "raised_at": iso(AS_OF),
                "resolved_at": None,
                "resolved_by": None,
            }
        ]
    return []


def evidence_signals(rows: list[dict[str, Any]]) -> list[gap_math.Evidence]:
    return [
        gap_math.Evidence(
            kind=str(row["kind"]),
            weight=Decimal(str(row["weight"])),
            summary=str(row["summary"]),
            ref=str(row["ref"]),
        )
        for row in rows
    ]


def build_gap(
    *,
    employee_id: str,
    skill_id: str,
    skill_name: str,
    current: int,
    required: int,
    mandatory: bool,
    weight: Decimal,
    max_weight: Decimal,
    evidence: list[dict[str, Any]],
    status: str,
    decided_by: str | None,
) -> dict[str, Any]:
    assessment = gap_math.assess(
        skill_name,
        required,
        current,
        mandatory=mandatory,
        weight=weight,
        max_weight=max_weight,
        evidence=evidence_signals(evidence),
    )
    gap_id = f"GAP-{employee_id}-{skill_id.replace('SKILL-', '')}"
    return {
        "gap_id": gap_id,
        "employee_id": employee_id,
        "skill_id": skill_id,
        "current_level": current,
        "required_level": required,
        "gap": assessment.gap,
        "severity": assessment.severity.label,
        "severity_score": str(assessment.severity.score.quantize(Decimal("0.0001"))),
        "confidence": str(assessment.confidence),
        "message": assessment.message,
        "factors": [
            {
                "key": factor.key,
                "label": factor.label,
                "weight": str(factor.weight),
                "value": str(factor.value),
                "contribution": str(factor.contribution),
            }
            for factor in assessment.severity.factors
        ],
        "evidence": evidence,
        "status": status,
        "decided_by": decided_by,
        "decided_at": iso(AS_OF) if decided_by else None,
        "decision_note": None,
        "decision_record_id": f"DR-{gap_id}" if status in {"confirmed", "closed"} else None,
    }


def hero_gaps() -> list[dict[str, Any]]:
    k8s = build_gap(
        employee_id=HERO,
        skill_id="SKILL-K8S",
        skill_name="Kubernetes",
        current=1,
        required=3,
        mandatory=True,
        weight=Decimal("1.0"),
        max_weight=Decimal("1.0"),
        evidence=[
            {
                "kind": "inferred",
                "weight": "1",
                "summary": "Screening: 14 PRs touched manifests, zero deployment ownership",
                "ref": "SCREEN-CAND-001",
            },
            {
                "kind": "manager",
                "weight": "1",
                "summary": "Day-60 review: 2/5 on deployment ownership",
                "ref": "REV-EMP-002-041",
            },
            {
                "kind": "inferred",
                "weight": "1",
                "summary": "No CKA certification on file",
                "ref": "CERT-NONE-041",
            },
        ],
        status="confirmed",
        decided_by="EMP-002",
    )
    obs = build_gap(
        employee_id=HERO,
        skill_id="SKILL-OBS",
        skill_name="Observability",
        current=1,
        required=3,
        mandatory=True,
        weight=Decimal("0.9"),
        max_weight=Decimal("1.0"),
        evidence=[
            {
                "kind": "inferred",
                "weight": "1",
                "summary": "Screening: no incident-review or dashboard ownership evidence",
                "ref": "SCREEN-CAND-001-OBS",
            }
        ],
        status="proposed",
        decided_by=None,
    )
    return [k8s, obs]


def background_gaps() -> list[dict[str, Any]]:
    rows = []
    for number in range(16, 25):
        employee_id = f"EMP-{number:03d}"
        rows.append(
            build_gap(
                employee_id=employee_id,
                skill_id="SKILL-K8S",
                skill_name="Kubernetes",
                current=2,
                required=3,
                mandatory=True,
                weight=Decimal("1.0"),
                max_weight=Decimal("1.0"),
                evidence=[
                    {
                        "kind": "manager",
                        "weight": "1",
                        "summary": "Day-30 review: deployment work is reviewed, not owned",
                        "ref": f"REV-EMP-002-{employee_id[-3:]}",
                    },
                    {
                        "kind": "applied_evidence",
                        "weight": "1",
                        "summary": "Touched manifests, no rollout or rollback ownership",
                        "ref": f"PRS-{employee_id[-3:]}",
                    },
                ],
                status="confirmed",
                decided_by="EMP-002",
            )
        )
    return rows


def plan_gap_for_014() -> dict[str, Any]:
    return build_gap(
        employee_id="EMP-014",
        skill_id="SKILL-COMM",
        skill_name="Communication",
        current=3,
        required=3,
        mandatory=True,
        weight=Decimal("1.0"),
        max_weight=Decimal("1.0"),
        evidence=[
            {
                "kind": "assessment",
                "weight": "1",
                "summary": "Post-course assessment: 88/100",
                "ref": "ENR-EMP-014-COMM",
            },
            {
                "kind": "applied_evidence",
                "weight": "1",
                "summary": "Two stakeholder updates delivered after the course",
                "ref": "PRS-EMP-014",
            },
        ],
        status="closed",
        decided_by="EMP-003",
    )


def hero_recommendation() -> dict[str, Any]:
    return {
        "recommendation_id": "REC-EMP-041-K8S",
        "gap_id": "GAP-EMP-041-K8S",
        "employee_id": HERO,
        "kind": "course",
        "course_id": "CRS-K8S-01",
        "mentor_employee_id": "EMP-009",
        "rationale": (
            "Start with Kubernetes Fundamentals; it is 6 hours, 0 TND, and the team's "
            "internal expert EMP-009 is available for pairing. The next step is "
            "CRS-K8S-02 if the gap is still open at day 60."
        ),
        "cost_tnd": "0.00",
        "hours": 6,
        "kpi_id": "KPI-MTTR",
        "expected_effect": "Lower MTTR for deployment incidents (hypothesis)",
        "status": "proposed",
        "approval_id": None,
    }


def completed_training() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    recommendation = {
        "recommendation_id": "REC-EMP-014-COMM",
        "gap_id": "GAP-EMP-014-COMM",
        "employee_id": "EMP-014",
        "kind": "course",
        "course_id": "CRS-COMM-01",
        "mentor_employee_id": None,
        "rationale": "Clear Communication closes the level-3 requirement; the manager approved it.",
        "cost_tnd": "0.00",
        "hours": 3,
        "kpi_id": "KPI-90D",
        "expected_effect": "Clearer check-ins and escalations (hypothesis)",
        "status": "completed",
        "approval_id": "APR-EMP-014-REC",
    }
    enrollment = {
        "enrollment_id": "ENR-EMP-014-COMM",
        "recommendation_id": "REC-EMP-014-COMM",
        "employee_id": "EMP-014",
        "course_id": "CRS-COMM-01",
        "status": "completed",
        "started_at": "2026-09-07T09:00:00",
        "completed_at": "2026-09-10T17:00:00",
        "score": 88,
        "evidence": {"assessment": 88, "applied": "two stakeholder updates"},
        "verified_by": "EMP-003",
        "verified_at": "2026-10-02T10:00:00",
    }
    observed = gap_math.observed_delta(
        treated_baseline="82.0",
        treated_post="84.0",
        comparison_baseline="82.0",
        comparison_post="82.5",
        comparison_n=5,
    )
    impact = {
        "impact_id": "IMP-EMP-014-COMM",
        "recommendation_id": "REC-EMP-014-COMM",
        "kpi_id": "KPI-90D",
        "baseline_value": "82.0",
        "post_value": "84.0",
        "delta": "2.0",
        "comparison_employee_ids": ["EMP-003", "EMP-033", "EMP-040", "EMP-013", "EMP-032"],
        "comparison_n": 5,
        "method": "difference-in-differences over 30 days; no random assignment",
        "observed_delta": str(observed.value),
        "label": observed.label,
        "measured_at": "2026-10-25T10:00:00",
        "caveat": "Observed change, not causal. Comparison group n=5.",
    }
    return recommendation, enrollment, impact


def build_plan(
    config: dict[str, Any], roster: dict[str, dict[str, Any]], templates: dict[str, Any]
) -> dict[str, Any]:
    employee = roster[str(config["employee_id"])]
    template = templates[str(config["template"])]
    start = date.fromisoformat(str(config["start"]))
    tasks = build_tasks(employee, template, str(config["status"]))
    checkins = build_checkins(employee)
    flags = build_flags(employee, tasks)
    plan_gaps: list[dict[str, Any]] = []
    recommendation = None
    enrollment = None
    impact = None
    dossier = None
    if employee["employee_id"] == HERO:
        plan_gaps = hero_gaps()
        recommendation = hero_recommendation()
    if employee["employee_id"] == "EMP-014":
        plan_gaps = [plan_gap_for_014()]
        recommendation, enrollment, impact = completed_training()
        dossier = planning.dossier(tasks, checkins, plan_gaps)
    if employee["employee_id"] == "EMP-016":
        plan_gaps = []
    plan_phase = planning.phase_for_day(planning.working_days_between(start, AS_OF.date()))
    return {
        "plan_id": f"PLAN-{employee['employee_id']}",
        "employee_id": str(employee["employee_id"]),
        "display_name": str(employee["display_name"]),
        "position_id": str(employee["position_id"]),
        "org_unit_id": str(employee["org_unit_id"]),
        "manager_id": employee.get("manager_id"),
        "buddy_id": employee.get("buddy_id"),
        "template_id": str(template["id"]),
        "start_date": str(config["start"]),
        "target_ramp_date": iso(planning.due_at(start, 90)),
        "status": str(config["status"]),
        "phase": plan_phase,
        "plan_approved_by": None if str(config["status"]) == "draft" else "EMP-006",
        "approval_id": f"APR-{employee['employee_id']}-PLAN",
        "tasks": tasks,
        "checkins": checkins,
        "support_flags": flags,
        "gaps": plan_gaps,
        "recommendations": [recommendation] if recommendation else [],
        "enrollments": [enrollment] if enrollment else [],
        "impact_measures": [impact] if impact else [],
        "dossier": dossier,
    }


def main() -> None:
    roster = read_roster()
    templates = {
        str(template["position_id"]): template
        for template in read_json("onboarding_templates.json")["templates"]
    }
    plans = [build_plan(config, roster, templates) for config in PLAN_CONFIG]
    payload = {
        "version": 1,
        "as_of": iso(AS_OF),
        "note": "Fictional seed. Plans are proposals until a human approves; "
        "training levels change only after verification.",
        "background_gaps": background_gaps(),
        "plans": plans,
    }
    path = SEED / "plans.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}: {len(plans)} plans, {len(payload['background_gaps'])} heatmap gaps")
    for plan in plans:
        line = (
            f"  {plan['plan_id']} phase={plan['phase']} "
            f"tasks={len(plan['tasks'])} flags={len(plan['support_flags'])}"
        )
        print(line)


if __name__ == "__main__":
    main()
