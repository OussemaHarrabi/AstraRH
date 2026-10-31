# Finance pack plan: Tunisia Payroll, CIVP and payment

Status: **draft for review. No code written yet.** Pack id `finance`, schema `finance`.
Sources: `docs/handoff/finance.md`, `docs/ARCHITECTURE.md`, `docs/PLAN.md`, the two interface specs pasted by the owner (workflow integration map and the Tunisia Payroll & CIVP interface spec), and the kernel code as it stands (`trust`, `explain`, `events`, `registry`, `adapters`, `talent` pack).

## 1. What we are building

One pack that owns, end to end, the money side of an employee's life at Carthage Demo Systems:

1. **Engagements**: CDI, CDD and CIVP, with validation and human review of exceptions.
2. **CIVP placements**: ANETI allowance and employer complement tracked as two separate funding sources, training hours, extensions, completion, and transition to a separate CDI.
3. **Payroll**: approved inputs, a versioned rule set, a deterministic draft run, review, approval, payslips.
4. **Payment**: preparation, release through the executor, status returned, reconciliation.
5. **Cost intelligence** (from the original finance brief, after the above): people-cost dashboard, 12-month forecast and scenarios, cost of attrition, training ROI.

Golden rule applies unchanged: **the code calculates, the AI explains, a human decides.** Payroll approval, payment release, rule changes, engagement activation and CIVP eligibility are never automatic.

### Boundary: what the pack owns and what it does not

| Capability | Owner in AstraRH | Consequence for this pack |
|---|---|---|
| Employee identity, general profile | `core.person`, `core.employee` (kernel) | We reference `employee_id`, never copy identity |
| Hiring and contract approval | `talent` (and later `journey`) | We consume an event, we do not own hiring |
| Document storage and access | kernel `files` (MinIO) | We store **document references and verification status** only |
| Time, leave | `workforce` pack (not built yet) | We define the inbound contract and ship a seed/import path until it exists |
| Tasks, reminders, notifications | kernel jobs and `core.notification` | We raise tasks through events and jobs |
| Tunisia payroll rules and calculation | **`finance`** | Ours |
| CIVP ledger and placement tracking | **`finance`** | Ours |
| Payroll approval and audit | kernel `trust` and `explain`, driven by `finance` | We use the gate, we do not rebuild it |
| Bank payment execution | **executor adapter**, behind R3 approval | Sandbox provider for the demo, real provider is a production swap |
| Statutory filing (CNSS, tax) | Out of scope. We **export and create a human task**, never claim to have filed | Stated on screen |
| AI suggestions | kernel `ai` gateway | Suggestions plus evidence, never authoritative data |

## 2. Hard limits (inherited, and what they mean here)

- **LLMs never compute money or decide legality.** No tax, contribution, net pay, CIVP eligibility, CDD validity or payroll approval from a model. The model may explain a flag in words, and a validator rejects any narration whose numbers are not in the record (`kernel.explain.validate_narrative`).
- **`Decimal` only.** TND has 3 decimals (millimes). Quantize explicitly, one rounding rule per line, documented in the rule set. No floats anywhere in the pack. Enforced by a test that scans the pack for `float`.
- **Rates and brackets are configurable demo values, not legally certified.** Contribution rates, income tax brackets, CIVP amounts and training limits are **data in a rule set**, marked `demo`, and must be checked against current CNSS, tax authority and ANETI instructions before any real use. The screen, the payslip footer and the pitch say so.
- **No salary, bank or identity data in Neo4j, in event payloads beyond IDs and totals the consumer needs, in spans or in logs.** Events carry IDs and status. Details are fetched through the API under authorisation.
- **No individual scoring of people.** No "flight risk". Attrition cost is an estimate for a role level with visible assumptions, not a prediction about a person.
- **A pack imports only `kernel.*` public APIs and other packs' `contracts.py`.** Foreign keys point only into `core`. Every table has `tenant_id` and RLS, with a follow-up migration enabling RLS (a test fails otherwise).

## 3. How it plugs into the existing kernel

What already exists and we reuse as is:

| Need | Existing piece |
|---|---|
| Propose, edit, approve, execute, audit | `kernel.trust` (`propose`, `approve`, `execute`, hash-bound approvals, step-up, no self-approval on R3) |
| Two-key authorisation | `kernel.authz.can_approve`. The `finance` role already exists in `ROLES` |
| Factors that sum exactly, replay, counterfactuals | `kernel.explain` with `register_scorer(name, version)` |
| Reliable events | `kernel.events.publish` (transactional outbox) and isolated deliveries per consumer |
| Background work | `kernel.jobs` (Procrastinate). A new queue must be added to `WORKER_QUEUES` |
| Pack discovery | `packages/packs/finance/manifest.yaml`, loaded by `kernel.registry`. Actions, agents, graph projections and routers are wired from it |
| External actions | `executor` process, the only holder of external credentials. Adapters live in `kernel/adapters/` |
| Per-pack migrations | Alembic branch per pack, then an RLS revision like `talent_0002` |

