# Finance pack: payroll inputs

Reference for how approved hours, absences, bonuses, allowances and reimbursements get into payroll. Part of the [finance documentation](FINANCE_INDEX.md). The use cases are B1 to B3 in [FINANCE_USE_CASES.md](FINANCE_USE_CASES.md).

**This step covers getting inputs in and checking them.** A payroll run does not read them yet (see section 10).

Limits marked **[verify]** are configuration standing in for a real rule and have not been checked against labour law or company policy.

## 1. Files

| File | What |
|---|---|
| `packages/packs/finance/validation/inputs.py` | The row checks and the conflict rules. Pure: no database, no clock, no model |
| `packages/packs/finance/inputs.py` | CSV parsing, import, batch validation, withdrawal |
| `packages/packs/finance/issues.py` | The issue workflow shared with engagements |
| `packages/packs/finance/api.py` | The routes (section 8) |
| `packages/packs/finance/migrations/versions/df4c291a2cdf_payroll_inputs_reference_and_rejections.py`, `finance_0005_input_guards.py` | The `reference` and `line_number` columns, the `payroll_input_rejection` table, row-level security and the database guards |
| `tests/test_finance_input_rules.py`, `tests/test_finance_inputs.py`, `tests/test_finance_schema.py` | Tests |

## 2. The flow

```
CSV or JSON rows ─▶ row checks ─▶ rejected (kept with a reason)  or  stored as an input
        stored inputs ─▶ conflict checks against the period and the engagements ─▶ issues
        a person resolves review items, finance withdraws wrong inputs, the batch becomes ready
```

Two different outcomes, on purpose:
- **Rejected**: the row is malformed, so it is not stored. It is kept with its line number and reason so the sender can fix and resend it.
- **Issue**: the row is well formed and stored, but it conflicts with something or needs a person to look at it.

## 3. The CSV format

The header must be exactly `employee,kind,effective_date,quantity,amount,reference`, in that order. Anything else is refused as a whole file.

| Column | Rule |
|---|---|
| `employee` | The employee's external id, for example `EMP-009` (letters, digits and `. _ : / -`, up to 64) |
| `kind` | `hours`, `absence`, `bonus`, `allowance` or `reimbursement` (case ignored) |
| `effective_date` | `YYYY-MM-DD`, a real date, inside the batch period |
| `quantity` | For `hours` (above 0, at most 24 a row) and `absence` (days, above 0, at most 31). Empty for the other kinds |
| `amount` | For `bonus`, `allowance`, `reimbursement` (above 0, at most 10,000,000). Empty for hours and absence |
| `reference` | Optional. The sender's own id for the row (up to 64, letters, digits and `. _ : / -`) |

Numbers are plain digits with up to 3 decimals: no signs, exponents, thousands separators, `NaN` or `Infinity`. A reference that starts with `=`, `+`, `-` followed by odd characters, or `@` is refused, so a value can never turn into a spreadsheet formula later. A UTF-8 byte-order mark and Windows line endings are accepted.

**A file is refused as a whole (422) when:** it is empty or has no rows, is not UTF-8 text, contains binary bytes, has the wrong header, has an unterminated quote, is larger than 1 MB, has more than 5,000 rows, or the period is missing, ends before it starts or is 62 days or longer.

**A row is rejected, not the file, when:** it has the wrong number of columns (`ROW_MALFORMED`), or fails one of the checks below.

| Rejection code | Meaning |
|---|---|
| `EMPLOYEE_INVALID` | Missing or odd characters |
| `EMPLOYEE_UNKNOWN` | No employee with that external id |
| `KIND_UNKNOWN` | Not one of the five kinds |
| `DATE_INVALID` | Not `YYYY-MM-DD` or not a real date |
| `DATE_OUTSIDE_PERIOD` | Before the period starts or after it ends |
| `QUANTITY_INVALID` | Missing, zero, too large, or not plain digits |
| `AMOUNT_INVALID` | Missing, zero, too large, or not plain digits |
| `VALUE_NOT_ALLOWED` | A quantity on an amount kind, or an amount on a quantity kind |
| `REFERENCE_INVALID` | Odd characters or too long |
| `DUPLICATE_IN_FILE` | Same input as an earlier line of the same file (the message names the line) |
| `ALREADY_IMPORTED` | Same input stored by an earlier batch |

## 4. Idempotency

Sending the same thing twice changes nothing.

- **Same content, same batch.** A batch is identified by a hash of its content and period. Uploading the same file again, or sending the same JSON rows again, returns the existing batch (HTTP 200 instead of 201) and stores nothing. The same file for a different period is a new batch.
- **Same input, stored once.** Each stored input has a unique source key. With a `reference` the key is the employee plus the reference, so the same reference twice is the same input even if the values differ. **Without a reference** the key is the employee, kind, date, quantity and amount, so two identical rows count as one. **To enter two genuinely identical amounts, give them different references.**
- Two inputs with the same values but different references are both stored, and raise a `POSSIBLE_DUPLICATE` review issue for a person to confirm.
- **A withdrawn input is not imported again.** Sending its row again gives `ALREADY_IMPORTED`. A corrected row needs a different date, value or reference.

