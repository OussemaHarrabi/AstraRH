# Finance pack: use cases

Companion to [FINANCE_PLAN.md](FINANCE_PLAN.md). The plan says what we build and how it plugs in. This file says **who does what, in which situations, and what must happen when things go wrong.** Each use case becomes acceptance tests.

Priority: **P1** demo-critical, build first. **P2** needed for a credible product. **P3** valuable, cut first if time runs out.
Risk is the action class from the plan (R0 read, R1 internal draft, R2 affects a person or leaves the system, R3 serious, step-up, no self-approval).
Anything that depends on a Tunisian legal value is marked **[verify]**: the value lives in a reviewed rule set, never in code.

## 1. Actors

| Actor | Who in the demo | Can do | Cannot do |
|---|---|---|---|
| Payroll preparer | `finance` role (a finance clerk) | Create runs, import inputs, calculate, submit for approval, resolve warnings | Approve their own run, release payment |
| Payroll approver | `EMP-007` Sami Ferchichi (`finance`) | Approve or reject a run, release payment, activate a rule set. Needs step-up | Approve a run they prepared or edited |
| HR business partner | `EMP-006` Leila Haddad (`hr`) | Validate and activate engagements, confirm documents and AI suggestions, approve CIVP steps | See salary-level payroll data (totals only), approve payroll |
| Recruiter | `EMP-008` Nadia Bouzid | Triggers the hire that starts the chain | Anything in finance |
| Employee | any employee | See their own payslips and CIVP summary | See anyone else's |
| Manager | team managers | Nothing salary-level. Approve leave elsewhere | Payroll data |
| Auditor | `auditor` | Read audit, rule versions, decision records, run history | Change anything |
| Admin | `admin` | Rule administration with finance, access setup | Bypass approvals |
| System | events, jobs | Create drafts, calculate, validate, reconcile, remind | Approve, release, activate, change a rule |
| AI assistant | model via the gateway | Suggest fields, explain flags | Write authoritative data, calculate money, decide legality |
| Payment provider | sandbox bank | Return paid, failed, part-paid, reversed | Mark a run approved |
| ANETI / CNSS | external, **not integrated** | Nothing. We record outcomes entered by a human | |

## 2. Use case catalogue

### A. Engagements and documents

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| A1 | P1 | **Hire becomes a draft engagement** | System | Hired event arrives with IDs only. Create employee link, draft CDI engagement, default document checklist, HR task | Duplicate event creates nothing. Unknown employee parks the event and retries. Missing salary terms gives a blocking issue | R1 |
| A2 | P1 | **Validate an engagement** | System | Check required fields, dates, hours, pay items, documents, engagement-type rules. Return issues with code, severity, field, next action, owner role | Same request twice returns the same result. Any `blocking` stops activation, any `review` needs a named human | R0 |
| A3 | P1 | **Activate a CDI engagement** | HR | HR reviews issues, activation proposal with a decision record, HR approves, engagement becomes `active`, event published | Open `blocking` or `review` issue refuses activation. Edited payload voids approval. Approver lacking the role gets 403 and an audit `denied` entry | R2 |
| A4 | P1 | **CDD with unclear reason goes to review** | System, HR | CDD with missing or unrecognised reason code gets a `review` issue to HR/legal. Cannot proceed until a named human resolves it with a written reason | Reason code must come from the locally validated list **[verify]**. AI is never asked whether it is legal. A CDD with no end date is blocking | R2 |
| A5 | P2 | **Amend an engagement** (salary raise, hours, title) | HR, finance | Create an effective-dated amendment. History stays. Next open run uses it | Change effective in a closed period creates an adjustment (see D7), never rewrites the past. Salary below the minimum wage gives a `review` issue **[verify SMIG]** | R2 |
| A6 | P2 | **Document checklist and verification** | HR | Checklist by engagement type. HR marks each document verified with actor and date. Verified set unlocks "ready for payroll review" | Missing document creates an HR task and a blocking issue. Document references only, never file copies. Unverified AI-extracted data does not count | R1 |
| A7 | later | **AI extracts contract fields (deferred, AI paused, decision D14; HR enters and confirms fields by hand meanwhile)** | AI, HR | Quarantined reader returns suggestions with value, confidence and the quoted source. HR confirms or rejects each | Suggestion stays `unconfirmed` and unused until confirmed. A quote not in the file is dropped. Injected text in the PDF is flagged and ignored | R2 on confirm |
| A8 | P2 | **End a fixed-term engagement** | System, HR | `ending_soon` event before the end date. HR decides: let it end, renew as a new engagement, convert to CDI | A renewal is a new engagement with its own validation, not a date edit. Limits on successive CDDs **[verify]** | R2 |
| A9 | P2 | **Terminate an engagement** | HR | Termination date, reason, final-pay flag. Engagement `terminated`, last payroll includes proration, future runs exclude it | Termination mid-month needs proration. Final settlement items are P3 (see H3) | R3 |
| A10 | P3 | **Promotion or position change** | HR | Amendment with new pay items effective on a date | Same rules as A5 | R2 |

