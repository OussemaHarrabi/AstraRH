"""AstraGraph: a Neo4j read model rebuilt from the event log. Never a source of truth.

Writes: declarative projections, from pack manifests, with labels checked against strict
patterns and all values passed as parameters, so text in a CV stays inert data.
Reads: named query templates only, always with tenant_id injected by the kernel.
No LLM writes Cypher, and salaries, cases and contact details can't be projected.
"""

import logging
import os
import re
from typing import Any
from uuid import UUID

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.errors import GraphUnavailable, NotFound, ValidationFailed
from kernel.events import Consumer, EventOutbox, add_consumer

LABEL_PATTERN = re.compile(r"^[A-Z][A-Za-z]{1,40}$")
REL_PATTERN = re.compile(r"^[A-Z][A-Z_]{1,40}$")
PROP_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
FORBIDDEN_LABELS = {"Salary", "Payslip", "Compensation", "Case", "Conflict", "Grievance"}
FORBIDDEN_PROPS = {
    "salary",
    "gross",
    "net",
    "email",
    "phone",
    "address",
    "quote",
    "narrative",
    "body",
    "cv_text",
}
PROJECTOR_CONSUMER = "graph.projector"
CONNECT_TIMEOUT_SECONDS = 2
MAX_QUERY_ROWS = 1000

log = logging.getLogger("astra.graph")

_driver: Driver | None = None
_constrained: set[str] = set()
_projections: dict[str, list["Projection"]] = {}
_queries: dict[str, str] = {}


class NodeRef(BaseModel):
    label: str
    id: str

    @field_validator("label")
    @classmethod
    def _check_label(cls, value: str) -> str:
        if not LABEL_PATTERN.match(value):
            raise ValueError(f"Invalid graph label {value!r}")
        if value in FORBIDDEN_LABELS:
            raise ValueError(f"{value} must never enter the graph")
        return value


