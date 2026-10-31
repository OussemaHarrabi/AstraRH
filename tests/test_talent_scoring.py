"""The ranking formula and identity separation. Pure functions: no database, no model."""

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from packs.talent import scoring
from packs.talent.blind import BLIND_TOKEN, blind
from packs.talent.signals import (
    chunk_text,
    compute_signal,
    find_sentence,
    role_years,
    verified_years,
)

PYTHON = {
    "id": "python",
    "label": "Python",
    "weight": "0.60",
    "must_have": True,
    "required_years": 4,
}
SOFT = {
    "id": "soft",
    "label": "Mentoring",
    "weight": "0.40",
    "must_have": False,
    "required_years": 0,
}


def inputs(python: dict, soft: dict | None = None) -> dict:
    return {"criteria": [PYTHON, SOFT], "signals": {"python": python, "soft": soft or {}}}


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ({"direct": True, "years": "4"}, "1.0000"),
        ({"direct": True, "years": "8"}, "1.0000"),
        ({"direct": True, "years": "2"}, "0.8000"),
        ({"direct": True, "years": None}, "0.6000"),
        ({"direct": False, "related": "0.5"}, "0.2000"),
        ({"direct": False, "similarity": "0.85"}, "0.3500"),
        ({"direct": False, "similarity": "0.65"}, "0.1750"),
        ({"direct": False, "similarity": "0.40"}, "0.0000"),
        ({"direct": False, "similarity": "0.99"}, "0.3500"),
        ({}, "0.0000"),
        ({"direct": False, "override": "0.7"}, "0.7000"),
        ({"direct": True, "years": "9", "override": "0.1"}, "0.1000"),
    ],
)
def test_value_formula(signal, expected):
    assert scoring.criterion_value(PYTHON, signal) == Decimal(expected)


def test_direct_proof_always_beats_similar_wording_alone():
    best_semantic = scoring.criterion_value(PYTHON, {"direct": False, "similarity": "1"})
    weakest_direct = scoring.criterion_value(PYTHON, {"direct": True, "years": None})
    assert weakest_direct > best_semantic


def test_strongest_signal_wins_and_signals_do_not_add_up():
    both = {"direct": True, "years": None, "related": "1", "similarity": "0.99"}
    assert scoring.criterion_value(PYTHON, both) == Decimal("0.6000")


def test_soft_criterion_with_no_required_years_counts_fully_when_present():
    assert scoring.criterion_value(SOFT, {"direct": True}) == Decimal(1)


def test_score_is_the_exact_sum_of_weight_times_value():
    result = scoring.score(inputs({"direct": True, "years": "2"}, {"similarity": "0.65"}))
    assert result.score == Decimal("0.60") * Decimal("0.8000") + Decimal("0.40") * Decimal("0.1750")
    assert sum(f.contribution for f in result.factors) == result.score


def test_score_never_exceeds_one():
    perfect = inputs({"direct": True, "years": "50"}, {"direct": True})
    assert scoring.score(perfect).score == Decimal(1)


def test_scoring_ignores_anything_outside_the_formula():
    """Identity can't influence the result, even if it is passed in by mistake."""
    base = inputs({"direct": True, "years": "2"})
    with_identity = {**base, "name": "Someone", "gender": "x", "age": 50}
    assert scoring.score(base).score == scoring.score(with_identity).score


def test_same_inputs_always_give_the_same_score():
    base = inputs({"direct": True, "years": "3"}, {"similarity": "0.6123"})
    assert len({scoring.score(base).score for _ in range(50)}) == 1


def test_must_haves_rank_above_a_higher_score_without_them():
    items = [
        scoring.Ranked("high_but_missing", Decimal("0.9"), False, "a"),
        scoring.Ranked("lower_but_qualified", Decimal("0.5"), True, "b"),
    ]
    assert [i.key for i in scoring.rank_all(items)] == ["lower_but_qualified", "high_but_missing"]


def test_must_have_needs_real_proof_not_similar_wording():
    assert scoring.meets_must_have(PYTHON, {"direct": True})
    assert not scoring.meets_must_have(PYTHON, {"direct": False, "similarity": "0.99"})
    assert not scoring.meets_must_have(PYTHON, {"direct": False, "related": "0.5"})
    assert scoring.meets_must_have(PYTHON, {"direct": False, "related": "0.8"})


def test_ties_break_on_content_hash_regardless_of_input_order():
    a = scoring.Ranked("a", Decimal("0.5"), True, "1111")
    b = scoring.Ranked("b", Decimal("0.5"), True, "2222")
    assert [i.key for i in scoring.rank_all([a, b])] == [i.key for i in scoring.rank_all([b, a])]
    assert scoring.rank_all([b, a])[0].key == "a"