### B. Payroll inputs

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| B1 | P1 | **Collect approved inputs for a period** | System, preparer | At cut-off, gather approved hours, absences, bonuses, allowances, reimbursements for the pay period into a batch | Each input is keyed by its source event id, so a duplicate `time.approved` cannot double-count. Missing approvals create flags, not guesses | R1 |
| B2 | P1 | **Import inputs without an upstream system** | Preparer | Upload a CSV batch (the `workforce` pack is not built). Rows validated, rejected rows listed with reasons, accepted rows stored with a stable source id | Re-uploading the same file changes nothing. Unknown employee or inactive engagement rejects the row. Amount outside plausible range gives a warning | R1 |
| B3 | P1 | **Detect conflicting or missing inputs** | System | Flag duplicate pay items, input for an employee with no active engagement, hours above a limit, approved leave overlapping hours | Each flag has code, severity, owner and next action. Blocking flags stop calculation of that employee only, others proceed | R0 |
| B4 | P2 | **Late input after cut-off** | Preparer | Input arrives after the run was calculated. Run goes back to `draft` if still open, otherwise becomes an adjustment in the next run | Closed or paid runs are never edited | R1 |
| B5 | P2 | **Unpaid leave and absences** | System | Approved unpaid absence reduces earnings by a rule-defined proration | The proration method is a rule **[verify]**. Paid leave does not reduce pay | R1 |
| B6 | P2 | **Overtime** | System | Approved overtime hours become earnings using configured premium rates, taxed and contributed like other earnings under the rule set | Premium rates, caps and any exemptions are data **[verify]**. Hours without an approval are never paid. Shown as its own payslip line | R1 |
| B7 | P2 | **Salary advance and its recovery** | Preparer, HR | An advance is approved (R2), paid, then recovered by a fixed deduction over agreed months in later runs | Never makes net negative: the recovery is capped and the balance carries over. Recovery limits **[verify]**. Remaining balance visible to the employee and finance. Ending the engagement flags the open balance for final settlement | R2 |

### C. Net pay calculator

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| C1 | P1 | **Gross to net, instantly** | Any finance or HR user | Enter gross, family status, children, month. Get each line with rate, amount and rule id, then net and employer cost | Uses the rule set active for that month. Shows the "demo values, not certified" banner. Same function as the payroll run | R0 |
| C2 | P1 | **Why this line?** | Any viewer | Click a line to see base, rate, rule, source reference, rule-set version | Hand-checked example must reproduce exactly | R0 |
| C3 | P2 | **Compare scenarios** | HR, finance | Side-by-side: with or without a child, raise of X, different regime | Pure calculation, nothing saved unless the user saves it as a scenario | R0 |
| C4 | P3 | **Net to gross (reverse)** | HR, finance | "I want 2,000 net, what gross?" solved numerically, verified by running the forward calculation | If no gross gives exactly that net due to rounding, return the closest and say so | R0 |
| C5 | P2 | **Offer-stage salary estimate** | Recruiter, HR | Employer cost and net for a proposed salary on a job | Only aggregates shown to the recruiter, never stored against a candidate identity | R0 |

