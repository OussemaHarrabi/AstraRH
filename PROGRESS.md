# AstraRH progress log

**Single running log of the build.** Updated after every completed step, so work can resume at any moment, including after a context reset.

## Resume here

**If you are resuming after a context reset, read in this order:** this section → `docs/PLAN.md` (the approved plan, full detail) → `docs/ARCHITECTURE.md` → `docs/SETUP.md`.

- **Current phase:** P2 complete, committed and pushed. Waiting for Oussema's go for P3.
- **Exact next action:** on Oussema's go, start **P3 `platform-v0`**:
  1. `packages/packs/_example/`: the copy-me pack with a full flow (manifest → agent → DecisionRecord → proposal → approve → execute → audit → event → graph), including its migration (`depends_on` kernel), `seed.py`, tests and an eval.
  2. Stub packs `talent`, `journey`, `finance`, `workforce`: manifest, one table, one route, one page, one event, status `preview`.
  3. `astra.py seed` loading the demo world from `docs/handoff/DEMO_WORLD.md` and teammates' `seed/` files, with a demo tenant and users for each role. Also `astra.py new-pack`.
  4. Web shell: login, manifest-driven dashboard and nav, approval inbox with edit/approve/reject and step-up, audit timeline with verify, `<WhyPanel>`, typed client from OpenAPI, OTel for the web service. Read `apps/web/node_modules/next/dist/docs/` first.
  5. CI (GitHub Actions) with `import-linter` pack boundaries, plus `CODEOWNERS`, PR template, `AGENTS.md`/`CLAUDE.md`, `docs/PACK_GUIDE.md`, `docs/THREAT_MODEL.md`, `contracts/events/` export, agent prompts in `docs/handoff/`.
  6. Run the foundation gate in `docs/PLAN.md` §15 (fresh clone, `_example` in a browser, `new-pack` passes CI, a boundary violation fails CI), then tag `platform-v0` and push. Replace the worker and executor heartbeats' noise if traces get crowded.
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
| P2 Kernel | **Done** |
| P3 `platform-v0` | Next |
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
| 2026-10-31 | **Approved actions split into external (executor) and internal (worker), through one gate** | Refines "the executor acts": the executor's role can't write pack tables by design, yet actions like "advance a stage" must. Both use `trust.execute` with the same checks |
| 2026-10-31 | **No `strong` model tier; tiers are `fast` and `standard`, both Haiku** | Oussema asked for Haiku only. Adding a stronger tier later is a config and small code change |
| 2026-10-31 | **Agent runs end at a proposal, with no `interrupt()`** | Already in the plan; now implemented. LangGraph is for graphs with branches, and is optional per agent |
| 2026-10-31 | **Groq's remote guard is off by default (`GUARD_REMOTE=off`)** | It uses Groq's roughly 1,000 requests a day. Heuristics always run, and when on, its failure denies (fail closed). Turn on for the demo if the quota allows |
| 2026-10-31 | **Test tenants are `active=false`; background processes skip them** | Tests run against the live database, proving real role permissions, without the running worker and executor racing them |
| 2026-10-31 | **Worker serves named queues only (`kernel.jobs.WORKER_QUEUES`)** | A new queue must be added there. It also stops the live worker taking test jobs |

## Log

### P2 Kernel: 2026-10-31

**Built, in `packages/kernel/`**
- `db`, `rls`, `migrate`, `migrations/`: tenant sessions with `set_config` under RLS, Alembic with one branch per pack, revisions `e354e5b41221` (tables) and `kernel_0002` (rules in `migrations/rules/*.sql`).
- `identity`, `authz`: Argon2, JWT in an httpOnly cookie, double-submit CSRF, login lockout, step-up, scoped roles, two-key check.
- `people`: person, org, position, employee, skills with relations and evidence, KPI registry.
- `trust`: action catalogue, proposals, hash-bound approvals, gated execution, crash reconciliation, hash-chained audit.
- `explain`: decision records, exact factor sums, scorer registry, replay, counterfactuals by real re-scoring, narrative validator.
- `events`, `jobs`: transactional outbox, event catalogue, isolated deliveries with retry and dead-letter; Procrastinate in schema `jobs`.
- `ai`: sanitizer, injection guard, identifier masking, Anthropic and Groq providers, gateway (no tools parameter by design), quarantined reader with span checking, agent runtime, LangGraph checkpoints in schema `agent_ckpt`.
- `graph`, `manifest.yaml`: declarative Neo4j projections with strict label and property checks, named query templates, rebuild from the event log.
- `registry`: manifest models, catalogue sync, policy version, pack loading that survives a broken pack.
- `adapters`: mail through SMTP with a deterministic Message-ID for reconciliation.
- `web`: HTTP routes for auth, trust, explain, graph, AI runs, people and the pack registry.
- `apps/`: real worker (relay, internal actions, jobs) and executor (poll, execute, reconcile). New `migrate` one-shot service, the only holder of the owner password.

**Verified**
- `python astra.py check`: ruff clean, **160 passed, 2 skipped**. The skips are the live-stack test and the live model call, run separately below.
- `python astra.py smoke`: all checks pass, including the new end-to-end check: nothing sent before approval, then the **real executor** sends to the real mailbox, the audit chain verifies, and the **real worker** projects it into Neo4j.
- `python astra.py live`: a real Haiku structured call through the full gateway.
- §15 trust tests: edit voids approval, duplicate execute calls the provider once, crash after send produces no duplicate, unauthorized approver gets denied and audited, audit tampering detected, RLS blocks cross-tenant reads and writes.
- §15 explainability tests: no DecisionRecord means refused, factors sum exactly, replay reproduces, wrong-number narrative rejected, counterfactual matches a real re-score.
- §15 graph tests: Neo4j loss leaves trust and other consumers working, rebuild restores the graph, replay creates no duplicates, tenants stay separate, malicious text stays inert.

**Real bugs tests caught**
- Identifier masking hid CV date ranges such as 2019-2024 as phone numbers.
- Graph relationships came back with blank nodes.
- Live worker was taking test queue jobs.

**Not done or not verified**
- Kernel modules deferred to their phases: `files` (P4), `comms`, `calendar` (P5), `knowledge` (P6), `notify`.
- Presidio name detection (P4). Masking covers emails, phones, URLs and long numbers only for now.
- Prompt injection hasn't been tried against the real model yet (P4 and P8).
- Agents wired from a manifest (`register_agent`) and internal actions (`run_internal_actions`) have no end-to-end test yet: the `_example` pack in P3 is that test.
- Secure mode starts healthy after this phase's changes, but the full smoke suite ran only in dev this time.
- Test runs leave `test.*` rows in the action catalogue. They are harmless and are removed by `down --wipe`.
- The Neo4j query-language injection boundary relies on kernel templates alone, since Community Edition has no per-database permissions.

**Problems hit and fixes**
- `%` in SQL files was read as a parameter → the driver now runs rule files raw.
- The worker needs Procrastinate's async connector → `PsycopgConnector`, with sync deferring through `open()`.
- Running raw `docker compose` used the shell's wrong key again → `python astra.py live` exists for this.

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
