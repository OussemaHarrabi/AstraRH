"""AstraRH ML process: parses and embeds untrusted files on a network with no internet."""

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from kernel.obs import setup_telemetry

setup_telemetry()

app = FastAPI(title="AstraRH ML", version="0.1.0", docs_url=None, redoc_url=None)
FastAPIInstrumentor.instrument_app(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/v0/ping")
def ping() -> dict[str, str]:
    return {"service": "ml"}