**The payroll run is a scorer.** A payslip is a decision whose factors are its lines (gross, each contribution, each tax step, net). `register_scorer("finance.payroll", "1")` makes every payslip replayable: "Recalculate" recomputes from stored inputs and rule version and compares digit by digit, exactly as screening does. Factor sum equals net pay, enforced by the kernel.

### Contract changes needed from the kernel owner

Teammates edit only `packages/packs/finance/**` and `apps/web/src/modules/finance/**`. These need a contract-change issue to Oussema, raised early:

| # | Change | Why | Fallback if not ready |
|---|---|---|---|
| C1 | `talent.candidate.hired.v1` (or documented use of `talent.application.stage_changed.v1` with `to_stage=hired`) | Trigger for the whole chain. The plan lists it but `talent` does not emit it yet | Consume `stage_changed` where `to_stage == "hired"` |
| C2 | A payment adapter in `kernel/adapters/` plus its registration in the executor, with `find()` for reconciliation like the mail adapter | Payment release is an external R3 action | Build a **sandbox bank** adapter ourselves in the pack's PR and hand it over for review |
| C3 | Add `finance` queue to `kernel.jobs.WORKER_QUEUES` | Payroll calculation as a durable job | Run calculation synchronously in the API for the demo size |
| C4 | Employee-scoped role grant for self-service payslips (`scope_type="employee"`) | Employees see only their own payslip | `authz` already supports scoped grants, so confirm the grant shape only |
| C5 | Event-envelope extras (`correlation_id`, `idempotency_key`) | The spec wants them on every event | Put them in our payload fields, kernel dedupes on `event_id` already |
| C6 | Optional: a kernel document-checklist helper | Spec has a document stage | Keep `document_ref` and checklist inside `finance` (the kernel has no documents module yet) |

## 4. Domain model

Schema `finance`. Every table: `id` (uuid7), `tenant_id`, `created_at`, RLS on. IDs are stable across systems, and any `external_request_id` is unique per tenant so a retry cannot create a duplicate.

**Engagement and documents**
- `engagement`: `employee_id` (to `core.employee`), `type` (CDI, CDD, CIVP), `status`, `starts_on`, `ends_on`, `job_title`, `work_location`, `weekly_hours`, `cdd_reason_code`, `external_request_id`, `source_event_id`.
- `engagement_amendment`: effective-dated change records (field, old, new, `effective_from`, actor, reason). Amendments never overwrite history.
- `pay_item`: `engagement_id`, `code` (BASE_SALARY, ALLOWANCE, BONUS, REIMBURSEMENT...), `amount`, `currency`, `frequency`, `valid_from`, `valid_to`. Effective-dated.
- `document_ref`: `employee_id`, `engagement_id`, `doc_type`, `file_key` (the MinIO key from `kernel.files`, no foreign key), `verification_status`, `verified_by`, `verified_at`. No file bytes here.
- `validation_issue`: `entity_type`, `entity_id`, `code`, `severity` (info, warning, review, blocking), `field`, `message`, `next_action`, `owner_role`, `resolved_by`, `resolved_at`.

**CIVP**
- `civp_placement`: `engagement_id`, `aneti_reference`, `approval_status`, `participant_category`, `starts_on`, `ends_on`, `training_hours_limit`, `status`.
- `civp_ledger_entry`: `placement_id`, `month`, `payer` (`aneti` or `employer`), `due_amount`, `paid_amount`, `status`, `payment_ref`. **The two payers are separate rows, never summed into one.**
- `civp_training`: `placement_id`, `date`, `hours`, `topic`, `recorded_by`.
- `civp_extension_request`: `placement_id`, `requested_end`, `status`, `approved_by`. A date change needs approval.

**Rules**
- `rule_set`: `kind` (tax, contributions, civp), `jurisdiction`, `version`, `status` (draft, tested, approved, active, superseded), `valid_from`, `valid_to`, `source_ref`, `approved_by`, `definition` (JSONB: brackets, rates, caps, rounding), `definition_hash`, `is_demo`.

