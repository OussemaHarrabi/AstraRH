"""The cross-encoder reranker: policy search order, CV job match, and what happens without it."""

from decimal import Decimal

import pytest
from conftest import as_role, role_url

from kernel import knowledge, ml_client
from kernel.db import tenant_session
from kernel.errors import ProviderUnavailable
from kernel.explain import rescore
from packs.talent import scoring

SECTIONS = (
    "# Sick leave\nA medical certificate is needed from the third day of sick leave.\n\n"
    "# Annual leave\nEmployees earn 22 working days of paid annual leave per year.\n\n"
    "# Remote work\nRemote work is allowed two days a week with the manager's agreement.\n"
)


@pytest.fixture
def leave_policy(tenant, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", role_url("worker"))
    with as_role("worker"), tenant_session(tenant) as session:
        knowledge.ingest_document(session, tenant, "L", "Leave policy", SECTIONS)
    return tenant


def test_the_reranker_scores_the_passage_that_answers_the_question_highest():
    scores = ml_client.rerank(
        "How many days of annual leave do I get each year?",
        [
            "A medical certificate is needed from the third day of sick leave.",
            "Employees earn 22 working days of paid annual leave per year.",
            "Les congés payés annuels sont de 22 jours ouvrables par an.",
        ],
    )
    assert len(scores) == 3 and all(0 <= s <= 1 for s in scores)
    assert scores[1] > scores[0] and scores[2] > scores[0]


def test_the_reranker_is_deterministic():
    query, passages = "remote work", ["Remote work is allowed two days a week."]
    assert ml_client.rerank(query, passages) == ml_client.rerank(query, passages)


def test_policy_search_puts_the_reranked_answer_first(leave_policy):
    with as_role("worker"), tenant_session(leave_policy) as session:
        hits = knowledge.search(session, "How many days of annual leave per year?", ["employee"])
    assert hits[0].section == "Annual leave"
    assert hits[0].relevance is not None
    assert hits[0].as_json("C1")["relevance"] == str(hits[0].relevance)


def test_policy_search_keeps_working_if_the_reranker_is_down(leave_policy, monkeypatch):
    def down(*_args, **_kwargs):
        raise ProviderUnavailable("down")

    monkeypatch.setattr(knowledge.ml_client, "rerank", down)
    with as_role("worker"), tenant_session(leave_policy) as session:
        hits = knowledge.search(session, "annual leave days per year", ["employee"])
    assert hits and all(hit.relevance is None for hit in hits)
    assert any(hit.section == "Annual leave" for hit in hits)


def test_job_match_includes_the_reranker_when_it_ran():
    with_rerank = {"dense": "0.6", "lexical": "0.5", "rerank": "0.9"}
    without = {"dense": "0.6", "lexical": "0.5", "rerank": None}
    assert scoring.job_match_value(with_rerank) == Decimal("0.6600")  # .24 + .15 + .27
    assert scoring.job_match_value(without) == Decimal("0.5500")  # .30 + .25


def test_rankings_made_before_the_reranker_replay_to_the_same_score():
    inputs = {
        "criteria": [{"id": "c1", "label": "Python", "weight": "1", "must_have": False}],
        "signals": {"c1": {"direct": True}},
        "match": {"dense": "0.7", "lexical": "0.4"},
    }
    old = rescore(scoring.SCORER, "2", inputs)
    new = rescore(scoring.SCORER, scoring.SCORER_VERSION, inputs)
    assert old.score == new.score == Decimal("0.70") + Decimal("0.30") * Decimal("0.55")
