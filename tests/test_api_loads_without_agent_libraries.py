"""The API image deliberately has no agent or model libraries. Every pack's API module must
still import there, or that pack's routes silently disappear from the running API (the registry
logs the failure and carries on). The tests run in an image that has those libraries, so this
blocks them in a fresh interpreter to reproduce the API image."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kernel.registry import active_packs

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = (
    "langgraph",
    "langgraph.graph",
    "langgraph.checkpoint",
    "langgraph.checkpoint.postgres",
    "anthropic",
    "openai",
    "groq",
)
PACK_APIS = [(m.id, m.api) for m in active_packs() if m.api]

SCRIPT = """
import sys
for name in {blocked!r}:
    sys.modules[name] = None
from importlib import import_module
module, attribute = {api!r}.split(":")
getattr(import_module(module), attribute)
"""


@pytest.mark.parametrize(("pack", "api"), PACK_APIS)
def test_a_pack_api_loads_without_the_agent_libraries(pack, api):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "packages"), str(ROOT)])}
    result = subprocess.run(  # noqa: S603 - fixed arguments, no user input
        [sys.executable, "-c", SCRIPT.format(blocked=BLOCKED, api=api)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"{pack} cannot load in the API process:\n{result.stderr[-800:]}"


def test_the_packs_with_an_api_are_checked():
    assert {"talent", "finance"} <= {pack for pack, _ in PACK_APIS}
