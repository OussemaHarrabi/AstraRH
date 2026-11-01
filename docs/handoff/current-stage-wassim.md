# Current Stage — Wassim

**Pack:** `journey` (AstraRH)  
**Branch:** `feat/journey/scope-v2`  
**Status:** Tier 1 backend complete and verified; frontend not started; Tier 2 not started.  
**Purpose of this file:** hand this branch to the teammate who will merge the first MVP into `main`. Wassim continues with Tier 2 for v2.

---

## 1. Where we are

We are at the **end of the Tier 1 backend phase** for the journey pack.

- The full journey backend is implemented, seeded, and tested.
- The real trust approval path is proven end to end.
- The demo database is in its intended state: **one pending plan-activation proposal**, EMP-010 plan still `draft`.
- No frontend work has started.
- No Tier 2 work has started.
- The branch has **not been pushed or merged** in this session.

This is the build that should become the **first MVP**.

---

## 2. What is done — Tier 1 backend

All 12 Tier 1 features now have a backend path.

| ID | Feature | Backend status |
|---|---|---|
| J1 | Hire → 30/60/90 plan proposal | Done: deterministic tasks, owners, due dates, evidence, DecisionRecord, R2 proposal |
| J2 | Plan activation + buddy | Done: hash-bound payload applies tasks, buddy, activation audit |
| J3 | New-hire portal | Done: `GET /plans/me/portal` returns today’s 3 tasks, progress, buddy, cohort, next check-in, Ask preview |
| J4 | Evidence-first milestones | Done: completion requires evidence; manager/HR verification is an R2 proposal |
| J5 | Check-ins + structured pulse | Done: D7/30/60/90 scheduling, canonical questions, submit route; optional email series is not wired |
| J6 | Support flags with facts | Done: create, fact-driven sweep, HR notification proposal |
| J7 | Gap proposal + human confirmation | Done: deterministic gap math, evidence, DecisionRecord, R2 confirm |
| J8 | Training recommendation | Done: ordered path, cost, hours, KPI, mentor alternative |
| J9 | Enrollment + verification | Done: assign, enroll, verify, level-change event |
| J10 | Impact measure | Done: `POST /impact` records baseline/post/delta, comparison group, method and caveat |
| J11 | Day-90 completion | Done: plan closes and emits `journey.onboarding.completed.v1` with verified skills |
| J12 | Ramp attention | Done: overdue mandatory tasks, missed check-ins and low answers as facts/reason codes |

### Tier 1 HTTP surface added

```text
GET  /packs/journey/plans/me/portal
GET  /packs/journey/plans/{plan_id}
POST /packs/journey/plans/{plan_id}/tasks/{task_id}/complete
POST /packs/journey/plans/{plan_id}/tasks/{task_id}/verify
POST /packs/journey/plans/{plan_id}/checkins/{checkin_id}/submit
POST /packs/journey/plans/{plan_id}/flags
POST /packs/journey/plans/{plan_id}/flags/sweep
POST /packs/journey/plans/{plan_id}/flags/{flag_id}/notify
POST /packs/journey/plans/{plan_id}/complete
GET  /packs/journey/plans/{plan_id}/dossier
GET  /packs/journey/gaps
GET  /packs/journey/recommendations
POST /packs/journey/impact
GET  /packs/journey/impact
GET  /packs/journey/heatmap
```

The `/verify`, `/flags/{id}/notify` routes create **R2 proposals**; they do not execute directly.

---

## 3. Trust-path proof

The important bug fixed during this stage:

- Plan approval originally ended as `unknown` because the worker could not resolve `core.employee` / `core.tenant` foreign keys.
- The journey models now load the core metadata in the worker.
- Verified end to end:
  - HR approves the proposal.
  - Worker applies the hash-bound payload.
  - Plan becomes `in_progress`.
  - Tasks and four check-ins exist.
  - Audit chain verifies `ok`.
- The demo DB was reset afterward so the demo still starts from the pending proposal.

Additional kernel change:

- Added `kernel_0003` migration granting `astra_api` `INSERT` on `trust.proposal`.
- This is required for human-initiated R2 proposals (milestone verification, support-flag notification). Approval remains a separate step; the API still cannot approve its own proposal.
- The existing talent API already assumed this grant, so the migration also repairs that path.

---

## 4. What is not done

### Frontend
No journey UI has been started:

- `/journey` plan list
- `/journey/[planId]` detail, timeline, tasks, check-ins, flags, gaps
- `/journey/me` new-hire portal
- `/journey/gaps`
- shared approval card integration
- `<WhyPanel>` / evidence drawer / edit-then-approve diff

### Optional Tier 1 email series
The in-app check-in flow is complete. The optional R2 email series for check-ins is not wired. This is optional in the design and does not block the MVP.

### Tier 2
Untouched as a product layer:

