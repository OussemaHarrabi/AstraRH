"""Deterministic gap math for the journey pack.

No kernel imports, no LLM, no database. Every number here is reproducible and
unit-tested with hand-checked answers. The LLM may narrate these numbers; it may
never compute them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

LEVEL_MIN = 1
LEVEL_MAX = 4

# Severity is a weighted sum, not a product, so the factors sum exactly to the
# score and a DecisionRecord can replay it. See journey-design.md §6.1.
GAP_WEIGHT = Decimal("0.60")
MANDATORY_WEIGHT = Decimal("0.25")
REQUIREMENT_WEIGHT = Decimal("0.15")
HIGH_THRESHOLD = Decimal("0.70")
MEDIUM_THRESHOLD = Decimal("0.45")

# Evidence trust. Self-declaration is never sufficient alone.
SOURCE_TRUST: Mapping[str, Decimal] = {
    "assessment": Decimal("1.0"),
    "applied_evidence": Decimal("1.0"),
    "manager": Decimal("0.7"),
    "course": Decimal("0.6"),
    "inferred": Decimal("0.5"),
    "self": Decimal("0.2"),
}
SELF_ONLY_CAP = Decimal("0.25")


class InvalidLevel(ValueError):
    """A level outside the 1-4 scale."""


def _check_level(level: int) -> int:
    if not isinstance(level, int) or not LEVEL_MIN <= level <= LEVEL_MAX:
        raise InvalidLevel(f"level must be an int in {LEVEL_MIN}..{LEVEL_MAX}, got {level!r}")
    return level


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: Decimal, low: Decimal = Decimal("0"), high: Decimal = Decimal("1")) -> Decimal:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Evidence:
    """One signal behind a level. Weight is the signal's share in the confidence average."""

    kind: str
    weight: Decimal
    summary: str
    ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_TRUST:
            raise ValueError(f"unknown evidence kind {self.kind!r}")
        if _decimal(self.weight) < 0:
            raise ValueError("evidence weight must be >= 0")


@dataclass(frozen=True)
class Factor:
    """A DecisionRecord factor. `contribution` is exactly `weight * value`."""

    key: str
    label: str
    weight: Decimal
    value: Decimal

    @property
    def contribution(self) -> Decimal:
        return self.weight * self.value

    def validate(self) -> None:
        if self.weight * self.value != self.contribution:
            raise AssertionError(f"factor {self.key}: weight * value != contribution")


@dataclass(frozen=True)
class Severity:
    label: str
    score: Decimal
    factors: tuple[Factor, ...]


@dataclass(frozen=True)
class Assessment:
    current_level: int
    required_level: int
    gap: int
    severity: Severity
    confidence: Decimal
    evidence: tuple[Evidence, ...]
    message: str


@dataclass(frozen=True)
class CoursePath:
    items: tuple[Mapping[str, Any], ...]
    total_hours: Decimal
    total_cost_tnd: Decimal
    closes_gap: bool


@dataclass(frozen=True)
class ObservedDelta:
    value: Decimal | None
    label: str
    reason: str | None = None


def compute_gap(required_level: int, current_level: int) -> int:
    """`required - current`, floored at zero. Levels are 1-4."""
    required = _check_level(required_level)
    current = _check_level(current_level)
    return max(0, required - current)


def severity(
    required_level: int,
    current_level: int,
    *,
    mandatory: bool,
    weight: Any = 1,
    max_weight: Any = 1,
) -> Severity:
    """Weighted-sum severity on a 0..1 scale.

    score = 0.60 * (gap / required)
          + 0.25 * (1 if mandatory else 0)
          + 0.15 * (weight / max_weight)

    gap == 0 -> none / 0.0. High >= 0.70, medium >= 0.45, else low.
    """
    required = _check_level(required_level)
    current = _check_level(current_level)
    gap = max(0, required - current)
    if gap == 0:
        return Severity(label="none", score=Decimal("0"), factors=())

    max_w = _decimal(max_weight)
    if max_w <= 0:
        raise ValueError("max_weight must be > 0")
    weight_value = _decimal(weight) / max_w
    if weight_value < 0:
        raise ValueError("weight must be >= 0")
    weight_value = _clamp(weight_value)

    # 0.60 / required is exact for required in 1..4; value = gap keeps the
    # contribution exact and makes the factor explainable.
    factors = (
        Factor(
            key="gap",
            label="Gap against the role requirement",
            weight=GAP_WEIGHT / Decimal(required),
            value=Decimal(gap),
        ),
        Factor(
            key="mandatory",
            label="Mandatory requirement",
            weight=MANDATORY_WEIGHT,
            value=Decimal(1) if mandatory else Decimal(0),
        ),
        Factor(
            key="requirement_weight",
            label="Role-profile weight",
            weight=REQUIREMENT_WEIGHT,
            value=weight_value,
        ),
    )
    for factor in factors:
        factor.validate()
    score = sum((factor.contribution for factor in factors), Decimal("0"))
    if score >= HIGH_THRESHOLD:
        label = "high"
    elif score >= MEDIUM_THRESHOLD:
        label = "medium"
    else:
        label = "low"
    return Severity(label=label, score=score, factors=factors)


