# Workforce service + UI system: brief for the workforce owner

**You own two things:** workforce tracking with conflict management, and **the design system that makes four services look like one product**. Start the UI work first, because everyone depends on it.

**Read first:** [ARCHITECTURE.md](../ARCHITECTURE.md), especially the invariants and "What we will not build", and [DEMO_WORLD.md](DEMO_WORLD.md).

## Job 1: the design system

You will own `apps/web/src/ui`. Oussema's side builds the Next.js shell, then you take over its look.

Start now in Figma or on paper:
- **Identity:** AstraRH's name treatment, colours, type, spacing, in light and dark.
- **Shared components:** table, card, form, badge, drawer, empty/loading/error states.
- **Signature components:**
  - **Approval card:** what the AI proposes, what will happen, approve / edit / reject.
  - **`<WhyPanel>`:** factors, evidence, counterfactuals, human decision. This is our explainability story.
  - **Risk badge:** R0, R1, R2, R3.
- **`/graph` page:** Skills Graph, Decision Graph and Agent Mesh, with Cytoscape.js. This is the wow moment, so its look is yours.

Deliver design tokens as CSS variables so other modules inherit them with no effort.

## Job 2: the one slice to ship

**Tracking:** shifts, time entries, leave requests and balances. Requesting leave is simple; approval is R2. Coverage and overload alerts work on **team totals**.

**Conflict management, two kinds:**
- **Operational:** overlapping leave, shift clashes, double bookings. Detected by rules, with a suggested fix for a manager to approve.
- **Between people:** a confidential case: intake → structured summary → suggested process from company policy with citations → human mediator → recorded resolution. Closing a case is R3.

**The slice to demo:** the hire event arrives and Engineering capacity updates; a leave clash is detected and resolved with approval; a case is opened and an agent suggests a process, citing policy.

## Hard limits for this service

This is the most legally sensitive service. Judges may probe here.

- **No** sentiment or emotion analysis of messages. It's prohibited at work under EU AI Act Art. 5(1)(f).
- **No** webcam, keystroke, screen or location tracking.
- **No** individual "conflict risk" or productivity score, and no map of who conflicts with whom.
- Alerts are about team workload, never ranking individuals.
- Cases are visible only to named parties and mediators. Cases never go into the graph database.
- The agent suggests process. Only a human mediator decides outcomes.

## Tables (schema `workforce`)

`shift`, `time_entry`, `leave_type`, `leave_balance`, `leave_request`, `capacity_snapshot`, `case`, `case_party`, `case_event`, `resolution_plan`.

## Events

- **Consumes:** `talent.candidate.hired.v1`.
- **Publishes:** `workforce.leave.approved.v1`, `workforce.case.opened.v1`.

## Start now, before the repo is ready (about 2 hours)

The UI work above, plus these, locally in `seed/workforce/`. You will commit them when you branch.

| File | Contents |
|---|---|
| `employees.csv` | `employee_id, name, email, org_unit_id, position_id, manager_id, start_date` for `EMP-001` to `EMP-040`. **This is the shared master list; share it with the team early** |
| `leave_requests.csv` | 30 requests, including 2 planted overlaps in Engineering |
| `time_entries.csv` | 4 weeks by team, with Engineering overloaded in week 4 |
| `shifts.csv` | Support team shifts, including 1 planted clash |
| `cases.json` | 3 fictional, non-graphic workplace cases for the demo |
| `conflict_policy.md` | A fictional conflict-resolution policy the agent can cite |
| `scenarios.md` | Your slice as acceptance checks: given, when, then |

Also think about what the demo should show in **20 seconds** for your service.

## What you get at `platform-v0`

The repo link, a working `_example` pack to copy, and a ready-to-paste prompt for your coding agent. You will work in `packages/packs/workforce/`, `apps/web/src/modules/workforce/` and `apps/web/src/ui/`.
