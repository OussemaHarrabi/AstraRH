"""Generate the journey-scoped employee skill evidence from the role profiles.

Deterministic: run `python seed/journey/build_employee_skills.py` and commit the CSV.
The master employee list belongs to workforce; this file only references DEMO_WORLD IDs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed" / "journey"

# The nine Engineering employees with a confirmed Kubernetes gap. This powers the
# read-only team heatmap (9 of 14 Engineering staff). EMP-009/025/026 are the
# non-gap backend engineers; EMP-002 is the manager and EMP-011 is data.
K8S_GAP_IDS = {f"EMP-{number:03d}" for number in range(16, 25)}
OBS_ONLY_HOLDER = "EMP-009"
HERO_ID = "EMP-041"

SOURCES = ("manager", "applied_evidence", "assessment", "self")
SOURCE_EVIDENCE = {
    "manager": "day-30 review",
    "applied_evidence": "merged PR or ticket evidence",
    "assessment": "role assessment",
    "self": "profile claim",
}


def read_csv(name: str) -> list[dict[str, str]]:
    with (SEED / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_roster() -> list[dict[str, object]]:
    payload = json.loads((SEED / "roster.json").read_text(encoding="utf-8"))
    return list(payload["employees"])


def requirements_by_position() -> dict[str, list[dict[str, str]]]:
    rows = read_csv("skill_requirements.csv")
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["position_id"], []).append(row)
    return grouped


def level_for(
    *,
    employee_id: str,
    skill_id: str,
    mandatory: bool,
    index: int,
    org_unit_id: str,
) -> tuple[int, str, str]:
    if skill_id == "SKILL-K8S" and employee_id in K8S_GAP_IDS:
        level = 1 if index % 2 == 0 else 2
        return level, "manager", "day-30 review: no deployment ownership"
    if skill_id == "SKILL-K8S" and org_unit_id == "ORG-ENG":
        level = 3 if index % 2 == 0 else 4
        return level, "applied_evidence", "merged deployment manifests; on-call rotation"
    if skill_id == "SKILL-OBS" and employee_id == OBS_ONLY_HOLDER:
        return 4, "applied_evidence", "on-call owner; incident reviews"
    level = 3 if mandatory else 2
    if index % 4 == 0:
        level += 1
    level = min(4, max(1, level))
    source = SOURCES[(int(employee_id[-3:]) + index) % len(SOURCES)]
    return level, source, SOURCE_EVIDENCE[source]


def build_rows() -> list[dict[str, str | int]]:
    roster = read_roster()
    requirements = requirements_by_position()
    rows: list[dict[str, str | int]] = []
    for employee in roster:
        employee_id = str(employee["employee_id"])
        if employee_id == HERO_ID:
            continue
        position_id = str(employee["position_id"])
        org_unit_id = str(employee["org_unit_id"])
        for index, requirement in enumerate(requirements[position_id]):
            skill_id = requirement["skill_id"]
            # The handoff requires EMP-009 to be the only SKILL-OBS holder in Engineering.
            if (
                skill_id == "SKILL-OBS"
                and org_unit_id == "ORG-ENG"
                and employee_id != OBS_ONLY_HOLDER
            ):
                continue
            level, source, evidence = level_for(
                employee_id=employee_id,
                skill_id=skill_id,
                mandatory=requirement["is_mandatory"] == "true",
                index=index,
                org_unit_id=org_unit_id,
            )
            rows.append(
                {
                    "employee_id": employee_id,
                    "skill_id": skill_id,
                    "level": level,
                    "source": source,
                    "evidence": evidence,
                }
            )
    rows.sort(key=lambda row: (str(row["employee_id"]), str(row["skill_id"])))
    return rows


def main() -> None:
    rows = build_rows()
    path = SEED / "employee_skills.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["employee_id", "skill_id", "level", "source", "evidence"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    roster = read_roster()
    engineering = {
        str(row["employee_id"])
        for row in roster
        if row["org_unit_id"] == "ORG-ENG" and row["employee_id"] != HERO_ID
    }
    gaps = {
        str(row["employee_id"])
        for row in rows
        if row["skill_id"] == "SKILL-K8S" and int(str(row["level"])) < 3
    }
    obs = {
        str(row["employee_id"])
        for row in rows
        if row["skill_id"] == "SKILL-OBS" and str(row["employee_id"]) in engineering
    }
    print(f"wrote {path} ({len(rows)} rows)")
    print(f"Engineering={len(engineering)} Kubernetes gaps={len(gaps)}")
    print(f"SKILL-OBS holders in Engineering={sorted(obs)}")


if __name__ == "__main__":
    main()


