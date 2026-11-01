# Finance pack: rule sets and the payslip formula

Reference for the data the payroll calculation runs on and the formula that uses it. Part of the [finance documentation](FINANCE_INDEX.md). Where each value came from and how sure we are is in [FINANCE_PLAN.md](FINANCE_PLAN.md) section 8.1.

**Every value here is an unverified demo value** from secondary sources. The demo rule set says so in its own `source_ref`, and a rule set with `is_demo: true` must show a banner wherever its results appear. Do not call any result certified.

## 1. Files

| File | What |
|---|---|
| `data/demo/finance/rule_set_tn_2026_demo.json` | The demo rule set (id `tn-private-2026-demo-v1`) |
| `packages/packs/finance/payroll/rules.py` | Reads, checks and hashes a rule set. Picks the one in force on a day |
| `packages/packs/finance/payroll/calc.py` | The pure payslip formula |
| `packages/packs/finance/payroll/examples.py` | Runs a rule set's own hand-checked examples |
| `tests/test_finance_calc.py` | 47 pure tests, with expected values worked out by hand |
| `tests/test_finance_rules_api.py` | Rule sets and the calculator over HTTP, with the real database roles |

## 2. Rule set format

All decimal values **must be written as strings** and must be finite. A JSON number, `NaN` or `Infinity` is refused with a clear message. This keeps the stored text exactly what was approved, because the database rewrites some JSON numbers (for example `1e20`), which would break the hash. Whole numbers such as `version`, `rounding_places` and `max_children` stay plain integers.

| Field | Meaning | Checked |
|---|---|---|
| `id`, `version`, `jurisdiction` | Identity of the set | required |
| `valid_from`, `valid_to` | Period in force. `valid_to` may be null | `valid_to` not before `valid_from` |
| `is_demo`, `source_ref` | Verification status and where the values came from | |
| `rounding_places` | Decimal places for displayed lines. 3 for TND millimes | 0 to 6 |
| `contributions.cnss_employee_rate`, `cnss_employer_rate` | CNSS rates | between 0 and 1 |
| `contributions.cnss_monthly_ceiling` | Cap on the CNSS base, or null for none | not negative |
| `professional_expenses.rate`, `cap_annual` | Deduction for professional expenses and its yearly cap | rate 0 to 1 |
| `family.head_of_family`, `child`, `student_child`, `disabled_child` | Yearly deductions. `disabled_child` may be null, meaning unsupported | not negative |
| `family.max_children` | Only the first N children count | not negative |
| `irpp_brackets` | Annual income tax bands: `up_to` and `rate`. The last band has `up_to: null` | limits increase, rates 0 to 1, only the last is open |
| `css.rate`, `css.exempt_up_to` | Solidarity levy rate and the net taxable amount up to which it is not charged | |
| `employer_charges` | Extra employer charges as `code`, `label`, `rate` | codes unique |

A malformed rule set raises `RuleSetInvalid` and is never loaded. `definition_hash` is a SHA-256 of the canonical definition, so any change to any value changes the hash, and a payslip can record exactly which rules produced it.

**Choosing a rule set.** `select(rule_sets, day)` returns the one set in force on that day. None, or more than one, raises `RuleSetUnavailable`. Calculation refuses to guess or fall back to a default.

## 3. The formula

```
employee CNSS      = rate x gross                       (base limited by the ceiling, if any)
monthly taxable    = gross - employee CNSS
annual taxable     = monthly taxable x 12
expenses           = rate x annual taxable, capped
family deductions  = head of family + first N children (child, student or disabled amounts)
net taxable        = annual taxable - expenses - family deductions, never below 0
income tax         = progressive brackets on net taxable, divided by 12
solidarity levy    = rate x net taxable, divided by 12, none when net taxable is within the exempt amount
net pay            = gross - employee CNSS - income tax - solidarity levy
employer cost      = gross + employer CNSS + other employer charges
```

