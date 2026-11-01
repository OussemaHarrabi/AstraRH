"""Turn a frozen CV profile and its stored text into evidence signals for each criterion.

Deterministic given the same stored inputs. Models don't run here: the reader already ran once
and its output was frozen; the embedding of the rubric is fixed by the model version.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from packs.talent.models import EMBEDDING_DIMENSIONS

SIMILARITY_PLACES = Decimal("0.0001")
QUOTE_MAX_CHARS = 240
LIST_KEYWORD_THRESHOLD = 4
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s*")


@dataclass
class SignalResult:
    signal: dict[str, Any]
    evidence: list[dict[str, Any]]


def keyword_pattern(keyword: str) -> re.Pattern:
    return re.compile(rf"(?<![\w+#]){re.escape(keyword)}(?![\w+#])", re.IGNORECASE)


def find_sentence(text_value: str, keywords: list[str]) -> str | None:
    """The first sentence with a keyword: repeating a word many times earns nothing extra."""
    patterns = [keyword_pattern(keyword) for keyword in keywords]
    for sentence in _SENTENCE_SPLIT.split(text_value):
        if any(pattern.search(sentence) for pattern in patterns):
            return sentence.strip()[:QUOTE_MAX_CHARS]
    return None


def verified_years(claim: dict[str, Any]) -> Decimal | None:
    """Trust a stated duration only if that number is really in the quote from the CV."""
    years = claim.get("years")
    if years is None:
        return None
    value = Decimal(str(years))
    if value <= 0:
        return None
    quote = claim.get("evidence", {}).get("quote", "")
    numbers = {Decimal(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", quote)}
    return value if value in numbers else None


def role_years(profile: dict[str, Any], keywords: list[str], source_text: str) -> Decimal | None:
    """Years of experience computed from dated roles that really name this skill.

    Every input is checked: the years must be in the role's quote, and the skill must be in the
    CV's own text. Overlapping roles count once. The arithmetic is ours, not the model's.
    """
    patterns = [keyword_pattern(keyword) for keyword in keywords]
    if not any(pattern.search(source_text) for pattern in patterns):
        return None
    as_of = profile.get("as_of_year")
    spans: list[tuple[int, int]] = []
    for role in profile.get("roles", []):
        if not any(p.search(skill) for skill in role.get("skills", []) for p in patterns):
            continue
        quote = role.get("evidence", {}).get("quote", "")
        start, end = role.get("start_year"), role.get("end_year")
        if start is None or str(start) not in quote:
            continue
        if end is not None and str(end) not in quote:
            continue
        finish = end if end is not None else as_of
        if finish is None or finish < start:
            continue
        spans.append((start, finish))
    if not spans:
        return None
    ordered = sorted(spans)
    total, current_start, current_end = 0, ordered[0][0], ordered[0][1]
    for start, finish in ordered[1:]:
        if start > current_end:
            total += current_end - current_start
            current_start, current_end = start, finish
        else:
            current_end = max(current_end, finish)
    total += current_end - current_start
    return Decimal(total) if total > 0 else None


def looks_like_keyword_list(quote: str, all_keywords: list[str]) -> bool:
    """Many of the job's terms in one line, and no stated duration: a list, not experience."""
    hits = sum(1 for keyword in all_keywords if keyword_pattern(keyword).search(quote))
    return hits >= LIST_KEYWORD_THRESHOLD


