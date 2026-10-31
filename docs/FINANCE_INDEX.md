# Finance pack: documentation index

Start here. The finance pack covers Tunisian payroll, CIVP placements, payment and cost intelligence for AstraRH. **Status: planning. No finance code exists yet.**

## 1. Documents

| Document | Answers | Status |
|---|---|---|
| [FINANCE_INDEX.md](FINANCE_INDEX.md) | Where everything is, the working approach, decisions, glossary | This file |
| [FINANCE_PLAN.md](FINANCE_PLAN.md) | What we build, boundary with the kernel, rules, data model, Tunisian rate research with sources | Draft |
| [FINANCE_USE_CASES.md](FINANCE_USE_CASES.md) | Who does what in which situation, exceptions, negative cases, priorities | Draft |
| [FINANCE_FEATURES.md](FINANCE_FEATURES.md) | The feature list, release slices, out of scope, definition of done | Draft |
| [FINANCE_SYSTEM_DESIGN.md](FINANCE_SYSTEM_DESIGN.md) | Architecture, modules, tables, state machines, sequences, API, events, security, tests | Draft |
| [FINANCE_AUDIT.md](FINANCE_AUDIT.md) | Audit of 2026-11-01: code defects, document drift, repository state, and how each was resolved | Resolved, except P2 and P4 |
| [FINANCE_RUNBOOK.md](FINANCE_RUNBOOK.md) | Start, test and troubleshoot on macOS, the init-script problem and its workaround, the observed baseline | Written from a real run |
| [FINANCE_ENGAGEMENTS.md](FINANCE_ENGAGEMENTS.md) | Engagement lifecycle, validation rules, documents, activation and amendment, hire notices, database guards, what is not built | Written with the code |
| [FINANCE_RULES.md](FINANCE_RULES.md) | Rule set format, the payslip formula, demo values and their verification status, hand-checked cases | Written with the code |
| [FINANCE_PAYMENT_DESIGN.md](FINANCE_PAYMENT_DESIGN.md) | How payment is sent, how its result and bank statuses come back, the sandbox bank, and the single list of kernel requests K1 to K12 | Draft |
| [ARCHITECTURE.md](ARCHITECTURE.md), [PLAN.md](PLAN.md), [handoff/finance.md](handoff/finance.md) | Platform rules and the original finance brief | Existing |
| [../PROGRESS.md](../PROGRESS.md) | Platform running log | Existing |

**Documents still to write as work lands:** rules reference (each value, source, verification status), API reference generated from the code, event reference, runbook (setup on macOS, seed, demo script), test report, decision records, finance progress log.

## 2. The approach we line up with

**Principle: the code calculates, the AI explains, a human decides.** This is the platform's golden rule and finance inherits it unchanged.

1. **Document first.** Every decision lives in a doc, with the reason, before or with the code. Code comments stay sparse and match the surrounding code. This is a standing rule from the owner.
2. **Align with the platform, do not fork it.** Reuse the kernel's proposals, approvals, audit, decision records, events and jobs. A gap becomes a contract-change request to the kernel owner, never a private copy.
3. **Vertical slices, demonstrable at each step.** Slices S1 to S5 in the features doc. Build the smallest end-to-end path first, then widen. Cut later slices before cutting depth in earlier ones.
4. **A deterministic, replayable core.** Money is `Decimal`. The calculation is a pure function over versioned rules, so any payslip can be recomputed digit for digit.
5. **Rules are data, and legal values are unverified until proven.** Every Tunisian value carries a source and a verification status, shows a demo banner, and never lives in code.
6. **Human approval where people or money are affected.** R2 and R3 actions follow the kernel gate, with step-up and no self-approval on R3.
7. **Least data, least privilege.** Events carry IDs and totals. The executor sees only the trust ledger. Salaries never reach the graph, logs or spans.
8. **Fail closed.** A missing rule, approval or hash means deny.
9. **Tests are derived from the docs.** Use cases and negative cases become acceptance tests. Worked examples are calculated by hand first.
10. **Small, reviewable changes on a feature branch.** Work on the owner's branches (`finance-v0`, `finance-v1`, and so on), edit only the finance pack folders, and verify each step before the next.

