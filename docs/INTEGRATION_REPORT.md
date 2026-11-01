# Integration report: main-agent phase

**Branch:** `integration/final`  
**Remote:** `origin/integration/final`  
**Latest commit at this report:** `8c5d8a3`  
**Scope:** merge the teammate branches, fix integration seams, freeze and document the API contract. UI work intentionally excluded.

## 1. Starting point

When I took over, `main` was at `df385d2` (calendar and ICS import) with one untracked file, `packages/kernel/limits.py`. That file is still untracked and is not part of this branch.

The teammate branches were:

| Branch | Ahead / behind `main` | Textual merge |
|---|---:|---|
| `origin/feat/journey/scope-v2` | 26 / 13 | clean |
| `origin/finance-v2` | 10 / 3 | one conflict |
| `origin/feat/workforce/scope-v1` | 7 / 8 | clean, but not semantically mergeable |

## 2. What was merged

### Journey

`origin/feat/journey/scope-v2` was merged first on `integration/final`.

The merge itself was clean. The first full test run exposed one integration bug: the journey tests had a `packages/packs/journey/tests/conftest.py` that shadowed the kernel `tests/conftest.py` when pytest collected `packages/`. Root tests then failed with:

```
ImportError: cannot import name 'role_url' from 'conftest'
```

Fix: renamed it to `path_setup.py` and kept only its path setup. A later syntax error in that renamed helper was fixed as a separate commit.

### Finance

`origin/finance-v2` was merged next. The only conflict was `packages/packs/talent/communications.py`.

Resolution:

- kept main’s newer inbound-mail / candidate-time-answer logic;
- kept finance’s lazy LangGraph imports, so the API process can load the module without agent libraries;
- did not merge finance’s stale copy of `contracts/openapi.json`; regenerated the contract after the merge;
- kept finance’s `tests/test_api_loads_without_agent_libraries.py`.

### Workforce

**Not merged.** The branch has models, scoring, seed and tests, but it is not a working service:

- no `api.py`;
- no `handlers.py`;
- no `agents/` directory;
- no RLS migration;
- its manifest route would 404;
- `test_architecture.py` would fail on its tables.

It remains a separate branch. Do not expose it in the dashboard until it passes the same gates as journey and finance.

## 3. Database and runtime fixes

### Migrations

The merged branch has these heads:

```
kernel_0009 (evidence ref width)
finance_0006
journey_0002
talent_0004
```

Packs still depend on `kernel_0002`; `python -m kernel.migrate up` upgrades all heads. A fresh-volume run was performed, not only an incremental upgrade.

### Migration added

`kernel_0009_evidence_ref.py` widens `trust.decision_evidence.ref` from 16 to 128 characters. Journey evidence uses stable references such as `plan:<uuid>`, which the original 16-character column could not store.

### Seed fixes

A fresh seed exposed three journey-data assumptions that did not match the merged generator output:

1. `_date()` accepted date-only strings but the plan file contains datetimes (`2027-04-07T09:00:00`); it now takes the date prefix.
2. Seed plan tasks have `task_id` such as `GEN-01`, not `position`; the loader now resolves the template task by title or task-id suffix.
3. The evidence reference column was too narrow; fixed by `kernel_0009`.

After those fixes, `python astra.py seed` succeeded on a fresh database: tenant seeded, 42 CVs queued, 5 policy documents loaded, 22 emails loaded.

### API proposal permission

Added `kernel_0008_api_proposals.py`: `GRANT INSERT ON trust.proposal TO astra_api`.

This fixes the K9 gap: human-initiated actions proposed from the API (hire, reject, interview booking, finance activation, amendment, payroll submission) previously failed because the API role could not insert a proposal. The API still cannot approve or record an execution.

The four finance tests that were strict `xfail` for K9 are now normal tests. The obsolete xfail markers were removed.

## 4. Cross-service data flow fixes

### Employee creation bridge

Added `POST /people/employees` (admin/hr). It:

- turns a hired person into a `core.employee`;
- validates org unit, position and manager;
- updates `person.lifecycle` to `employee`;
- emits `core.employee.created.v1` with IDs and start date only;
- writes an audit record.

This closes the gap where finance required an employee that no API could create.

### Onboarding trigger

Journey’s onboarding planner now accepts:

- `talent.candidate.hired.v1` (person ID; no-op until an employee exists);
- `core.employee.created.v1` (employee UUID; creates the plan);
- `finance.engagement.activated.v1` (employee UUID + start date; fallback).

The planner can resolve an employee by UUID, external ID, or person ID, and accepts `starts_on` as well as `start_date`.

Journey’s manifest now declares those events and consumers.