**Payroll**
- `payroll_input_batch`: `source` (time, leave, compensation, manual import), `period`, `status`, `received_event_id`.
- `payroll_input`: `batch_id`, `employee_id`, `kind` (hours, absence, bonus, allowance, reimbursement), `quantity`, `amount`, `effective_date`, `source_event_id` (**unique**, so a duplicated `time.approved` cannot double-count).
- `payroll_run`: `external_request_id`, `period_start`, `period_end`, `pay_date`, `regime_id`, `status`, `rule_set_refs` (JSONB), `input_batch_refs`, `calculated_at`, `inputs_hash`, `results_hash`, `decision_record_id`.
- `payslip`: `run_id`, `employee_id`, `engagement_id`, `gross`, `employee_deductions`, `income_tax`, `net_pay`, `employer_cost`, `status`, `decision_record_id`.
- `payslip_line`: `payslip_id`, `code`, `label`, `base`, `rate`, `amount`, `rule_ref`, `kind` (earning, deduction, tax, employer_cost, adjustment). **Every line names the rule that produced it.**
- `adjustment`: a correction created in a later run for a change effective in a closed period. A closed run is never rewritten.

**Payment and reconciliation**
- `payment_line`: `run_id`, `payslip_id`, `amount`, `status` (due, submitted, paid, part_paid, failed, reversed), `bank_ref_token` (an opaque reference, never an account number), `idempotency_key`.
- `payment_status_event`: append-only history of provider responses, for reconciliation.

**Cost intelligence (later phases)**
- `budget`, `budget_line`, `cost_snapshot`, `scenario`, `forecast_run`, `forecast_point`, plus `attrition_assumption`.

**AI**
- `ai_suggestion`: `task`, `document_ref`, `field`, `value`, `confidence`, `evidence`, `status` (unconfirmed, confirmed, rejected), `confirmed_by`, `confirmed_at`. A suggestion changes nothing until a human confirms it, and the confirming actor and source are stored.

## 5. State machines

Status and outcome are separate. Each transition names who may cause it.

| Object | Flow | Who moves it |
|---|---|---|
| Engagement | `draft` → `pending_review` → `approved` → `active` → `completed` or `terminated` | Validation moves to review or approved. **Activation is an R2 action.** AI cannot move any state |
| CIVP placement | `draft` → `aneti_pending` → `approved` → `active` → `extension_review` or `completed` | ANETI status arrives as an event or a human entry. Activation needs eligibility documents verified plus a human decision. An extension needs approval before any date change |
| Payroll run | `draft` → `calculated` → `approval_pending` → `approved` → `payment_pending` → `paid` → `closed` | Calculation is a job. Submit is R1. **Approve is R3.** Payment status moves it forward. A payment service can never mark a run approved |
| Payment line | `due` → `submitted` → `paid` or `part_paid` or `failed` or `reversed` | Release is an **R3 external action**. Status comes back from the provider and is reconciled |
| Rule set | `draft` → `tested` → `approved` → `active` → `superseded` | **Activation is R3.** A rule set needs its tests green before `tested` |

Blocking validation issues stop a transition. Warnings and review items need a named human to resolve them, with a reason, before approval.

## 6. Actions and risk classes

All declared in `packages/packs/finance/manifest.yaml`. An undeclared action cannot run.

| Action id | Risk | Channel | Approvers | Notes |
|---|---|---|---|---|
| `finance.engagement.validate` | R0 | | | Deterministic validation, logged |
| `finance.engagement.draft` | R1 | | | Draft from an event |
| `finance.engagement.activate` | R2 | internal | hr, finance, admin | CDD and CIVP exceptions force a review item first |
| `finance.engagement.amend` | R2 | internal | hr, finance, admin | Effective-dated, never overwrites |
| `finance.civp.activate` | R2 | internal | hr, admin | Needs verified eligibility documents |
| `finance.civp.extension.approve` | R2 | internal | hr, admin | |
| `finance.civp.complete` | R2 | internal | hr, admin | Closes the placement, may open a separate CDI draft |
| `finance.payroll.calculate` | R1 | | | Deterministic draft, stores inputs and rule versions |
| `finance.payroll.approve` | **R3** | internal | finance (EMP-007 in the demo) | Step-up, no self-approval, blocking issues must be cleared |
| `finance.payment.release` | **R3** | **external** | finance, admin | Runs only in `executor`, payload hash bound |
| `finance.rules.activate` | **R3** | internal | admin, finance | Rule changes are never silent |
| `finance.document.confirm_extraction` | R2 | internal | hr | Confirms an AI-suggested field |
| `finance.forecast.publish` | R1 | | | Later phase |

Every R2 and R3 proposal carries a `DecisionRecord` (the kernel refuses it otherwise).

## 7. Events

