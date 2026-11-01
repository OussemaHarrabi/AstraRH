# Finance pack: payroll runs

Reference for how a payroll run is created, calculated, checked, submitted and approved. Part of the [finance documentation](FINANCE_INDEX.md). The use cases are D1 to D8 in [FINANCE_USE_CASES.md](FINANCE_USE_CASES.md). The formula and rate values are in [FINANCE_RULES.md](FINANCE_RULES.md), the inputs in [FINANCE_INPUTS.md](FINANCE_INPUTS.md).

**A run produces approved payslips. It does not pay anyone yet.** Payment, reconciliation and closing a run come with the payment step (section 11).

Values and treatments marked **[verify]** are configuration standing in for a real rule and are not checked against Tunisian law.

## 1. Files

| File | What |
|---|---|
| `packages/packs/finance/runs.py` | Create, calculate, submit, recall, replay |
| `packages/packs/finance/payroll/scorer.py` | A payslip as an explainable, replayable decision |
| `packages/packs/finance/payroll/calc.py` | The pure formula (now with pay components and reimbursements) |
| `packages/packs/finance/handlers.py` | `approve_run`, the effect of the approved action |
| `packages/packs/finance/consumers.py` | Calculation and rejection consumers (run in the worker) |
| `packages/packs/finance/api.py` | The routes (section 9) |
| `packages/packs/finance/migrations/versions/c610f6d481b6_*.py`, `finance_0006_run_guards.py` | New run columns, the run-input link table, and the database guards |
| `tests/test_finance_runs.py`, `tests/test_finance_schema.py` | Tests |

## 2. Lifecycle

```
draft ──calculate──▶ calculated ──submit──▶ approval_pending ──approve (R3)──▶ approved ──▶ payment_pending ──▶ paid ──▶ closed
  ▲                      │                        │
  └── recalculate ◀──────┘        recall / reject ─┘ (back to draft, calculate again)
```

The three states after `approved` belong to the payment step. **Status and outcome are separate: calculated, approved and paid are three different facts.** The database enforces the path and who may take each step (section 10).

## 3. Creating a run

`POST /payroll-runs` with `period_start`, `period_end`, `pay_date`, an optional `regime_id` (default `TN_PRIVATE_NON_AGRI`), optional `input_batch_ids` and an optional `external_request_id`. Roles `finance` and `admin`.

| Rule | Result |
|---|---|
| Same `external_request_id` and same content | The existing run is returned (200 instead of 201). Different content gives 409 |
| Period ends before it starts, is 31 days or longer, or the pay date is before the period starts | 422 |
| Another run covers part of the period | 409. Off-cycle corrections are not built yet |
| No active rule set covers **the whole** period | 409. A rule change inside a period is not supported |
| An input batch does not exist (404) or is not inside the period (422) | Refused |

A new run is a draft with `prepared_by` set to the creator.

## 4. Calculation

`POST /payroll-runs/{id}/calculate` answers **202** and publishes `finance.payroll.calculation_requested.v1`. **The worker does the calculation**, because only the worker may write payslips. Poll the run: `calculation_state` goes `requested` then `done` (status `calculated`) or `failed` (with `calculation_error`).

Calculation can be asked again while the run is a draft or calculated. It rebuilds everything, so the same inputs give the same results (the results hash proves it). A second request while one waits gives 409. A run that is waiting for approval or approved cannot be recalculated.

**Who is paid.** Every employee with an `active` engagement overlapping the period, except a CIVP (its allowance and employer complement are a ledger, not payroll).

**How the gross is built.** Pay items in force for the whole period become components (`BASE_SALARY` and any recurring item such as an allowance). Inputs add to them:

| Input kind | Effect |
|---|---|
| `bonus`, `allowance` | Added to the gross as a component of the same code. Taxed and contribute to CNSS **[verify the treatment of allowances]** |
| `reimbursement` | Paid on top of net pay, not taxed, not part of CNSS **[verify]** |
| `hours` | Linked to the run but does not change pay (salaries are monthly) |
| `absence` | Raises `ABSENCE_NOT_PRICED` (below): no deduction is calculated yet |

The payslip lines are `GROSS`, then one line per component, then the deductions and taxes, `REIMBURSEMENT` when there is one, and the employer lines. Every line names the rule it came from.

**Each payslip is a decision.** The kernel records a decision per payslip whose factors are signed lines: gross and reimbursements count +1, employee CNSS, income tax and the solidarity levy count -1, so the factors add up exactly to net pay. The stored inputs include the **rule set itself**, so a replay needs nothing else. The decision is visible to `admin`, `finance` and `auditor`, **not HR**, and it records what was not considered (name, gender, age, nationality, address).

**Inputs used are linked to the run** (`payroll_run_input`), so they cannot be withdrawn once the run is submitted.

## 5. Exceptions and anomalies

One employee's problem never stops the others. It becomes an issue on the run, and the employee gets no payslip until it is fixed. The issue workflow is the one engagements and inputs use: a **blocking** issue must be fixed, a **review** issue is decided by a person with a written reason, and a decision survives a recalculation.

| Code | Severity | Raised when |
|---|---|---|
| `PARTIAL_PERIOD` | blocking | The engagement starts after the period starts or ends before it ends. Proration is not built |
| `PAY_CHANGE_IN_PERIOD` | blocking | A pay item changes inside the period, or two items share a code. Proration is not built |
| `NO_BASE_SALARY` | blocking | No `BASE_SALARY` for the whole period |
| `MULTIPLE_ENGAGEMENTS` | blocking | Several active engagements overlap the period |
| `INPUT_WITHOUT_PAYSLIP` | blocking | An employee has inputs in the run but gets no payslip |
| `BATCH_NEEDS_ATTENTION` | blocking | An input batch of the run still has open issues |
| `PAYSLIP_REFUSED` | blocking | The formula refused the data |
| `NET_PAY_NOT_POSITIVE` | blocking | Net pay is zero or negative |
| `ABSENCE_NOT_PRICED` | review | An absence was recorded. A deduction for unpaid absence is not calculated, so a person confirms that none applies |
| `NET_CHANGE_LARGE` | review | Net pay moved more than 20 percent from the same employee's last approved run **[verify]**. The message gives both figures |

The reasons are templated from the numbers, not written by a model. A later AI agent may rephrase them (decision D14).

## 6. Submitting and approving

**Submit** (`POST /payroll-runs/{id}/submit`, finance or admin): the run must be calculated, have no open blocking or review issue and at least one payslip, and its payslips must still match the calculated results. It creates an **R3 proposal** bound to the exact results by their hash, with a decision record (totals, the items a person decided, the limits) visible to `admin`, `finance` and `auditor`, and moves the run to `approval_pending`.

