"""Durable jobs and timers on Postgres (Procrastinate). Tables live in the `jobs` schema.

app = get_job_app()

@app.task(name="talent.followup")
def send_followup(tenant_id: str, application_id: str): ...

with app.open():
    send_followup.configure(schedule_in={"days": 3}).defer(tenant_id=..., application_id=...)
"""

import os
from urllib.parse import quote

import procrastinate

JOBS_SEARCH_PATH = "jobs"
# The worker serves these queues. A new queue name must be added here to be processed.
WORKER_QUEUES = ["default", "agents"]

_app: procrastinate.App | None = None


def _conninfo() -> str:
    url = os.environ["DATABASE_URL"]
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options={quote(f'-csearch_path={JOBS_SEARCH_PATH}')}"


def get_job_app() -> procrastinate.App:
    global _app
    if _app is None:
        # The async connector serves the worker and also provides sync deferring through open().
        _app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo()))
    return _app


def schema_sql() -> str:
    """The Procrastinate schema, applied by a kernel migration."""
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector())
    return app.schema_manager.get_schema()