## 3. Working process

| Step | Output |
|---|---|
| Clarify the use case | Entry in the use-case doc, with exceptions |
| Design | Update the system design (tables, states, events, API) |
| Raise kernel dependencies | Contract-change request to the kernel owner |
| Write tests from the use case | Failing tests that name the expected behaviour |
| Implement | Smallest change that passes, in the pack only |
| Verify | `python astra.py check`, then `smoke` and a browser run for user-facing steps |
| Record | Feature status table, finance progress log, decision record if something was decided |

## 4. Decisions so far

| # | Decision | Why |
|---|---|---|
| D1 | One `finance` pack owns payroll, CIVP, rule sets and payment lines | Matches the pack model, keeps migrations and RLS isolated |
| D2 | Full interface spec is the target scope, delivered in slices S1 to S5 | Spec given by the owner. Slices let us stop with a working product |
| D3 | Overtime, salary advances and the CIVP-to-CDI incentive are in scope | Owner decision |
| D4 | Payslip is a registered explain scorer with signed factors | Gives replay and the Why panel for free |
| D5 | Rates, brackets and amounts are rule-set data marked demo | Secondary sources only, so nothing is hard-coded or called certified |
| D6 | Payment goes through an executor adapter, sandbox for the demo | Only the executor may act externally. No real bank is available |
| D7 | Executor results update payment lines through a worker consumer | The executor role cannot write finance tables |
| D8 | We export files and create human tasks, never claim a CNSS, tax or ANETI filing | No integration exists, and the spec says not to pretend |
| D9 | Documentation is complete and separate from code comments | Owner instruction |
| D10 | Code starts only when the owner says so | Owner instruction |
| D11 | Payment results reach finance tables through a worker consumer of executor events | The executor role cannot write finance tables (payment design, section 4) |
| D12 | Bank status travels as events published by an executor poll hook | The worker has no bank access (payment design, section 6) |
| D13 | The hire event is the kernel and `talent` owner's work, finance only requests it | Owner decision. Fallback is the stage-change event |
| D15 | A rule set is `draft` then `active`. Testing is computed on demand and re-checked at activation, and approval is the R3 proposal | Stronger than stored `tested` and `approved` flags, and the API role may not change a rule set's status |
| D16 | Person-initiated proposals need kernel request K9 (the API role cannot insert proposals). Finance builds on the worker side meanwhile and marks the HTTP test as an expected failure | Verified in the running system. The same defect affects the talent reject endpoint |
| D17 | The solidarity levy applies to the whole net taxable amount once above 5,000, so a step at the threshold is intended | The law as written (LF 2018 art. 53, LF 2020 art. 39). Recorded with sources in the rules reference |
| D18 | The demo rule set ends on 2026-12-31 | The half-point levy is extended only through 2026 |
| D19 | Decimal values in a rule set must be finite strings | The database rewrites some JSON numbers, which would break the approved hash |
| D20 | Fix the macOS database init in the shared ops files (K8), although ops belongs to the kernel owner | Owner's instruction. `01-init.sh` became `01-init.sql`, verified identical, flagged for Oussema to review |
| D21 | Commits are authored as `Moetaz Dhahri <61095319+MoetazDhahri@users.noreply.github.com>`, set in this repository only | Owner's instruction. The GitHub no-reply address links commits to the account without exposing a private email |
| D22 | Finance event consumers are registered by importing the finance module in `apps/worker/main.py`, as `talent` does, until the manifest `consumers:` section (K7) exists | That is how the platform wires packs today. The one-line edit is in a kernel-owner file, so it is requested, not made |
| D23 | The hire event creates a **hire notice** for HR to complete, not an engagement | The event has no employee, salary or start date, and `talent` never reaches `hired`. A notice is honest about what is known |
| D24 | Engagement activation and later changes are guarded in the database: the API role cannot activate or edit an active engagement or its pay | Same lesson as the audit: enforce it in the database, not only in code |
| D25 | Added a hire action, event and endpoint to the talent pack, and a one-line import to the worker, although both belong to the kernel owner | Owner's instruction to fix the hire flow. Additive, flagged for the kernel owner's review |
| D26 | Hiring is R3: a second person, a fresh password, and only `admin` and `hr` approve | A hire affects a person as seriously as a rejection, which is already R3 |
| D27 | Made the talent pack's `langgraph` import lazy and added a test that loads every pack's API without the agent libraries | On `main` the talent pack failed to load in the real API. Found while fixing the hire flow |
| D14 | **No AI work for now.** Build the deterministic features an AI agent will later work on. Every action is a plain service function with a manifest entry, so an agent can call it later through the same proposal and approval path | Owner decision. Deferred: FT-08 contract extraction, FT-09 AI explanation of flags. The rule-based anomaly checks and human entry of document fields stay. No LLM keys are needed for finance until this is lifted |

