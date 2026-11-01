#!/usr/bin/env python3
"""AstraRH task runner. Standard library only, same commands on Windows, macOS and Linux.

python astra.py init             create .env with generated secrets
python astra.py up [--secure]    build and start (--secure: no dev ports or live reload)
python astra.py down [--wipe]    stop (--wipe: also delete all local data)
python astra.py ps               show service status
python astra.py logs [service]   follow logs
python astra.py check [args]     lint and all tests (args pass to pytest)
python astra.py seed [--no-cvs]  load the demo company and CVs
python astra.py evals            measure ranking quality with real models
python astra.py export-api       write contracts/openapi.json
python astra.py live             one real model call, to test your LLM key
python astra.py makemigration <kernel|pack> "message"
python astra.py graph-rebuild    rebuild Neo4j from the event log
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
    result = compose(
        "up", "--build", "--detach", "--wait", "--wait-timeout", "420", secure=args.secure
    )
    if result.returncode == 0:
        print(f"\nAstraRH: {EDGE_URL}\nGrafana: {GRAFANA_URL}")
        if not args.secure:
            print(
                "Mail:    http://127.0.0.1:8025\nNeo4j:   http://127.0.0.1:7474\nMinIO:   http://127.0.0.1:9001"
            )
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


def cmd_check(args: argparse.Namespace) -> int:
    require_env()
    run_tool = ("run", "--rm", "--build", "--no-deps", "tests")
    failed = compose(
        *run_tool, "ruff", "check", "--no-cache", "apps", "packages", "tests"
    ).returncode
    failed |= compose(
        *run_tool, "pytest", "-q", "-p", "no:cacheprovider", *args.pytest_args
    ).returncode
    return failed


def cmd_seed(args: argparse.Namespace) -> int:
    """Load the fictional company, then send the demo CVs through the real pipeline."""
    require_env()
    code = compose("run", "--rm", "--no-deps", "migrate", "python", "-m", "kernel.seed").returncode
    if code or args.no_cvs:
        return code
    code = compose("exec", "-T", "worker", "python", "-m", "packs.talent.load_demo").returncode
    if code:
        return code
    code = compose("exec", "-T", "worker", "python", "-m", "kernel.knowledge.load_demo").returncode
    if code:
        return code
    return compose("exec", "-T", "worker", "python", "-m", "kernel.comms.load_demo").returncode


def cmd_export_api(_: argparse.Namespace) -> int:
    """Write the OpenAPI document that docs/API.md points to."""
    require_env()
    code = "import json; from apps.api.main import app; print(json.dumps(app.openapi(), indent=2))"
    result = compose("exec", "-T", "api", "python", "-c", code, capture=True)
    if result.returncode:
        print(result.stderr)
        return result.returncode
    target = ROOT / "contracts" / "openapi.json"
    target.parent.mkdir(exist_ok=True)
    start = result.stdout.index("{")
    target.write_text(result.stdout[start:], encoding="utf-8", newline="\n")
    print(f"Wrote {target}")
    return 0


def _run_eval(module: str, filename: str) -> int:
    result = compose("run", "--rm", "--no-deps", "tests", "python", "-m", module, capture=True)
    print(result.stdout)
    if result.returncode:
        print(result.stderr[-3000:])
        return result.returncode
    marker = "EVAL_RESULT_JSON:"
    line = next(x for x in result.stdout.splitlines() if x.startswith(marker))
    target = ROOT / "docs" / "evals" / filename
    target.parent.mkdir(exist_ok=True)
    report = json.dumps(json.loads(line[len(marker) :]), indent=2, ensure_ascii=False)
    target.write_text(f"{report}\n", encoding="utf-8", newline="\n")
    print(f"Saved {target}")
    return 0


def cmd_evals(_: argparse.Namespace) -> int:
    """Measure ranking, inbox and policy answers with the real model. Costs about 3 cents."""
    require_env()
    return _run_eval("packs.talent.evals.screening", "screening.json") or _run_eval(
        "packs.talent.evals.communications", "communications.json"
    )


def cmd_live(_: argparse.Namespace) -> int:
    """One real model call. Spends a fraction of a cent."""
    require_env()
    return compose(
        "run",
        "--rm",
        "--no-deps",
        "-e",
        "RUN_LIVE=1",
        "tests",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/test_ai.py::test_live_haiku_returns_valid_structured_output",
    ).returncode


def cmd_makemigration(args: argparse.Namespace) -> int:
    require_env()
    return compose(
        "run",
        "--rm",
        "--build",
        "migrate",
        "python",
        "-m",
        "kernel.migrate",
        "new",
        args.scope,
        args.message,
    ).returncode


def cmd_graph_rebuild(_: argparse.Namespace) -> int:
    require_env()
    code = (
        "from kernel import graph, registry\n"
        "from kernel.db import active_tenant_ids, tenant_session\n"
        "registry.install_graph_projections()\n"
        "for tenant_id in active_tenant_ids():\n"
        "    with tenant_session(tenant_id) as session:\n"
        "        print(tenant_id, graph.rebuild(session, tenant_id), 'events replayed')\n"
    )
    return compose("exec", "-T", "worker", "python", "-c", code).returncode


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
        "exec",
        "-T",
        "-e",
        f"PGPASSWORD={password}",
        "postgres",
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        role,
        "-d",
        "astra",
        "-tAc",
        sql,
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
    for service in ["api", "executor"]:
        no_sdk = service_python(service, "import anthropic")
        s.check(f"{service} image has no LLM library", no_sdk.returncode != 0)
    has_sdk = service_python("worker", "import anthropic, langgraph")
    s.check("worker image has the LLM libraries", has_sdk.returncode == 0)
    env_exposed = service_python(
        "api", "import os,sys; sys.exit(0 if os.path.exists('/app/.env') else 1)"
    )
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
    s.check(
        "executor cannot use the talent schema",
        not postgres_allows("astra_executor", exec_pw, usage),
    )
    flags = (
        "SELECT 1/(count(*)=0)::int FROM pg_roles "
        "WHERE rolname LIKE 'astra_%' AND (rolsuper OR rolbypassrls);"
    )
    s.check(
        "no app role can bypass row-level security", postgres_allows("astra_owner", owner_pw, flags)
    )
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


def smoke_end_to_end(s: Smoke) -> None:
    print("\nEnd to end (real worker, executor, mailbox and graph)")
    result = compose(
        "run",
        "--rm",
        "--no-deps",
        "--quiet-pull",
        "-e",
        "RUN_LIVE_STACK=1",
        "tests",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/test_live_stack.py",
        capture=True,
    )
    s.check("approve, execute, send, audit and project", result.returncode == 0)
    if result.returncode != 0:
        print(result.stdout[-2000:])


def cmd_smoke(_: argparse.Namespace) -> int:
    require_env()
    smoke = Smoke()
    smoke_health(smoke)
    smoke_isolation(smoke)
    smoke_database(smoke)
    smoke_telemetry(smoke)
    smoke_end_to_end(smoke)
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
    check = commands.add_parser("check")
    check.add_argument("pytest_args", nargs="*")
    check.set_defaults(run=cmd_check)
    commands.add_parser("live").set_defaults(run=cmd_live)
    seed = commands.add_parser("seed")
    seed.add_argument("--no-cvs", action="store_true", help="skip uploading the demo CVs")
    seed.set_defaults(run=cmd_seed)
    commands.add_parser("export-api").set_defaults(run=cmd_export_api)
    commands.add_parser("evals").set_defaults(run=cmd_evals)
    migration = commands.add_parser("makemigration")
    migration.add_argument("scope", help="kernel or a pack id")
    migration.add_argument("message")
    migration.set_defaults(run=cmd_makemigration)
    commands.add_parser("graph-rebuild").set_defaults(run=cmd_graph_rebuild)
    commands.add_parser("smoke").set_defaults(run=cmd_smoke)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
