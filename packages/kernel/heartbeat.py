"""Liveness file for processes that serve no HTTP. The Docker healthcheck reads its age."""

from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/heartbeat")  # noqa: S108 - container tmpfs, not shared


def beat() -> None:
    HEARTBEAT_FILE.touch()
