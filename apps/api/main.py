"""AstraRH API process: kernel and service packs behind one FastAPI app."""

import os

import httpx
import psycopg
from fastapi import FastAPI, Response
from neo4j import GraphDatabase
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from kernel import registry, web
from kernel.obs import setup_telemetry

setup_telemetry()

is_dev = os.environ.get("ASTRA_ENV", "dev") == "dev"
app = FastAPI(
    title="AstraRH API",
    version="0.1.0",
    docs_url="/docs" if is_dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if is_dev else None,
)
FastAPIInstrumentor.instrument_app(app)
web.install(app)
registry.mount_pack_routers(app)


def _postgres_ok() -> bool:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def _graph_ok() -> bool:
    try:
        auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
        with GraphDatabase.driver(
            os.environ["NEO4J_URI"], auth=auth, connection_timeout=2
        ) as driver:
            driver.verify_connectivity()
        return True
    except Exception:  # noqa: BLE001 - any graph failure means "unavailable", never a crash
        return False


def _files_ok() -> bool:
    try:
        url = f"{os.environ['S3_ENDPOINT']}/minio/health/live"
        return httpx.get(url, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    """Postgres and files are required. Neo4j is a read model, so losing it only degrades graphs."""
    postgres, files = _postgres_ok(), _files_ok()
    ready = postgres and files
    response.status_code = 200 if ready else 503
    return {
        "status": "ready" if ready else "not_ready",
        "postgres": "ok" if postgres else "down",
        "files": "ok" if files else "down",
        "graph": "ok" if _graph_ok() else "degraded",
    }