### D. Payroll run

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| D1 | P1 | **Create a run** | Preparer | Period, pay date, regime, input batches. Idempotent on `external_request_id` | Overlapping period for the same employer is refused. Needs an active rule set for the period | R1 |
| D2 | P1 | **Calculate a draft** | System (job) | Deterministic per employee: earnings, contributions, tax, net, employer cost. Store inputs hash, rule versions, results hash, a decision record per payslip | Same inputs give identical output. One employee's error does not abort the run, it becomes an exception. Rounding per line, once | R1 |
| D3 | P1 | **Review exceptions** | Preparer | See blocking, review and warning items, resolve each with a reason or fix the source data and recalculate | Blocking items must be fixed, not just acknowledged. Resolutions are audited | R1 |
| D4 | P1 | **Anomaly check and explanation** | System (AI explanation deferred, decision D14) | Rule-based comparison with previous runs (net change over threshold, missing pay item, duplicate, negative net). Each flag carries a templated plain-words reason built from the computed numbers. A later AI agent may rephrase it | Narration with a number not in the record is rejected. AI never changes a figure | R0 |
| D5 | P1 | **Submit and approve (R3)** | Preparer, approver | Preparer submits. Approver sees totals, exceptions, anomalies, Why. Approves with step-up | Preparer cannot approve. Blocking issue present refuses. Editing after submit voids approval. Policy version re-checked at approval | R3 |
| D6 | P1 | **Reject a run** | Approver | Reject with reason, run returns to `draft` | Reason mandatory, audited | R2 |
| D7 | P1 | **Retroactive change creates an adjustment** | System | A change effective in a closed period produces adjustment lines in the next open run, shown separately on the payslip | The closed run's hash does not change. Adjustment cites the amendment and the original run | R1 |
| D8 | P1 | **Replay a payslip** | Auditor, finance | Recalculate from stored inputs and rule versions, compare digit by digit | Mismatch is a loud failure and an audit event | R0 |
| D9 | P2 | **Close a run** | Approver | After payment reconciliation, close. Closed runs are immutable | Cannot close with unreconciled lines unless each is explicitly resolved | R2 |
| D10 | P2 | **Off-cycle run** (single employee, correction) | Preparer | Same pipeline for one employee and reason | Cannot overlap an existing normal run's employee/period without it being an adjustment | R3 |
| D11 | P2 | **Compare to previous run** | Approver | Variance by org unit, new joiners, leavers, changes | Aggregates by default, individual lines on click, with access audited | R0 |
| D12 | P3 | **Mid-month joiner or leaver proration** | System | Proration by calendar or working days per rule **[verify]** | Method is a rule setting, shown on the payslip | R1 |

### E. Payment and reconciliation

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| E1 | P1 | **Prepare payment lines** | System | Approved run creates one payment line per payslip with a deterministic idempotency key | Created once. Zero or negative net creates no line and an exception | R1 |
| E2 | P1 | **Release payment** | Approver | Release proposal shows total, count, file reference. Approver confirms with step-up. Executor calls the sandbox bank | Executor re-checks approval, hash and destination allowlist. Duplicate release calls the provider once | R3 |
| E3 | P1 | **Provider timeout** | System | Execution marked unknown. Reconciler asks the provider by key and records the true state | Never retried blindly. Never reported as paid without confirmation | R1 |
| E4 | P1 | **Reconcile statuses** | System | Provider returns paid, failed, part-paid, reversed per reference. Match by reference and amount, update lines, update run state | Unmatched reference or amount mismatch goes to a finance exception queue | R1 |
| E5 | P1 | **Handle a failed payment** | Finance | See failed line with reason, choose retry (a new R3 release for just those lines) or manual resolution | Retry gets a new idempotency key. Original failure stays in history | R3 |
| E6 | P2 | **Part-paid line** | Finance | Remaining amount stays due and visible | Total paid never exceeds approved net | R1 |
| E7 | P2 | **Reversal** | Finance | Reversal recorded, line returns to due, finance task created | Run cannot be `closed` while a reversal is open | R1 |
| E8 | P2 | **Accounting and filing exports** | Finance | Generate a payroll journal export and a contribution summary file from an approved run | **We export and create a human task, we never claim to have filed with CNSS or tax authorities.** Export is audited | R2 |
| E9 | P3 | **Payment file format** | Finance | Bank file in a configurable format | Format is an adapter detail, the sandbox accepts a simple one | R2 |

