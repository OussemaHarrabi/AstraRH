# Finance pack: features we will implement

What the finance pack will do, grouped as features, with the use cases each one covers ([FINANCE_USE_CASES.md](FINANCE_USE_CASES.md)), the risk class of its actions, and the release slice it ships in. Design is in [FINANCE_SYSTEM_DESIGN.md](FINANCE_SYSTEM_DESIGN.md). Plan and rules are in [FINANCE_PLAN.md](FINANCE_PLAN.md).

**Slices.** Each slice is demonstrable on its own and every later slice builds on the one before.

| Slice | Goal | Done when |
|---|---|---|
| **S1 Demo core** | The hire becomes an engagement, a payroll run is calculated and approved, payment is released with one failure reconciled | The 60-second finance demo beat runs in a browser |
| **S2 CIVP** | A CIVP placement with two separate payers, training, completion and transition to CDI | Spec scenarios 3, 4 and 7 pass |
| **S3 Credible product** | Rules administration, documents and AI assist, amendments and adjustments, exports, employee self-service | Spec scenarios 1 to 10 all pass |
| **S4 Cost intelligence** | Dashboard, forecast, what-if, attrition, training ROI | Hire event updates the forecast with its drivers |
| **S5 Extended payroll** | Overtime, advances, termination and final settlement, incentive | Each has hand-checked tests |

## Feature list

Status of every feature is `planned` unless noted below. Update this table as work lands.

**Progress (tables):** the data model for S1 to S3 is built, with security rules and 16 database tests (FT-58 and the integrity parts of FT-57, FT-59, FT-61 and FT-62 are partly in place at the database level). See [FINANCE_SYSTEM_DESIGN.md](FINANCE_SYSTEM_DESIGN.md) section 4.1.

**Progress (runs):** FT-16 (the run lifecycle up to approval), FT-17 (deterministic calculation with one decision record per payslip), FT-18 (anomaly checks) and FT-19 (replay) are built and tested, see [FINANCE_RUNS.md](FINANCE_RUNS.md). Payslips are replayable and the approval re-verifies them. Not yet: payment (FT-27 to FT-31), adjustments (FT-20), run comparison (FT-21), off-cycle runs (FT-22), proration (FT-23). Submitting over HTTP waits for kernel request K9.

**Progress (inputs):** FT-14 (input collection and CSV import, with idempotent source ids and per-row rejection reasons) and FT-15 (conflict detection) are built and tested, see [FINANCE_INPUTS.md](FINANCE_INPUTS.md). Inputs from workforce events wait for those events to exist on `main`. A run does not read inputs yet.

**Progress (engagements):** FT-01 (engagement record), FT-02 (validation engine), FT-03 (activation, as an R2 action), FT-04 (CDD review path), FT-05 (amendments, effective-dated) and FT-07 (document checklist) are built and tested, see [FINANCE_ENGAGEMENTS.md](FINANCE_ENGAGEMENTS.md). The hire flow (use case A1) is built end to end: talent can now hire (R3), emits `talent.candidate.hired.v1`, and finance records a hire notice for HR to complete (see [FINANCE_ENGAGEMENTS.md](FINANCE_ENGAGEMENTS.md) section 7). Not yet: FT-06 (termination), the ending-soon reminder, editing a draft's terms. Activation and amendment cannot be proposed over HTTP until kernel request K9, and the hire consumer is not registered in the worker until K7.

**Progress (calculation and rules):** FT-10 (calculator), FT-42 (rule sets as data), FT-43 (rule tests) and the activation part of FT-44 are built and tested, see [FINANCE_RULES.md](FINANCE_RULES.md) and [FINANCE_SYSTEM_DESIGN.md](FINANCE_SYSTEM_DESIGN.md) section 8.1. FT-11 (compare) is built. Activation over HTTP waits for kernel request K9. Impact preview (FT-45), employer configuration (FT-46) and the verification record (FT-47) are still to do. Everything else is planned.

