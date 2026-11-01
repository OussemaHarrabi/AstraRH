"""Client for the sandboxed ml service: parsing and embeddings. Failures fail closed."""

import os
from dataclasses import dataclass, field

import httpx

from kernel.errors import ProviderUnavailable, ValidationFailed

PARSE_TIMEOUT_SECONDS = 90
EMBED_TIMEOUT_SECONDS = 60
EMBED_BATCH = 64
RERANK_TIMEOUT_SECONDS = 120
RERANK_BATCH = 32


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    hidden_text: str
    pages: int
    method: str
    findings: list[str] = field(default_factory=list)
    lines: str = ""  # visible text line by line; Docling's `text` joins lines into paragraphs


def _url(path: str) -> str:
    return f"{os.environ['ML_URL']}{path}"


def parse(filename: str, data: bytes) -> ParsedDocument:
    try:
        response = httpx.post(
            _url("/v0/parse"), files={"file": (filename, data)}, timeout=PARSE_TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("The parsing service is unavailable") from exc
    if response.status_code == 422:
        raise ValidationFailed(response.json().get("detail", "This document could not be read"))
    if response.status_code != 200:
        raise ProviderUnavailable(f"The parsing service returned {response.status_code}")
    return ParsedDocument(**response.json())


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        try:
            response = httpx.post(
                _url("/v0/embed"), json={"texts": batch}, timeout=EMBED_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The embedding service is unavailable") from exc
        vectors.extend(response.json()["vectors"])
    return vectors


def rerank(query: str, passages: list[str]) -> list[float]:
    """Cross-encoder relevance of each passage to the query, from 0 to 1, in the same order."""
    scores: list[float] = []
    for start in range(0, len(passages), RERANK_BATCH):
        try:
            response = httpx.post(
                _url("/v0/rerank"),
                json={"query": query, "passages": passages[start : start + RERANK_BATCH]},
                timeout=RERANK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The reranking service is unavailable") from exc
        scores.extend(float(x) for x in response.json()["scores"])
    return scores


def model_info() -> dict[str, str | int]:
    try:
        response = httpx.get(_url("/v0/model"), timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("The embedding service is unavailable") from exc
    return response.json()