**Approve** goes through the kernel gate: a different `finance` or `admin` person, with a fresh password confirmation. The requester cannot approve. **When it runs, the handler checks everything again:**
- the run is still waiting for approval and the results hash is the one that was submitted;
- the payslips still match that hash;
- no blocking or review issue is open;
- **the approver is not the person who prepared the run** (a second rule on top of the kernel's, because the preparer and the submitter can differ);
- **every payslip replays to the figures that were recorded**, and a replay that cannot run counts as a failed replay.

Any failure makes the action fail with a stated reason and changes nothing. On success the run becomes `approved`, records the approver and time, its payslips become `approved`, and `finance.payroll.approved.v1` (run id and payslip count only) is published.

**Reject:** the approver rejects through the kernel. A consumer returns the run to draft with its calculation marked idle, so it must be calculated again, and publishes `finance.payroll.rejected.v1`.

**Recall:** the preparer can take a submitted run back (`POST .../recall`). The open request is superseded and the run returns to draft. It also frees a run whose approval failed, so a run is never stuck.

**While submitted,** the run's issues cannot be decided and inputs it used cannot be withdrawn.

## 7. Replaying a payslip

`POST /payslips/{id}/verify` recomputes one payslip from its stored inputs and compares. `POST /payroll-runs/{id}/verify` does it for every payslip and also checks the run's results hash. A payslip altered after the fact, a decision record altered, or a run hash that no longer matches is reported, and `submit` and `approve` both refuse.

## 8. Who can do what

| | admin | finance | hr | auditor | others |
|---|:-:|:-:|:-:|:-:|:-:|
| Create, calculate, submit, recall, decide issues | yes | yes | no | no | no |
| Run list and totals | yes | yes | **totals only** | yes | no |
| Payslips, issues, replay | yes | yes | no | read | no |
| Approve a run (R3) | yes | yes | no | no | no |

HR sees a run's counts and totals, never a payslip or an issue. Employees seeing their own payslips comes later.

## 9. Routes

Under `/api/packs/finance`.

| Route | Roles | What |
|---|---|---|
| `POST /payroll-runs` | admin, finance | Create (201, or 200 for the same request id) |
| `GET /payroll-runs`, `GET /payroll-runs/{id}` | admin, finance, hr, auditor | Runs with totals, open issue counts, rule set |
| `POST /payroll-runs/{id}/calculate` | admin, finance | Ask the worker to calculate (202) |
| `GET /payroll-runs/{id}/payslips` | admin, finance, auditor | One row per employee |
| `GET /payslips/{id}` | same | Every line with its base, rate and rule |
| `GET /payroll-runs/{id}/issues` | same | Exceptions and anomalies, filter by `status` |
| `POST /issues/{id}/resolve` | admin, finance for run and input issues | Decide a review item |
| `POST /payroll-runs/{id}/verify`, `POST /payslips/{id}/verify` | same | Replay |
| `POST /payroll-runs/{id}/submit` | admin, finance | Propose approval. **Blocked over HTTP by kernel request K9** |
| `POST /payroll-runs/{id}/recall` | admin, finance | Take it back |

Amounts are strings. A run that used a demo rule set carries the "demo values, not certified" notice.

## 10. What the database enforces

Migration `finance_0006`, tested in `tests/test_finance_schema.py` and `tests/test_finance_runs.py`.

| Rule | Detail |
|---|---|
| Results are worker-only | Only the worker (or the owner role) can change a run's results hash, inputs hash, rule set, calculation time, approver, period, pay date, regime, batches or creator |
| `calculated` is worker-only | The API role cannot move a run to `calculated`, `approved`, `payment_pending`, `paid` or `closed` |
| Inputs are locked | The `payroll_run_input` links cannot be inserted, changed or deleted once the run is submitted, for any role. The API cannot write them at all |
| No withdrawal | An input used by a submitted run cannot be withdrawn by any role |
| Frozen payslips | Unchanged from `finance_0003`: a submitted run's payslips and lines cannot be inserted, changed, deleted or moved |

## 11. Not built yet

| Item | Why |
|---|---|
| Proposing over HTTP (`submit`) | Kernel request K9. The service function works and the tests propose through the worker |
| Proration for part-month engagements and mid-period pay changes (D12, B5) | Flagged as blocking instead of guessed |
| Unpaid absence deduction, overtime, advances | Later slices. An absence needs a person's decision |
| Adjustments for changes effective in a closed period (D7) | Not started |
| Run comparison (D11) and off-cycle runs (D10) | Not started |
| Payment lines, release, reconciliation, closing a run (D9) | The payment step |
| Calculation as a durable job on its own queue | Kernel request K5. It runs from an event in the worker, which retries a failure |
| Employees seeing their own payslips (H1) | Later |
| Previous-run anomaly needs an approved run to compare with | The first run has nothing to compare |
