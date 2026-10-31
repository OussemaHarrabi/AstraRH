"""Company documents: hybrid search with permissions applied before ranking, never after.

Same idea as CV ranking: vector similarity for meaning, plus full-text search for exact terms,
combined by reciprocal rank fusion. A person can't retrieve text they couldn't read.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from kernel import ml_client
from kernel.db import utcnow
from kernel.events import EventOutbox, event_type, subscribe
from kernel.knowledge.models import Chunk, Document, Question, Ticket

__all__ = [
    "Chunk",
    "Document",
    "Question",
    "Ticket",
    "chunk_markdown",
    "index_document",
    "ingest_document",
    "search",
]

RRF_K = 60
TOP_K = 5
CANDIDATES = 20
SECTION = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


@event_type("knowledge.question.asked.v1")
class QuestionAsked(BaseModel):
    question_id: UUID


@event_type("knowledge.question.escalated.v1")
class QuestionEscalated(BaseModel):
    question_id: UUID
    ticket_id: UUID


@event_type("knowledge.ticket.resolved.v1")
class TicketResolved(BaseModel):
    ticket_id: UUID
    question_id: UUID
    outcome: str  # answered | closed


@event_type("knowledge.document.submitted.v1")
class DocumentSubmitted(BaseModel):
    document_id: UUID


@dataclass(frozen=True)
class Hit:
    chunk_id: UUID
    document_title: str
    document_version: str
    section: str
    text: str
    similarity: Decimal
    score: Decimal

    def as_json(self, ref: str) -> dict[str, Any]:
        return {
            "ref": ref,
            "chunk_id": str(self.chunk_id),
            "document": self.document_title,
            "version": self.document_version,
            "section": self.section,
            "text": self.text,
        }


def chunk_markdown(markdown: str) -> list[tuple[str, str]]:
    """One passage per section, so a citation points at something a person can check."""
    chunks: list[tuple[str, str]] = []
    matches = list(SECTION.finditer(markdown))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end() : end].strip()
        if body:
            chunks.append((match.group(1).strip(), body))
    if not chunks and markdown.strip():
        chunks.append(("Document", markdown.strip()))
    return chunks


def ingest_document(
    session: Session,
    tenant_id: UUID,
    external_id: str,
    title: str,
    markdown: str,
    audience_roles: list[str] | None = None,
    version: str = "1",
    effective_date: date | None = None,
) -> Document:
    """Index a document now. Uploads through the API go through `index_document` in the worker."""
    document = Document(
        tenant_id=tenant_id,
        external_id=external_id,
        title=title,
        version=version,
        effective_date=effective_date,
        audience_roles=audience_roles or [],
        status="processing",
        source=markdown,
    )
    session.add(document)
    session.flush()
    _index(session, document)
    return document


def _index(session: Session, document: Document) -> None:
    """Chunk and embed, then make this the only active version of its external_id."""
    tenant_id, title, audience = document.tenant_id, document.title, document.audience_roles
    sections = chunk_markdown(document.source or "")
    if not sections:
        document.status = "failed"
        return
    vectors = ml_client.embed([f"{title}. {name}. {body}" for name, body in sections])
    for position, ((name, body), vector) in enumerate(zip(sections, vectors, strict=True)):
        session.add(
            Chunk(
                tenant_id=tenant_id,
                document_id=document.id,
                position=position,
                section=name,
                text=body,
                audience_roles=audience,
                embedding=vector,
            )
        )
    older = select(Document.id).where(
        Document.external_id == document.external_id,
        Document.id != document.id,
        Document.status == "active",
    )
    older_ids = list(session.scalars(older))
    if older_ids:
        session.execute(
            update(Document)
            .where(Document.id.in_(older_ids))
            .values(status="superseded", superseded_at=utcnow())
        )
        session.execute(update(Chunk).where(Chunk.document_id.in_(older_ids)).values(active=False))
    document.status = "active"
    session.flush()


@subscribe("knowledge.document.submitted.v1", "knowledge.index_document")
def index_document(session: Session, event: EventOutbox) -> None:
    """Embedding needs the ml service, which only the worker reaches, so uploads index here."""
    document = session.get(Document, UUID(event.payload["document_id"]), with_for_update=True)
    if document is None or document.status != "processing":
        return
    _index(session, document)


def search(session: Session, question: str, roles: list[str], top_k: int = TOP_K) -> list[Hit]:
    """Permissions are inside the WHERE of both searches, so forbidden text can't even rank."""
    vector = ml_client.embed([question])[0]
    literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    allowed = "c.active AND (c.audience_roles = '{}' OR c.audience_roles && CAST(:roles AS text[]))"
    params = {"literal": literal, "roles": roles, "question": question, "limit": CANDIDATES}
    dense = session.execute(
        text(
            "SELECT c.id, 1 - (c.embedding <=> CAST(:literal AS vector(384))) AS similarity "
            f"FROM knowledge.chunk c WHERE {allowed} "
            "ORDER BY c.embedding <=> CAST(:literal AS vector(384)), c.id LIMIT :limit"
        ),
        params,
    ).all()
    lexical = session.execute(
        text(
            "SELECT c.id FROM knowledge.chunk c "
            f"WHERE {allowed} AND to_tsvector('simple', c.text || ' ' || c.section) "
            "@@ websearch_to_tsquery('simple', :query) "
            "ORDER BY ts_rank_cd(to_tsvector('simple', c.text || ' ' || c.section), "
            "websearch_to_tsquery('simple', :query)) DESC, c.id LIMIT :limit"
        ),
        {**params, "query": _or_query(question)},
    ).all()

    fused: dict[UUID, Decimal] = {}
    for rows in (dense, lexical):
        for rank, row in enumerate(rows, start=1):
            fused[row.id] = fused.get(row.id, Decimal(0)) + Decimal(1) / Decimal(RRF_K + rank)
    similarity = {
        row.id: Decimal(str(row.similarity)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        for row in dense
    }
    top = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], str(chunk_id)))[:top_k]
    if not top:
        return []
    rows = session.execute(
        text(
            "SELECT c.id, c.section, c.text, d.title, d.version FROM knowledge.chunk c "
            "JOIN knowledge.document d ON d.id = c.document_id WHERE c.id = ANY(:ids)"
        ),
        {"ids": top},
    ).all()
    by_id = {row.id: row for row in rows}
    return [
        Hit(
            chunk_id=chunk_id,
            document_title=by_id[chunk_id].title,
            document_version=by_id[chunk_id].version,
            section=by_id[chunk_id].section,
            text=by_id[chunk_id].text,
            similarity=similarity.get(chunk_id, Decimal(0)),
            score=fused[chunk_id],
        )
        for chunk_id in top
    ]


def _or_query(question: str) -> str:
    words = [w for w in re.findall(r"[^\W_]{3,}", question)]
    return " OR ".join(words) if words else question