class NodeSpec(NodeRef):
    props: dict[str, str] = Field(default_factory=dict)

    @field_validator("props")
    @classmethod
    def _check_props(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not PROP_PATTERN.match(key):
                raise ValueError(f"Invalid graph property {key!r}")
            if key in FORBIDDEN_PROPS:
                raise ValueError(f"Property {key!r} must never enter the graph")
        return value


class EdgeSpec(BaseModel):
    type: str
    from_: NodeRef = Field(alias="from")
    to: NodeRef

    @field_validator("type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if not REL_PATTERN.match(value):
            raise ValueError(f"Invalid graph relationship {value!r}")
        return value


class Projection(BaseModel):
    event: str
    for_each: str | None = None
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_empty(self) -> "Projection":
        if not self.nodes and not self.edges:
            raise ValueError("A projection needs nodes or edges")
        return self


def register_projection(projection: Projection) -> None:
    existing = _projections.setdefault(projection.event, [])
    if projection not in existing:
        existing.append(projection)


def register_query(name: str, cypher: str) -> None:
    if "$tenant_id" not in cypher:
        raise ValidationFailed(f"Query {name} must filter by $tenant_id")
    _queries[name] = cypher


def _get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
            connection_timeout=CONNECT_TIMEOUT_SECONDS,
            max_transaction_retry_time=5,
        )
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def _resolve(expression: str, event: EventOutbox, item: dict[str, Any] | None) -> Any:
    """ "$.path" reads the payload, "@.path" the for_each item, "$event.x" the event row."""
    if expression == "$event.id":
        return str(event.id)
    if expression == "$event.type":
        return event.type
    if expression.startswith("fmt:"):
        scope = {**event.payload, **(item or {})}
        try:
            return expression[4:].format(**scope)
        except (KeyError, IndexError):
            return None
    if expression.startswith(("$.", "@.")):
        value: Any = event.payload if expression[0] == "$" else (item or {})
        for part in expression[2:].split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value
    return expression


def _scalar_props(props: dict[str, str], event: EventOutbox, item: dict | None) -> dict[str, Any]:
    resolved = {key: _resolve(expr, event, item) for key, expr in props.items()}
    return {k: v for k, v in resolved.items() if isinstance(v, str | int | float | bool)}


def _uid(tenant_id: UUID, value: Any) -> str:
    return f"{tenant_id}:{value}"


def _ensure_constraint(tx_runner: Any, label: str) -> None:
    if label in _constrained:
        return
    # The label has passed LABEL_PATTERN, and Cypher can't parameterize labels.
    tx_runner.run(
        f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE"
    )
    _constrained.add(label)


def _statements(event: EventOutbox) -> list[tuple[str, dict[str, Any]]]:
    tenant_id = event.tenant_id
    statements: list[tuple[str, dict[str, Any]]] = [
        (
            "MERGE (n:Event {uid: $uid}) SET n.id = $id, n.tenant_id = $tenant_id, n.type = $type",
            {
                "uid": _uid(tenant_id, event.id),
                "id": str(event.id),
                "tenant_id": str(tenant_id),
                "type": event.type,
            },
        )
    ]
    for projection in _projections.get(event.type, []):
        items: list[dict[str, Any] | None] = [None]
        if projection.for_each:
            found = _resolve(projection.for_each, event, None)
            items = [entry for entry in (found or []) if isinstance(entry, dict)]
        for item in items:
            for node in projection.nodes:
                node_id = _resolve(node.id, event, item)
                if node_id is None:
                    continue
                statements.append(
                    (
                        f"MERGE (n:{node.label} {{uid: $uid}}) "
                        "SET n += $props, n.id = $id, n.tenant_id = $tenant_id",
                        {
                            "uid": _uid(tenant_id, node_id),
                            "id": str(node_id),
                            "tenant_id": str(tenant_id),
                            "props": _scalar_props(node.props, event, item),
                        },
                    )
                )
            for edge in projection.edges:
                source = _resolve(edge.from_.id, event, item)
                target = _resolve(edge.to.id, event, item)
                if source is None or target is None:
                    continue
                statements.append(
                    (
                        f"MERGE (a:{edge.from_.label} {{uid: $source}}) "
                        "SET a.id = $source_id, a.tenant_id = $tenant_id "
                        f"MERGE (b:{edge.to.label} {{uid: $target}}) "
                        "SET b.id = $target_id, b.tenant_id = $tenant_id "
                        f"MERGE (a)-[:{edge.type}]->(b)",
                        {
                            "source": _uid(tenant_id, source),
                            "source_id": str(source),
                            "target": _uid(tenant_id, target),
                            "target_id": str(target),
                            "tenant_id": str(tenant_id),
                        },
                    )
                )
    return statements


def _labels_in(event_type: str) -> set[str]:
    labels = {"Event"}
    for projection in _projections.get(event_type, []):
        labels.update(node.label for node in projection.nodes)
        for edge in projection.edges:
            labels.update({edge.from_.label, edge.to.label})
    return labels


def project_event(event: EventOutbox) -> None:
    statements = _statements(event)
    try:
        with _get_driver().session() as session:
            for label in _labels_in(event.type):
                _ensure_constraint(session, label)

            def work(tx: Any) -> None:
                for cypher, params in statements:
                    tx.run(cypher, **params)

            session.execute_write(work)
    except (ServiceUnavailable, SessionExpired, OSError) as exc:
        raise GraphUnavailable("The graph database is unavailable") from exc


def _project_consumer(_session: Session, event: EventOutbox) -> None:
    project_event(event)


def install_projector() -> None:
    """Retries forever: when Neo4j returns, the graph catches up. Other consumers are unaffected."""
    add_consumer("*", Consumer(PROJECTOR_CONSUMER, _project_consumer, retry_forever=True))


def query(tenant_id: UUID, name: str, **params: Any) -> dict[str, Any]:
    """Run a named template. Returns {"nodes": [...], "edges": [...], "rows": [...]}."""
    cypher = _queries.get(name)
    if cypher is None:
        raise NotFound(f"Unknown graph query {name}")
    params["tenant_id"] = str(tenant_id)
    params.setdefault("limit", MAX_QUERY_ROWS)
    try:
        with _get_driver().session() as session:
            records = list(session.run(cypher, **params))
    except (ServiceUnavailable, SessionExpired, OSError, Neo4jError) as exc:
        raise GraphUnavailable("The graph view is temporarily unavailable") from exc
    return _shape(records)


def _node_json(node: Any) -> dict[str, Any]:
    data = dict(node)
    data.pop("uid", None)
    data.pop("tenant_id", None)
    return {"id": data.pop("id", None), "label": next(iter(node.labels), "Node"), "props": data}


def _shape(records: list[Any]) -> dict[str, Any]:
    """A relationship's endpoints carry no properties, so templates return its nodes too."""
    nodes: dict[str, dict[str, Any]] = {}
    relationships: list[Any] = []
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                continue
            if hasattr(value, "labels"):
                nodes[value.element_id] = _node_json(value)
            elif hasattr(value, "start_node") and hasattr(value, "type"):
                relationships.append(value)
            else:
                row[key] = value
        if row:
            rows.append(row)
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rel in relationships:
        start = nodes.get(rel.start_node.element_id)
        end = nodes.get(rel.end_node.element_id)
        if start and end:
            edges[(start["id"], rel.type, end["id"])] = {
                "from": start["id"],
                "to": end["id"],
                "type": rel.type,
            }
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "rows": rows}