Naming follows the repo convention `<pack>.<entity>.<verb>.v1`, with versioned models in `packs/finance/events.py`. The spec's names map as shown. Payloads carry IDs, status and totals the consumer needs, never raw salary lines.

**Published**

| Spec name | AstraRH event |
|---|---|
| `engagement.validation.completed` / `.failed` | `finance.engagement.validated.v1` (carries pass or fail and issue count) |
| `engagement.activated` / `.amended` / `.ending_soon` | `finance.engagement.activated.v1`, `.amended.v1`, `.ending_soon.v1` |
| `civp.approval.pending` / `.activated` | `finance.civp.approval_pending.v1`, `finance.civp.activated.v1` |
| `civp.payment.due` / `.reconciled` | `finance.civp.payment_due.v1`, `finance.civp.payment_reconciled.v1` |
| `civp.training.recorded` / `civp.extension.review_required` / `civp.completed` | `finance.civp.training_recorded.v1`, `.extension_review_required.v1`, `.completed.v1` |
| `payroll.inputs.validation_failed` | `finance.payroll.inputs_failed.v1` |
| `payroll.run.calculated` / `.approval_required` / `.approved` / `.rejected` / `.closed` | `finance.payroll.calculated.v1`, `.approval_required.v1`, `.approved.v1`, `.rejected.v1`, `.closed.v1` |
| `payroll.payment.reconciliation_updated` | `finance.payment.reconciled.v1` |
| (original brief) forecast | `finance.forecast.published.v1` |

**Consumed**

| Spec name | AstraRH source | Status |
|---|---|---|
| `engagement.approved` | `talent.candidate.hired.v1` (**C1**) | Needs contract change |
| `employee.created` / `.updated` | core people events | Confirm they exist in the catalogue |
| `document.verification.updated` | none yet. Fed by our own `document_ref` UI and the AI-confirm action | Internal until a documents module exists |
| `time.approved`, `leave.approved` | `workforce.leave.approved.v1`, time via import | Workforce pack not built, so use an **import adapter** that writes `payroll_input` with the same unique `source_event_id` |
| `compensation.change.approved` | own `finance.engagement.amended.v1` | Internal |
| `payroll.rules.approved` | own `finance.rules.activate` | Internal |
| `payment.status.updated` | sandbox bank via the executor adapter | See C2 |
| `civp.aneti_status.updated` | manual entry or a sandbox ANETI feed | We never pretend to contact ANETI. A human task records the result |
| `journey.skill_gap.confirmed.v1`, `journey.training.completed.v1` | `journey` pack | Training budget and ROI, later phase |

**Idempotency and replay:** consumers key every write on `source_event_id` plus a unique constraint, so duplicate delivery changes nothing and replay is safe. Out-of-order delivery is handled where cheap (for example a status event arriving before its entity is parked and retried).

## 8. Payroll calculation design

- **Pure function module** `packs/finance/payroll/calc.py`: input is the engagement terms, approved inputs and the rule set definitions, output is lines and totals. It imports no database table and no model client (a test enforces this, like `scoring.py` in talent).
- **Order of evaluation** is data in the rule set: earnings, then contribution bases, employee contributions, taxable base, income tax by bracket, net, then employer cost lines. Each step records base, rate, amount and the rule id.
- **Rule sets are data, not code.** Versioned, effective-dated, with `definition_hash`. A run stores `rule_set_refs` and `inputs_hash`, so "Recalculate" reproduces the original exactly.
- **Closed runs are immutable.** A change effective in a prior period produces an `adjustment` line in the next open run, visible on the payslip.
- **CIVP is not a normal payroll line.** ANETI allowance and employer complement stay in the CIVP ledger as separate payers. The payslip shows only what the rules say applies, and the treatment is a configurable, reviewed rule, never a hard-coded assumption.
- **Anomaly detection is deterministic first**: compare against the previous runs (large net change, missing input, duplicate pay item, negative net). The AI may then explain a flag in plain language from numbers already computed, validated by the narrative checker.

### 8.1 Net pay calculator (type a gross salary, get net automatically)

A screen and an API call that take a gross monthly salary plus a few facts and return every line down to net pay and employer cost. It calls the same `calc.py` the payroll run uses, so a preview can never disagree with a payslip. No AI is involved.

**Inputs:** gross monthly salary, marital status or head of family, number of dependent children (and which are students or disabled), payroll regime, month. Optional: allowances, bonuses, advances.
**Output:** each line with base, rate, amount and the rule id, then net pay, then employer cost. A "Why" view shows the arithmetic, and every result names its rule-set version.
**Reverse mode** (later): "I want X net, what gross?" solved numerically with the same function, rounded and verified by running the forward calculation.

