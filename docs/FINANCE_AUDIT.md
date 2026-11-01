# Finance pack: audit of 2026-11-01

**Status: all findings resolved on 2026-11-01 except P4 (message ready, not yet sent). See section 5.**

Audit of everything built so far on `finance-v0` and `finance-v1`, plus the uncommitted rule-set and calculator work. Part of the [finance documentation](FINANCE_INDEX.md).

**How it was done.** An independent reviewer read the code, migrations and tests without being told what to look for. The main author audited the documents and the repository. Every code finding below was confirmed by reading the exact code path, and the key ones also by a read-only database query or by running the pure code. Nothing was changed during the audit.

**Overall.** The core holds: the formula matches all four hand-checked payslips, money is `Decimal` only, the formula is pure, approvals are hash-bound with step-up and no self-approval, the executor cannot touch finance data, all 20 tables have row-level security, and bank status history is append-only. The defects are in **database enforcement that is weaker than the docs claim**, one **legal question about the solidarity levy**, and **document drift**.

## 1. Code findings, most severe first

| # | Severity | Where | Defect | Scenario | Confirmed |
|---|---|---|---|---|---|
| A1 | Medium-high | `finance_0002_security.py` | The API role can **insert** a rule set that is already `active`. Only update and delete were revoked, and nothing checks the status on insert | Any API code path or bug inserting `status="active"` puts rules into use with no proposal | Yes, grants query: `rule_set` = INSERT, SELECT for `astra_api`, no triggers |
| A2 | Medium | `service.py` `active_rule_sets`, no trigger on `rule_set` | An **active** rule set's definition can be edited by the worker or owner role, and calculations neither notice nor refuse. The hash shown is recomputed from the edited data | `UPDATE finance.rule_set SET definition = ...` after activation silently changes every payslip | Yes, code path and no trigger |
| A3 | Medium | `finance_0002_security.py` freeze triggers | "Frozen when submitted" can be bypassed: (a) new lines or payslips can be **inserted** into a frozen run; (b) a payslip or line can be **moved** to another run or payslip by changing its parent id; (c) the API role can set an `approved` or `paid` run back to `draft`, which unfreezes it with no proposal | Edit an approved payroll without approval | Yes, triggers fire on update and delete only and check `OLD` ids only; grants query: `payroll_run` = full write for `astra_api` |
| A4 | Medium, **legal question** | `calc.py` solidarity levy | The levy is charged on the **whole** net taxable amount once it passes 5,000, so net pay can **fall when gross rises** | Gross 512.580 gives net 462.962; gross 512.581 gives net 460.880 | Yes, by running it. Whether the law charges the whole amount or only the part above 5,000 is **unverified**. The published example we matched uses the whole amount |
| A5 | Low-medium | `service.py` idempotency key | A rejected, expired or failed activation can never be retried. The same key returns the old proposal, the API answers 202 with status `rejected`, and a new orphan decision record is written each time | After a rejection the only way forward is a new rule-set id | Yes, `trust.propose` returns any existing proposal |
| A6 | Low | `service.py` `describe_changes` and rationale | With no earlier rule set, every field is listed as "none -> value" and the text says "changes against the previous rule set". `valid_to` and `is_demo` are excluded, so the approver never sees those change | Misleading text in front of the approver | Yes, code path |
| A7 | Low | `rules.py` | `NaN` or `Infinity` values cause a server error (500) instead of a refusal (422). An example with gross `Infinity` makes `/test` and `/activate` crash, and the worker would mark the proposal `unknown` instead of `failed`. A JSON number of 1e16 or more is renormalised by the database, so the stored hash no longer matches and the draft can never be activated | Bad input gives a crash instead of a clear refusal | Yes, `NaN` reproduced. The 1e16 case was reproduced by the reviewer |
| A8 | Low | `handlers.py` | The overlap check is not serialised. Two workers activating at once could each see no overlap | Two overlapping active sets, after which the calculator refuses (fails closed) | Plausible. Not reachable today because only one worker runs |
| A9 | Low | `calc.py`, `api.py` | Display: the IRPP and CSS lines show an annual base next to a monthly amount. The gross line is not rounded with the rest. `date.today()` uses the server's UTC date, not Tunis time | Confusing lines, and a wrong rule set for an hour around 1 January | Yes, code path |

