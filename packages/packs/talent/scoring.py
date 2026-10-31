"""The ranking formula. Pure arithmetic: no database, no model, no identity, no randomness.

    score = sum(weight x value) over the job's criteria, with weights summing to 1
    value = the strongest evidence signal for that criterion, from 0 to 1

Direct evidence      0.60 + 0.40 x min(1, stated years / required years)
                     Found in the CV's visible text. Years are stated in a verified quote,
                     or computed from dated roles that really name the skill.
Listed only          0.30
                     Named in a bare keyword list, with no stated or dated experience.
                     Stuffing a CV with keywords earns this much and no more.
Related skill        0.40 x relation strength
                     For example Docker counts partly toward Kubernetes.
Semantic similarity  0.35 x (similarity - 0.45) / (0.85 - 0.45), limited to 0 to 0.35
                     Similar wording with no exact term. Deliberately worth less than direct proof.
Human override       The recruiter's value, recorded with a reason.

Candidates who meet every must-have rank above those who don't. Nobody is removed: the recruiter
sees everyone and decides. Ties break on the document's content hash, so the order never
depends on upload order or on who the person is.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from kernel.explain import Factor, ScoreResult, register_scorer

SCORER = "talent.rubric"
SCORER_VERSION = "1"

DIRECT_BASE = Decimal("0.60")
LISTED_VALUE = Decimal("0.30")
DIRECT_YEARS_MAX = Decimal("0.40")
RELATED_MAX = Decimal("0.40")
SEMANTIC_MAX = Decimal("0.35")
SEMANTIC_LOW = Decimal("0.45")
SEMANTIC_HIGH = Decimal("0.85")
MUST_HAVE_RELATED_STRENGTH = Decimal("0.80")
MUST_HAVE_OVERRIDE_VALUE = Decimal("0.60")
FOUR_PLACES = Decimal("0.0001")


def _round(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def criterion_value(criterion: dict[str, Any], signal: dict[str, Any]) -> Decimal:
    override = signal.get("override")
    if override is not None:
        return _round(min(Decimal(1), max(Decimal(0), Decimal(str(override)))))

    candidates = [Decimal(0)]
    if signal.get("listed"):
        candidates.append(LISTED_VALUE)
    elif signal.get("direct"):
        required = Decimal(str(criterion.get("required_years") or 0))
        years = signal.get("years")
        if required == 0:
            candidates.append(Decimal(1))
        elif years is None:
            candidates.append(DIRECT_BASE)
        else:
            ratio = min(Decimal(1), Decimal(str(years)) / required)
            candidates.append(DIRECT_BASE + DIRECT_YEARS_MAX * ratio)
    related = signal.get("related")
    if related is not None:
        candidates.append(RELATED_MAX * Decimal(str(related)))
    similarity = signal.get("similarity")
    if similarity is not None:
        distance = (Decimal(str(similarity)) - SEMANTIC_LOW) / (SEMANTIC_HIGH - SEMANTIC_LOW)
        candidates.append(SEMANTIC_MAX * min(Decimal(1), max(Decimal(0), distance)))
    return _round(max(candidates))


def meets_must_have(criterion: dict[str, Any], signal: dict[str, Any]) -> bool:
    if not criterion.get("must_have"):
        return True
    if signal.get("override") is not None:
        return Decimal(str(signal["override"])) >= MUST_HAVE_OVERRIDE_VALUE
    if signal.get("direct") and not signal.get("listed"):
        return True
    related = signal.get("related")
    return related is not None and Decimal(str(related)) >= MUST_HAVE_RELATED_STRENGTH


@register_scorer(SCORER, SCORER_VERSION)
def score(inputs: dict[str, Any]) -> ScoreResult:
    factors = []
    for criterion in inputs["criteria"]:
        weight = Decimal(str(criterion["weight"]))
        value = criterion_value(criterion, inputs["signals"].get(criterion["id"], {}))
        factors.append(
            Factor(
                key=criterion["id"],
                label=criterion["label"],
                weight=weight,
                value=value,
                contribution=weight * value,
            )
        )
    return ScoreResult(score=sum((f.contribution for f in factors), Decimal(0)), factors=factors)


def missing_must_haves(inputs: dict[str, Any]) -> list[str]:
    return [
        criterion["label"]
        for criterion in inputs["criteria"]
        if not meets_must_have(criterion, inputs["signals"].get(criterion["id"], {}))
    ]


@dataclass(frozen=True)
class Ranked:
    key: str
    score: Decimal
    meets_must_haves: bool
    tiebreak: str
    rank: int = 0


def order_key(score_value: Decimal, meets: bool, tiebreak: str) -> tuple:
    return (not meets, -score_value, tiebreak)


def rank_all(items: list[Ranked]) -> list[Ranked]:
    ordered = sorted(items, key=lambda i: order_key(i.score, i.meets_must_haves, i.tiebreak))
    return [
        Ranked(i.key, i.score, i.meets_must_haves, i.tiebreak, position)
        for position, i in enumerate(ordered, start=1)
    ]


def rank_if(items: list[Ranked], key: str, new_score: Decimal, new_meets: bool) -> int:
    """Where this candidate would land with a different score, others unchanged."""
    changed = [
        Ranked(i.key, new_score, new_meets, i.tiebreak) if i.key == key else i for i in items
    ]
    return next(i.rank for i in rank_all(changed) if i.key == key)