**Open decisions:** termination and final settlement scope, minimum-wage check, whether S1 alone is the demo target, who verifies the rate sources, sandbox bank versus a real provider, payslip PDFs, and the sector for employer rates.

## 5. Glossary

| Term | Meaning |
|---|---|
| **CDI** | Open-ended employment contract |
| **CDD** | Fixed-term employment contract. Valid reasons come from a locally validated list **[verify]** |
| **CIVP** | Internship-style insertion contract (Contrat d'Initiation à la Vie Professionnelle), formerly SIVP, with a state allowance and an employer complement |
| **ANETI** | National employment agency that approves CIVP placements and pays the state allowance |
| **CNSS** | National social security fund. Employee and employer contributions |
| **IRPP** | Personal income tax, progressive by bracket |
| **CSS** | Social solidarity contribution, a small levy on taxable income |
| **TFP** | Vocational training tax paid by the employer |
| **FOPROLOS** | Housing promotion fund contribution paid by the employer |
| **SMIG** | Guaranteed minimum wage. Value to verify |
| **TND, millime** | Tunisian dinar and its thousandth. Money keeps three decimals |
| **Engagement** | A person's employment or placement record with dates and terms. A CIVP and a later CDI are separate engagements |
| **Rule set** | Versioned, effective-dated data holding rates, brackets and deductions |
| **Payroll run** | One calculation for a period and employer, from draft to closed |
| **Adjustment** | A correction in a later run for a change effective in a closed period |
| **Reconciliation** | Matching the provider's reported payment status to the approved run |
| **R0 to R3** | Platform risk classes. R2 and R3 need human approval, R3 adds step-up and no self-approval |
| **Decision record** | The kernel's stored explanation of a computed result, replayable |
| **Step-up** | Re-entering the password to perform a serious action |
| **RLS** | Row-level security that scopes every row to a tenant |
| **Idempotency key** | A stable key that makes a repeated request change nothing |

## 6. Finance progress log

| Date | Entry |
|---|---|
| 2026-10-31 | Cloned the repo, read all platform docs, created branch `feat/finance/backend`. Wrote the plan with researched Tunisian rates, the use-case catalogue, the feature list, the system design and this index. Scope decisions D2 and D3 recorded. No code written. |
| 2026-10-31 | Plan for S1 to S3 backend approved. Decision D14: no AI for now. Generated `.env` (no LLM keys needed). Docker Desktop was not running, so the stack and the full test suite have not been run on this Mac. Wrote the pure calculation core: `packages/packs/finance/payroll/rules.py` and `calc.py`, the demo rule set `data/demo/finance/rule_set_tn_2026_demo.json`, and `tests/test_finance_calc.py`. Four payslips were worked out by hand first and the code matched all four. 35 pure tests pass and ruff is clean, run in a throwaway environment with `--noconftest`, not through `astra.py check`. Next: pack skeleton, tables and migrations (needs the stack for autogenerate and RLS tests). |
| 2026-10-31 | Pushed the above to branch `finance-v0` (commit d0083ca). Started the stack on macOS. The Postgres init script failed on Docker Desktop (mount treats it as executable), fixed locally by feeding it through standard input, no repo change, no data lost. Baseline: all services healthy, `smoke` passes except the expected empty-LLM-key check, `check` gives 288 passed and 2 skipped including the 35 finance tests. Wrote `FINANCE_RUNBOOK.md` and raised kernel request K8. |
| 2026-10-31 | Phase 1 foundation built: pack `manifest.yaml` (status preview), `models.py` (20 tables), `events.py` (14 events), migrations `3e65e32a7d91` and `finance_0002` (row-level security, role permissions, append-only bank history, frozen submitted payslips, immutable closed runs). Applied to the running database: 20 tables, all with row-level security. Wrote `tests/test_finance_schema.py` (16 tests with the real database roles). `astra.py check`: **304 passed, 2 skipped**, ruff clean. Corrected the design: documents hold a MinIO `file_key`, and overlap checks move to the service layer because `btree_gist` is not installed. Not yet pushed. |
| 2026-10-31 | Pushed Phase 1 to branch `finance-v1`. Built rule-set storage and the calculator API: `service.py`, `handlers.py`, `api.py`, `payroll/examples.py`, hand-checked examples inside the demo rule set, action `finance.rules.activate` (R3), and 34 tests in `tests/test_finance_rules_api.py`. Covers date selection, overlap refusal, draft isolation, roles, two-person activation with password confirmation, and a rule set changed after approval being refused. `astra.py check`: **337 passed, 2 skipped, 1 expected failure**. Found a kernel defect: the API role cannot insert proposals (K9). |
| 2026-11-01 | Audit (independent code review plus document and repository review), written up in `FINANCE_AUDIT.md`. Fixed every finding: migration `finance_0003` (rule sets, frozen runs, run status path), tamper-refusing calculation, retryable activation, correct approver text, strict number parsing, activation lock, monthly tax bases, Tunis date. Researched the solidarity levy: the step is the law as written, and the half-point ends after 2026, so the demo rule set now ends on 2026-12-31. Unified kernel requests as K1 to K12. `astra.py check`: **374 passed, 2 skipped, 1 expected failure**. Not committed. |
| 2026-11-01 | Fixed the macOS setup bug (K8): `ops/postgres/init/01-init.sh` is now `01-init.sql`, run by psql with `\getenv`. Verified on throwaway containers: completes on macOS, identical roles, schemas and permissions to the old script, fails closed when a password is missing. Switched this repository's commit identity to the owner's GitHub account. |
| 2026-11-01 | Rebased onto the latest `main` (`63529ca`, five commits from the kernel owner adding inbox triage, calendar, policy answers, replies and follow-ups). No conflicts: the one shared file, `PROGRESS.md`, merged cleanly. Applied the new migrations: the database is at `kernel_0006`, `talent_0004` and `finance_0003`. `astra.py check`: **420 passed, 2 skipped, 1 expected failure**. `smoke`: only the expected empty-LLM-key check fails. Re-checked every kernel request against `main` (payment design section 8.1). K9 is still open, K7 has a known pattern, K8 is fixed on this branch. Pushed as `finance-v2`. |
| 2026-11-01 | Phase 3 built: engagements with 12 validation rules, issues a person can decide with a reason, documents and checklists, R2 activation bound to the exact terms, effective-dated amendments, the hire notice flow, and database guards (`finance_0004`, plus `hire_notice` table, 21 tables). Found that `talent` never reaches `hired` and its event has no terms (K1 is larger). Wrote `FINANCE_ENGAGEMENTS.md`. `astra.py check`: **518 passed, 2 skipped, 4 expected failures** (K9 three times, K7 once), each confirmed to fail for its stated reason. Not yet pushed. |
| 2026-11-01 | Fixed the hire flow. Talent had no `hired` stage, so it could not hire. Added `talent.application.hire` (R3), its handler, `POST /applications/{id}/hire`, and the event `talent.candidate.hired.v1`. Finance now records a hire notice with the person, and HR can complete it without naming the employee when one exists for that person. The worker imports the finance consumers. Found and fixed a bug on `main`: the talent pack failed to load in the real API because `communications.py` imported `langgraph` at module level (the API image has none). New regression test fails without the fix. Regenerated `contracts/openapi.json` (61 paths, 15 talent, 19 finance). `astra.py check`: **537 passed, 2 skipped, 4 expected failures** (all K9, each confirmed). `smoke`: only the expected LLM-key check fails. Not yet pushed. |