- D1 probation dossier — backend exists, UI missing
- D2 manager readiness pack — template tasks exist, dedicated pack missing
- D3 team gap heatmap — backend exists, UI missing
- D4 explainability pack — records/envelope exist, UI missing
- D5 manager weekly briefing — not built (explicit first cut)
- D6 reverse doc feedback — seed data only, no portal action
- D7 mentor alternative — backend computation exists, UI missing
- D8 FR/EN copy and accessibility — not started

### Tier 3
Intentionally deferred: campaigns, adoption telemetry, skill decay, Ask → gap loop, certification expiry.

---

## 5. Demo state

Current seeded database:

| Item | Value |
|---|---|
| Tenant | `cds` |
| Pending plan-activation proposals | 1 |
| Draft plan | EMP-010 |
| Draft plan tasks | 29 |
| Draft plan check-ins | 4 |
| Hero | EMP-041, Yasmine Trabelsi |
| Hero portal login | `yasmine@cds.example.test` |
| HR login | `leila@cds.example.test` |
| Manager login | `karim@cds.example.test` |
| Demo password | `DEMO_PASSWORD` in `.env` |

The hero portal returns:

- 3 “today” tasks
- progress 17/29 (59%)
- buddy Mehdi Sassi
- cohort size 1
- next check-in `day30`
- Ask link disabled with reason `preview`

---

## 6. Verification evidence

### Full gate

```bash
python astra.py check
```

Result:

```text
308 passed, 2 skipped
```

The 2 skipped tests are live-stack tests; they are not failures.

### Tier 1 HTTP checks performed manually

- Hero portal: `200`
- Task completion: `200`, status `completed`
- Verification proposal: `200`, status `pending_approval`
- Verification approval → worker → task `verified`
- Support flag create: `200`
- Flag sweep: `200`
- Flag notification proposal: `200`
- HR approval → executor email confirmed in Mailpit
- Impact recording: `200`, delta `-1.5`

### Smoke

```bash
python astra.py smoke
```

Almost everything passes, including:

- service health
- network isolation
- credential isolation
- database permissions
- traces
- real approve → execute → send → audit → graph

One failure remains:

```text
FAIL  worker holds an LLM key
```

This is an environment configuration issue, not a Tier 1 code failure. `ANTHROPIC_API_KEY` is missing or empty in the worker environment. `.env` was not modified. The deterministic Tier 1 path does not depend on it; AI narrative/eval work does.

---

## 7. Key files

| Area | Files |
|---|---|
| Pack | `packages/packs/journey/manifest.yaml` |
| Models | `packages/packs/journey/models.py` |
| Migrations | `packages/packs/journey/migrations/versions/journey_0001_tables.py`, `journey_0002_security.py` |
| Services | `packages/packs/journey/service.py`, `services/planning.py`, `services/gap.py`, `services/pulse.py` |
| Handlers | `packages/packs/journey/handlers.py` |
| API | `packages/packs/journey/api.py` |
| Agents | `packages/packs/journey/agents/onboarding_planner.py`, `skill_gap_analyst.py`, `training_planner.py` |
| Events | `packages/packs/journey/events.py` |
| Seed | `packages/packs/journey/seed.py`, `seed/journey/*` |
| Tests | `packages/packs/journey/tests/`, `tests/test_journey_activation.py`, `tests/test_journey_tier1.py` |
| Kernel grant | `packages/kernel/migrations/versions/kernel_0003_api_proposals.py` |
| Design | `docs/handoff/journey-design.md`, `docs/handoff/explain_wassim.md` |

---

## 8. Merge checklist for the MVP owner

1. Review the kernel migration `kernel_0003_api_proposals.py`. It grants proposal creation, not approval.
2. Run:
   ```bash
   python astra.py up
   python astra.py seed --no-cvs
   python astra.py check
   ```
3. Set `ANTHROPIC_API_KEY` in `.env`, then run:
   ```bash
   python astra.py smoke
   ```
4. Confirm the demo state:
   - one pending plan proposal
   - EMP-010 `draft`
   - 29 tasks
   - 4 check-ins
   - hero login exists
5. Open the PR from `feat/journey/scope-v2` to `main`.
6. Keep Tier 2 out of the first MVP merge.

There is one untracked local duplicate, `docs/Hackathon Specifications.pdf`. It is not part of this work; do not merge it.

---

## 9. What Wassim does next

Wassim continues on Tier 2 for v2:

1. D1 probation dossier UI
2. D3 team gap heatmap UI
3. D2 manager readiness pack
4. D4 `<WhyPanel>` + evidence drawer + edit diff
5. D7 mentor alternative UI
6. D6 reverse doc-feedback action
7. D8 FR/EN copy + accessibility
8. D5 manager weekly briefing only if time remains

Do not expand the heatmap into a campaign scheduler; campaigns remain Tier 3.

---

## 10. One-line handoff

**Tier 1 journey backend is complete, tested, and demo-ready. Merge this branch for MVP; do not wait for Tier 2 or the frontend.**