### Journey agent runtime

The journey agents were direct functions (`run(ctx, event)`) but the registry expects a LangGraph builder. They were silently failing at runtime with a `TypeError`. Each agent now exposes a `build()` graph wrapper around its deterministic `run` function, and the manifest entries point at `:build`.

The new `tests/test_employee_flow.py` proves the whole bridge: HR creates an employee → `core.employee.created.v1` → relay → onboarding agent → `journey.plan.activate` proposal with an `org_unit` target.

### Scoped manager access

`has_role` already required a target for scoped grants, but most journey endpoints called `require_role` without one. Added `require_role_any_scope` for row-filtered read/write endpoints; the service still restricts rows to the actor’s own employee/direct reports.

Journey approval targets now include `org_unit` through `employee_target()`. Seeded and agent-generated proposals use it, so a manager scoped to `ORG-ENG` can approve own-team actions.

Talent no longer advertises `manager` in its UI roles because its API read set does not include manager; this removes a sidebar route that would return 403.

## 5. API contract

### Generated contract

- `contracts/openapi.json`: 111 paths, 122 operations, security schemes.
- `contracts/openapi.d.ts`: generated with `openapi-typescript@7`.
- `docs/API.md`: short operations guide.
- `docs/API_CONTRACT.md`: detailed route inventory, request schemas, auth, roles and data flow.

The OpenAPI contract now declares:

- `sessionCookie` (`astra_session`, cookie);
- `csrfHeader` (`x-csrf-token`, header);
- per-operation security: session for reads, session + CSRF for mutations, public for login/logout/health.

Command:

```bash
python astra.py export-api
npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts
```

### Contract limitation

Most successful responses are still open JSON objects because the backend serializers return dictionaries. The generated TypeScript is reliable for paths, methods, request bodies and auth. Domain response types are still in `apps/web/src/lib/api.ts`; named response DTOs are the next contract step before the UI is built.

## 6. Verification performed

| Check | Result |
|---|---|
| Journey merge | clean |
| Finance merge | one conflict, resolved and committed |
| Journey tests | 66 passed (with hire tests) |
| Employee + finance HTTP tests | 161 passed |
| Fresh DB migration + seed | passed after the three seed fixes |
| Initial post-merge full suite | 234 failed, 626 passed — all failures were missing finance tables before migration |
| Full suite after migration | 861 passed, 4 failed — all four were obsolete strict XPASS markers for K9; markers removed |
| Final contract generation | passed; 111 paths / 122 operations |
| Full suite after the final changes | **not confirmed green**; the run exceeded the tool window at roughly 74% with no observed failures |

The final full-suite run was still in progress when time ran out. Do not treat the branch as fully green until it completes. Targeted suites are green.

## 7. Commits pushed

| Commit | Purpose |
|---|---|
| `b334f22` | Merge journey |
| `0164655` | Fix journey conftest shadowing |
| `e50c90c` | Merge finance |
| `087259d` | Fix journey path helper syntax |
| `a128316` | Connect hire activation and scoped manager gates |
| `7e6d795` | Freeze contract and fix seed compatibility |
| `4654212` | Connect employee creation and fix journey agent runtime |
| `d2d3568` | Clarify contract source |
| `8c5d8a3` | Add the detailed API contract document |

All are pushed to `origin/integration/final`.

## 8. Current state and next actions

### Working

- `talent` and `journey` merge.
- `finance` merge and backend flows.
- Fresh database initialization and seed.
- Employee creation bridge to journey onboarding.
- API-initiated proposals and finance HTTP activation/submission tests.
- OpenAPI contract and generated TypeScript.
- Approval ledger, audit, explainability, inbox, knowledge and calendar remain intact.

### Still open

1. **Run the full suite to completion** after the final changes.
2. **Workforce** is not mergeable yet: add API, handlers, agents and RLS, then re-run architecture tests.
3. **UI**: not touched by request. Journey has a route but no page; finance has no `ui` block. Do not expose dead routes.
4. **Response DTOs**: add named Pydantic response models for UI-used endpoints, then regenerate OpenAPI and TypeScript.
5. **Role contract**: manager read/write gates were fixed for journey; review finance and future packs for target-key consistency.
6. **Untracked** `packages/kernel/limits.py` is not part of this branch. Decide whether to finish and commit it or discard it.

## 9. Operating commands

```bash
# full tests
python astra.py check

# fresh database
python astra.py down --wipe
python astra.py up
python astra.py seed

# contract
python astra.py export-api
npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts

# demo
python astra.py smoke
```

Demo login remains tenant `cds`, users in `data/world.json`, and the current `DEMO_PASSWORD` in `.env`.