def test_rank_if_predicts_the_real_rank():
    items = scoring.rank_all(
        [
            scoring.Ranked("a", Decimal("0.9"), True, "1"),
            scoring.Ranked("b", Decimal("0.7"), True, "2"),
            scoring.Ranked("c", Decimal("0.5"), True, "3"),
        ]
    )
    assert scoring.rank_if(items, "c", Decimal("0.8"), True) == 2
    changed = [i if i.key != "c" else scoring.Ranked("c", Decimal("0.8"), True, "3") for i in items]
    assert next(i.rank for i in scoring.rank_all(changed) if i.key == "c") == 2


def test_scoring_module_cannot_reach_identity_or_models():
    """The guarantee is structural: this file can't import a database table or a model client."""
    source = Path(scoring.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"dataclasses", "decimal", "typing", "kernel.explain"}


# ----- Evidence signals -----


def claim(name, years, quote):
    return {"name": name, "years": years, "evidence": {"quote": quote}}


def test_stated_years_must_appear_in_the_verified_quote():
    assert verified_years(claim("Python", 5, "5 years of Python")) == Decimal(5)
    assert verified_years(claim("Python", 9, "5 years of Python")) is None
    assert verified_years(claim("Python", None, "Python developer")) is None
    assert verified_years(claim("Python", 2.5, "2,5 ans de Python")) == Decimal("2.5")


KEYWORD_CRITERION = {**PYTHON, "keywords": ["python"]}


def role(start, end, skills, quote=None):
    return {
        "title": "Engineer",
        "start_year": start,
        "end_year": end,
        "skills": skills,
        "evidence": {"quote": quote or f"Engineer, {start} - {end or 'present'}"},
    }


TEXT = "Built services in Python."


def test_years_are_computed_from_dated_roles():
    profile = {"as_of_year": 2026, "roles": [role(2019, 2024, ["Python"])]}
    assert role_years(profile, ["python"], TEXT) == Decimal(5)


def test_present_uses_the_year_frozen_at_read_time():
    profile = {"as_of_year": 2026, "roles": [role(2020, None, ["Python"])]}
    assert role_years(profile, ["python"], TEXT) == Decimal(6)


def test_overlapping_roles_count_once():
    profile = {
        "as_of_year": 2026,
        "roles": [role(2015, 2020, ["Python"]), role(2018, 2022, ["Python"])],
    }
    assert role_years(profile, ["python"], TEXT) == Decimal(7)


def test_separate_roles_add_up():
    profile = {
        "as_of_year": 2026,
        "roles": [role(2010, 2012, ["Python"]), role(2020, 2023, ["Python"])],
    }
    assert role_years(profile, ["python"], TEXT) == Decimal(5)


def test_dates_not_in_the_quote_are_not_believed():
    fake = role(2000, 2024, ["Python"], quote="Engineer, 2023 - 2024")
    assert role_years({"as_of_year": 2026, "roles": [fake]}, ["python"], TEXT) is None


def test_a_skill_the_cv_never_mentions_is_not_believed():
    profile = {"as_of_year": 2026, "roles": [role(2010, 2024, ["Python"])]}
    assert role_years(profile, ["python"], "A career in sales.") is None


def test_role_for_another_skill_does_not_count():
    profile = {"as_of_year": 2026, "roles": [role(2010, 2024, ["Java"])]}
    assert role_years(profile, ["python"], TEXT) is None


def test_computed_years_lift_a_dated_cv_to_full_value():
    profile = {"as_of_year": 2026, "roles": [role(2019, 2024, ["Python"])]}
    outcome = compute_signal(KEYWORD_CRITERION, profile, TEXT, None, [], None, "cv")
    assert outcome.signal["years"] == "5"
    assert scoring.criterion_value(PYTHON, outcome.signal) == Decimal(1)


def test_keyword_stuffing_earns_no_more_than_one_mention():
    once = compute_signal(KEYWORD_CRITERION, {}, "Python.", None, [], None, "cv")
    stuffed = compute_signal(KEYWORD_CRITERION, {}, "Python " * 500, None, [], None, "cv")
    assert once.signal == stuffed.signal


def test_keyword_found_without_stated_years_gets_the_base_value_only():
    outcome = compute_signal(KEYWORD_CRITERION, {}, "Keywords: Python.", None, [], None, "cv")
    assert outcome.signal["direct"] is True
    assert outcome.signal["years"] is None
    assert scoring.criterion_value(PYTHON, outcome.signal) == Decimal("0.6000")


