"""AstraRH ML process: parses and embeds untrusted files on a network with no internet.

The embedding model is baked into the image at build time. Same model, same text, same vector,
rounded so that stored similarity scores are stable.
"""

import math
import threading

from fastapi import FastAPI, HTTPException, UploadFile
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field

from apps.ml.parsing import UnreadableDocument, parse_document, warm_up
from kernel.obs import setup_telemetry

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMENSIONS = 384
VECTOR_DECIMALS = 6
MAX_EMBED_TEXTS = 128
MAX_EMBED_CHARS = 4000
RERANK_MODEL = "BAAI/bge-reranker-v2-m3-int8"  # multilingual, Apache-2.0
MAX_RERANK_PASSAGES = 32
MAX_RERANK_CHARS = 2000

setup_telemetry()

app = FastAPI(title="AstraRH ML", version="0.1.0", docs_url=None, redoc_url=None)
FastAPIInstrumentor.instrument_app(app)


@app.on_event("startup")
def _warm_parser() -> None:
    threading.Thread(target=_warm_up, name="model-warm-up", daemon=True).start()


_model: TextEmbedding | None = None
_model_lock = threading.Lock()


def get_model() -> TextEmbedding:
    global _model
    with _model_lock:
        if _model is None:
            _model = TextEmbedding(model_name=EMBEDDING_MODEL, threads=2, lazy_load=False)
    return _model


_reranker: TextCrossEncoder | None = None
_reranker_lock = threading.Lock()


def get_reranker() -> TextCrossEncoder:
    global _reranker
    with _reranker_lock:
        if _reranker is None:
            _reranker = TextCrossEncoder(model_name=RERANK_MODEL, threads=4, lazy_load=False)
    return _reranker


def _warm_up() -> None:
    warm_up()
    get_reranker()


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_RERANK_CHARS)
    passages: list[str] = Field(min_length=1, max_length=MAX_RERANK_PASSAGES)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_EMBED_TEXTS)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/v0/ping")
def ping() -> dict[str, str]:
    return {"service": "ml"}


@app.get("/v0/model")
def model() -> dict[str, str | int]:
    return {
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "reranker": RERANK_MODEL,
    }


@app.post("/v0/parse")
def parse(file: UploadFile) -> dict:
    data = file.file.read()
    try:
        result = parse_document(file.filename or "upload", data)
    except UnreadableDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "text": result.text,
        "hidden_text": result.hidden_text,
        "pages": result.pages,
        "method": result.method,
        "findings": result.findings,
        "lines": result.lines,
    }


@app.post("/v0/embed")
def embed(body: EmbedRequest) -> dict:
    texts = [text[:MAX_EMBED_CHARS] for text in body.texts]
    with _model_lock:
        loaded = _model
    vectors = list((loaded or get_model()).embed(texts))
    return {"vectors": [[round(float(x), VECTOR_DECIMALS) for x in v] for v in vectors]}


@app.post("/v0/rerank")
def rerank(body: RerankRequest) -> dict:
    """How well each passage answers the query, from 0 to 1. Same inputs, same scores."""
    passages = [passage[:MAX_RERANK_CHARS] for passage in body.passages]
    logits = list(get_reranker().rerank(body.query, passages, batch_size=8))
    return {
        "model": RERANK_MODEL,
        "scores": [round(1 / (1 + math.exp(-float(x))), VECTOR_DECIMALS) for x in logits],
    }
