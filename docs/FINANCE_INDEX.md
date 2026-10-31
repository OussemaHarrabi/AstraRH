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
| [FINANCE_RULES.md](FINANCE_RULES.md) | Rule set format, the payslip formula, demo values and their verification status, hand-checked cases | Written with the code |
| [FINANCE_PAYMENT_DESIGN.md](FINANCE_PAYMENT_DESIGN.md) | How payment is sent, how its result and bank statuses come back, the sandbox bank, and the kernel requests K1 to K6 | Draft |
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
10. **Small, reviewable changes on a feature branch.** Work on `feat/finance/*`, edit only the finance pack folders, and verify each step before the next.

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