### F. CIVP

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| F1 | P1 | **Create a CIVP placement** | HR | Participant, category, ANETI reference, dates, configured allowance and complement, eligibility documents | Category decides the default amounts from the rule set **[verify]**. Dates must fit the allowed duration **[verify]** | R1 |
| F2 | P1 | **Eligibility and document review** | HR | Verify diploma and ANETI documents. Eligibility is a human decision recorded with the evidence | AI may extract fields but never decides eligibility. Incomplete creates HR task or ANETI follow-up | R2 |
| F3 | P1 | **Activate a placement** | HR | After ANETI approval entered by a human and documents verified, activate | Cannot activate with `aneti_pending`. No pretending we contacted ANETI | R2 |
| F4 | P1 | **Monthly ledger, two payers** | System | Each month create a due entry for ANETI allowance and a separate one for the employer complement | The two are never summed or merged. Each reconciles on its own | R1 |
| F5 | P1 | **Reconcile a CIVP month** | Finance | Record the ANETI payment and the employer payment separately, matched to ledger rows | Under or over payment is flagged. Partial payment keeps the rest due | R1 |
| F6 | P1 | **Record training** | HR, participant | Training date, hours, topic added to the placement | Hours above the configured limit give a `review` warning. Limit empty means no check, stated on screen **[verify]** | R1 |
| F7 | P2 | **Placement summary** | HR, finance | Dates, amounts by payer, paid and due, training hours, status, issues | Employee sees only their own | R0 |
| F8 | P2 | **Extension request** | HR | Request with reason. Refused automatically unless the allowed condition is met **[verify: disabled holder of a higher-education diploma or BTS since 1 Oct 2025]**, then approval needed before any date changes | A refused request creates no date change | R2 |
| F9 | P1 | **Complete a placement** | HR | Completion closes the placement and the final ledger, produces the summary | Open ledger rows must be resolved first | R2 |
| F10 | P1 | **CIVP then CDI** | HR | After completion, hire on CDI opens a **separate** CDI engagement linked to the placement, with its own validation and payroll | The CIVP engagement stays closed and its history is untouched. The employer hiring incentive, if any, is a configured item, not assumed **[verify]** | R2 |
| F11 | P2 | **Early end of a placement** | HR | Record end date and reason, final ledger prorated | Proration method is a rule **[verify]** | R2 |
| F12 | P2 | **Employer eligibility to host** | HR | Check the company's retention condition before creating a placement | Computed from our own records where available, otherwise a human attestation recorded **[verify]** | R0 |
| F13 | P2 | **CDI hiring incentive after a CIVP** | HR, finance | After F10, HR records whether the incentive applies (one source says the State may cover the employer social contribution for two years, with limits). If confirmed, the separate CDI engagement carries an `incentive` record with start, end and the covered contribution, and payroll shows the employer-cost reduction as its own visible line | Eligibility is a human decision with evidence, never assumed or inferred by AI. Conditions, duration and caps are rule-set data **[verify with ANETI and CNSS]**. The incentive stops on its end date or if the engagement ends. It affects employer cost only, never the employee's net. Without a confirmed record, no reduction is applied | R2 |

### G. Rules administration

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| G1 | P1 | **Load demo rule set** | Admin, finance | Seed CNSS, deductions, IRPP brackets, CSS, CIVP amounts as data with `is_demo` and `source_ref` | Cannot be active without a version, validity period and hash | R1 |
| G2 | P1 | **Test a rule set** | Finance | Run the rule set's own hand-checked examples. Nothing is stored (decision D15) | A failing example blocks activation, at the request and again when it takes effect | R1 |
| G3 | P1 | **Activate a rule set (R3)** | Approver | Activation proposal with the diff against the active one and the test results. Approver confirms with step-up | New set must not overlap an active period. Old set becomes `superseded`, never deleted. Past runs still replay with the old set | R3 |
| G4 | P2 | **Rule change notice** | System | When a rule set is activated, finance gets a task to review its next run and the impact preview | Preview is a calculation, not an AI guess | R0 |
| G5 | P2 | **Impact preview** | Finance | Recalculate last run's inputs with a draft rule set, show totals and per-employee differences | Nothing is saved | R0 |
| G6 | P2 | **Employer configuration** | Admin | Legal entity, sector, regime, identifiers, sector rates for accident and training tax | Sector missing blocks calculation of employer cost, not net | R2 |
| G7 | P3 | **Mark rules verified** | Finance, auditor | Record who checked which source on which date and drop the demo flag | A rule set with `is_demo` shows the banner everywhere it is used | R2 |

