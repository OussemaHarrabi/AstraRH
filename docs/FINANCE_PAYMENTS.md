# Finance pack: payment and reconciliation

Reference for how an approved payroll run is paid, how the result comes back, and how a run is closed. Part of the [finance documentation](FINANCE_INDEX.md). The use cases are E1 to E7 and D9 in [FINANCE_USE_CASES.md](FINANCE_USE_CASES.md). The reasoning behind the design, and the kernel requests it depends on, are in [FINANCE_PAYMENT_DESIGN.md](FINANCE_PAYMENT_DESIGN.md). The runs it follows are in [FINANCE_RUNS.md](FINANCE_RUNS.md).

**Everything here pays through a sandbox bank.** The bank is a small container of ours that behaves predictably. Nothing leaves the system and no money moves. Every payment view and decision record says so.

## 1. Files

| File | What |
|---|---|
| `packages/packs/finance/payments.py` | Destinations, lines, release, recording, status handling, reconciliation, closing |
| `packages/kernel/payments.py` | The shared token and amount formats and the status event `bank.payment.status_reported.v1` |
| `packages/kernel/adapters/payments.py` | The `payment.release` adapter: `build` (checks, no network), `send`, `find`, `statuses` |
| `apps/bank/main.py` | The sandbox bank |
| `apps/executor/main.py` | `poll_bank`: reads the bank's statuses, compares amounts, publishes events |
| `packages/packs/finance/consumers.py` | `record_payment_release` and `apply_payment_status`, run in the worker |
| `packages/packs/finance/handlers.py` | `approve_run` (creates the lines) and `close_run` |
| `packages/packs/finance/migrations/versions/ac048a31a8b4_*.py`, `finance_0007_payment_guards.py` | The destination table and the database guards |
| `tests/test_bank.py`, `tests/test_payments_adapter.py`, `tests/test_finance_payments.py` | 102 tests (100 pass, 2 expected failures for K9) |

## 2. The path of a payment

```
approve run (R3) ──▶ payment lines (due)
        │
release proposal (R3, a second person) ──▶ executor sends one batch to the bank ──▶ proposal executed
        │                                                                                 │
        ▼                                                          trust.action.executed.v1 (worker)
   lines: due ──▶ submitted ──▶ paid / part_paid / failed / reversed ◀── bank statuses, polled by the executor
        │
all lines paid ──▶ run paid ──close (R2)──▶ closed
```

Three processes, each with the access it needs and no more:

| Process | Does | Cannot |
|---|---|---|
| **api** | Records destinations, shows payments, proposes | Write a line or a batch, send anything |
| **worker** | Creates lines, records the release, applies bank statuses, reconciles | Reach the bank |
| **executor** | Sends the approved batch, polls the bank, publishes statuses | Read or write any finance table |

The executor sees only the trust ledger, so the result of a send reaches finance as an event, and the worker updates the lines.

## 3. Payment destinations

Each employee has one destination, an **opaque account token** such as `ACC-7F3A91C2D004`. An account number or IBAN is never stored: the database refuses anything that does not look like `ACC-` followed by 4 to 40 capital letters, digits or dashes. Tokens are shown masked (`ACC-...D004`) everywhere, in the API, the decision record and the events (which carry none).

`PUT /employees/{id}/payment-destination` (admin, finance) sets or replaces it. `GET /payment-destinations` lists them masked (admin, finance, auditor). HR and employees get 403: a destination is pay data.

**A run cannot be paid to nobody.** Calculation raises a blocking `NO_PAYMENT_DESTINATION` issue for each employee without one, and approval refuses a run where one is still missing. The other employees are unaffected until the run is submitted.

## 4. Payment lines

Approving a run creates one **payment line** per payslip with net pay above zero, in status `due`. The line holds the amount, the destination token at that moment, and the key `pay:{payslip_id}`, which is unique, so approval repeated creates nothing twice.

| Status | Meaning |
|---|---|
| `due` | Approved, not sent |
| `submitted` | In a batch the bank accepted. Waiting for its outcome |
| `paid` | The bank paid exactly the approved amount |
| `part_paid` | The bank paid only part |
| `failed` | The bank could not pay it (reason kept) |
| `reversed` | The bank returned money it had paid |

