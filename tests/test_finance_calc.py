"""The payslip formula and rule sets. Pure functions: no database, no model.

Expected values were worked out by hand from the demo rule set, not copied from the code.
"""

import ast
import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from packs.finance.payroll import calc, rules

ROOT = Path(__file__).resolve().parents[1]
RULE_FILE = ROOT / "data/demo/finance/rule_set_tn_2026_demo.json"
CALC_FILE = ROOT / "packages/packs/finance/payroll/calc.py"


@pytest.fixture(scope="module")
def definition() -> dict:
    return json.loads(RULE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rule_set(definition) -> rules.RuleSet:
    return rules.parse(definition)


def run(rule_set, gross, head=False, kids=()):
    return calc.payslip(calc.PayslipInput(Decimal(gross), head, tuple(kids)), rule_set)


def line(slip: calc.Payslip, code: str) -> Decimal:
    return next(item.amount for item in slip.lines if item.code == code)


@pytest.mark.parametrize(
    ("gross", "head", "kids", "cnss", "tax", "css", "net", "employer_cnss", "cost"),
    [
        (
            "2000",
            True,
            ["child", "child"],
            "193.600",
            "253.683",
            "7.990",
            "1544.727",
            "341.400",
            "2341.400",
        ),
        (
            "3500",
            True,
            ["child", "child"],
            "338.800",
            "670.279",
            "14.764",
            "2476.157",
            "597.450",
            "4097.450",
        ),
        ("400", False, [], "38.720", "0.000", "0.000", "361.280", "68.280", "468.280"),
        ("10000", True, [], "968.000", "2931.967", "44.202", "6055.831", "1707.000", "11707.000"),
    ],
)
def test_hand_checked_payslips(
    rule_set, gross, head, kids, cnss, tax, css, net, employer_cnss, cost
):
    slip = run(rule_set, gross, head, kids)
    assert slip.employee_deductions == Decimal(cnss)
    assert slip.income_tax == Decimal(tax)
    assert slip.solidarity == Decimal(css)
    assert slip.net_pay == Decimal(net)
    assert line(slip, "CNSS_EMPLOYER") == Decimal(employer_cnss)
    assert slip.employer_cost == Decimal(cost)


def test_working_values_show_each_step(rule_set):
    slip = run(rule_set, "2000", True, ["child", "child"])
    assert slip.working == {
        "monthly_taxable": Decimal("1806.400"),
        "annual_taxable": Decimal("21676.800"),
        "professional_expenses": Decimal("2000"),
        "family_deductions": Decimal("500"),
        "annual_net_taxable": Decimal("19176.800"),
    }


@pytest.mark.parametrize("gross", ["120.500", "999.999", "1800", "2750.125", "5000", "18000"])
def test_lines_always_add_up_to_net_pay(rule_set, gross):
    slip = run(rule_set, gross, True, ["child"])
    earned = sum(i.amount for i in slip.lines if i.kind == calc.EARNING)
    taken = sum(i.amount for i in slip.lines if i.kind in {calc.DEDUCTION, calc.TAX})
    assert earned - taken == slip.net_pay


def test_net_is_below_gross_and_rises_with_gross(rule_set):
    previous = Decimal(0)
    for gross in range(300, 12001, 300):
        slip = run(rule_set, str(gross))
        assert 0 < slip.net_pay < Decimal(gross)
        assert slip.net_pay > previous
        previous = slip.net_pay


def test_same_input_gives_identical_output(rule_set):
    assert run(rule_set, "2345.678", True, ["child"]) == run(rule_set, "2345.678", True, ["child"])


def test_expenses_are_capped(rule_set):
    slip = run(rule_set, "3500", False, [])
    assert slip.working["professional_expenses"] == Decimal("2000")
    low = run(rule_set, "1000", False, [])
    assert low.working["professional_expenses"] == low.working["annual_taxable"] * Decimal("0.10")


def test_only_the_first_four_children_count(rule_set):
    four = run(rule_set, "3000", True, ["child"] * 4)
    six = run(rule_set, "3000", True, ["child"] * 6)
    assert four == six
    assert four.working["family_deductions"] == Decimal("700")


def test_student_and_disabled_children_use_their_own_amounts(rule_set):
    slip = run(rule_set, "3000", False, ["student", "disabled", "child"])
    assert slip.working["family_deductions"] == Decimal("2300")


def test_solidarity_levy_is_skipped_within_the_exempt_amount(rule_set):
    low = run(rule_set, "400")
    assert low.solidarity == Decimal("0.000")
    assert low.income_tax == Decimal("0.000")


def test_net_taxable_never_goes_below_zero(rule_set):
    slip = run(rule_set, "50", True, ["child"] * 4)
    assert slip.working["annual_net_taxable"] == Decimal(0)
    assert slip.income_tax == Decimal("0.000")


def test_income_tax_follows_the_brackets_at_their_edges(rule_set):
    for annual, expected in [
        ("5000", "0"),
        ("10000", "750"),
        ("20000", "3250"),
        ("70000", "20750"),
    ]:
        assert calc._income_tax_annual(rule_set, Decimal(annual)) == Decimal(expected)


def test_ceiling_limits_the_cnss_base(definition):
    capped = copy.deepcopy(definition)
    capped["contributions"]["cnss_monthly_ceiling"] = "1000"
    slip = run(rules.parse(capped), "3000")
    assert line(slip, "CNSS_EMPLOYEE") == Decimal("96.800")
    assert line(slip, "CNSS_EMPLOYER") == Decimal("170.700")


def test_employer_charges_add_to_employer_cost_only(definition):
    charged = copy.deepcopy(definition)
    charged["employer_charges"] = [{"code": "TFP", "label": "Training tax", "rate": "0.01"}]
    base = run(rules.parse(definition), "2000", True, ["child", "child"])
    more = run(rules.parse(charged), "2000", True, ["child", "child"])
    assert more.net_pay == base.net_pay
    assert more.employer_cost == base.employer_cost + Decimal("20.000")


def test_bad_input_is_refused(rule_set):
    with pytest.raises(calc.PayslipInvalid):
        run(rule_set, "0")
    with pytest.raises(calc.PayslipInvalid):
        run(rule_set, "-5")
    with pytest.raises(calc.PayslipInvalid):
        run(rule_set, "2000", False, ["pet"])


def test_a_rule_set_without_a_disabled_child_value_refuses_to_guess(definition):
    partial = copy.deepcopy(definition)
    partial["family"]["disabled_child"] = None
    with pytest.raises(calc.PayslipInvalid):
        run(rules.parse(partial), "2000", False, ["disabled"])


def test_rule_set_hash_changes_with_any_value(definition):
    changed = copy.deepcopy(definition)
    changed["css"]["rate"] = "0.01"
    assert rules.parse(definition).definition_hash != rules.parse(changed).definition_hash
    assert rules.parse(definition).definition_hash == rules.parse(definition).definition_hash


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["contributions"].update(cnss_employee_rate="1.5"),
        lambda d: d["irpp_brackets"].reverse(),
        lambda d: d["irpp_brackets"].pop(),
        lambda d: d["irpp_brackets"][0].update(up_to="not a number"),
        lambda d: d.update(valid_to="2025-01-01"),
        lambda d: d.pop("css"),
        lambda d: d["family"].update(max_children=-1),
        lambda d: d.update(employer_charges=[{"code": "A", "label": "a", "rate": "0.1"}] * 2),
    ],
)
def test_malformed_rule_sets_are_rejected(definition, mutate):
    broken = copy.deepcopy(definition)
    mutate(broken)
    with pytest.raises(rules.RuleSetInvalid):
        rules.parse(broken)


def test_exactly_one_rule_set_must_apply(definition, rule_set):
    later = copy.deepcopy(definition)
    later.update(id="later", valid_from="2026-07-01")
    overlapping = rules.parse(later)
    assert rules.select([rule_set], date(2026, 3, 1)).id == rule_set.id
    with pytest.raises(rules.RuleSetUnavailable):
        rules.select([rule_set], date(2025, 12, 31))
    with pytest.raises(rules.RuleSetUnavailable):
        rules.select([rule_set, overlapping], date(2026, 8, 1))


def test_the_demo_rule_set_is_marked_as_unverified(rule_set):
    assert rule_set.is_demo
    assert "UNVERIFIED" in rule_set.source_ref


def test_calc_is_pure_and_uses_no_floats():
    tree = ast.parse(CALC_FILE.read_text(encoding="utf-8"))
    allowed = {
        "dataclasses",
        "decimal",
        "packs.finance.payroll.rules",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= allowed, f"calc.py imports {imported - allowed}"
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        assert not (isinstance(node, ast.Name) and node.id == "float")
