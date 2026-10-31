# Finance pack: rule sets and the payslip formula

Reference for the data the payroll calculation runs on and the formula that uses it. Part of the [finance documentation](FINANCE_INDEX.md). Where each value came from and how sure we are is in [FINANCE_PLAN.md](FINANCE_PLAN.md) section 8.1.

**Every value here is an unverified demo value** from secondary sources. The demo rule set says so in its own `source_ref`, and a rule set with `is_demo: true` must show a banner wherever its results appear. Do not call any result certified.

## 1. Files

| File | What |
|---|---|
| `data/demo/finance/rule_set_tn_2026_demo.json` | The demo rule set (id `tn-private-2026-demo-v1`) |
| `packages/packs/finance/payroll/rules.py` | Reads, checks and hashes a rule set. Picks the one in force on a day |
| `packages/packs/finance/payroll/calc.py` | The pure payslip formula |
| `tests/test_finance_calc.py` | 35 tests, with expected values worked out by hand |

## 2. Rule set format

All numbers are strings and become `Decimal`. Nothing is a float.

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
- **Refusals:** gross of zero or less, an unknown child kind, or a disabled child when the rule set has no value for it all raise `PayslipInvalid`.
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
| Solidarity levy | 0.5 percent, exempt within 5,000 | Unverified. Described as temporary |
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

## 6. Running the tests

The full suite runs through `python astra.py check` once the stack is up. The calculation tests need no database, so they can also run alone with pytest and `--noconftest` from the repository root with `PYTHONPATH=packages`.
