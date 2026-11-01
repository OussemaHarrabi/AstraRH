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

## 3. macOS: the database init step (fixed on 2026-11-01)

**What used to happen.** The roles and schemas were created by `ops/postgres/init/01-init.sh`, mounted into the Postgres container. Docker Desktop for Mac reports that file as executable but cannot run it, so the first start failed with `01-init.sh: /bin/bash: bad interpreter: Permission denied`. The roles were never created, and `migrate` then failed with `password authentication failed for user "astra_owner"`.

**The fix.** The script is now `ops/postgres/init/01-init.sql`. The Postgres entrypoint reads `.sql` files with `psql`, so nothing has to be executable, and it behaves the same on macOS, Windows and Linux. The passwords are read from the container environment with psql's `\getenv`. The SQL body is unchanged.

**How it was verified, on this Mac, without touching the running stack:**
- A throwaway Postgres container with an empty volume ran `01-init.sql` through the normal entrypoint and completed.
- A second throwaway database, built with the **old** script fed through standard input, was compared with it: 39 facts (4 roles and their flags, 11 schemas with owners and permissions, 20 default-permission rules, extensions, database grants) are **identical**.
- The API role logged in with its password.
- With one password missing, initialisation **stops** with an error (exit code 3) instead of creating a role with an empty password.

**If your database was created before the fix** and `migrate` fails with a password error, the init step never ran. Either run it once by hand, which keeps your data:

```bash
docker exec -i astrarh-postgres-1 psql -v ON_ERROR_STOP=1 -U postgres -d astra < ops/postgres/init/01-init.sql
python3 astra.py up
```

or, if the database holds nothing you need, `python3 astra.py down --wipe` then `python3 astra.py up`. **`--wipe` deletes all local data.**

## 4. Baseline observed on 2026-10-31 (first run) and 2026-11-01 (after rebasing onto the latest `main`)

| Check | Result |
|---|---|
| `python3 astra.py up` | All services healthy after the workaround |
| `python3 astra.py smoke` | All pass except **"worker holds an LLM key"**, which fails only because the keys are empty. This is expected while AI is paused |
| `python3 astra.py check` | First run, 2026-10-31: **288 passed, 2 skipped** (the platform's 253 plus 35 finance calculation tests). After the finance work and the rebase onto `main` `63529ca`, 2026-11-01: **420 passed, 2 skipped, 1 expected failure** (the K9 test) |
| Migrations | Database at `kernel_0006`, `talent_0004`, `finance_0003` (2026-11-01), then `finance_0004` after the engagement work (**518 passed**), then `finance_0005` after payroll inputs (**678 passed**), then up to `finance_0006` after payroll runs, when `check` gave **748 passed, 2 skipped, 5 expected failures** |

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