### H. Employee and manager views

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| H1 | P1 | **My payslips** | Employee | See own payslips with line breakdown and Why | Scoped grant. Another employee's id returns 404, not 403, and is audited | R0 |
| H2 | P2 | **Payslip released only after approval** | System | Employee is notified only when the run is approved or paid, per policy | Draft payslips are never visible to the employee | R1 |
| H3 | P3 | **Final settlement** (leave payout, notice, prorated items) | HR, finance | Computed with rules at termination **[verify]** | Out of v1, listed so it is not forgotten | R3 |
| H4 | P2 | **Question about my payslip** | Employee | Ask, a ticket is created for finance, the knowledge assistant may answer from policy documents only | No salary data is sent to the model for a policy question | R1 |
| H5 | P3 | **Certificates** (salary or employment attestation) | HR | Generate from verified data after approval | R2 |

### I. Cost intelligence (after payroll is solid)

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| I1 | P2 | **People-cost dashboard** | Finance, CEO | Actual versus budget by org unit and month | Aggregates only for non-finance roles. Salaries never in Neo4j | R0 |
| I2 | P2 | **Hire cascade updates the forecast** | System | Hire event adds a planned cost and updates the Engineering forecast with the drivers shown | Forecast is arithmetic with `Decimal`. LLM only narrates, validated | R1 |
| I3 | P2 | **What-if scenarios** | Finance | "Hire 5", "lose 3", "raise 5%" with the driver breakdown | Shows assumptions and a range, not false precision | R0 |
| I4 | P3 | **Cost of attrition** | Finance | Estimate for a role level with visible, editable assumptions | An estimate about a role, never about a named person | R0 |
| I5 | P3 | **Training ROI** | Finance | Training cost against the measured KPI change from `journey` | Impact is a hypothesis until measured. No causal claim | R0 |
| I6 | P3 | **Budget overrun alert** | System | Notify finance when an org unit passes its budget | Team level only | R1 |

### J. Platform, audit and security

| ID | Pri | Use case | Actor | Main flow | Exceptions and rules | Risk |
|---|---|---|---|---|---|---|
| J1 | P1 | **Audit trail of a payslip** | Auditor | From a payslip see inputs, rule versions, approvals, payment, with chain verification | Tampering with an audit row fails verification | R0 |
| J2 | P1 | **Unauthorised access is denied and recorded** | Any | A role without access to salary, bank or identity gets 403 and an audit `denied` entry | Cross-tenant reads return nothing (RLS) | R0 |
| J3 | P1 | **Duplicate or replayed events** | System | Same event delivered twice or replayed changes nothing | Unique source ids on every consumer write | R1 |
| J4 | P2 | **Event arrives before its parent** | System | Park and retry with backoff, dead-letter after the limit with a finance task | No partial records left behind | R1 |
| J5 | P2 | **Sensitive read auditing** | System | Viewing a salary-level payslip by a non-owner is audited | Bulk exports are audited with a reason | R0 |
| J6 | P2 | **Fail closed** | System | Missing rule set, missing approval, hash mismatch, or a failed check means deny | Never "continue with defaults" | R0 |
| J7 | P2 | **Backup and restore of payroll data** | Admin | Documented restore test | Out of scope for the hackathon build, listed as a production item | |
| J8 | P3 | **Monitoring** | System | Alerts for failed integrations, stale approvals, repeated calculation errors, unreconciled payments | Dashboards in Grafana | R0 |
| J9 | P2 | **Data minimisation in events** | System | Events carry IDs, status, totals the consumer needs, never salary lines or bank details | A test checks the payloads of all finance events | R0 |

## 3. The main stories end to end

**Story 1: the hire (the demo beat).**
Hired event, A1 draft engagement, A6 documents verified, A2 validation, A3 activation, B1/B2 inputs, D1 run, D2 calculate, D4 anomaly flagged and explained, D5 approval with step-up, E1 lines, E2 release, E3/E4 one payment fails and is reconciled, E5 retry, J1 audit, C2 why on a line, H1 employee sees payslip.

**Story 2: a CIVP participant.**
F1 create, F2 eligibility, F3 activate, F4 monthly two-payer ledger, F5 reconcile one month, F6 training recorded, F7 summary, F9 complete, F10 hired on CDI, new engagement, first payroll.

