#!/usr/bin/env python3
"""AstraRH task runner. Standard library only, same commands on Windows, macOS and Linux.

    python astra.py init             create .env with generated secrets
    python astra.py up [--secure]    build and start (--secure: no dev ports or live reload)
    python astra.py down [--wipe]    stop (--wipe: also delete all local data)
    python astra.py ps               show service status
    python astra.py logs [service]   follow logs
    python astra.py check            lint and unit tests
    python astra.py smoke            verify health, isolation, permissions and telemetry
"""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
EDGE_URL = "http://127.0.0.1:8080"
GRAFANA_URL = "http://127.0.0.1:3001"
HEALTHY_SERVICES = ["postgres", "neo4j", "ml", "api", "worker", "executor", "web", "otel-lgtm"]
RUNNING_SERVICES = ["caddy", "minio", "mailpit"]
TRACED_SERVICES = ["astra-api", "astra-worker", "astra-executor", "astra-ml"]


def compose_args(secure: bool = False) -> list[str]:
    files = ["-f", "ops/compose.yaml"]
    if not secure:
        files += ["-f", "ops/compose.dev.yaml"]
    return ["docker", "compose", "--project-directory", ".", "--env-file", ".env", *files]


def compose(*args: str, secure: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    # Compose prefers shell variables over --env-file. .env must win, or a stray
    # ANTHROPIC_API_KEY in someone's shell silently replaces the project's key.
    env = {**os.environ, **read_env()}
    return subprocess.run(  # noqa: S603 - fixed command, arguments come from this script
        [*compose_args(secure), *args],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=False,
    )


def require_env() -> None:
    if not ENV_FILE.exists():
        sys.exit("No .env yet. Run: python astra.py init")


def read_env() -> dict[str, str]:
    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def cmd_init(_: argparse.Namespace) -> int:
    existing = read_env() if ENV_FILE.exists() else {}
    lines = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if not match:
            lines.append(line)
            continue
        key, default = match.groups()
        if existing.get(key):
            value = existing[key]
        elif default == "__generate__":
            value = secrets.token_urlsafe(24)
        else:
            value = default
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    env = read_env()
    print(".env ready.")
    if not env.get("ANTHROPIC_API_KEY") and not env.get("GROQ_API_KEY"):
        print("Add an LLM key to .env before running AI features. See docs/SETUP.md.")
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    require_env()
    result = compose("up", "--build", "--detach", "--wait", "--wait-timeout", "420", secure=args.secure)
    if result.returncode == 0:
        print(f"\nAstraRH: {EDGE_URL}\nGrafana: {GRAFANA_URL}")
        if not args.secure:
            print("Mail:    http://127.0.0.1:8025\nNeo4j:   http://127.0.0.1:7474\nMinIO:   http://127.0.0.1:9001")
    return result.returncode


def cmd_down(args: argparse.Namespace) -> int:
    require_env()
    if args.wipe:
        return compose("down", "--volumes", "--remove-orphans").returncode
    return compose("down", "--remove-orphans").returncode


def cmd_ps(_: argparse.Namespace) -> int:
    require_env()
    return compose("ps", "--all").returncode


def cmd_logs(args: argparse.Namespace) -> int:
    require_env()
    extra = [args.service] if args.service else []
    return compose("logs", "--follow", "--tail", "100", *extra).returncode


def cmd_check(_: argparse.Namespace) -> int:
    require_env()
    failed = 0
    for tool_args in (
        ["ruff", "check", "--no-cache", "apps", "packages", "tests"],
        ["pytest", "-q", "-p", "no:cacheprovider"],
    ):
        failed |= compose("exec", "-T", "api", *tool_args).returncode
    return failed


class Smoke:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        suffix = f"  ({detail})" if detail else ""
        print(f"  {'PASS' if passed else 'FAIL'}  {label}{suffix}")
        self.failures += 0 if passed else 1


def service_python(service: str, code: str) -> subprocess.CompletedProcess:
    return compose("exec", "-T", service, "python", "-c", code, capture=True)


def can_reach(service: str, host: str, port: int) -> bool:
    code = f"import socket; socket.create_connection(({host!r}, {port}), timeout=4).close()"
    return service_python(service, code).returncode == 0


def env_var_present(service: str, name: str) -> bool:
    code = f"import os,sys; sys.exit(0 if os.environ.get({name!r}) else 1)"
    return service_python(service, code).returncode == 0


def http_json(url: str, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers or {})  # noqa: S310 - local URLs only
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 0, {}


def postgres_allows(role: str, password: str, sql: str) -> bool:
    result = compose(
        "exec", "-T", "-e", f"PGPASSWORD={password}", "postgres",
        "psql", "-h", "127.0.0.1", "-U", role, "-d", "astra", "-tAc", sql,
        capture=True,
    )
    return result.returncode == 0


def trace_found(service: str) -> bool:
    credentials = b64encode(b"admin:admin").decode()
    query = urllib.parse.urlencode({"tags": f"service.name={service}", "limit": 1})
    url = f"{GRAFANA_URL}/api/datasources/proxy/uid/tempo/api/search?{query}"
    status, body = http_json(url, {"Authorization": f"Basic {credentials}"})
    return status == 200 and bool(body.get("traces"))


def smoke_health(s: Smoke) -> None:
    print("\nHealth")
    result = compose("ps", "--all", "--format", "json", capture=True)
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    state = {row["Service"]: row for row in rows}
    for name in HEALTHY_SERVICES:
        health = state.get(name, {}).get("Health", "missing")
        s.check(f"{name} healthy", health == "healthy", "" if health == "healthy" else health)
    for name in RUNNING_SERVICES:
        running = state.get(name, {}).get("State", "missing")
        s.check(f"{name} running", running == "running", "" if running == "running" else running)

    status, body = http_json(f"{EDGE_URL}/api/readyz")
    s.check("API ready through the edge", status == 200, json.dumps(body))
    s.check("Neo4j connected", body.get("graph") == "ok", str(body.get("graph")))
    status, _ = http_json(f"{EDGE_URL}/healthz")
    s.check("Web reachable through the edge", status == 200)
    request = urllib.request.Request(f"{EDGE_URL}/api/healthz")  # noqa: S310
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        s.check("Security headers present", "Content-Security-Policy" in response.headers)


def smoke_isolation(s: Smoke) -> None:
    print("\nNetwork isolation")
    for service in ["api", "executor", "ml"]:
        s.check(f"{service} has no internet", not can_reach(service, "1.1.1.1", 443))
    s.check("worker can reach the LLM provider", can_reach("worker", "api.anthropic.com", 443))
    s.check("ml cannot reach Postgres", not can_reach("ml", "postgres", 5432))
    s.check("executor cannot reach Neo4j", not can_reach("executor", "neo4j", 7687))
    s.check("executor cannot reach files", not can_reach("executor", "minio", 9000))
    s.check("worker cannot reach mail", not can_reach("worker", "mailpit", 1025))
    s.check("executor can reach mail", can_reach("executor", "mailpit", 1025))

    print("\nCredential isolation")
    for service in ["api", "executor", "ml"]:
        s.check(f"{service} holds no LLM key", not env_var_present(service, "ANTHROPIC_API_KEY"))
    s.check("worker holds no mail settings", not env_var_present("worker", "SMTP_HOST"))
    s.check("executor holds no Neo4j password", not env_var_present("executor", "NEO4J_PASSWORD"))
    s.check("worker holds an LLM key", env_var_present("worker", "ANTHROPIC_API_KEY"))
    env_exposed = service_python("api", "import os,sys; sys.exit(0 if os.path.exists('/app/.env') else 1)")
    s.check(".env is not inside containers", env_exposed.returncode != 0)


def smoke_database(s: Smoke) -> None:
    print("\nDatabase permissions")
    env = read_env()
    api_pw, exec_pw = env["ASTRA_API_PASSWORD"], env["ASTRA_EXECUTOR_PASSWORD"]
    owner_pw = env["ASTRA_OWNER_PASSWORD"]
    create = "CREATE TABLE talent.zz_smoke(id int); DROP TABLE talent.zz_smoke;"
    s.check("owner can create tables", postgres_allows("astra_owner", owner_pw, create))
    s.check("api cannot create tables", not postgres_allows("astra_api", api_pw, create))
    usage = "SELECT 1/has_schema_privilege('talent','USAGE')::int;"
    s.check("api can use the talent schema", postgres_allows("astra_api", api_pw, usage))
    s.check("executor cannot use the talent schema", not postgres_allows("astra_executor", exec_pw, usage))
    flags = (
        "SELECT 1/(count(*)=0)::int FROM pg_roles "
        "WHERE rolname LIKE 'astra_%' AND (rolsuper OR rolbypassrls);"
    )
    s.check("no app role can bypass row-level security", postgres_allows("astra_owner", owner_pw, flags))
    vector = "SELECT 1/count(*)::int FROM pg_extension WHERE extname='vector';"
    s.check("pgvector installed", postgres_allows("astra_owner", owner_pw, vector))


def smoke_telemetry(s: Smoke) -> None:
    print("\nTelemetry (waits up to 2 minutes for first traces)")
    pending = list(TRACED_SERVICES)
    for _ in range(4):
        http_json(f"{EDGE_URL}/api/readyz")
    deadline = time.monotonic() + 120
    while pending and time.monotonic() < deadline:
        pending = [service for service in pending if not trace_found(service)]
        if pending:
            http_json(f"{EDGE_URL}/api/readyz")
            time.sleep(5)
    for service in TRACED_SERVICES:
        s.check(f"{service} traces in Grafana", service not in pending)


def cmd_smoke(_: argparse.Namespace) -> int:
    require_env()
    smoke = Smoke()
    smoke_health(smoke)
    smoke_isolation(smoke)
    smoke_database(smoke)
    smoke_telemetry(smoke)
    print(f"\n{'ALL PASSED' if not smoke.failures else f'{smoke.failures} FAILED'}")
    return 1 if smoke.failures else 0


def main() -> int:
    if not shutil.which("docker"):
        sys.exit("Docker is required: https://www.docker.com/products/docker-desktop/")
    parser = argparse.ArgumentParser(description="AstraRH task runner")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(run=cmd_init)
    up = commands.add_parser("up")
    up.add_argument("--secure", action="store_true", help="no dev ports or live reload")
    up.set_defaults(run=cmd_up)
    down = commands.add_parser("down")
    down.add_argument("--wipe", action="store_true", help="also delete all local data")
    down.set_defaults(run=cmd_down)
    commands.add_parser("ps").set_defaults(run=cmd_ps)
    logs = commands.add_parser("logs")
    logs.add_argument("service", nargs="?")
    logs.set_defaults(run=cmd_logs)
    commands.add_parser("check").set_defaults(run=cmd_check)
    commands.add_parser("smoke").set_defaults(run=cmd_smoke)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