**Calculation order** (from the sources below, all values live in the rule set):

1. Employee CNSS = rate × gross.
2. Monthly taxable salary = gross − employee CNSS.
3. Annualise (× 12).
4. Professional expenses = 10% of the annual taxable salary, capped at 2,000 TND a year.
5. Family deductions: head of family, per child, student child, disabled child.
6. Annual net taxable income = step 3 − step 4 − step 5.
7. IRPP by progressive bracket on step 6, then ÷ 12 for the monthly amount.
8. CSS on the same base, then ÷ 12, exempt when annual net income is within the 0% bracket.
9. **Net pay = monthly taxable salary − monthly IRPP − monthly CSS** (− advances).
10. Employer cost = gross + employer CNSS + other employer charges.

**Rule values found in research on 2026-10-31. Status: demo values from secondary sources. None is verified against the official text yet.**

| Rule | Value found | Confidence and notes |
|---|---|---|
| CNSS, employee | **9.68%** of gross | Consistent: base 9.18% plus 0.50% from the 2025 Finance Law (Law 48-2024, Art. 17, per [PKF](https://pkf.tn/documents/Loi%20de%20finances%202025.pdf)). Some guides still show 9.18%, which looks out of date |
| CNSS, employer | **17.07%** of gross | Base 16.57% plus 0.50%. Some guides still show 16.57% |
| CNSS ceiling | Unclear | One guide says employee base capped at 5,000 TND a month. Most give no cap. **Do not assume a cap until checked with CNSS** |
| Professional expenses | 10%, max 2,000 TND a year | Sources agree. One says 10% of annual gross, others of taxable salary. We follow the version that deducts CNSS first |
| Head of family | 300 TND a year | Consistent |
| Child | 100 TND each, first 4 | Consistent. Under 20 on 1 January |
| Student child | 1,000 TND (replaces the 100) | Under 25, no grant |
| Disabled child | 1,200 TND in one source | Another source gives no amount. **Verify** |
| Dependent parents | Exists, amount not found | Leave out of v1, mark as unsupported |
| IRPP scale (annual) | 0% to 5,000; 15% to 10,000; 25% to 20,000; 30% to 30,000; 33% to 40,000; 36% to 50,000; 38% to 70,000; 40% above | Same 8 brackets in all sources. One RemotePass page claims a 7-bracket 2026 scale and looks wrong. **Verify against the Finance Law 2026 text** |
| CSS | **0.5%** for 2026 (standard 1%) | Described as temporary. Base is annual net taxable income. Exempt if that is within the 0% bracket |
| FOPROLOS (employer) | 1% of gross payroll | One source only |
| TFP, training tax (employer) | 1% or 2% by sector | One source only |
| Work accident (employer) | 0.4% to 4% by sector | Two sources. Needs the employer's sector rate |

**Hand-checked example, which becomes the first test.** Gross 2,000.000, head of family, two children, 2026 rates (checked by hand against the figures above):

| Step | TND |
|---|---:|
| Employee CNSS (9.68%) | 193.600 |
| Monthly taxable salary | 1,806.400 |
| Annual taxable salary | 21,676.800 |
| Professional expenses (10% = 2,167.680, capped) | 2,000.000 |
| Family deductions (300 + 2 × 100) | 500.000 |
| Annual net taxable income | 19,176.800 |
| Annual IRPP (0 on 5,000; 15% × 5,000 = 750.000; 25% × 9,176.800 = 2,294.200) | 3,044.200 |
| Monthly IRPP | 253.683 |
| Monthly CSS (0.5% × 19,176.800 ÷ 12) | 7.990 |
| **Net pay** | **1,544.727** |
| Employer CNSS (17.07%) | 341.400 |
| Employer cost, before TFP, FOPROLOS and work-accident | 2,341.400 |

This matches the worked example in the [Swifto guide](https://www.swifto.io/en/blog/paie-tunisie-cnss-irpp-css.html). **Do not use the SmartPaie worked examples as test data: its own figures are inconsistent with its stated brackets.**

**Rounding.** Round to the millime (3 decimals) once per displayed line with half-up rounding, and keep unrounded values internally until then. The rule set records the rule, so code and hand-checked tests agree.

**Not covered in v1, and said on screen:** overtime, benefits in kind, taxable bonus treatment, dependent parents, special sector schemes, and withholdings other than the ones above.

**CIVP values found (also demo until verified):**
- ANETI monthly allowance: **200 TND** for higher-education graduates and BTS holders, **150 TND** for other levels, plus **50 TND** more for a person with a disability.
- Minimum employer complement: **200 TND** and **150 TND** for the same categories.
- Duration: **12 months** for new ordinary files. The old "up to 24 months" no longer applies since **1 October 2025**, and extension remains only for disabled holders of a higher-education diploma or BTS. So an extension request must be refused unless that condition is met.
- Social treatment: the monthly allowance is **not subject to social contributions or IRPP** (one source). The beneficiary is covered by the student social scheme, and CNSS covers work accidents. **Who funds the student scheme is not stated. Verify.**
- Eligibility: Tunisian first-time job seekers for graduates. The company must have kept at least half of the people who finished a CIVP in the last three years (Decree 2023-461).
- Not found: training-hours limit and the CDI hiring incentive (one source says the State may cover the employer contribution for two years, with limits). Leave both as configurable fields, empty by default. **The example payload's 400-hour limit is a placeholder from the spec.**

**Verification step before anything is called ready.** Check the CNSS rates and ceiling on cnss.tn, the IRPP scale, deductions and CSS in the Finance Law 2026 text (DGI), and the CIVP amounts, duration and training rules with ANETI or its [employer page](https://idaraty.tn/fr/procedures/contrat-d-initiation-a-la-vie-professionnelle-civp-entreprises). Record the source, article and date in each rule set's `source_ref`, and only then drop the "demo" flag.

**Sources used (all secondary except where noted):**
- [Swifto: Tunisia payroll calculator 2026](https://www.swifto.io/en/blog/paie-tunisie-cnss-irpp-css.html), cites Act 2024-48, Act 2025-17 and Decree 2026-67
- [SmartPaie: Paie en Tunisie 2026](https://smartpaie.tn/guides/paie-tunisie-2026) and [Taux CNSS 2026](https://smartpaie.tn/guides/taux-cnss-tunisie-2026)
- [La Presse: salary simulator article](https://www.lapresse.tn/2026/02/04/ce-simulateur-en-ligne-permet-de-calculer-votre-salaire-net-en-tunisie/)
- [PKF: Loi de finances 2025 (PDF)](https://pkf.tn/documents/Loi%20de%20finances%202025.pdf), [K-Noon](https://www.k-noon.tn/blog/fiscalite/nouvelles-mesures-fiscales-et-sociales-en-2025/) and [Kapitalis](https://kapitalis.com/tunisie/2025/02/28/tunisie-en-attendant-la-mise-en-place-du-regime-dassurance-perte-demploi/) on the CNSS increase
- [SmartPaie: CIVP guide](https://smartpaie.tn/guides/contrat-civp-sivp-tunisie-2025-2026), [Managers.tn: CIVP](https://managers.tn/2026/08/03/civp-en-tunisie-ce-quil-faut-savoir-avant-de-signer-un-contrat/), [ANETI](https://www.emploi.nat.tn/fo/Fr/global.php?menu1=75&libre=1132)

## 9. Payment and reconciliation design

1. Approved run produces `payment_line` rows with a deterministic `idempotency_key` per line.
2. `finance.payment.release` (R3, external) is proposed with the totals and a payment-file reference, shown to the approver.
3. After approval, the **executor** calls the payment adapter. It returns a reference. The adapter exposes `find(key)` so a timeout is reconciled, never retried blindly (the same pattern as the mail adapter).
4. Status events (paid, failed, part_paid, reversed) are appended to `payment_status_event` and matched to the line by reference and amount.
5. Unmatched or failed payments create a finance task and an exception, never a silent drop.
6. **Demo provider:** a sandbox bank that accepts a payment file and returns configurable outcomes (including one failure), with destinations allowlisted. State clearly that real bank integration is a production step.

## 10. AI usage (advisory only)

| Task | Output | Guard |
|---|---|---|
| Extract contract fields from a document | `ai_suggestion` rows with value, confidence, page and quote evidence | Goes through the quarantined reader (no tools, quote must exist in the file). Stays `unconfirmed` until a named HR user confirms |
| Explain a validation or anomaly flag | Plain-language text | Numbers validated against the record, wrong numbers rejected |
| Summarise a policy or rule change | Summary with citations | Read only |

It must never calculate tax, decide CIVP eligibility or contract legality, approve payroll, move a state, or trigger a payment. Injected text in a contract PDF is treated like an injected CV: sanitised, no tools, validated.

## 11. API surface

Mounted under `/api/packs/finance/...` (the repo's convention, not the spec's `/v1`). Semantics match the spec so a later gateway can map them.

- **Engagements:** `POST /employees/{employee_id}/engagements`, `GET /engagements/{id}`, `PATCH /engagements/{id}` (creates an amendment), `POST .../validate`, `POST .../activate` (creates a proposal), `POST .../close`.
- **CIVP:** `POST /engagements/{id}/civp`, `GET`, `POST .../payments`, `.../training`, `.../extension-requests`, `.../complete`.
- **Payroll:** `POST /payroll-runs`, `GET /payroll-runs/{id}`, `POST .../calculate`, `.../submit-for-approval`, `.../approve` and `.../reject` (through the kernel trust endpoints), `.../close`, `GET .../results`, `POST .../payslips/{id}/verify`.
- **Payments:** `GET /payroll-runs/{id}/payments`, reconciliation view, manual resolution of a failure.
- **Rules:** list, view, draft, test, propose activation.
- **Inputs:** import a batch (CSV or event), view validation failures.
- **Self-service:** `GET /me/payslips` scoped to the signed-in employee.

All state-changing calls follow the existing CSRF and session rules, and errors use the standard `{error, message}` shape. Validation responses return the spec's field-level issue format (code, severity, field, message, next action, owner role).

## 12. Security and access

- **Roles:** `finance` and `admin` see payroll and rules, `hr` sees engagements and documents but only totals of pay, `manager` sees nothing salary-level, `employee` sees only their own payslip through an employee-scoped grant, `auditor` reads audit and rule versions. Two-key check on every approval.
- **Sensitive data:** bank references are opaque tokens. Identity documents are file references. Encryption at rest for those columns (decide: pgcrypto column encryption or rely on volume encryption, and state it).
- **Audit:** every calculation, approval, export and rule change lands in the hash-chained audit with rule versions and trace id. Payroll data reads are audited too (the spec asks for access auditing), via `log_action` for sensitive reads.
- **Fail closed:** missing rule set, missing approval, hash mismatch or blocked validation means deny.
- **Tests that must exist:** RLS blocks cross-tenant reads, an unauthorised role gets 403 and an audit `denied` entry, an edited payload voids an approval, duplicate release calls the provider once, a payment adapter timeout reconciles instead of re-sending.

## 13. UI (`apps/web/src/modules/finance`)

Uses the shared kit in `apps/web/src/ui` and `<WhyPanel>`. Every screen handles empty, loading and error states.

1. **Payroll runs**: list, a run page with totals, exceptions, a payslip table, **Why** on each payslip (lines, rules, Recalculate), approve with step-up, and the demo-values banner.
2. **Engagements**: list and detail with validation issues grouped by severity, activate and amend.
3. **CIVP**: placement page with the two payer ledgers side by side, training hours against the limit, extension and completion.
4. **Payments**: status per line, reconciliation, failures.
5. **Documents and AI suggestions**: checklist, "AI suggested, confirm?" with the quote shown.
6. **Rules**: versions, status, activate (R3).
7. **My payslips**: employee view.
8. **Cost dashboard and forecast** (later): actual against budget by org unit, scenario "hire 5 / lose 3" with the drivers that changed.

## 14. Seed data (shared Carthage Demo Systems world)

Uses the IDs in `docs/handoff/DEMO_WORLD.md` (EMP-001 to EMP-040, `ORG-*`, `POS-*`). All fictional. Files under `data/demo/finance/`:

- `compensation.csv`, `rule_set.json` (marked demo), `budget.csv` (Engineering slightly over), `payroll_history.csv` (6 months, **one planted anomaly**), `attrition_assumptions.json`.
- `engagements.json`: mostly CDI, one CDD with an unclear reason code, two CIVP placements.
- `civp.json`: ANETI reference, categories, dates, monthly amounts as configured values, training plan.
- `documents.json`: verified and missing ones to trigger blocking issues.
- `inputs/`: time and leave batches including one **duplicate event** and one retroactive salary change.
- `worked_examples.md`: 3 payslips, 1 CIVP month and 1 forecast **calculated by hand**. These become the tests.
- `scenarios.md`: the ten acceptance scenarios as given, when, then.

## 15. Acceptance scenarios (from the spec) and where they are verified

| # | Scenario | Verified by |
|---|---|---|
| 1 | CDI hire becomes an active payroll engagement | End-to-end test from the hired event to `active`, plus browser run |
| 2 | CDD with unclear info goes to review and cannot proceed silently | Test that activation is refused while a `review` issue is open |
| 3 | CIVP keeps ANETI and employer amounts separate and reconciles a month | Ledger test with two payer rows and one reconciled payment |
| 4 | CIVP training hours recorded and in the summary | Test plus summary view, limit warning |
| 5 | Payroll uses approved inputs, reproducible, needs human approval | Replay test (digit for digit), approval-required test |
| 6 | Prior-period salary change produces a visible adjustment | Test that the closed run is unchanged and the next run has an adjustment line |
| 7 | CIVP completion then CDI hire closes the placement and opens a separate engagement | Test of the completion event chain |
| 8 | Duplicate or delayed event creates no duplicate pay items or payments | Replay the same event twice, assert counts |
| 9 | AI-extracted date stays unverified until HR confirms | Test that the engagement uses only confirmed values |
| 10 | Unauthorised user cannot reach salary, bank or identity data | Role matrix test plus RLS test |

Plus the invariants: no float in the pack, `calc.py` imports no database or model client, every R2 and R3 proposal has a `DecisionRecord`, and a wrong-number narration is rejected.

## 16. Build order

Each phase ends with tests passing and a short report. Later phases are cut first if time runs out.

| Phase | Build | Done when |
|---|---|---|
| **F0 Contracts** | Raise C1 to C6 with the kernel owner. Write the event models and manifest skeleton. Confirm role and grant shapes | Decisions recorded, no open blockers |
| **F1 Foundations** | Pack skeleton, tables, migrations with RLS, seed loader, rule-set model and loader, role matrix | `astra.py check` green, seed loads |
| **F2 Engagements and validation** | Engagement and amendment, validation engine with severities, document refs, hire event consumer, activate as R2 | Scenarios 1, 2, 9 (non-AI part) |
| **F3 Payroll core** | Rule engine, `calc.py`, inputs import with idempotency, run lifecycle, payslips with lines, scorer registration, replay, adjustments | Scenarios 5, 6, 8 for inputs; hand-checked examples pass |
| **F4 Review and approval** | Anomaly checks, approval card, R3 approve with step-up, Why panel, narration validator | Approval cannot pass with blocking issues, edit voids approval |
| **F5 Payment** | Sandbox bank adapter (C2), release as R3 external, reconciliation, failure handling | Duplicate release calls the provider once, timeout reconciles |
| **F6 CIVP** | Placement, two-payer ledger, training, extension, completion, transition to CDI | Scenarios 3, 4, 7 |
| **F7 AI assist** | Contract extraction with evidence, explanation of flags, confirm flow | Scenario 9 end to end, injection test on a contract |
| **F8 UI and proof** | Screens above, self-service, cost dashboard, forecast, scenarios, attrition, training ROI, security drills, README section and demo beat | Scenarios 1 to 10 pass, one browser run, demo beat rehearsed |

**Demo beat for finance (about 60 seconds):** the hire event arrives, an engagement is validated and activated, a payroll run is calculated from approved inputs, the planted anomaly is flagged and explained, the approver confirms with step-up, one payment fails and is reconciled, Why shows a payslip line down to its rule, and a CIVP month shows two separate payers.

## 17. Risks and open questions

**Risks**
- **Legal accuracy.** Tunisian contribution rates, income tax brackets, CIVP amounts and limits change. We ship them as reviewed demo data with a source reference field, and say so. No claim of compliance.
- **Upstream not ready.** `talent` does not emit a hire event, and `workforce` does not exist. Mitigation: fallback consumers and an import path (C1, inputs adapter).
- **Scope.** This is the full spec plus the original finance brief. If time runs short, cut in this order: training ROI, attrition, forecast scenarios, AI extraction, CIVP extension, then the cost dashboard. **Never cut** payroll calculation with replay, R3 approval, audit and payment reconciliation.
- **Currency precision.** Three decimals and rounding rules need to be fixed once in the rule set format, or hand-checked examples will disagree with code.
- **Machine.** The repo was built on Windows. Setup here on macOS has not been run, so the first task is `python astra.py init`, `up` and `smoke`.

**Questions for the owner**
1. Is the demo regime `TN_PRIVATE_NON_AGRI` only, or do you also need other regimes?
2. Which real references will you give for the demo rule values (CNSS, tax authority, ANETI), so the `source_ref` fields are honest?
3. Should salary-level payroll data be visible to `hr`, or only to `finance` and `admin`?
4. Is a sandbox bank acceptable for the demo, or do you have a provider in mind?
5. Who is the payroll approver in the demo (the doc says `EMP-007`, Sami Ferchichi), and who is the second person for any R3 that needs one?
6. Who will check the rule values against the official sources (section 8.1), and do you want to review them before they are loaded?
7. Do you want reverse mode (net to gross) in the first version of the calculator, or later?
8. Which sector does the demo company use, for the work-accident and training-tax rates?
9. Should payslip PDFs be generated (needs a renderer in `ml` or the executor), or is a web payslip enough?