def rebuild(session: Session, tenant_id: UUID) -> int:
    """Drop this tenant's graph and replay its event log. Postgres is the source of truth."""
    try:
        with _get_driver().session() as graph:
            graph.run("MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n", tenant_id=str(tenant_id))
    except (ServiceUnavailable, SessionExpired, OSError) as exc:
        raise GraphUnavailable("The graph database is unavailable") from exc
    count = 0
    for event in session.scalars(select(EventOutbox).order_by(EventOutbox.id)).yield_per(200):
        project_event(event)
        count += 1
    return count


register_query(
    "agent_mesh",
    """
    MATCH (a)-[r]->(b)
    WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
      AND labels(a)[0] IN ['Event','AgentRun','Proposal','Human','Execution']
      AND labels(b)[0] IN ['Event','AgentRun','Proposal','Human','Execution']
    RETURN a, r, b LIMIT $limit
    """,
)
register_query(
    "decision_chain",
    """
    MATCH (d:Decision {tenant_id: $tenant_id, id: $id})
    OPTIONAL MATCH (d)-[r1]-(n1) WHERE n1.tenant_id = $tenant_id
    OPTIONAL MATCH (n1)-[r2]-(n2) WHERE n2.tenant_id = $tenant_id
    RETURN d, r1, n1, r2, n2 LIMIT $limit
    """,
)
register_query(
    "skills_graph",
    """
    MATCH (a)-[r]->(b)
    WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
      AND labels(a)[0] IN ['Person','Skill','Position','Course','Kpi','OrgUnit']
      AND labels(b)[0] IN ['Person','Skill','Position','Course','Kpi','OrgUnit']
    RETURN a, r, b LIMIT $limit
    """,
)
register_query(
    "bus_factor",
    """
    MATCH (p:Person {tenant_id: $tenant_id})-[:HAS_SKILL]->(s:Skill {tenant_id: $tenant_id})
    WITH s, collect(p.id) AS holders
    WHERE size(holders) = 1
    RETURN s.id AS skill_id, s.name AS skill, holders[0] AS person_id
    ORDER BY skill LIMIT $limit
    """,
)
register_query(
    "learning_path",
    """
    MATCH (p:Person {tenant_id: $tenant_id, id: $person_id})
    MATCH (target:Skill {tenant_id: $tenant_id, id: $skill_id})
    MATCH (c:Course {tenant_id: $tenant_id})-[t:TEACHES]->(target)
    OPTIONAL MATCH (target)-[i:INFLUENCES]->(k:Kpi {tenant_id: $tenant_id})
    RETURN p, c, t, target, i, k LIMIT $limit
    """,
)
