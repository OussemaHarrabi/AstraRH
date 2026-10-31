# Journey service: brief for Wassim

**You own what happens after the hire:** onboarding, follow-up, skill gaps, and training tied to KPIs.

**Why it matters in the pitch:** replacing an employee costs far more than hiring one, and the first 90 days are where you keep them. Our edge: the gaps found during hiring seed the plan, so nothing is learned twice.

**Read first:** [ARCHITECTURE.md](../ARCHITECTURE.md), especially the invariants and "What we will not build", and [DEMO_WORLD.md](DEMO_WORLD.md).

## The one slice to ship

1. `talent.candidate.hired.v1` arrives.
2. An agent proposes a 30-60-90 plan from the role's requirements and the hire's own gaps.
3. HR (`EMP-006`) approves or edits it. Approval is R2.
4. Tasks and a buddy are assigned.
5. Check-ins fire on day 7, 30, 60 and 90, with a short pulse survey.
6. Support flags appear for HR when tasks slip or a pulse answer is low, with the reason shown.
7. A skill gap is confirmed by a human.
8. A training recommendation appears, stating **cost, capability gained, and the KPI it should move**. Approval is R2.

Depth over breadth: this path working end to end beats five half-built modules.

## Rules for this service

- Agents draft. A human approves anything that affects a person.
- A support flag is a prompt for a conversation. Show the facts behind it, never a "flight risk" score.
- Pulse answers are what the person chose to tell us. Never infer mood from messages or behaviour.
- A skill gap needs evidence: what is required against what was found. Say "no evidence found", never "lacks".
- Training impact is a hypothesis until measured. Report before and after, with a comparison group if you have one. Never claim training caused a change without evidence.

## Tables (schema `journey`)

`onboarding_template`, `template_task`, `onboarding_plan`, `onboarding_task`, `buddy_assignment`, `checkin`, `pulse_survey`, `pulse_response`, `support_flag`, `skill_requirement`, `skill_gap`, `course`, `training_recommendation`, `enrollment`, `impact_measure`.

## Events

- **Consumes:** `talent.candidate.hired.v1`, `trust.action.executed.v1`.
- **Publishes:** `journey.onboarding.completed.v1`, `journey.skill_gap.confirmed.v1`, `journey.training.completed.v1`.

**Graph:** you own the `Course`, `TEACHES` and `INFLUENCES` data for the Skills Graph.

## Start now, before the repo is ready (about 2 hours)

Create these locally in a folder `seed/journey/`. You will commit them when you branch.

| File | Contents |
|---|---|
| `onboarding_templates.json` | Templates for `POS-BE` and `POS-AE`, with day-30/60/90 goals and 15+ tasks, each with owner role and due day |
| `skill_requirements.csv` | `position_id, skill_id, level_required (1-4)` for every position in DEMO_WORLD |
| `employee_skills.csv` | `employee_id, skill_id, level, source, evidence`. `EMP-009` must be the only `SKILL-OBS` holder in Engineering |
| `courses.csv` | 10 courses: `course_id, title, cost_tnd, hours, skill_id, level_gained, kpi_id, expected_effect`. Must include `CRS-K8S-01` |
| `pulse_survey.json` | Day 7/30/60/90 questions, each short and factual |
| `scenarios.md` | Your slice as acceptance checks: given, when, then. Your coding agent will build against these |

Also think about what the demo should show in **20 seconds** for your service.

## What you get at `platform-v0`

The repo link, a working `_example` pack to copy, and a ready-to-paste prompt for your coding agent. You will work only in `packages/packs/journey/` and `apps/web/src/modules/journey/`.
