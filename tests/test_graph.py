"""Neo4j is a read model: it can be lost and rebuilt, and it holds nothing sensitive."""

from uuid import uuid4

import pytest
from conftest import as_role, make_proposal, make_user
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from kernel import events, graph, registry, trust
from kernel.db import tenant_session
from kernel.errors import GraphUnavailable, NotFound, ValidationFailed
from kernel.events.models import EventDelivery, EventOutbox
from kernel.graph import Projection

registry.install_graph_projections()


@events.event_type("test.skill.seen.v1")
class SkillSeen(BaseModel):
    person_id: str
    skill_id: str
    skill_name: str


graph.register_projection(
    Projection.model_validate(
        {
            "event": "test.skill.seen.v1",
            "nodes": [
                {"label": "Skill", "id": "$.skill_id", "props": {"name": "$.skill_name"}},
                {"label": "Person", "id": "$.person_id"},
            ],
            "edges": [
                {
                    "type": "HAS_SKILL",
                    "from": {"label": "Person", "id": "$.person_id"},
                    "to": {"label": "Skill", "id": "$.skill_id"},
                }
            ],
        }
    )
)


def clean_graph(tenant) -> None:
    with graph._get_driver().session() as session:
        session.run("MATCH (n {tenant_id: $t}) DETACH DELETE n", t=str(tenant))


@pytest.fixture(autouse=True)
def isolated_graph(tenant, other_tenant):
    yield
    clean_graph(tenant)
    clean_graph(other_tenant)


def publish_skill(tenant, person="p1", skill="s1", name="Python") -> None:
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(
            session, tenant, SkillSeen(person_id=person, skill_id=skill, skill_name=name)
        )
    with as_role("worker"):
        events.relay_once(tenant)


def counts(tenant) -> tuple[int, int]:
    with graph._get_driver().session() as session:
        nodes = session.run(
            "MATCH (n {tenant_id: $t}) RETURN count(n) AS c", t=str(tenant)
        ).single()
        edges = session.run(
            "MATCH (a {tenant_id: $t})-[r]->(b {tenant_id: $t}) RETURN count(r) AS c", t=str(tenant)
        ).single()
    return nodes["c"], edges["c"]


def test_event_projects_into_the_graph(tenant):
    publish_skill(tenant)
    result = graph.query(tenant, "skills_graph")
    assert {n["label"] for n in result["nodes"]} == {"Person", "Skill"}
    assert result["edges"] == [{"from": "p1", "to": "s1", "type": "HAS_SKILL"}]


