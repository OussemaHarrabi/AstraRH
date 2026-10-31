"""Guards the static security boundaries of the stack. Runs without Docker in any Python."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "ops" / "compose.yaml"


def service_block(name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|^\w)", text, re.M | re.S)
    assert match, f"service {name} not found"
    return match.group(1)


def test_only_worker_holds_llm_keys():
    for service in ["api", "executor", "ml", "web", "caddy"]:
        block = service_block(service)
        assert "ANTHROPIC_API_KEY" not in block
        assert "GROQ_API_KEY" not in block
    assert "ANTHROPIC_API_KEY" in service_block("worker")


def test_only_executor_reaches_mail():
    for service in ["api", "worker", "ml", "web"]:
        assert "mail" not in re.search(r"networks: \[(.*?)\]", service_block(service)).group(1)
    assert "mail" in service_block("executor")


def test_only_worker_has_internet_egress():
    for service in ["api", "executor", "ml", "web", "postgres", "neo4j", "minio", "mailpit"]:
        assert "llm_egress" not in service_block(service)
    assert "llm_egress" in service_block("worker")


def test_ml_is_on_internal_networks_only():
    text = COMPOSE.read_text(encoding="utf-8")
    assert re.search(r"^  ml: \{ internal: true \}", text, re.M)
    assert re.search(r"^  telemetry: \{ internal: true \}", text, re.M)
    assert "networks: [ml, telemetry]" in service_block("ml")


def test_executor_cannot_reach_files_or_graph():
    networks = re.search(r"networks: \[(.*?)\]", service_block("executor")).group(1)
    assert "files" not in networks
    assert "graph" not in networks