**Tests that do not prove their name:**
- `test_the_api_cannot_activate_a_rule_set` only tries an update, not an insert (A1).
- `test_net_is_below_gross_and_rises_with_gross` steps by 300 TND, so it never meets the levy cliff (A4).
- No test covers insert into a frozen run, moving a payslip between runs, editing an active rule set, or retrying after a rejection.

## 2. Document drift

| # | Where | Problem |
|---|---|---|
| D1 | `FINANCE_PLAN.md` (rule set status list and state table), `FINANCE_SYSTEM_DESIGN.md` section 5, `FINANCE_USE_CASES.md` G2 | Still describe `draft → tested → approved → active`. Decision D15 replaced it with `draft → active` |
| D2 | `FINANCE_SYSTEM_DESIGN.md` section 2 | Says the API "creates proposals". It cannot (K9) |
| D3 | `FINANCE_SYSTEM_DESIGN.md` section 4 | Still promises exclusion constraints and a database-enforced "closed run" rule that is weaker than stated (A3). Section 4.1 corrects the first point only |
| D4 | `FINANCE_SYSTEM_DESIGN.md` section 4.1, `FINANCE_RULES.md` section 6 | Claim the API "can draft but not change a rule set" and "a stored rule set is never edited". Not enforced (A1, A2) |
| D5 | `FINANCE_SYSTEM_DESIGN.md` section 14 | "macOS setup untested" is now done |
| D6 | `FINANCE_INDEX.md` | Lists the payment design as covering K1 to K6. It now has K1 to K9 |
| D7 | `FINANCE_PLAN.md` section 3 and `FINANCE_PAYMENT_DESIGN.md` section 8 | Two numbering schemes for kernel requests (C1 to C6 and K1 to K9) that overlap |
| D8 | `FINANCE_INDEX.md` approach point 10 | Says to work on `feat/finance/*`. The real branches are `finance-v0` and `finance-v1`, as the owner asked |

## 3. Repository and process