def confidence(evidence: Iterable[Evidence]) -> Decimal:
    """Weighted average of source trust. No evidence -> 0; self-only caps at 0.25."""
    signals = tuple(evidence)
    if not signals:
        return Decimal("0")
    total = sum((_decimal(item.weight) for item in signals), Decimal("0"))
    if total <= 0:
        return Decimal("0")
    score = sum((_decimal(item.weight) * SOURCE_TRUST[item.kind] for item in signals), Decimal("0"))
    score = _clamp(score / total)
    if all(item.kind == "self" for item in signals):
        score = min(score, SELF_ONLY_CAP)
    return score.quantize(Decimal("0.0001"))


def assess(
    skill: str,
    required_level: int,
    current_level: int,
    *,
    mandatory: bool,
    weight: Any = 1,
    max_weight: Any = 1,
    evidence: Iterable[Evidence] = (),
) -> Assessment:
    """The full deterministic assessment used by the Skill Gap Analyst."""
    signals = tuple(evidence)
    gap = compute_gap(required_level, current_level)
    sev = severity(
        required_level,
        current_level,
        mandatory=mandatory,
        weight=weight,
        max_weight=max_weight,
    )
    conf = confidence(signals)
    if not signals:
        message = f"No evidence found for {skill}. The role requires level {required_level}."
    elif gap == 0:
        message = f"{skill} meets the role requirement ({current_level}/{required_level})."
    else:
        message = (
            f"{skill} is at level {current_level}; the role requires {required_level}. "
            f"{len(signals)} evidence signal(s), confidence {conf}."
        )
    return Assessment(
        current_level=current_level,
        required_level=required_level,
        gap=gap,
        severity=sev,
        confidence=conf,
        evidence=signals,
        message=message,
    )


def priority(severity_score: Any, kpi_weight: Any = 1) -> Decimal:
    """Rank gaps by severity and the KPI they can move. Deterministic."""
    return (_decimal(severity_score) * _decimal(kpi_weight)).quantize(Decimal("0.0001"))


def course_path(
    courses: Iterable[Mapping[str, Any]],
    *,
    skill_id: str,
    required_level: int,
    current_level: int,
) -> CoursePath:
    """Order matching courses by level_gained -> hours -> cost -> id until the gap closes."""
    gap = compute_gap(required_level, current_level)
    if gap == 0:
        return CoursePath(
            items=(), total_hours=Decimal("0"), total_cost_tnd=Decimal("0"), closes_gap=True
        )

    matches = [
        course
        for course in courses
        if course.get("skill_id") == skill_id and int(course.get("level_gained", 0)) > 0
    ]
    matches.sort(
        key=lambda course: (
            int(course.get("level_gained", 0)),
            _decimal(course.get("hours", 0)),
            _decimal(course.get("cost_tnd", 0)),
            str(course.get("course_id", "")),
        )
    )
    chosen: list[Mapping[str, Any]] = []
    gained = 0
    hours = Decimal("0")
    cost = Decimal("0")
    for course in matches:
        chosen.append(course)
        gained += int(course.get("level_gained", 0))
        hours += _decimal(course.get("hours", 0))
        cost += _decimal(course.get("cost_tnd", 0))
        if gained >= gap:
            break
    return CoursePath(
        items=tuple(chosen),
        total_hours=hours,
        total_cost_tnd=cost,
        closes_gap=gained >= gap,
    )


def mentor_candidates(
    holders: Iterable[Mapping[str, Any]],
    *,
    required_level: int,
    learner_id: str,
    manager_id: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Internal experts at or above the requirement, excluding the learner and manager."""
    required = _check_level(required_level)
    rows = [
        holder
        for holder in holders
        if int(holder.get("level", 0)) >= required
        and str(holder.get("employee_id")) != learner_id
        and (manager_id is None or str(holder.get("employee_id")) != manager_id)
    ]
    rows.sort(key=lambda holder: (-int(holder.get("level", 0)), str(holder.get("employee_id"))))
    return tuple(rows)


def cost_per_closed_gap(total_cost_tnd: Any, closed_gaps: int) -> Decimal | None:
    """Money per verified closed gap; None when nothing closed (never divide by zero)."""
    if closed_gaps <= 0:
        return None
    return (_decimal(total_cost_tnd) / Decimal(closed_gaps)).quantize(Decimal("0.0001"))


def observed_delta(
    *,
    treated_baseline: Any,
    treated_post: Any,
    comparison_baseline: Any,
    comparison_post: Any,
    comparison_n: int,
) -> ObservedDelta:
    """Difference-in-differences. Refuses to compute when the comparison group is too small."""
    if comparison_n < 5:
        return ObservedDelta(
            value=None,
            label="insufficient_comparison_group",
            reason="comparison group has fewer than 5 people; no number is shown",
        )
    treated = _decimal(treated_post) - _decimal(treated_baseline)
    comparison = _decimal(comparison_post) - _decimal(comparison_baseline)
    return ObservedDelta(
        value=(treated - comparison).quantize(Decimal("0.0001")),
        label="observed",
        reason=None,
    )