STUFFED = "Keywords: Python PostgreSQL FastAPI Docker Kubernetes."
ALL_KEYWORDS = ["python", "postgresql", "fastapi", "docker", "kubernetes"]


def test_a_bare_keyword_list_earns_the_listed_tier_only():
    outcome = compute_signal(KEYWORD_CRITERION, {}, STUFFED, None, [], None, "cv", ALL_KEYWORDS)
    assert outcome.signal["listed"] is True
    assert outcome.evidence[0]["kind"] == "listed"
    assert scoring.criterion_value(PYTHON, outcome.signal) == Decimal("0.3000")


def test_a_keyword_list_cannot_satisfy_a_must_have():
    assert not scoring.meets_must_have(PYTHON, {"direct": True, "listed": True})


def test_the_same_line_with_dated_experience_is_not_a_list():
    profile = {"as_of_year": 2026, "roles": [role(2019, 2024, ["Python"])]}
    outcome = compute_signal(
        KEYWORD_CRITERION, profile, STUFFED, None, [], None, "cv", ALL_KEYWORDS
    )
    assert "listed" not in outcome.signal
    assert scoring.criterion_value(PYTHON, outcome.signal) == Decimal(1)


def test_keywords_do_not_match_inside_other_words():
    assert find_sentence("I worked on Pythonic things and javascripts.", ["python"]) is None
    assert find_sentence("Scripting with C++ daily.", ["c"]) is None
    assert find_sentence("I know sql.", ["SQL"]) == "I know sql."


def test_verified_years_win_over_an_unverified_claim():
    profile = {
        "skills": [
            claim("Python", 20, "Python everywhere"),
            claim("Python", 5, "5 years of Python"),
        ]
    }
    outcome = compute_signal(KEYWORD_CRITERION, profile, "", None, [], None, "cv")
    assert outcome.signal["years"] == "5"
    assert outcome.evidence[0]["quote"] == "5 years of Python"


def test_related_skill_used_when_no_direct_proof():
    criterion = {"id": "k8s", "label": "Kubernetes", "keywords": ["kubernetes"]}
    related = [{"name": "Docker", "strength": "0.5", "keywords": ["Docker"]}]
    outcome = compute_signal(criterion, {}, "Shipped with Docker.", None, related, None, "cv")
    assert outcome.signal["related"] == "0.5"
    assert outcome.evidence[0]["kind"] == "related:Docker"


def test_chunks_group_lines_and_stay_readable():
    text = "\n".join(f"Line number {i} of the CV." for i in range(60))
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert "\n".join(chunks) == text


# ----- Identity separation -----

CV = """Yasmine Trabelsi
Senior Backend Engineer
yasmine.trabelsi@mail.example.test | +216 67 511 641
Date of birth: 12/05/1995
Nationality: Tunisian
Marital status: Married
Address: 12 Rue de Carthage, Tunis
Summary
Backend engineer. Yasmine led 3 projects.
6 years of Python.
References: Y. Trabelsi and yasmine@mail.example.test"""


def test_blind_extracts_contact_details_for_separate_storage():
    result = blind(CV)
    assert result.name == "Yasmine Trabelsi"
    assert result.email == "yasmine.trabelsi@mail.example.test"
    assert result.phone == "+216 67 511 641"


@pytest.mark.parametrize(
    "secret",
    [
        "Yasmine",
        "Trabelsi",
        "mail.example.test",
        "67 511",
        "12/05/1995",
        "Tunisian",
        "Married",
        "Carthage",
    ],
)
def test_blind_text_contains_no_identity(secret):
    assert secret.lower() not in blind(CV).text.lower()


def test_blind_keeps_the_job_facts():
    text = blind(CV).text
    assert "6 years of Python" in text
    assert BLIND_TOKEN in text
    assert blind(CV).removed_lines == 4


def test_two_people_with_the_same_cv_produce_identical_blind_text():
    other = (
        CV.replace("Yasmine", "Mohamed").replace("Trabelsi", "Sassi").replace("yasmine", "mohamed")
    )
    other = other.replace("trabelsi", "sassi")
    assert blind(CV).text == blind(other).text


def test_a_job_title_on_the_first_line_is_not_taken_for_a_name():
    assert blind("Senior Backend Engineer\n5 years of Python").name is None


def test_french_protected_lines_are_removed():
    text = "Nom Prenom\nNé le 3 mars 1990\nSituation familiale: mariée\nAdresse: Tunis\nPython"
    result = blind(text).text
    for secret in ("1990", "mariée", "Tunis"):
        assert secret not in result