The database enforces the path: `due → submitted`, `submitted → paid / part_paid / failed / reversed`, `part_paid → paid`, `paid → reversed`, and `failed` or `reversed → submitted` for a retry. A line's amount and key never change, and a line is never deleted. The destination on a line can be corrected only while the line is `due`, `failed` or `reversed`, never while money is in flight.

## 5. Releasing

`payments.request_release` (service function, route `POST /payroll-runs/{id}/payments/release`) proposes paying **every line that is due, failed or reversed**. It is an **R3 external action**: a different `finance` or `admin` person approves, with a fresh password, and only then does the executor act. The run must be approved or payment pending, and its payslips must still match the approved results hash.

**The payload is what the approval binds.** It holds the run, the release number, the currency (`TND`), and for each line the id, token, amount and key, with the total, the count and the results hash. Editing it voids the approval. Tokens are taken from each employee's *current* destination, so a corrected destination is used by the next release.

**One release is one batch** at the bank, identified by the proposal's key `finance.payment.release:{run}:{release number}`. The executor re-validates the payload (`build`), sends, and records the bank's reference. Sending the same batch again returns the same reference and pays once.

**Recording.** `trust.action.executed.v1` reaches the worker, which creates the `payment_batch`, marks its lines `submitted` (with their token and a fresh status counter), moves the run `approved → payment_pending`, and publishes `finance.payment.submitted.v1`. Recording the same execution twice makes one batch.

## 6. What comes back from the bank

The executor polls the bank every 5 seconds for statuses after a cursor. **It holds the approved payload, so it compares the amount the bank says it paid with the amount that was approved**, and publishes `bank.payment.status_reported.v1` with only `provider_ref`, `key`, `line_id`, `status`, `status_seq`, `amount_matches` and `reason_code`. No amount, token or name travels in the event.

The worker applies each status:

| Rule | Effect |
|---|---|
| Every status is recorded once | History in `payment_status_event` (unique per line, release and sequence). Delivered twice, it is stored once |
| Only a newer status changes the line | A late older status is kept as history and changes nothing. This makes out-of-order delivery safe |
| A status of another release is ignored | A failed line retried under a new release is not reverted by the old release's statuses |
| `amount_matches = false` | The line **stays `submitted`** with reason `AMOUNT_MISMATCH` and a blocking issue. A payment is never marked paid when the amount differs |
| A status that arrives before the release is recorded | The consumer raises and the bus retries it after a backoff, so it is not lost |
| An unknown line or status | Refused and retried until dead-lettered |

**Reconciliation** runs after every change: the worker recomputes the issues on the run and, when every line is `paid`, moves the run to `paid` and its payslips to `paid`. A reversal that arrives after that **reopens the run** to `payment_pending`. It publishes `finance.payment.reconciled.v1` (counts only).

| Issue (entity `payroll_payment`) | Raised when |
|---|---|
| `PAYMENT_FAILED` | A line failed. Fix the destination, release again |
| `PAYMENT_PART_PAID` | A line was only partly paid |
| `PAYMENT_REVERSED` | The bank returned a payment |
| `PAYMENT_AMOUNT_MISMATCH` | The bank's amount differs from the approved one |

All are blocking, and clear themselves when the line is paid.

## 7. Failures and the unknown outcome

| Situation | What happens |
|---|---|
| The bank **refuses the batch** (bad token, total mismatch, refused account) | The execution is `failed`, nothing is recorded, the lines stay `due`, the run stays `approved`. `GET .../payments` shows `release.state = failed` with the reason. Fix the cause and release again |
| One line **fails** at the bank | The others are paid. The run stays `payment_pending`. A new release pays only the failed line |
| **Timeout** or an unexpected error while sending | The outcome is `unknown`. **The release is never resent automatically**, because the bank may have paid. A person checks with the bank |
| The executor **crashes after the bank accepted** | The kernel's existing reconciliation asks the bank by key, finds the batch, and marks the execution succeeded without sending again |