- **Rounding:** unrounded `Decimal` is used internally. Each displayed line is rounded once, half up, to `rounding_places`. Net pay is the sum of the rounded lines, so the lines always add up exactly.
- **Output:** a payslip lists each line with `code`, `label`, `kind` (earning, deduction, tax, employer cost), `base`, `rate`, `amount` and a `rule_ref` such as `tn-private-2026-demo-v1#cnss_employee`. It also returns the working values (monthly and annual taxable, expenses, family deductions, net taxable) so a screen can show the arithmetic.
- **Solidarity levy step (intended).** Above the exempt amount the levy applies to the **whole** net taxable amount, so one millime more gross can lower net pay (gross 512.580 gives net 462.962, gross 512.581 gives 460.880). This follows the law as written: LF 2018 art. 53 raises **every** rate of the income tax scale, including the 0% band, and LF 2020 art. 39 exempts income **up to and including** 5,000. Sources: [LF 2018 text](https://jibaya.tn/wp-content/uploads/2024/01/Loi-de-Finances-2018.pdf), [OpenFisca Tunisia issue 474](https://github.com/openfisca/openfisca-tunisia/issues/474). Still to verify against the official texts, like every value here.
- **Display.** The income tax and levy lines show the monthly share of net taxable (net taxable divided by 12) as their base. The annual figures are in the working values.
- **Refusals:** gross with more decimal places than the rule set rounds to, gross of zero or less, an unknown child kind, or a disabled child when the rule set has no value for it all raise `PayslipInvalid`.
- **Not covered yet:** overtime, benefits in kind, taxable bonus treatment, dependent parents, sector schemes, proration. These are listed as unsupported, not approximated.

## 4. Demo values and verification status

| Value | Demo setting | Status |
|---|---|---|
| CNSS employee | 9.68 percent | Unverified. 9.18 percent base plus 0.5 point from the 2025 Finance Law, per secondary sources |
| CNSS employer | 17.07 percent | Unverified. Same reasoning |
| CNSS ceiling | none | Unverified. One source mentions 5,000 TND a month, most give none |
| Professional expenses | 10 percent, 2,000 TND a year cap | Unverified. Sources differ on whether the base is gross or after CNSS. We use after CNSS |
| Head of family | 300 TND a year | Unverified |
| Child | 100 TND each, first 4 | Unverified |
| Student child | 1,000 TND | Unverified |
| Disabled child | 1,200 TND | Unverified. One source gives no amount |
| Income tax brackets | 0, 15, 25, 30, 33, 36, 38, 40 percent at 5,000, 10,000, 20,000, 30,000, 40,000, 50,000, 70,000 | Unverified. One source claims a different 2026 scale and looks wrong |
| Solidarity levy | 0.5 percent, exempt up to and including 5,000, charged on the whole amount above | Unverified. Half a point is extended through 2026 (LF 2026 art. 87, NC 1/2026), and 1 point is expected from 2027. **The demo rule set therefore ends on 2026-12-31** |
| Employer charges | none in the demo rule set | Sector rates (training tax, housing fund, work accident) belong to employer configuration |

**To drop the demo flag:** check each value against the official text (CNSS, Finance Law 2026 from the tax authority, ANETI), record who checked what and when in `source_ref`, and set `is_demo` to false. That change goes through the R3 rule activation once it exists.

## 5. Hand-checked test cases

Each result was worked out by hand before the code was run, then compared. The code matched all four.

| Gross | Family | CNSS | Income tax | Solidarity | Net pay | Employer CNSS | Employer cost |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2,000.000 | head, 2 children | 193.600 | 253.683 | 7.990 | **1,544.727** | 341.400 | 2,341.400 |
| 3,500.000 | head, 2 children | 338.800 | 670.279 | 14.764 | **2,476.157** | 597.450 | 4,097.450 |
| 400.000 | single | 38.720 | 0.000 | 0.000 | **361.280** | 68.280 | 468.280 |
| 10,000.000 | head | 968.000 | 2,931.967 | 44.202 | **6,055.831** | 1,707.000 | 11,707.000 |

Worked example for the first row: CNSS is 9.68 percent of 2,000 = 193.600. Monthly taxable is 1,806.400, annual 21,676.800. Expenses are 10 percent = 2,167.680, capped at 2,000. Family deductions are 300 + 2 x 100 = 500. Net taxable is 19,176.800. Tax is 0 on the first 5,000, 15 percent of the next 5,000 = 750, and 25 percent of 9,176.800 = 2,294.200, so 3,044.200 a year or 253.683 a month. Solidarity is 0.5 percent of 19,176.800 divided by 12 = 7.990. Net is 2,000 - 193.600 - 253.683 - 7.990 = 1,544.727.

The first row also matches a published worked example from a payroll guide. A second guide's examples contradict its own brackets, so they are not used.

Other tests cover: lines summing to net pay, net rising with gross, identical output for identical input, the expense cap, only four children counting, student and disabled amounts, the exempt levy, net taxable never below zero, bracket edges, the CNSS ceiling, employer charges changing only employer cost, refusals, hash changes, malformed rule sets, and exactly-one rule-set selection. A final test checks that `calc.py` imports nothing but `dataclasses`, `decimal` and the rules module, and contains no float.

**Pay components and reimbursements (added with payroll runs).** The formula can take the gross as components (base salary, bonus, allowance), which must add up to it. Each is shown as its own line and all are taxed and contribute to CNSS together as one amount **[verify the treatment of allowances]**. Reimbursements are paid on top of net pay, are not taxed and are not part of CNSS **[verify]**. Hand-checked: 2,500 gross as 2,000 base and 500 bonus with 100 reimbursed, head of family and two children, gives CNSS 242.000, income tax 385.733, solidarity levy 10.248, **net 1,962.019** and employer cost 3,026.750.

## 6. Examples and the rule set lifecycle

**Examples.** A rule set carries its own hand-checked examples in an `examples` list: `name`, `input` (`gross`, `head_of_family`, `children`) and `expect` (any of `employee_deductions`, `income_tax`, `solidarity`, `net_pay`, `employer_cost`). The demo rule set holds the four cases in section 5. `payroll/examples.py` runs them against the formula and reports each mismatch with the expected and actual value. A rule set with no example, or with a failing one, **cannot be activated**.

**Lifecycle (simplified from the design).** `draft` then `active`. The earlier design had separate `tested` and `approved` states. Testing is now a result computed on demand and re-checked at activation, which is stronger than a stored flag, and approval is the R3 proposal itself. The `superseded` state is reserved and not used yet.

| Step | Who | How |
|---|---|---|
| Save a draft | `finance`, `admin` | `POST /packs/finance/rule-sets`. A malformed set is refused, a duplicate id gives 409 |
| Try the examples | `finance`, `hr`, `admin`, `auditor` | `POST /packs/finance/rule-sets/{id}/test`. Nothing changes |
| Propose activation | `finance`, `admin` | `POST /packs/finance/rule-sets/{id}/activate`. Needs examples that pass and no overlap with an active set. Creates an R3 proposal with a decision record that lists every field that changes against the previous rule set |
| Approve | A **different** `finance` or `admin` user | Password confirmation required. The requester cannot approve. A rejected, failed or expired request can be made again (an expired one is marked superseded). While one is open, a second request gets 409 |
| Take effect | The worker | Takes a per-tenant lock, then re-checks the hash, the examples and overlaps. A rule set changed after approval is refused and the proposal fails. After activation the database forbids any change to its content |

**Date selection.** A calculation uses the one **active** rule set whose period contains the date. Drafts are never used. None, or several, gives an error and no result.

**Overlap.** A new rule set must not overlap an active one. To replace a set from a given date, the earlier set needs its own `valid_to` before the new set's `valid_from`, because an active rule set can never be edited (the database enforces it).

**Which day.** When no date is given, the calculator uses today's date in Tunis (UTC+1 all year), not the server's UTC date.

**Known limit.** Proposing over HTTP does not work yet because of kernel request K9 in [FINANCE_PAYMENT_DESIGN.md](FINANCE_PAYMENT_DESIGN.md). The endpoint exists and its test is marked as an expected failure until the kernel is fixed.

## 7. Running the tests

The full suite runs through `python astra.py check` once the stack is up. The calculation tests need no database, so they can also run alone with pytest and `--noconftest` from the repository root with `PYTHONPATH=packages`.
