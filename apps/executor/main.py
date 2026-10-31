"""AstraRH executor process: the only holder of outbound credentials.

It runs approved proposals after re-validating them. It never reads CVs or calls LLMs.
"""

import logging
import time

from opentelemetry import trace

from kernel.heartbeat import beat
from kernel.obs import setup_telemetry

HEARTBEAT_SECONDS = 30

log = logging.getLogger("astra.executor")


def main() -> None:
    setup_telemetry()
    tracer = trace.get_tracer("astra.executor")
    log.info("executor started")
    while True:
        beat()
        with tracer.start_as_current_span("executor.heartbeat"):
            pass
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