| # | Finding |
|---|---|
| P1 | The rule-set and calculator work (5 new files, 10 changed) is **not committed or pushed**. `finance-v1` on GitHub matches the last local commit |
| P2 | Both commits are authored as `alae22 <alae220@gmail.com>` (this machine's git identity), not the GitHub account `MoetazDhahri`, and carry a Claude co-author line. The owner has not said whether to keep either |
| P3 | The pushed migration `3e65e32a7d91` was reformatted afterwards. The change is formatting only (identical syntax tree), so the database is unaffected |
| P4 | The kernel issue K9 (API cannot insert proposals) also breaks the existing talent "reject candidate" endpoint. Oussema has not been told yet |
| P5 | No secrets are tracked. `.env` is ignored |

## 4. Proposed fixes

| Fix | Covers | Where |
|---|---|---|
| New migration `finance_0003`: a trigger on `rule_set` that allows insert only as `draft`, allows the status change from `draft` to `active` only, and forbids any change to `definition`, `definition_hash`, `valid_from` or `valid_to` once active | A1, A2, D4 | finance migration |
| Same migration: freeze triggers also on **insert** and on changes to parent ids; and a status-transition rule on `payroll_run`, so going back to `draft` is only allowed from `calculated` or `approval_pending` | A3 | finance migration |
| `active_rule_sets` refuses a record whose hash does not match its definition | A2 | `service.py` |
| Treat a rejected, expired or failed activation as retryable with a fresh key, and return 409 instead of a misleading 202 | A5 | `service.py` |
| Fix the rationale text and include `valid_to` and `is_demo` | A6 | `service.py` |
| Refuse non-finite numbers and very large literals with a clear message | A7 | `rules.py` |
| Lock active rule sets during activation | A8 | `handlers.py` |
| Show monthly bases for IRPP and CSS, round every line, use the Tunis date | A9 | `calc.py`, `api.py` |
| Tests for every case above, and fix the two misleading tests | Tests | test files |
| Solidarity levy: **verify the legal base before changing anything.** If the law charges only the part above 5,000, change the formula and the examples. If it charges the whole amount, document the cliff as intended | A4 | owner decision |
| Update the drifted documents and use one numbering for kernel requests | D1 to D8 | docs |
| Tell Oussema about K9, including the talent endpoint | P4 | message |

## 5. Resolution (2026-11-01)

| Finding | Resolution | Proof |
|---|---|---|
| A1 | Migration `finance_0003`: a new rule set must be a draft unless the owner role inserts it | `test_the_api_cannot_activate_a_rule_set` now also tries the insert, as API and worker |
| A2 | `finance_0003` forbids any change to an active rule set's content, owner included, and allows only `draft → active → superseded`. The service refuses an active rule set whose hash no longer matches, so calculation stops | `test_an_active_rule_set_never_changes_even_for_the_owner`, `test_a_tampered_active_rule_set_stops_all_calculation` (tampering simulated by a database superuser with triggers off) |
| A3 | `finance_0003`: freeze triggers also fire on insert and on parent-id changes. Run status follows an allowed path, and the approval-only steps are reserved to the worker | `test_nothing_can_be_added_to_a_submitted_run`, `test_payslips_and_lines_cannot_be_moved_out_of_or_into_a_submitted_run`, `test_a_run_follows_the_allowed_path_and_only_the_worker_approves` |
| A4 | Researched. The levy on the whole amount follows the law as written (LF 2018 art. 53 raises every rate including 0%; LF 2020 art. 39 exempts up to 5,000), so the step is **intended** and documented. Also found: the half-point rate is extended only through 2026, so the demo rule set now ends on 2026-12-31 | `test_the_solidarity_levy_steps_at_the_exempt_amount_as_the_law_reads`. Still unverified against the official texts, like every rate |
| A5 | A rejected, failed or expired request can be made again with a new key. An expired one is marked superseded. An open one gives 409, before any decision record is written | `test_a_rejected_activation_can_be_requested_again`, `test_an_expired_activation_request_is_replaced` |
| A6 | First rule set says there is nothing to compare. `valid_to` and `is_demo` changes are shown. The previous set is named | `test_the_first_rule_set_says_there_is_nothing_to_compare`, `test_a_change_to_the_end_date_or_demo_flag_is_shown` |
| A7 | Decimal values must be finite strings. `NaN`, `Infinity` and JSON numbers are refused with 422 | `test_non_finite_or_unquoted_numbers_are_refused_not_crashed`, `test_rates_must_be_finite_numbers_written_as_strings` |
| A8 | The activation handler takes a per-tenant advisory lock before the overlap check | Not covered by an automated test (needs two concurrent workers). Reviewed in code |
| A9 | Tax lines show the monthly share of net taxable as base. Gross with more decimal places than the rule set rounds to is refused. The default date is Tunis time | `test_tax_lines_show_the_monthly_share_of_net_taxable_as_base`, `test_gross_with_more_places_than_the_rule_set_rounds_to_is_refused`, `test_today_is_taken_in_tunis_time` |
| Tests | The two misleading tests were corrected | See A1 and A4 |
| D1 to D8 | All corrected. Kernel requests now use one numbering, K1 to K12, in the payment design. K7 was missing from the repo docs and is now recorded | Document diff |
| P1 | Committed and pushed only when the owner asks | |
| P2 | Left to the owner: commit author and co-author line | |
| P3 | No action: formatting only | |
| P2 (update) | Switched to the owner's GitHub identity on request | Decision D21 |
| K8 (update) | The macOS init bug was fixed on request, verified identical | Runbook section 3 |
| P4 | Message to the kernel owner rewritten to lead with K9 and K8. **It still has to be sent by a person** | `FINANCE_PAYMENT_DESIGN.md` section 8 |

**Result after the fixes:** `python3 astra.py check` gave **374 passed, 2 skipped, 1 expected failure** (the K9 test), ruff clean, migrations `3e65e32a7d91`, `finance_0002` and `finance_0003` applied. After the rebase onto the latest `main` on 2026-11-01 the same suite, now including the kernel owner's new tests, gives **420 passed, 2 skipped, 1 expected failure**.
