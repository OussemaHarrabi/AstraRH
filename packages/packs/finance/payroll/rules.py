"""Payroll rule sets: read from data, checked, hashed. No database, no clock, no model.

A rule set holds every rate, bracket and deduction the calculation uses, so a payslip can name
exactly which rules produced it and be recomputed later. Values are strings in the data and become
Decimal here, never float.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from kernel.canonical import payload_hash


class RuleSetInvalid(ValueError):
    pass


class RuleSetUnavailable(ValueError):
    """No rule set, or more than one, applies on that day. Calculation refuses to guess."""


@dataclass(frozen=True)
class Bracket:
    up_to: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class FamilyRules:
    head_of_family: Decimal
    child: Decimal
    student_child: Decimal
    disabled_child: Decimal | None
    max_children: int


@dataclass(frozen=True)
class EmployerCharge:
    code: str
    label: str
    rate: Decimal


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: int
    jurisdiction: str
    valid_from: date
    valid_to: date | None
    is_demo: bool
    source_ref: str
    places: int
    cnss_employee_rate: Decimal
    cnss_employer_rate: Decimal
    cnss_monthly_ceiling: Decimal | None
    professional_expenses_rate: Decimal
    professional_expenses_cap_annual: Decimal
    family: FamilyRules
    brackets: tuple[Bracket, ...]
    css_rate: Decimal
    css_exempt_up_to: Decimal
    employer_charges: tuple[EmployerCharge, ...]
    definition_hash: str

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


def _decimal(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - any bad literal is a data error
        raise RuleSetInvalid(f"{name}: {value!r} is not a number") from exc


def _rate(value: Any, name: str) -> Decimal:
    number = _decimal(value, name)
    if not Decimal(0) <= number <= Decimal(1):
        raise RuleSetInvalid(f"{name}: a rate must be between 0 and 1, not {number}")
    return number


def _amount(value: Any, name: str) -> Decimal:
    number = _decimal(value, name)
    if number < 0:
        raise RuleSetInvalid(f"{name}: must not be negative")
    return number


def _optional_amount(value: Any, name: str) -> Decimal | None:
    return None if value is None else _amount(value, name)


def _brackets(raw: list[dict[str, Any]]) -> tuple[Bracket, ...]:
    if not raw:
        raise RuleSetInvalid("irpp_brackets: at least one bracket is needed")
    brackets = []
    previous = Decimal(0)
    for index, item in enumerate(raw):
        last = index == len(raw) - 1
        up_to = None if item.get("up_to") is None else _amount(item["up_to"], "bracket up_to")
        if last != (up_to is None):
            raise RuleSetInvalid("irpp_brackets: only the last bracket has no upper limit")
        if up_to is not None and up_to <= previous:
            raise RuleSetInvalid("irpp_brackets: limits must increase")
        brackets.append(Bracket(up_to, _rate(item["rate"], "bracket rate")))
        previous = up_to if up_to is not None else previous
    return tuple(brackets)


def parse(definition: dict[str, Any]) -> RuleSet:
    try:
        valid_from = date.fromisoformat(definition["valid_from"])
        valid_to = definition.get("valid_to")
        valid_to = date.fromisoformat(valid_to) if valid_to else None
        if valid_to is not None and valid_to < valid_from:
            raise RuleSetInvalid("valid_to is before valid_from")
        contributions = definition["contributions"]
        expenses = definition["professional_expenses"]
        family = definition["family"]
        css = definition["css"]
        places = int(definition.get("rounding_places", 3))
        if not 0 <= places <= 6:
            raise RuleSetInvalid("rounding_places must be between 0 and 6")
        charges = tuple(
            EmployerCharge(c["code"], c["label"], _rate(c["rate"], f"charge {c['code']}"))
            for c in definition.get("employer_charges", [])
        )
        if len({c.code for c in charges}) != len(charges):
            raise RuleSetInvalid("employer_charges: codes must be unique")
        max_children = int(family["max_children"])
        if max_children < 0:
            raise RuleSetInvalid("family.max_children must not be negative")
        return RuleSet(
            id=str(definition["id"]),
            version=int(definition["version"]),
            jurisdiction=str(definition["jurisdiction"]),
            valid_from=valid_from,
            valid_to=valid_to,
            is_demo=bool(definition.get("is_demo", True)),
            source_ref=str(definition.get("source_ref", "")),
            places=places,
            cnss_employee_rate=_rate(contributions["cnss_employee_rate"], "cnss_employee_rate"),
            cnss_employer_rate=_rate(contributions["cnss_employer_rate"], "cnss_employer_rate"),
            cnss_monthly_ceiling=_optional_amount(
                contributions.get("cnss_monthly_ceiling"), "cnss_monthly_ceiling"
            ),
            professional_expenses_rate=_rate(expenses["rate"], "professional_expenses.rate"),
            professional_expenses_cap_annual=_amount(expenses["cap_annual"], "cap_annual"),
            family=FamilyRules(
                head_of_family=_amount(family["head_of_family"], "head_of_family"),
                child=_amount(family["child"], "child"),
                student_child=_amount(family["student_child"], "student_child"),
                disabled_child=_optional_amount(family.get("disabled_child"), "disabled_child"),
                max_children=max_children,
            ),
            brackets=_brackets(definition["irpp_brackets"]),
            css_rate=_rate(css["rate"], "css.rate"),
            css_exempt_up_to=_amount(css["exempt_up_to"], "css.exempt_up_to"),
            employer_charges=charges,
            definition_hash=payload_hash(definition),
        )
    except RuleSetInvalid:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RuleSetInvalid(f"Rule set is incomplete or malformed: {exc!r}") from exc


def select(rule_sets: Iterable[RuleSet], day: date) -> RuleSet:
    """The one rule set in force on a day. Zero or several is an error, never a default."""
    found = [r for r in rule_sets if r.covers(day)]
    if not found:
        raise RuleSetUnavailable(f"No rule set is in force on {day.isoformat()}")
    if len(found) > 1:
        ids = ", ".join(sorted(r.id for r in found))
        raise RuleSetUnavailable(f"Several rule sets overlap on {day.isoformat()}: {ids}")
    return found[0]