### Engagements

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-01 | **Engagement record** for CDI, CDD and CIVP with effective-dated pay items | A1, A5 | R1 | S1 |
| FT-02 | **Validation engine** returning issues with code, severity, field, next action and owner role | A2 | R0 | S1 |
| FT-03 | **Activation** of an engagement through a human-approved proposal | A3 | R2 | S1 |
| FT-04 | **CDD review path**: unclear reason or missing end date routes to a named human and cannot proceed silently | A4, A8 | R2 | S3 |
| FT-05 | **Amendments** (raise, hours, title) that never overwrite history | A5, A10 | R2 | S3 |
| FT-06 | **Termination** with proration flag and open-advance warning | A9 | R3 | S5 |

### Documents and AI assist

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-07 | **Document checklist** per engagement type, with references and verification status only | A6 | R1 | S3 |
| FT-08 | **AI field extraction** from contracts as unconfirmed suggestions with quoted evidence. **Deferred: AI is paused (decision D14)** | A7 | R2 on confirm | later |
| FT-09 | **AI explanation** of validation and anomaly flags, checked against the numbers. **Deferred: AI is paused (decision D14)** | D4 | R0 | later |

### Net pay calculator

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-10 | **Gross to net calculator**: type a salary, get every line down to net and employer cost, with rule and source on each line | C1, C2 | R0 | S1 |
| FT-11 | **Scenario compare** side by side | C3 | R0 | S3 |
| FT-12 | **Offer-stage estimate** shown to recruiters as aggregates only | C5 | R0 | S3 |
| FT-13 | **Net to gross** solver verified by the forward calculation | C4 | R0 | S5 |

### Payroll

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-14 | **Input collection and CSV import** with idempotent source ids and per-row rejection reasons | B1, B2 | R1 | S1 |
| FT-15 | **Input conflict detection** (duplicates, orphan inputs, limits) | B3 | R0 | S1 |
| FT-16 | **Payroll run lifecycle**: create, calculate, review, submit, approve, reject, close | D1, D2, D3, D5, D6, D9 | R1 to R3 | S1 |
| FT-17 | **Deterministic calculation** under versioned rule sets, one decision record per payslip | D2 | R1 | S1 |
| FT-18 | **Anomaly checks** against previous runs | D4 | R0 | S1 |
| FT-19 | **Replay and verify** a payslip digit for digit | D8 | R0 | S1 |
| FT-20 | **Adjustments** for changes effective in closed periods | D7, B4 | R1 | S3 |
| FT-21 | **Run comparison** by org unit, joiners and leavers | D11 | R0 | S3 |
| FT-22 | **Off-cycle run** for a single correction | D10 | R3 | S3 |
| FT-23 | **Proration** for mid-month joiners and leavers | D12, B5 | R1 | S5 |
| FT-24 | **Overtime** with configured premiums | B6 | R1 | S5 |
| FT-25 | **Salary advances** with capped recovery | B7 | R2 | S5 |
| FT-26 | **Final settlement** computed at termination | H3 | R3 | S5 |

### Payment and reconciliation

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-27 | **Payment preparation**: one idempotent line per payslip | E1 | R1 | S1 |
| FT-28 | **Payment release** through the executor, bound to the approved hash | E2 | R3 | S1 |
| FT-29 | **Timeout reconciliation**: ask the provider, never retry blindly | E3 | R1 | S1 |
| FT-30 | **Status reconciliation** for paid, failed, part-paid and reversed | E4, E6, E7 | R1 | S1 |
| FT-31 | **Failure handling** with a new release for only the failed lines | E5 | R3 | S1 |
| FT-32 | **Accounting and filing exports** that produce a file and a human task, never a filing | E8 | R2 | S3 |

