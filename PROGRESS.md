# AstraRH progress log

**Single running log of the build.** Updated after every completed step, so work can resume at any moment, including after a context reset.

## Resume here

**If you are resuming after a context reset, read in this order:** this section → `docs/PLAN.md` (the approved plan, full detail) → `docs/ARCHITECTURE.md`.

- **Current phase:** P0 complete and committed. Waiting for Oussema's go for P1.
- **Exact next action:** on Oussema's go, start **P1 Infra**: create `ops/compose.yaml` (web, api, worker, executor, ml, postgres + pgvector, neo4j, minio, mailpit, otel-lgtm, caddy), separate Docker networks with `ml` on an `internal` network, per-process Postgres roles in `ops/postgres/`, `.env.example` with no values, and the `astra.py` task runner. Done when `python astra.py up` is healthy and a test trace reaches Grafana.
- **Before P1:** Docker Desktop must be running. It was stopped at the end of P0.
- **Working style Oussema asked for:** one phase at a time. At the end of each phase, report what was verified and **exactly what to send the team**, then wait for go. Keep this file detailed.

## Phase status

| Phase | Status |
|---|---|
| P0 Foundation docs | **Done** |
| P1 Infra | Not started |
| P2 Kernel | Not started |
| P3 `platform-v0` | Not started |
| P4 Screening | Not started |
| P5 Communication | Not started |
| P6 Knowledge | Not started |
| P7 AstraGraph | Not started |
| P8 Integration and proof | Not started |

## Facts to remember

- **Hackathon:** Astropreneur SupCom "Secure AI HR System". About 15 h remained when the plan was approved (2026-10-31, evening). Deliverables: source, README, 5-minute demo. Brief: `docs/brief/hackathon-bool.pdf`.
- **Team:** Oussema (lead, kernel and `talent`), Wassim (`journey`), finance owner (`finance`), workforce owner (`workforce` and design system). The last two names are not known yet.
- **Models:** Groq first; Claude or OpenRouter only for hard cases. Oussema's Groq plan limits are unverified.
- **Machine:** Windows 11, PowerShell. Git 2.55, Docker 29.6, Compose 5.3, Python 3.13, Node 24, `gh` installed. **`make` is not installed.**
- **Git identity** is set for this repo only. No remote yet; Oussema must give the GitHub URL before pushing.

## Decisions log

Plan decisions are in `docs/PLAN.md` §2. Changes and additions since approval:

| Date | Decision | Why |
|---|---|---|
| 2026-10-31 | **`python astra.py <command>` replaces `make`** everywhere the plan says `make X` | `make` isn't on this Windows machine and teammates' systems are unknown. Python runs everywhere |
| 2026-10-31 | **Shared fictional company in `docs/handoff/DEMO_WORLD.md`, with stable IDs** | Seed data prepared separately must join up for the cross-service demo |
| 2026-10-31 | **`docs/PLAN.md` is a copy of the approved plan** | The original is outside the repo. In the repo it survives and teammates can read it |

## Log

### P0 Foundation docs: 2026-10-31

**Done**
- `git init` on `main`, `.gitignore` covering secrets and generated files.
- `.gitattributes`: LF everywhere for Linux containers, and PDFs and images marked binary. Added after Git's line-ending warning flagged the brief PDF as text, which could have corrupted it on checkout.
- Moved the brief to `docs/brief/` and the research to `docs/research/`; removed the empty old folders.
- Wrote `docs/PLAN.md`, `docs/ARCHITECTURE.md`.
- Wrote team material in `docs/handoff/`: `00-SEND-NOW.md`, `DEMO_WORLD.md`, `journey.md`, `finance.md`, `workforce.md`.

**Open items**
- GitHub remote URL needed from Oussema before anything can be pushed (latest at P3).
- Names of the finance and workforce owners, for CODEOWNERS at P3.
- Pitch cost figures come from secondary blogs and must be checked at the original source before going on slides.
