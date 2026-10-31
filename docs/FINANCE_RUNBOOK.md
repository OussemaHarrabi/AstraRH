# Finance pack: runbook for macOS

How to start the stack, run the finance tests, and what to do when something fails. Part of the [finance documentation](FINANCE_INDEX.md). The general setup is in [SETUP.md](SETUP.md), which was written on Windows. This file records what differs on macOS and what was actually observed.

## 1. What you need

- Docker Desktop, **running**, with at least 8 GB of memory (Settings, Resources). Observed: 8.3 GB, 10 CPUs.
- Git, and Python 3 only to run `astra.py` (Python 3.14 worked, `astra.py` needs no packages). **No local Python 3.12 or `uv` is needed**: everything else runs in containers.
- LLM keys are **not needed** for finance while AI work is paused (decision D14). Leave them empty in `.env`.

## 2. First start

```bash
python3 astra.py init     # writes .env with generated secrets. Git-ignored. Never commit it
python3 astra.py up       # builds and starts everything. First run downloads images
python3 astra.py smoke    # health, isolation, permissions, telemetry, one end-to-end flow
python3 astra.py check    # lint and the full test suite, run in a container
```

Ports used on the host: 8080 (app), 3001 (Grafana), 8025 (mail), 7474 and 7687 (Neo4j), 9001 (MinIO), 55432 (Postgres). Another project using 5432 or 6379 does not conflict.

## 3. Known issue on macOS: the database init script does not run

**Symptom.** `up` ends with `service "migrate" didn't complete successfully`. The migrate log says `password authentication failed for user "astra_owner"`. The Postgres log, on first start, says `01-init.sh: /bin/bash: bad interpreter: Permission denied`, and the next start says `Skipping initialization`.

**Cause.** The script is mounted from the host into the Postgres container. On Docker Desktop for Mac the mount makes the entrypoint treat the file as executable although it is not, so it tries to run it and fails. The roles and schemas are never created. The repo was built on Windows, where this does not happen.

**Workaround used (changes nothing in the repo and loses no data):**

```bash
docker exec -i astrarh-postgres-1 bash -s < ops/postgres/init/01-init.sh
python3 astra.py up
```

This feeds the same script to bash through standard input. It creates the four roles (`astra_owner`, `astra_api`, `astra_worker`, `astra_executor`) and all ten schemas, including `finance`. Check with:

```bash
docker exec astrarh-postgres-1 psql -U postgres -d astra -Atc "select rolname from pg_roles where rolname like 'astra_%'"
```

If the database is brand new and holds nothing you need, `python3 astra.py down --wipe` followed by the workaround above also works. **`--wipe` deletes all local data.**

**Proper fix (kernel and ops owner).** Make the init step independent of the file's execute bit, for example by calling it through `bash` in a one-line `.sh` wrapper that the entrypoint sources, or by turning it into a SQL file with the passwords supplied another way. Raised as request **K8** in [FINANCE_PAYMENT_DESIGN.md](FINANCE_PAYMENT_DESIGN.md) section 8.

## 4. Baseline observed on 2026-10-31

| Check | Result |
|---|---|
| `python3 astra.py up` | All services healthy after the workaround |
| `python3 astra.py smoke` | All pass except **"worker holds an LLM key"**, which fails only because the keys are empty. This is expected while AI is paused |
| `python3 astra.py check` | **288 passed, 2 skipped** (the platform's 253 plus 35 finance calculation tests) |

## 5. Running only the finance calculation tests

They need no database. From the repository root, in any Python environment that has `pytest`:

```bash
PYTHONPATH=packages python -m pytest --noconftest -q tests/test_finance_calc.py
```

`--noconftest` skips the platform fixtures, which need the stack. The same tests also run inside `astra.py check`.

## 6. Everyday commands

| Command | Does |
|---|---|
| `python3 astra.py ps` | Status of every service |
| `python3 astra.py logs <service>` | Follow a service's log (`migrate`, `api`, `worker`, `executor`) |
| `python3 astra.py down` | Stop, keep data |
| `python3 astra.py down --wipe` | Stop and delete all local data |
| `python3 astra.py makemigration finance "message"` | Generate a finance migration (once the pack has tables) |
| `python3 astra.py export-api` | Regenerate `contracts/openapi.json` |

## 7. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop is not running. Start it |
| `migrate` fails with a password error | Section 3 |
| Port already in use | Another program holds it. Stop it or change the left-hand number in `ops/compose.dev.yaml` locally |
| A test fails only for finance | Run section 5 first to separate calculation errors from database ones |
| Wrong database passwords after editing `.env` | Postgres keeps the original ones. Use `down --wipe`, then start again |