## 5. Conflict checks and issues

Stored inputs are judged against all inputs of the same period (including other batches) and against the employees' **active** engagements. Only inputs of the batch being checked get the issues.

| Code | Severity | Raised when | Owner |
|---|---|---|---|
| `NO_ACTIVE_ENGAGEMENT` | blocking | The employee has no active engagement covering the input's date | HR |
| `POSSIBLE_DUPLICATE` | review | Another input has the same employee, kind, date, quantity and amount but a different reference | FINANCE |
| `ABSENCE_AND_HOURS_SAME_DAY` | review | Hours and an absence for the same employee on the same date | FINANCE |
| `MONTHLY_HOURS_HIGH` | review | More than 300 hours for the employee in the period **[verify]** | FINANCE |
| `LONG_DAY` | warning | More than 12 hours in one row | FINANCE |
| `AMOUNT_UNUSUAL` | warning | An amount above 20,000 **[verify]** | FINANCE |

The issue workflow is the one engagements use (decision D15 style, shared code in `issues.py`):
- A **blocking** issue cannot be waved through (409). Fix the cause (activate the engagement, or withdraw the input) and re-check.
- A **review** or **warning** issue is decided by a person with a reason of at least 3 characters. The decision survives later re-checks.
- When the cause disappears the system **clears** the issue.
- Issues on inputs can be decided only by `finance` and `admin`. HR cannot, because inputs carry pay amounts.

## 6. Batch status

| Status | Meaning |
|---|---|
| `ready` | At least one accepted input, no open blocking or review issue (warnings do not stop it) |
| `needs_attention` | An open blocking or review issue |
| `empty` | No accepted input (every row was rejected or withdrawn) |

A batch is re-checked after an import, a withdrawal, a decision on an issue, or on request (`POST .../validate`, for example after an engagement was activated).

## 7. Withdrawing

`POST /payroll-inputs/{id}/withdraw` with a reason of at least 3 characters, by `finance` or `admin`. The input stays in the record as `withdrawn` with the reason, its issues are cleared, and the batch is re-checked, which can clear monthly-hours and duplicate issues on the other inputs. Withdrawing twice gives 409. **An input is never edited or deleted.**

## 8. Routes

Under `/api/packs/finance`.

| Route | Roles | What |
|---|---|---|
| `POST /input-batches` | admin, finance | Multipart: `file`, `period_start`, `period_end`. 201 new, 200 existing |
| `POST /input-batches/rows` | admin, finance | JSON `{source, period_start, period_end, rows}` where `source` is `manual`, `time`, `leave` or `compensation`. Values are strings. Same checks, same idempotency |
| `GET /input-batches`, `GET /input-batches/{id}` | admin, finance, auditor | Batches with counts and open issues |
| `GET /input-batches/{id}/rows` | same | Stored inputs, filter by `status` |
| `GET /input-batches/{id}/rejections` | same | Rejected rows with line, code, message and the raw values |
| `GET /input-batches/{id}/issues` | same | Issues on the batch's inputs, filter by `status` |
| `POST /input-batches/{id}/validate` | admin, finance | Check again |
| `POST /payroll-inputs/{id}/withdraw` | admin, finance | Withdraw with a reason |
| `POST /issues/{id}/resolve` | admin, finance for input issues | Decide a review or warning issue |

**HR, managers, recruiters and employees get 403 on every input route.** Amounts are returned as strings.

**What is kept:** the rows and a hash, not the uploaded file. No file is stored, so there is nothing to scan or leak, and the kernel's document upload gate (which does not allow CSV) is not used. The size, encoding and structure limits above are the gate.

**Event:** every check publishes `finance.payroll.inputs_validated.v1` with the batch id, counts, status and number of open blocking and review issues. It carries no amounts, quantities, names or employee ids.

## 9. What the database enforces

These hold for every role, the owner included (migration `finance_0005`, tested in `tests/test_finance_schema.py`).

| Rule | Detail |
|---|---|
| An input's content never changes | Batch, employee, kind, quantity, amount, date, reference, line and source key are frozen |
| Status only moves `accepted → withdrawn` | Nothing moves back |
| An input is never deleted | It is withdrawn |
| A batch keeps its identity | Source, period, content hash and submitter cannot change. Counts and status can. A batch is never deleted |
| Rejections are history | No update, no delete. One rejection per line per batch |
| Isolation | Row-level security on the rejections table (22 finance tables in all) |

## 10. Not built yet

| Item | Why |
|---|---|
| Inputs from `time.approved` and `leave.approved` events (B1) | Those events do not exist on `main`. They are only declared in the unmerged workforce branch. The same import path (`import_rows`) is where a consumer would push rows |
| A payroll run reading inputs, and locking them | Next step (runs). Until then nothing stops a withdrawal. Once a run uses an input, withdrawal must be refused |
| Late input after a run (B4) | Needs runs |
| Unpaid leave proration (B5), overtime (B6), salary advances (B7) | Later slices |
| Editing a batch's period or an input | Not allowed by design. Withdraw and send a corrected row |
