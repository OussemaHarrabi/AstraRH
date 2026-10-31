# Finance service: brief for the finance owner

**You own people-cost intelligence:** payroll, budget, forecasts and what-if scenarios. This turns "losing people is expensive" into a live number on screen.

**Read first:** [ARCHITECTURE.md](../ARCHITECTURE.md), especially the invariants and "What we will not build", and [DEMO_WORLD.md](DEMO_WORLD.md).

## What this service contains, by priority

Finish each before starting the next.

1. **Payroll run.** Rule-driven: gross → deductions → net, per employee. Draft → anomalies explained → R3 approval by `EMP-007`. Every payslip line shows which rule produced it.
2. **People-cost dashboard.** Actual against budget, by org unit and month.
3. **Forecast and scenarios.** A 12-month projection from headcount, salaries and planned hires. "What if we hire 5?" "What if we lose 3?" The result shows **which drivers caused the change**.
4. **Cost of attrition.** Estimated cost of a departure, with every assumption visible and editable.
5. **Training ROI.** Uses Wassim's events: training cost against the measured KPI change.

**The slice to demo:** the hire event arrives, the Engineering forecast updates, and the screen shows exactly why.

## Rules for this service

- **The LLM never computes money.** Python calculates; the LLM may only explain results already calculated. A validator rejects a narration whose numbers don't match.
- Use `Decimal`, never floats. Each calculation needs a test with a hand-checked answer.
- Payroll rates are **configurable demo values, not legally certified**. Say so on screen and in the pitch.
- Running payroll is R3: approval, step-up and no self-approval.
- Salaries never go into the graph database, and access is restricted by role.
- Forecasts are estimates. Show assumptions and ranges, not false precision.

## Tables (schema `finance`)

`salary_structure`, `compensation`, `rule_set`, `payroll_run`, `payslip`, `payslip_line`, `budget`, `budget_line`, `cost_snapshot`, `scenario`, `forecast_run`, `forecast_point`.

## Events

- **Consumes:** `talent.candidate.hired.v1`, `journey.skill_gap.confirmed.v1`, `journey.training.completed.v1`, `workforce.leave.approved.v1`.
- **Publishes:** `finance.forecast.published.v1`.

## Start now, before the repo is ready (about 2 hours)

Create these locally in a folder `seed/finance/`. You will commit them when you branch.

| File | Contents |
|---|---|
| `compensation.csv` | `employee_id, gross_monthly_tnd, start_date` for `EMP-001` to `EMP-040`. Invented, plausible figures |
| `rule_set.json` | Deductions and contributions as data: rule ID, label, base, rate or brackets. Mark as demo values |
| `budget.csv` | `org_unit_id, month, budget_tnd` for 12 months, Engineering slightly over budget |
| `payroll_history.csv` | 6 past months per org unit, including one planted anomaly |
| `attrition_assumptions.json` | Replacement-cost assumptions by role level, with their sources |
| `worked_examples.md` | 3 payslips and 1 forecast calculated **by hand**. These become your tests |
| `scenarios.md` | Your slice as acceptance checks: given, when, then |

Also think about what the demo should show in **20 seconds** for your service.

## What you get at `platform-v0`

The repo link, a working `_example` pack to copy, and a ready-to-paste prompt for your coding agent. You will work only in `packages/packs/finance/` and `apps/web/src/modules/finance/`.
