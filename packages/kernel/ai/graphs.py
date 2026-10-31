"""Run a LangGraph agent with a Postgres checkpointer, so a crash resumes after the last node.

Checkpoints hold agent state, so only the worker's database role can reach their schema.
Worker image only: LangGraph is not installed in the API or executor images.
"""

import os
from typing import Any
from urllib.parse import quote
from uuid import UUID

CHECKPOINT_SEARCH_PATH = "agent_ckpt"


def _conn_string() -> str:
    url = os.environ["DATABASE_URL"]
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options={quote(f'-csearch_path={CHECKPOINT_SEARCH_PATH}')}"


def setup_checkpoints() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        saver.setup()


def run_graph(builder: Any, state: dict[str, Any] | None, run_id: UUID | str) -> dict[str, Any]:
    """Run a StateGraph builder. Pass state=None to resume a crashed run from its checkpoint."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_conn_string()) as saver:
        graph = builder.compile(checkpointer=saver)
        return graph.invoke(state, {"configurable": {"thread_id": str(run_id)}})
