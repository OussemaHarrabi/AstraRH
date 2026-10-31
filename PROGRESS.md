# AstraRH progress log

**Single running log of the build.** Updated after every completed step, so work can resume at any moment, including after a context reset.

## Resume here

**If you are resuming after a context reset, read in this order:** this section → `docs/PLAN.md` (the approved plan, full detail) → `docs/ARCHITECTURE.md` → `docs/SETUP.md`.

- **Current phase:** P1 complete, committed and pushed. Waiting for Oussema's go for P2.
- **Exact next action:** on Oussema's go, start **P2 Kernel** in `packages/kernel/`. Add SQLAlchemy, Alembic with per-pack branches, Pydantic and Procrastinate to `pyproject.toml`. Build in this order: `tenancy/identity/authz` → `people` → `trust` → `explain` → `events/jobs` → `ai` (load the `claude-api` skill before writing the gateway) → `graph` → `registry`. `obs` is already started. Done when the trust path and explainability tests in `docs/PLAN.md` §15 pass.
- **Working style Oussema asked for:**
  - One phase at a time. At the end of each, report what was verified and **exactly what to send the team**, then wait for go.
  - Keep this file detailed.
  - **Never swap a planned component for something weaker without asking.** Retry, then bring options.
  - **Commit as `OussemaHarrabi` only**, with no Claude attribution.

## Phase status

| Phase | Status |
|---|---|
| P0 Foundation docs | **Done** |
| P1 Infra | **Done** |
| P2 Kernel | Next |
| P3 `platform-v0` | Not started |
| P4 Screening | Not started |
| P5 Communication | Not started |
| P6 Knowledge | Not started |
| P7 AstraGraph | Not started |
| P8 Integration and proof | Not started |

## Facts to remember

- **Hackathon:** Astropreneur SupCom "Secure AI HR System". About 15 h remained when the plan was approved (2026-10-31, evening). Deliverables: source, README, 5-minute demo. Brief: `docs/brief/hackathon-bool.pdf`.
- **Team:** Oussema (lead, kernel and `talent`), Wassim (`journey`), finance owner (`finance`), workforce owner (`workforce` and design system). The last two names are not known yet.
- **Repo:** https://github.com/OussemaHarrabi/AstraRH (private). Branch `main`.
- **Machine:** Windows 11, PowerShell, 16 CPUs, 7.8 GB for Docker. `make` is not installed. Another project (`claimguard-db`) holds host port 5432, so ours is 55432. Don't touch it.
- **Keys:** in the git-ignored `.env`; Oussema will rotate them later. Never write them anywhere else.
- **Shell trap:** this machine's shell has its own different `ANTHROPIC_API_KEY`. `astra.py` makes `.env` win; plain `docker compose` would use the wrong key and get a 401.

## Model facts, tested 2026-10-31

| Provider | Finding |
|---|---|
| Anthropic | Key works. `claude-haiku-5-5` confirmed end to end from the worker container. **Oussema asked for Haiku only**, not Sonnet or Opus |
| Groq | Key works, strict JSON schema works on `gpt-oss-20b` and `gpt-oss-120b`. **Limits are only 8,000 tokens/min and about 1,000 requests/day**, far under the plan's assumed 250K/1K |

**Consequence:** Haiku is the primary model for `fast` and `standard`. Groq `gpt-oss-20b` is the fallback, and its prompt guard is one injection layer. Any Groq use must be batched and cached. Cost and token use must be tracked in the gateway so Anthropic quota isn't burned silently.

## Decisions log

Plan decisions are in `docs/PLAN.md` §2. Changes and additions since approval:

| Date | Decision | Why |
|---|---|---|
| 2026-10-31 | **`python astra.py <command>` replaces `make`** everywhere the plan says `make X` | `make` isn't on this machine and teammates' systems are unknown |
| 2026-10-31 | **Shared fictional company in `docs/handoff/DEMO_WORLD.md`** | Separately prepared seed data must join up for the demo |
| 2026-10-31 | **Haiku primary, Groq fallback** (reverses the plan's "Groq first") | Oussema's instruction to use Haiku directly for speed, and Groq's tested limits |
| 2026-10-31 | **MinIO kept, using Chainguard's image** `cgr.dev/chainguard/minio` | Upstream MinIO archived its repo and removed official images. Chainguard's build is current (RELEASE.2026-10-23). A `minio-volume-init` one-shot fixes volume ownership for its non-root user. Licence is AGPLv3: fine for running it unmodified; check before selling a hosted product. If it ever becomes a problem, the S3 API keeps replacement cheap |
| 2026-10-31 | **Next.js 16.4.3 with Tailwind.** Read `apps/web/node_modules/next/dist/docs/` before writing web code | This version has breaking changes, per its generated `AGENTS.md` |
| 2026-10-31 | **Rate limiting moves to the app (P2 login)** instead of Caddy | Standard Caddy has no rate-limit module; a custom build isn't worth the time |
| 2026-10-31 | **TLS deferred to real deployment.** The demo runs on loopback HTTP, with secure cookies switched by environment | Local certificates cause browser warnings during the demo |
| 2026-10-31 | **Script CSP allows `'unsafe-inline'` for now; tighten with nonces in P8** | Next.js needs inline scripts without a nonce setup. It's a known weak spot and must be revisited |

## Log

### P1 Infra: 2026-10-31

**Built**
- `ops/compose.yaml`: caddy, web, api, worker, executor, ml, postgres + pgvector, neo4j, minio, mailpit, otel-lgtm. Third-party images are pinned by digest. Memory limits suit a 7.8 GB host.
- `ops/compose.dev.yaml`: live reload and loopback tool ports. It mounts named folders only, so `.env` never enters a container.
- Networks: `edge_internal`, `data`, `graph`, `files`, `ml`, `mail` and `telemetry` are internal. Only `worker` gets `llm_egress`.
- `ops/postgres/init/01-init.sh`: roles `astra_owner`, `astra_api`, `astra_worker`, `astra_executor`, none with superuser or BYPASSRLS; ten schemas; executor limited to `trust`; pgvector and pg_trgm.
- `ops/caddy/Caddyfile`: security headers, CSP, 25 MB body cap.
- `astra.py`: `init`, `up [--secure]`, `down [--wipe]`, `ps`, `logs`, `check`, `smoke`.
- Process skeletons in `apps/`, `packages/kernel/obs.py` (traces, metrics, logs over OTLP), `kernel/heartbeat.py`.
- `apps/web`: Next.js 16 with `/healthz` and a placeholder page.
- `tests/test_compose_boundaries.py`, `docs/SETUP.md`.

**Verified**
- `python astra.py smoke` passes all 41 checks in **dev and `--secure`** modes: health, no internet from api/executor/ml, credential isolation, database permissions, traces from all four Python services in Tempo.
- `python astra.py check`: ruff clean, 5 tests pass.
- Stopping Neo4j gives `/readyz` = ready with graph `degraded`; nothing else fails.
- Secure mode: all tool ports closed, production web build serves, CSP has no `unsafe-eval`, api runs read-only, non-root, with all capabilities dropped.
- Haiku call succeeded from inside `worker`.
- Secret scan of tracked files before push: clean.

**Not verified yet**
- Setup on a fresh clone or another machine (P3 foundation gate; teammates will exercise it sooner).
- macOS or Linux hosts.
- MinIO file operations beyond its health endpoint (no bucket yet; `kernel.files` is P2/P4).
- Web service telemetry: only the Python services emit traces so far. Add in P3.

**Problems hit and fixes**
- Host port 5432 taken → our dev port is 55432.
- `--no-dev` overrode `--group dev`, then `${VAR:-}` passed a literal `1` → explicit shell conditional in the Dockerfile.
- Worker got the shell's Anthropic key instead of `.env`'s → `astra.py` merges `.env` over the environment.

**Open items**
- Names of the finance and workforce owners, for CODEOWNERS at P3.
- Pitch cost figures come from secondary blogs and must be checked at the source before going on slides.
- Docker has 7.8 GB and otel-lgtm uses about 1.2 GB. Docling and embeddings arrive in P4 and may need limits revisited.

### P0 Foundation docs: 2026-10-31

**Done**
- `git init` on `main`, `.gitignore`, `.gitattributes` (LF for containers, binary protection).
- Moved the brief to `docs/brief/` and research to `docs/research/`.
- Wrote `docs/PLAN.md`, `docs/ARCHITECTURE.md`, and team material in `docs/handoff/`.
- Rewrote the first two commits to remove co-author lines, before anything was pushed, as Oussema asked.