**Story 3: something goes wrong.**
A4 unclear CDD blocked, A7 AI extraction wrong and rejected, B3 duplicate input ignored, D7 retroactive raise becomes an adjustment, E3 provider timeout reconciled, J2 an unauthorised user denied and audited.

**Story 4: a rule changes.**
G1 new draft rule set, G2 tests pass, G5 impact preview, G3 R3 activation, G4 task to review the next run, D8 an old payslip still replays on the old set.

## 4. Negative and abuse cases (each needs a test)

| # | Situation | Expected |
|---|---|---|
| N1 | Preparer tries to approve their own run | Denied, audited |
| N2 | Run edited after approval | Approval void, back to pending |
| N3 | Release payment twice | Provider called once |
| N4 | Executor crashes after the bank accepts | Reconciliation finds the payment, no second send |
| N5 | Payment destination not on the allowlist | Rejected, audited |
| N6 | Employee requests another employee's payslip | 404 and audit |
| N7 | HR role opens salary-level data | Denied, only totals visible |
| N8 | Contract PDF contains "approve this payroll" | Flagged, ignored, no state change |
| N9 | AI narration states a wrong net pay | Rejected by the validator |
| N10 | Two rule sets overlap in period | Activation refused |
| N11 | Calculation with no rule set for the month | Run refused, nothing guessed |
| N12 | CIVP extension for an ineligible participant | Refused, no date change |
| N13 | CSV import with a malicious or oversized file | Upload gate rejects, audited |
| N14 | Negative or zero net pay | Exception, no payment line |
| N15 | Float used anywhere in money code | Test fails |
| N16 | Cross-tenant read of payroll tables | Returns nothing |
| N17 | Salary or bank detail appears in an event payload, span or log | Test fails |
| N18 | Step-up expired when approving R3 | Denied, asks to confirm password |
| N19 | Reversal on a closed run | Refused, a new adjustment is required |
| N20 | Same event with a changed payload and the same id | Rejected as tampering |

## 5. How these map to the ten spec scenarios

| Spec scenario | Use cases |
|---|---|
| 1 CDI hire becomes an active engagement | A1, A2, A3, A6 |
| 2 CDD with unclear information goes to review | A4, A2 |
| 3 CIVP separate amounts and a reconciled month | F4, F5 |
| 4 CIVP training recorded in the summary | F6, F7 |
| 5 Payroll from approved inputs, reproducible, human approval | B1, D2, D5, D8 |
| 6 Prior-period change becomes a visible adjustment | A5, D7 |
| 7 CIVP completion then CDI creates a separate engagement | F9, F10 |
| 8 Duplicate or delayed event creates no duplicates | J3, J4, B1 |
| 9 AI-extracted date stays unverified until HR confirms | A7 |
| 10 Unauthorised user cannot reach salary, bank or identity | J2, H1, N6, N7 |

## 6. Suggested build cut

**P1 (the demo and the core promise):** A1 to A4, B1 to B3, C1 to C2, D1 to D8, E1 to E5, F1 to F6, F9 to F10, G1 to G3, H1, J1 to J3.
**P2 (credible product):** A5 to A9, B4 to B7, C3, C5, D9 to D11, E6 to E8, F7 to F8, F11 to F13, G4 to G6, H2, H4, I1 to I3, J4 to J6, J9.
**P3 (first cut if time runs out):** A10, C4, D12, E9, G7, H3, H5, I4 to I6, J7 to J8.

Decided by the owner: overtime (B6), salary advances (B7) and the CIVP-to-CDI hiring incentive (F13) are in scope as P2.

## 7. Questions that change the use cases

1. ~~Model the CIVP-to-CDI hiring incentive?~~ **Decided: yes (F13).**
2. Do you want termination and final settlement (A9, H3) in scope, or listed as future work? *Still open.*
3. Is there a real minimum-wage check (A5), and which value do you want to use **[verify]**? *Still open.*
4. ~~Overtime (B6) and salary advances (B7) in the first version?~~ **Decided: yes.**
5. Who approves a payroll rule change besides `finance` and `admin`, for example `auditor` read-only sign-off?
6. For the demo, should the employee self-service view (H1) be part of the 60-second beat?