def _claims_for(profile: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    patterns = [keyword_pattern(keyword) for keyword in keywords]
    matched = []
    for claim in profile.get("skills", []):
        haystack = f"{claim.get('name', '')} {claim.get('evidence', {}).get('quote', '')}"
        if any(pattern.search(haystack) for pattern in patterns):
            matched.append(claim)
    return matched


def compute_signal(
    criterion: dict[str, Any],
    profile: dict[str, Any],
    blind_text: str,
    similarity: dict[str, Any] | None,
    related: list[dict[str, Any]],
    override: Decimal | None,
    cv_id: str,
    all_keywords: list[str] | None = None,
) -> SignalResult:
    keywords = criterion.get("keywords") or []
    signal: dict[str, Any] = {"direct": False, "years": None, "related": None, "similarity": None}
    evidence: list[dict[str, Any]] = []

    if keywords:
        claims = _claims_for(profile, keywords)
        best_years = None
        best_claim = None
        for claim in claims:
            years = verified_years(claim)
            if years is not None and (best_years is None or years > best_years):
                best_years, best_claim = years, claim
        best_claim = best_claim or (claims[0] if claims else None)
        computed = role_years(profile, keywords, blind_text)
        if computed is not None and (best_years is None or computed > best_years):
            best_years = computed
        quote = (
            best_claim["evidence"]["quote"] if best_claim else find_sentence(blind_text, keywords)
        )
        if quote:
            signal["direct"] = True
            signal["years"] = str(best_years) if best_years is not None else None
            listed = best_years is None and looks_like_keyword_list(quote, all_keywords or [])
            if listed:
                signal["listed"] = True
            evidence.append(
                {
                    "factor_key": criterion["id"],
                    "kind": "listed" if listed else "direct",
                    "years": signal["years"],
                    "quote": quote,
                    "source_id": cv_id,
                }
            )

    if not signal["direct"] and related:
        for item in sorted(related, key=lambda r: Decimal(str(r["strength"])), reverse=True):
            found = find_sentence(blind_text, item["keywords"])
            if found:
                signal["related"] = str(item["strength"])
                evidence.append(
                    {
                        "factor_key": criterion["id"],
                        "kind": f"related:{item['name']}",
                        "quote": found,
                        "source_id": cv_id,
                    }
                )
                break

    if similarity is not None:
        signal["similarity"] = str(similarity["similarity"])
        if not evidence and Decimal(similarity["similarity"]) > Decimal("0.45"):
            evidence.append(
                {
                    "factor_key": criterion["id"],
                    "kind": "semantic",
                    "quote": similarity["text"][:QUOTE_MAX_CHARS],
                    "source_id": cv_id,
                }
            )

    if override is not None:
        signal["override"] = str(override)
    return SignalResult(signal, evidence)


TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
BM25_K1 = Decimal("1.5")
BM25_B = Decimal("0.75")
MATCH_PLACES = Decimal("0.0001")


def tokenize(value: str) -> list[str]:
    return [token.casefold() for token in TOKEN.findall(value)]


def lexical_document(blind_text: str, all_keywords: list[str]) -> str:
    """Lines that are only a list of the job's keywords don't count, so stuffing can't game BM25."""
    return "\n".join(
        line for line in blind_text.splitlines() if not looks_like_keyword_list(line, all_keywords)
    )


def bm25_scores(query: str, documents: dict[Any, str]) -> dict[Any, Decimal]:
    """BM25 of each CV against the job, scaled so the best CV in this run is 1. Exact decimals."""
    tokens = {key: tokenize(text_value) for key, text_value in documents.items()}
    count = len(tokens)
    if count == 0:
        return {}
    average = Decimal(sum(len(t) for t in tokens.values())) / Decimal(count) or Decimal(1)
    terms = sorted(set(tokenize(query)))
    raw: dict[Any, Decimal] = {}
    for key, doc in tokens.items():
        total = Decimal(0)
        length = Decimal(len(doc))
        for term in terms:
            frequency = Decimal(doc.count(term))
            if not frequency:
                continue
            with_term = sum(1 for other in tokens.values() if term in other)
            idf = (
                (Decimal(count - with_term) + Decimal("0.5"))
                / (Decimal(with_term) + Decimal("0.5"))
                + 1
            ).ln()
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average)
            total += idf * frequency * (BM25_K1 + 1) / denominator
        raw[key] = total
    best = max(raw.values())
    if best <= 0:
        return {key: Decimal(0) for key in raw}
    return {
        key: (value / best).quantize(MATCH_PLACES, rounding=ROUND_HALF_UP)
        for key, value in raw.items()
    }


def weighted_dense_match(
    criteria: list[dict[str, Any]], similarities: dict[str, str | None]
) -> Decimal:
    """Criterion-weighted average of each criterion's closest passage in this CV."""
    total = Decimal(0)
    for criterion in criteria:
        value = similarities.get(criterion["id"])
        if value is not None:
            total += Decimal(str(criterion["weight"])) * max(Decimal(0), Decimal(str(value)))
    return total.quantize(MATCH_PLACES, rounding=ROUND_HALF_UP)


def rerank_closest(
    criteria: list[dict[str, Any]], closest: dict[str, dict[Any, dict[str, Any]]]
) -> dict[Any, dict[str, str]] | None:
    """Cross-encoder score of each criterion against each CV's closest passage.

    Returns {cv_id: {criterion_id: score}}, or None if the reranker is unavailable, in which
    case the ranking is made without it and says so.
    """
    from kernel import ml_client
    from kernel.errors import ProviderUnavailable

    out: dict[Any, dict[str, str]] = {}
    try:
        for criterion in criteria:
            rows = list(closest.get(criterion["id"], {}).items())
            if not rows:
                continue
            scores = ml_client.rerank(criterion_text(criterion), [row["text"] for _, row in rows])
            for (cv_id, _), value in zip(rows, scores, strict=True):
                out.setdefault(cv_id, {})[criterion["id"]] = str(
                    Decimal(str(value)).quantize(SIMILARITY_PLACES, rounding=ROUND_HALF_UP)
                )
    except ProviderUnavailable:
        return None
    return out


def criterion_text(criterion: dict[str, Any]) -> str:
    return f"{criterion['label']}: {criterion.get('description', '')}".strip()


def chunk_text(blind_text: str, max_chars: int = 400) -> list[str]:
    """Group lines into small passages, so similarity points at something a person can read."""
    chunks: list[str] = []
    current = ""
    for line in blind_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def best_similarities(
    session: Session, job_id: UUID, query_vector: list[float]
) -> dict[UUID, dict[str, Any]]:
    """For one criterion: each CV's closest passage in this job, by cosine similarity (pgvector).

    Exact, not approximate, so it is reproducible. Row-level security scopes it to the tenant.
    """
    statement = text(
        "SELECT DISTINCT ON (cv_id) cv_id, text, "
        f"1 - (embedding <=> CAST(:query AS vector({EMBEDDING_DIMENSIONS}))) AS similarity "
        "FROM talent.cv_chunk WHERE job_id = :job_id "
        f"ORDER BY cv_id, embedding <=> CAST(:query AS vector({EMBEDDING_DIMENSIONS})), position"
    ).bindparams(bindparam("query"), bindparam("job_id"))
    literal = "[" + ",".join(f"{x:.6f}" for x in query_vector) + "]"
    rows = session.execute(statement, {"query": literal, "job_id": job_id}).all()
    return {
        row.cv_id: {
            "similarity": str(
                Decimal(str(row.similarity)).quantize(SIMILARITY_PLACES, rounding=ROUND_HALF_UP)
            ),
            "text": row.text,
        }
        for row in rows
    }