def test_replaying_an_event_creates_no_duplicates(tenant):
    publish_skill(tenant)
    before = counts(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        event = session.scalars(select(EventOutbox)).first()
    graph.project_event(event)
    graph.project_event(event)
    assert counts(tenant) == before


def test_rebuild_restores_the_same_graph(tenant):
    publish_skill(tenant)
    publish_skill(tenant, person="p2", skill="s1")
    before = counts(tenant)
    clean_graph(tenant)
    assert counts(tenant) == (0, 0)
    with as_role("worker"), tenant_session(tenant) as session:
        assert graph.rebuild(session, tenant) == 2
    assert counts(tenant) == before


def test_queries_cannot_cross_tenants(tenant, other_tenant):
    publish_skill(tenant)
    publish_skill(other_tenant, person="p9", skill="s9", name="Secret")
    ids = {node["id"] for node in graph.query(tenant, "skills_graph")["nodes"]}
    assert ids == {"p1", "s1"}


def test_same_id_in_two_tenants_stays_separate(tenant, other_tenant):
    publish_skill(tenant, skill="same", name="Mine")
    publish_skill(other_tenant, skill="same", name="Theirs")
    names = [
        n["props"]["name"]
        for n in graph.query(tenant, "skills_graph")["nodes"]
        if n["label"] == "Skill"
    ]
    assert names == ["Mine"]


def test_malicious_text_stays_inert(tenant):
    attack = "x'}) DETACH DELETE n //"
    publish_skill(tenant, name=attack)
    other = "MATCH (n) DETACH DELETE n"
    publish_skill(tenant, person="p2", skill="s2", name=other)
    skills = {
        n["id"]: n["props"]["name"]
        for n in graph.query(tenant, "skills_graph")["nodes"]
        if n["label"] == "Skill"
    }
    assert skills == {"s1": attack, "s2": other}


@pytest.mark.parametrize(
    "spec",
    [
        {"event": "x", "nodes": [{"label": "Bad) DETACH DELETE n//", "id": "$.a"}]},
        {"event": "x", "nodes": [{"label": "Salary", "id": "$.a"}]},
        {"event": "x", "nodes": [{"label": "Case", "id": "$.a"}]},
        {"event": "x", "nodes": [{"label": "Person", "id": "$.a", "props": {"email": "$.e"}}]},
        {"event": "x", "nodes": [{"label": "Person", "id": "$.a", "props": {"salary": "$.s"}}]},
        {
            "event": "x",
            "edges": [
                {
                    "type": "X]->() DELETE",
                    "from": {"label": "A1", "id": "$.a"},
                    "to": {"label": "Bc", "id": "$.b"},
                }
            ],
        },
        {"event": "x"},
    ],
)
def test_unsafe_projections_are_refused(spec):
    with pytest.raises(ValidationError):
        Projection.model_validate(spec)


def test_only_named_queries_exist(tenant):
    with pytest.raises(NotFound):
        graph.query(tenant, "MATCH (n) RETURN n")


def test_a_query_must_filter_by_tenant():
    with pytest.raises(ValidationFailed):
        graph.register_query("unsafe", "MATCH (n) RETURN n")


def test_bus_factor_finds_single_holders(tenant):
    publish_skill(tenant, person="p1", skill="s1", name="Observability")
    publish_skill(tenant, person="p1", skill="s2", name="Python")
    publish_skill(tenant, person="p2", skill="s2", name="Python")
    rows = graph.query(tenant, "bus_factor")["rows"]
    assert rows == [{"skill_id": "s1", "skill": "Observability", "person_id": "p1"}]


def test_trust_flow_appears_in_the_agent_mesh_and_decision_chain(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, user.actor, proposal.id)
    with as_role("executor"):
        assert trust.execute(tenant, proposal.id, lambda a, p, k: "ref") == "succeeded"
    with as_role("worker"):
        events.relay_once(tenant)

    mesh = graph.query(tenant, "agent_mesh")
    types = {edge["type"] for edge in mesh["edges"]}
    assert {"APPROVED_BY", "EXECUTED", "EMITTED"} <= types
    labels = {node["label"] for node in mesh["nodes"]}
    assert {"Proposal", "Human", "Execution", "Event"} <= labels

    chain = graph.query(tenant, "decision_chain", id=str(proposal.decision_record_id))
    assert any(edge["type"] == "EXPLAINED_BY" for edge in chain["edges"])


def test_graph_holds_no_payload_or_quote_text(tenant):
    proposal = make_proposal(tenant, payload={"to": "secret@example.test", "body": "Private text"})
    with as_role("worker"):
        events.relay_once(tenant)
    assert proposal
    with graph._get_driver().session() as session:
        rows = session.run("MATCH (n {tenant_id: $t}) RETURN properties(n) AS p", t=str(tenant))
        text = " ".join(str(row["p"]) for row in rows)
    assert "secret@example.test" not in text
    assert "Private text" not in text


def test_neo4j_down_never_blocks_trust_or_other_consumers(tenant, monkeypatch):
    name = f"test.{uuid4().hex[:8]}.down.v1"

    @events.event_type(name)
    class Happened(BaseModel):
        value: int

    seen = []
    events.subscribe(name, f"test.alive.{name}")(lambda s, e: seen.append(1))

    def unavailable(event):
        raise GraphUnavailable("Down")

    monkeypatch.setattr(graph, "project_event", unavailable)

    user = make_user(tenant)
    proposal = make_proposal(tenant)
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, user.actor, proposal.id)
    with as_role("executor"):
        assert trust.execute(tenant, proposal.id, lambda a, p, k: "ref") == "succeeded"

    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(session, tenant, Happened(value=1))
    with as_role("worker"):
        events.relay_once(tenant)
    assert seen == [1]

    with as_role("worker"), tenant_session(tenant) as session:
        projector = session.scalars(
            select(EventDelivery).where(EventDelivery.consumer == graph.PROJECTOR_CONSUMER)
        ).all()
    assert projector
    assert all(d.status == "pending" and d.attempts == 1 for d in projector)


def test_query_reports_unavailable_when_neo4j_is_down(tenant, monkeypatch):
    from neo4j.exceptions import ServiceUnavailable

    class DownDriver:
        def session(self):
            raise ServiceUnavailable("Connection refused")

    monkeypatch.setattr(graph, "_get_driver", lambda: DownDriver())
    with pytest.raises(GraphUnavailable):
        graph.query(tenant, "skills_graph")