### CIVP

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-33 | **Placement record** with ANETI reference, category, dates and configured amounts | F1, F12 | R1 | S2 |
| FT-34 | **Eligibility and document review** as a human decision with evidence | F2 | R2 | S2 |
| FT-35 | **Activation** after human-entered ANETI approval and verified documents | F3 | R2 | S2 |
| FT-36 | **Two-payer monthly ledger**, never merged | F4, F5 | R1 | S2 |
| FT-37 | **Training records** with limit warning | F6 | R1 | S2 |
| FT-38 | **Summary** per placement | F7 | R0 | S2 |
| FT-39 | **Extension requests** refused unless the allowed condition is met | F8 | R2 | S2 |
| FT-40 | **Completion, early end, and CDI transition** into a separate engagement | F9, F10, F11 | R2 | S2 |
| FT-41 | **Hiring incentive record** shown as a separate employer-cost line | F13 | R2 | S5 |

### Rules administration

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-42 | **Rule sets as data**: CNSS, deductions, IRPP brackets, CSS, employer charges, CIVP amounts | G1 | R1 | S1 |
| FT-43 | **Rule tests** against hand-checked examples | G2 | R1 | S1 |
| FT-44 | **Rule activation** with diff and test results | G3 | R3 | S3 |
| FT-45 | **Impact preview** before activation | G4, G5 | R0 | S3 |
| FT-46 | **Employer configuration** (entity, sector, regime, sector rates) | G6 | R2 | S3 |
| FT-47 | **Verification record** (who checked which source, when) | G7 | R2 | S3 |

### Employee views

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-48 | **My payslips** with line breakdown and Why | H1, H2 | R0 | S1 |
| FT-49 | **Payslip questions** routed to finance, policy answers only | H4 | R1 | S3 |
| FT-50 | **Certificates** (salary or employment attestation) | H5 | R2 | S5 |

### Cost intelligence

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-51 | **People-cost dashboard** by org unit and month | I1 | R0 | S4 |
| FT-52 | **Hire cascade forecast update** with drivers | I2 | R1 | S4 |
| FT-53 | **What-if scenarios** | I3 | R0 | S4 |
| FT-54 | **Cost of attrition** by role level | I4 | R0 | S4 |
| FT-55 | **Training ROI** | I5 | R0 | S4 |
| FT-56 | **Budget overrun alert** | I6 | R1 | S4 |

### Platform

| ID | Feature | Use cases | Risk | Slice |
|---|---|---|---|---|
| FT-57 | **Audit trail per payslip** with chain verification | J1 | R0 | S1 |
| FT-58 | **Access control matrix** with scoped employee grants and audited denials | J2, H1 | R0 | S1 |
| FT-59 | **Idempotent event handling** with replay, parking and dead-letter | J3, J4 | R1 | S1 |
| FT-60 | **Sensitive read auditing** | J5 | R0 | S3 |
| FT-61 | **Fail-closed checks** everywhere a rule, approval or hash is missing | J6 | R0 | S1 |
| FT-62 | **Event minimisation**: IDs, status and totals only | J9 | R0 | S1 |
| FT-63 | **Monitoring and dashboards** in Grafana | J8 | R0 | S5 |

## Explicitly out of scope

| Item | Reason |
|---|---|
| Real bank, CNSS, tax or ANETI integrations | None is available. We export and create human tasks, and say so on screen |
| Legal certification of any rate or rule | Values are reviewed demo data until verified against the official text |
| Tax treatment of benefits in kind, special sector schemes, dependent parents | Not found in sources. Listed as unsupported on screen |
| Individual attrition or flight-risk prediction | Banned by the platform's "what we will not build" |
| Person-level pay data in Neo4j, in spans or in logs | Platform rule |
| Payslip PDF generation | Web payslip first. PDF only if a renderer is agreed |
| Backups and restore drills | Production item, documented but not built |

## Definition of done for a feature

1. Use cases implemented, with their negative cases tested.
2. Actions declared in the manifest with a risk class, and every R2 and R3 proposal carrying a decision record.
3. Money code uses `Decimal`, has hand-checked tests, and imports no database or model client.
4. Events carry no salary lines or bank details.
5. The UI handles empty, loading and error states, and shows the demo-values banner where a rule is used.
6. The docs are updated in the same change: this table, the API and event references, and the progress log.
