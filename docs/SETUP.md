# Setup

Takes about 10 minutes the first time, mostly image downloads.

## 1. Install

- **Docker Desktop**, running. Give it at least 8 GB of memory (Settings → Resources).
- **Git**
- **Python 3.12+**, only to run `astra.py`. It needs no packages.
- **Node 22+**, only if you run web tooling outside Docker.

## 2. Get the code and start it

```bash
git clone https://github.com/OussemaHarrabi/AstraRH.git
```

```bash
cd AstraRH
```

```bash
python astra.py init
```

Then open `.env` and fill in the LLM keys Oussema gives you. **Never paste keys in chat or commit them.** Everything else in `.env` is generated for you.

```bash
python astra.py up
```

```bash
python astra.py smoke
```

When smoke ends with `ALL PASSED`, you're ready.

## 3. Where things are

| What | URL |
|---|---|
| AstraRH | http://127.0.0.1:8080 |
| Grafana (traces, logs, metrics) | http://127.0.0.1:3001 |
| Fake mailbox | http://127.0.0.1:8025 |
| Neo4j browser | http://127.0.0.1:7474 |
| MinIO console | http://127.0.0.1:9001 |
| Postgres | `127.0.0.1:55432`, database `astra` |

Passwords are in your `.env`.

## 4. Commands

| Command | Does |
|---|---|
| `python astra.py up` | Build and start with live code reload |
| `python astra.py up --secure` | Hardened mode: no tool ports, production web build |
| `python astra.py down` | Stop, keeping data |
| `python astra.py down --wipe` | Stop and **delete all local data** |
| `python astra.py ps` | Status |
| `python astra.py logs [service]` | Follow logs |
| `python astra.py check` | Lint and all tests. Run before every PR |
| `python astra.py smoke` | Verify health, isolation, permissions, telemetry and one real end-to-end flow |
| `python astra.py live` | One real model call, to test your LLM key |
| `python astra.py makemigration <kernel\|pack> "message"` | Generate a database migration |
| `python astra.py graph-rebuild` | Rebuild Neo4j from the event log |

## 5. Troubleshooting

- **Port already in use:** another program holds a port from the table above. Stop it, or change the left-hand number in `ops/compose.dev.yaml` locally.
- **Wrong API key used:** `astra.py` makes `.env` win over shell variables. Plain `docker compose` does not, so always go through `astra.py`.
- **Service unhealthy:** run `python astra.py ps`, then `python astra.py logs <service>`.
- **Database passwords changed after first start:** Postgres keeps the original ones, so `python astra.py down --wipe` and start again.