An `unknown` outcome is not looked up again by itself. That needs kernel request **K2** (open). Until then it stays unknown for a person.

## 8. Closing

`payments.request_close` (route `POST /payroll-runs/{id}/close`) proposes closing a run whose payments are **all paid with no open payment issue**. It is an **R2 internal action** with a decision record. When approved, the handler checks again that every line is paid and nothing is open, then sets the run `closed` and publishes `finance.payroll.closed.v1`. A closed run never changes: its status cannot move, and the existing guards freeze its payslips. A reversal arriving first reopens the run, so it cannot be closed with a payment in doubt.

## 9. Sandbox bank

A FastAPI container on the internal `bank` network, reachable only from the executor. State is in memory: a restart clears it.

| Token ends with | The bank does |
|---|---|
| (anything else) | Pays the line in full |
| `-FAIL` | Fails it (`ACCOUNT_CLOSED`) |
| `-PART` | Pays half, rounded down to the millime |
| `-REV` | Pays it, then reports it returned (`RETURNED_BY_BANK`) |
| `-MISMATCH` | Reports paid with 1.000 less than approved |
| `-REFUSE` | Refuses the whole batch (422) |

A batch is idempotent by its key: the same key and content returns the same reference (200), a different content under the same key is 409. A batch with a malformed token or amount, or a total that does not match the lines, is 422 and nothing is recorded.

## 10. Who can do what

| | admin | finance | hr | auditor | others |
|---|:-:|:-:|:-:|:-:|:-:|
| Set a destination | yes | yes | no | no | no |
| See destinations (masked) and a run's payments | yes | yes | no | yes | no |
| Propose a release or a close | yes | yes | no | no | no |
| Approve a release (R3) | yes | yes | no | no | no |
| Approve a close (R2) | yes | yes | no | no | no |

The requester cannot approve a release. The decision records are visible to `admin`, `finance` and `auditor`, not HR.

## 11. Routes

Under `/api/packs/finance`.

| Route | Roles | What |
|---|---|---|
| `PUT /employees/{id}/payment-destination` | admin, finance | Set a token. Returns it masked |
| `GET /payment-destinations` | admin, finance, auditor | Masked tokens |
| `GET /payroll-runs/{id}/payments` | admin, finance, auditor | Lines, batches, the state of the last release, open issues, the sandbox notice |
| `POST /payroll-runs/{id}/payments/release` | admin, finance | Propose a release (202). **Blocked over HTTP by K9** |
| `POST /payroll-runs/{id}/close` | admin, finance | Propose closing (202). **Blocked over HTTP by K9** |

## 12. What the database enforces

Migration `finance_0007`, with the grants from the first finance migrations. Tested in `tests/test_finance_payments.py`.

| Rule | Detail |
|---|---|
| Tokens only | A destination must match the token format. One destination per employee per tenant |
| Lines keep their amount and key | Never changed, never deleted. Status follows the path in section 4 |
| Money in flight keeps its destination | The token cannot change while a line is `submitted`, `paid` or `part_paid` |
| Batches are history | Identity columns never change |
| Worker-only writes | The API role cannot write a line, batch or status event. The executor cannot read any finance table |
| A paid run can reopen | `paid → payment_pending` is allowed, for a late reversal. Nothing leaves `closed` |
| Isolation | Row-level security on the destination table (24 finance tables in all) |

## 13. Not built yet

| Item | Why |
|---|---|
| Proposing a release or a close over HTTP | Kernel request K9. The tests propose through the worker, and two strict expected-failure tests turn into failures when K9 is fixed |
| Looking up an `unknown` release by itself (E3) | Kernel request K2 |
| A durable queue and a sweep job for failed or unknown releases | Requests K5 and K6. The state is read from the request itself (`release.state`) |
| Partial release of a chosen subset, scheduling | Not requested |
| Accounting and filing exports (FT-32) | Later |
| A real bank | The sandbox stands in. A real provider needs its own adapter, credentials and a security review |
| Employees seeing their payment status (H1) | Later |
