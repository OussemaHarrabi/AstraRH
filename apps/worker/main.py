"""AstraRH worker process: runs agents and jobs. It can propose, never send or approve."""

import logging
import os
import time

import httpx
from opentelemetry import trace

from kernel.heartbeat import beat
from kernel.obs import setup_telemetry

HEARTBEAT_SECONDS = 30

log = logging.getLogger("astra.worker")


def main() -> None:
    setup_telemetry()
    tracer = trace.get_tracer("astra.worker")
    log.info("worker started")
    while True:
        beat()
        with tracer.start_as_current_span("worker.heartbeat") as span:
            try:
                status = httpx.get(f"{os.environ['ML_URL']}/v0/ping", timeout=5).status_code
                span.set_attribute("astra.ml.status", status)
            except httpx.HTTPError as exc:
                span.record_exception(exc)
                log.warning("ml service unreachable")
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
