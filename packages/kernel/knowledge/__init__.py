"""Company documents: hybrid search with permissions applied before ranking, never after.

Same idea as CV ranking: vector similarity for meaning, plus full-text search for exact terms,
combined by reciprocal rank fusion. A person can't retrieve text they couldn't read.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from kernel import ml_client
from kernel.events import event_type
from kernel.knowledge.models import Chunk, Document, Question, Ticket

__all__ = ["Chunk", "Document", "Question", "Ticket", "chunk_markdown", "ingest_document", "search"]

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
) -> Document:
    audience = audience_roles or []
    document = Document(
        tenant_id=tenant_id,
        external_id=external_id,
        title=title,
        version=version,
        audience_roles=audience,
    )
    session.add(document)
    session.flush()
    sections = chunk_markdown(markdown)
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
    session.flush()
    return document


def search(session: Session, question: str, roles: list[str], top_k: int = TOP_K) -> list[Hit]:
    """Permissions are inside the WHERE of both searches, so forbidden text can't even rank."""
    vector = ml_client.embed([question])[0]
    literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    allowed = "(c.audience_roles = '{}' OR c.audience_roles && CAST(:roles AS text[]))"
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
