# AstraRH: full handoff (2026-11-01)

For an agent or person picking this project up cold. Read this file first, then `PROGRESS.md`
("Resume here" and the log), then `docs/API_CONTRACT.md`. Everything below was true on `main`
at commit `76e85f9`.

---

## 1. What we are building, and why

**Context.** Astropreneur SupCom hackathon. The brief is `docs/brief/hackathon-bool.pdf` (two
pages). The client is a fictional Tunisian company (tenant slug `cds`, "CDS Tunis"). Teams bring
their own fictional data. Deliverables: code, a README and a **5-minute live demo** in front of
a jury.

**The brief asks for an AI HR platform covering six features ("axes")**, plus a dashboard:

1. A ranked shortlist of CVs for a job, with the evidence for each score.
2. A daily digest of the HR inbox, sorted by type and urgency, with "needs a person" flags.
3. Replies to candidates drafted from that candidate's own file only, sent after approval.
4. Automatic follow-ups for candidates who go quiet.
5. Interview slots proposed from the recruiter's real calendar, then booked.
6. Employee policy questions answered with citations, or passed to HR.

**The golden rule in the brief:** "the agent executes, the human decides about people". Nothing
is sent or recorded without a person's approval. It must work end to end on real volumes. Security
is judged on three fronts: AI (prompt injection), the system, and the web app.

**Our product: AstraRH, "hire to retain on one trust layer".** A kernel provides identity, an
approval ledger, explanations, an audit chain, events, an AI gateway and a graph. Domain
"packs" plug into it: `talent` (recruitment), `journey` (onboarding and training) and `finance`
(Tunisian payroll). Agents prepare work; every action that affects a person becomes a
**proposal** that a human approves; a separate **executor** process performs the external action
(sending mail); everything lands in a hash-chained audit log.

**Priority set by Oussema:** the brief's six axes must be deep and solid first, then what the
jury will see in the demo. Teammates' packs come after. Ship fast.

---

## 2. Rules for working on this repo

These come from Oussema and override defaults.

- **Commit as `OussemaHarrabi <oussema.harrabi@supcom.tn>` only. No Claude or AI co-author or
  attribution lines** in commits or PRs.
- **Commit in small steps and push to `origin main` after each one.** Record each step in
  `PROGRESS.md` (log section) with what was verified.
- **Never silently swap a planned component for a weaker one.** Retry, then bring options.
- **Models:** Claude Haiku only (`claude-haiku-5-5`) through the kernel AI gateway. Groq
  `openai/gpt-oss-20b` is the fallback. Packs call a *tier* (`fast`, ...), never a provider.
- **Test data:** use Oussema's corpus in `data/cvs/` and `data/jobs/`. Don't generate more CVs.
- **Tell the user what was done after every push.** Keep messages short and plain.
- Use `python astra.py <cmd>`, not make.
- **Windows quirks:** the shell is Git Bash on Windows. Multi-line Python in a Bash heredoc
  breaks on quotes, so write patch scripts to the scratchpad and run them with
  `.venv/Scripts/python.exe -I <script>`. Some files have CRLF line endings, so an exact-match
  edit can fail. Set `PYTHONIOENCODING=utf-8` when printing Arabic or French.
- Querying the DB: `docker exec astrarh-postgres-1 psql -U postgres -d astra`. Don't print `.env`
  values; it holds the DB password and API keys.

---

## 3. Architecture

Full detail: `docs/ARCHITECTURE.md`, `docs/PLAN.md` (approved plan, §13 demo script, §14 phases,
§15 verification), `docs/SETUP.md`.

### Processes (Docker Compose, `ops/compose.yaml` + `ops/compose.dev.yaml`)

| Service | Role |
|---|---|
| `caddy` | Reverse proxy on `http://127.0.0.1:8080`. `/api/*` → api, the rest → web. Sets security headers (CSP, nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy). **HSTS missing.** |
| `web` | Next.js 16, React, Tailwind 4 (`apps/web`). Fonts Bricolage Grotesque + Source Sans 3. First-pass pages only. |
| `api` | FastAPI (`apps/api`, routes from `packages/kernel/web.py` plus pack routers mounted at `/packs/{id}`). Must load **without** LangGraph or agent libraries (there is a test for this). |
| `worker` | Procrastinate jobs, event relay loop, internal actions, agents (LangGraph), periodic jobs: follow-up sweep every 30 min, daily digest at 07:00, inbound mail processing. |
| `executor` | The only process that can send mail or reach external systems. Polls approved external proposals, re-checks them, runs adapters (`kernel/adapters/`), and polls the inbound mailbox (Mailpit) every 5 s. Its DB role sees only the trust schema plus INSERT on `comms.inbound_mail`. |
| `ml` | FastAPI (`apps/ml`). Docling parsing with hidden-text removal, fastembed embeddings (`paraphrase-multilingual-MiniLM-L12-v2`, 384-d), cross-encoder reranker (`BAAI/bge-reranker-v2-m3-int8`). Models baked into the image; runs offline. mem_limit 4g. |
| `postgres` | Postgres with pgvector. Host port **55432**. Roles: api, worker, executor, owner. RLS on every tenant table. |
| `minio` | File storage (CVs, attachments, policies). |
| `mailpit` | Fake SMTP (1025) and web UI/API (8025). Outbound and inbound mail for the demo. |
| `otel-lgtm` | Grafana, Loki, Tempo, Prometheus for traces and logs. |
| Neo4j | AstraGraph (`kernel/graph`); reached only through kernel query templates. |
| `migrate` | Alembic migrations per schema (kernel and each pack). |

Networks isolate services: only the executor reaches `mail`, the executor can't reach files or
the graph. Tests check this (`tests/test_compose_boundaries.py`, `tests/test_architecture.py`).

### The ten invariants (enforced by tests)

1. Agents propose, humans approve, the executor acts.
2. Every action declares a risk class in its pack manifest; undeclared actions can't run.
3. Approvals bind to a payload hash; editing the payload voids approvals.
4. No explanation, no proposal: every R2/R3 proposal and every ranking has a `DecisionRecord`.
5. LLMs never compute decisions or money. Scores and payroll are deterministic code.
6. Untrusted text reaches a model only with no tools (`ctx.read_untrusted`); downstream gets
   validated structured data.
7. Packs call models by tier through the gateway.
8. Foreign keys point only into `core`; packs talk through contracts or events.
9. Every table has `tenant_id` under RLS. No LLM writes Cypher.
10. Security checks fail closed.

### Risk classes

- **R0:** read or harmless; runs freely.
- **R1:** internal, low risk; runs and is logged (`trust.log_action`).
- **R2:** needs one authorised person to approve the exact payload.
- **R3:** two different people, plus a fresh password check (`POST /auth/step-up`), no
  self-approval. Examples: reject or hire a candidate, activate payroll rules, approve payroll.

### Approval flow

`proposal (hash-bound payload, target scope, DecisionRecord)` → human approves or edits
(editing bumps `revision` and voids approvals) → execution: **internal** actions run in the
worker through a manifest `handler`; **external** actions (`kernel.email.send`) run in the
executor through an adapter → audit event in the chain → `trust.action.executed.v1`.

### Kernel modules (`packages/kernel/`)

| Module | What it does |
|---|---|
| `identity` | Users, roles, login (argon2, lockout after repeated failures, 429), sessions (HttpOnly cookie `astra_session`, CSRF cookie `astra_csrf` + `x-csrf-token` header), step-up. |
| `trust` | Proposals, approvals, execution status, hash-chained audit log, `verify_chain`. |
| `explain` | DecisionRecords with evidence quotes, verifiable. |
| `events` | Transactional outbox, catalogue of versioned events, `@subscribe` consumers, `relay_once`. |
| `ai` | Gateway (tiers, budgets 40k tokens per run and 2M per tenant per day, provider fallback, strict JSON schema), `reader.read_untrusted`, injection flags. |
| `graph` | Neo4j AstraGraph views and decision graph. |
| `people` | Employees, org units; `POST /people/employees` emits `core.employee.created.v1`. |
| `comms` | Inbox: threads, messages, LLM classification (11 types, urgency, needs-human with reason), daily digest, handled/reopen, human corrections, inbound mail and attachments. |
| `schedule` | Calendar: busy blocks (manual or imported from .ics), slot finding (Africa/Tunis), holds (72 h), bookings with a Postgres exclusion constraint against double booking, ICS invites (REQUEST/CANCEL). |
| `knowledge` | Policy documents with versions and role-based access, chunks with pgvector, hybrid search (dense + full text fused by RRF, then reranked), cited answers, refusal and HR tickets, feedback. |
| `adapters` | `mail.py` (build + send, Reply-To `hr@cds.example.test`, invite attachment only for attendees), `mailbox.py` (poll Mailpit for inbound mail). |
| `files.py` | Upload gate: PDF, DOCX, HTML, Markdown, TXT; magic-byte and UTF-8 checks; 20 MB per file, 200 per upload. |
| `ml_client.py` | Client for parse, embed, rerank, model info. |
| `registry.py` | Loads pack manifests, mounts pack routers, installs consumers, runs internal actions. |
| `limits.py` | **Untracked, unfinished.** Per-person hourly budgets (AI questions, AI runs, uploads, decisions). Not wired, no migration. Finish or delete. |

### Packs (`packages/packs/`)

**talent (recruitment, ours).**
- Jobs and rubrics: an agent drafts criteria from the job description; a person activates them.
- CV pipeline: upload, or a CV emailed to HR with the job reference in the subject. Then Docling
  parsing with hidden text removed, blinding (name, email, phone and photo lines hidden while
  scoring, using `ParseResult.lines`), and evidence extraction with quotes checked word for word
  against the CV.
- Ranking: a deterministic score of 70% evidence and 30% job match. Job match = 40% dense
  similarity, 30% BM25 and 30% reranker (falls back to 50/50 when the reranker is down).
  Rubric/scorer version `talent.rubric@3`, and @2 scores replay exactly. See
  `docs/RANKING.md`.
- Communications (`communications.py`):
  - The reply drafter sees only that candidate's file.
  - Follow-ups.
  - The scheduler proposes 3 held slots.
  - The slot picker reads a candidate's answer ("Tuesday works") and proposes the booking, or
    proposes a cancel-and-reschedule.
  - Booking and cancelling, with invites.
- Hire and reject are R3. Hiring emits `talent.candidate.hired.v1`.

**journey (teammate, merged).** Onboarding 30/60/90 plans proposed when an employee is created,
tasks, check-ins, buddy, support flags, skill gaps, training plans tied to KPIs, impact,
heatmap, dossier export. Agents: onboarding_planner, skill_gap_analyst, training_planner. Has
API routes but **no web page yet**. Its tests live in `packages/packs/journey/tests/`.

**finance (teammate, merged).**
- Tunisian payroll: rule sets (R3 to activate), engagements and CIVP placements, payroll input
  batches (CSV/JSON import, rejections and conflict checks).
- Payroll runs: calculate, exceptions, submit, R3 approval, replay and verify, payslips.
- A net/gross calculator, and hire notices from talent.
- Docs: `docs/FINANCE_*.md`. **No web page yet** and no `ui` block in its manifest.

**workforce (teammate, NOT merged).** Lives on its own branch. It lacks an API, handlers, agents
and RLS. Don't expose it.

### Cross-pack flow

```
talent.candidate.hired.v1 → finance hire notice → HR turns it into an engagement
POST /people/employees → core.employee.created.v1 → journey proposes the onboarding plan
finance.engagement.activated.v1 → journey fallback trigger
trust.proposal.* / trust.action.executed.v1 → ledger, audit, inbox "handled", hold release
```

---

## 4. API contract

- **Source of truth:** `contracts/openapi.json` (OpenAPI 3.1; 111 paths and 122 operations).
- **TypeScript types:** `contracts/openapi.d.ts`, generated; never hand-edit it.
- **Human guide:** `docs/API_CONTRACT.md` (roles, request bodies, response shapes, freeze
  rules, known gaps).
- **Regenerate:** `python astra.py export-api`, then
  `npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts`.

**Transport.** Base URL `http://127.0.0.1:8080/api`. Log in with
`POST /auth/login {tenant, email, password}`; every write sends `x-csrf-token`. Errors are
`{"error","message"}`. Times are ISO 8601 with a timezone. Money and scores are decimal
strings.

**Roles:** admin, hr, recruiter, manager (scoped by org_unit), finance, employee, auditor,
mediator (reserved).

**Route groups**

| Group | Paths |
|---|---|
| Platform | `/healthz`, `/readyz`, `/registry/packs` |
| Identity | `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/step-up` |
| People | `/people/employees` (GET, POST), `/people/org` |
| Trust | `/trust/proposals` (list, get, approve, reject, edit), `/trust/audit`, `/trust/audit/verify` |
| Explain / runs / graph | `/explain/{id}`, `/explain/{id}/verify`, `/ai/runs`, `/ai/runs/{id}`, `/graph/{view}`, `/graph/decision/{id}` |
| Inbox | `/comms/digest` (GET, POST rebuild), `/comms/stats`, `/comms/threads` (filters status, needs_human, type, q, cursor `before`), `/comms/threads/{id}`, `.../handled`, `.../reopen`, `PUT /comms/messages/{id}/sorting` |
| Knowledge | `/knowledge/questions` (ask, mine), `/knowledge/questions/{id}`, `.../feedback`, `/knowledge/tickets` (+ `/{id}`, claim, release, answer, close), `/knowledge/documents` (list, get, POST upload new version), `/knowledge/stats` |
| Calendar | `/calendar/busy` (GET, POST, DELETE `/{id}`), `/calendar/import` (.ics, multipart), `/calendar/free`, `/calendar/bookings` |
| Talent | `/packs/talent/jobs` (list, create, get), `.../cvs` (upload multipart, list), `.../cvs/from-email`, `.../rubrics`, `.../rubrics/{id}/activate`, `.../rankings`, `.../shortlist`, `.../interviews`; `/packs/talent/applications/{id}/profile`, `.../interviews`, `.../overrides`, `.../reject`, `.../hire`; `/packs/talent/interviews/{id}` (get, book, cancel); `/packs/talent/followups/check` |
| Journey | `/packs/journey/plans`, `/plans/me`, `/plans/{id}`, `.../dossier`, `.../tasks/{task_id}/complete`, `.../checkins/{checkin_id}/submit`, `/gaps`, `/heatmap`, `/impact`, `/recommendations` |
| Finance | `/packs/finance/rule-sets`, `/engagements`, `/hire-notices`, `/input-batches`, `/payroll-runs`, `/payslips`, `/issues`, `/documents`, `/calculator/net`, `/calculator/compare` (full list in the contract) |

**Known contract gaps:**
- Most responses are open objects with no named DTOs. Add Pydantic response models for the
  endpoints the UI uses, then regenerate.
- Pagination isn't uniform: the inbox uses a cursor, other lists are bare arrays.
- Errors carry no request_id.
- Only proposals have ETags.
- **Missing for the UI:** a `/overview` dashboard endpoint and a signup endpoint (accounts come
  only from the seed).

---

## 5. Data

- `data/world.json`: the fictional company, users and roles. Demo login is tenant `cds`; the
  password is `DEMO_PASSWORD` in `.env`.
- `data/cvs/`: **Oussema's test corpus.** 30 CVs (CV01, Aïcha Benali, ...) in pdf, docx,
  html, md and txt, plus `scanned/`, `index.csv`, `applications.csv` and
  `ground_truth.json`. The `json/` copies carry ground-truth metadata and are not uploadable.
  Built by `tools/build_cv_corpus.py`, whose zip now goes to `data/tech_cv_corpus.zip`
  (ignored). An old corrupt 6 GB zip may still sit in `data/cvs/`; it is git- and
  docker-ignored.
- `data/jobs/`: 12 job descriptions, J01 to J12.
- `data/demo/cvs/`: the original demo CVs, including attacks (white text, visible instruction,
  French instruction, keyword stuffing, scanned) and a hard set h01–h12. `load_demo` still
  seeds from here; **the `data/cvs` corpus isn't wired into the seed yet.**
- `data/demo/emails.json`: 22 inbox emails. `data/demo/policies/`: policy documents plus
  `index.yaml` (POL-PAY-BANDS is restricted to hr, admin and finance).
- `data/source/Resume.csv`: raw source, ignored.

---

## 6. Commands

```bash
python astra.py up            # build + start the stack + run migrations
python astra.py down [--wipe] # stop (wipe = drop volumes)
python astra.py seed          # company, demo CVs through the real pipeline, knowledge, inbox
python astra.py check [tests/...]   # ruff + pytest inside the tests container
python astra.py evals         # real-model evals, ~3 cents, writes docs/evals/*.json
python astra.py live          # one real model call
python astra.py smoke         # end-to-end demo smoke
python astra.py makemigration <kernel|pack> "msg"   # then add an enable_rls revision
python astra.py export-api    # regenerate contracts/openapi.json
python astra.py graph-rebuild
```

New tables need a follow-up migration revision calling `kernel.rls.enable_rls("schema.table")`,
or a test fails. `astra.py check` doesn't migrate; run `astra.py up` first.

---

## 7. Verified state

- **Full suite (integration agent, after the merges):** green. 867 passed, 2 skipped.
- **Real-model evals** (`docs/evals/screening.json`, `communications.json`):
  - Screening:
    - NDCG@5 and @10 1.0, hard set 1.0, 10 of 10 strong candidates in the top 10.
    - 177 of 177 quotes found word for word; 42 of 42 scores replay.
    - The hidden-text attack scores exactly like its clean twin; swapping the name doesn't
      change the score.
    - About $0.018 a run.
  - Inbox:
    - 17–18 of 20 types right (the misses are e09 other→spam, e10 legal→other, and sometimes
      e16).
    - 8 of 8 "needs a person" caught, 0 of 12 false alarms.
  - Policy answers: 8 of 8 right document, 6 of 6 correctly passed to HR, 0 leaks of restricted
    documents.
  - Slot picking: 8 of 8 read right (English, French, Arabic, "option 1", injection), 0 wrong
    bookings, 4 of 4 unclear answers left to a person.

---

## 8. History (one line per step)

- **P0–P2:** plan and architecture docs, infra stack and `astra.py`, trust kernel (identity,
  ledger, explainability, events, AI gateway, graph).
- **P3/P4:** web shell, seed, CV screening (LangGraph agents, formula ranking, explanations),
  two-layer ranking.
- **P5/P6, steps 1–12 (see the PROGRESS log):**
  1. Test corpus.
  2. Inbox triage, calendar and cited policy answers.
  3. Replies, follow-ups and booking.
  4. First-pass web pages.
  5. Slot holds.
  6. ICS invites, cancel and reschedule.
  7. HR tickets, feedback and policy versions.
  8. Inbox listing, handled state and corrections.
  9. Docling and the reranker.
  10. Live inbound mail and CVs by email.
  11. A candidate's time answer becomes a booking proposal.
  12. Recruiter calendar API and .ics import.
- **Integration (another agent, branch `integration/final`, fast-forwarded into main):**
  - Merged journey and finance.
  - Bridged employee creation to onboarding and hire to finance.
  - Froze the API contract.
  - Wrote `docs/INTEGRATION_REPORT.md`.

Decisions confirmed by Oussema: Docling (not pdfplumber only), a reranker (int8 bge-m3,
accepted even if slow), and heuristic name hiding (not Presidio).

---

## 9. What is left

### Backend, still worth doing for the demo and the jury

1. **`/overview` endpoint** for the dashboard: decisions waiting, today's interviews, open
   jobs, applications, days to shortlist, inbox needing a person, questions answered or passed
   on, payroll status, audit chain status, agent runs, blocked attacks and AI cost.
2. **Signup or invite endpoint**, if the UI shows signup.
3. **Per-person limits:** finish `packages/kernel/limits.py` (model `core.usage_event`,
   migration + RLS, call `spend_for(ctx, bucket)` on ask, rankings, rubric draft, digest
   rebuild, uploads and approvals) or delete it.
4. **HSTS** in Caddy.
5. **Candidate erasure and retention** (GDPR / Tunisian law 2004-63): a jury question.
6. **Wire the `data/cvs` corpus and `data/jobs` into the seed**, so the demo uses the real
   corpus.
7. **Proof:**
   - A load test on real volumes (hundreds of CVs, timing per CV).
   - Runnable security drills (prompt injection, cross-tenant access, CSRF, approval
     tampering, executor boundary).
   - A root **README** and the **demo script** (`docs/PLAN.md` §13).
8. Response DTOs for the endpoints the UI uses; regenerate the contract.

### Frontend (the next big phase; started, waiting for approval)

Oussema wants a real, polished UI inspired by **mercury.com** (calm, cinematic landing,
animated product window). The pages: landing, login, signup, dashboard, and every sidebar
page, connected to the APIs.

- **HTML previews built, not yet approved:** in the session scratchpad (not in the repo):
  `.../scratchpad/preview/landing.html` and `dashboard.html`. If they are gone, rebuild from
  this description.
  - **Landing:** a midnight starfield over a warm horizon, headline "The agents do the work.
    You make the calls.", an email field and a product window. The window animates CVs being
    scored and re-sorted, an invite proposal with a CV quote, approval, and the audit stamp.
  - **Rest of the landing page:**
    - A six-feature tabbed showcase.
    - A three-step "how decisions work" section with a ledger excerpt.
    - A "show what's hidden" CV attack demo.
    - A real eval-results table and a CTA.
  - **Dashboard:**
    - Navy sidebar grouped Hiring / People / Trust: Overview, Approvals, Inbox, Jobs,
      Candidates, Interviews, Onboarding and training, Payroll, Ask HR, Audit log, Settings.
    - "Waiting for your decision" queue with risk tags, a today timeline (interviews, held
      slots, now line) and 4 KPI tiles.
    - Hiring pipeline stacked bars per job (with a table view) and applications per week
      (line with crosshair).
    - Inbox by type with a needs-a-person callout, new joiners' progress, payroll steps and a
      trust strip.
- **Process agreed:** show HTML previews first, rebuild in Next.js only after approval, connect
  to the APIs page by page, and push to main after each step.
- **Existing web app** (`apps/web`): pages approvals, ask, audit, inbox, jobs, jobs/[id] and
  login, plus `src/lib/api.ts` and `src/ui/Shell.tsx`. ESLint reports one existing
  `react-hooks/set-state-in-effect` error in `jobs/[id]/page.tsx`.
- **Video skills for the demo** (Oussema must install them; the sandbox blocked it):
  - `git clone --depth 1 https://github.com/feitangyuan/onetake.git ~/.claude/skills/onetake`
    (non-commercial licence).
  - `claude plugin marketplace add heygen-com/hyperframes`, then
    `claude plugin install hyperframes@hyperframes`.
  - They need Node 22+ and FFmpeg.

### Later

- Workforce pack: needs an API, handlers, agents and RLS before merging.
- P7 AstraGraph UI, Trust Center and Agent Run Explorer dashboards, Grafana.
- Team tooling: `_example` pack, CI, CODEOWNERS.

---

## 10. Likely jury questions, and where the answer lives

| Question | Answer |
|---|---|
| How do you stop prompt injection in CVs and emails? | Hidden text is stripped before reading (`apps/ml/parsing.py`); untrusted text goes to a tool-less model with schema validation; injections are flagged and force needs-human; eval: the attack scores like its clean twin. |
| Can the AI send something on its own? | No. Proposals need approval bound to the payload hash; only the executor sends, on a separate network and DB role (tests in `test_architecture.py`, `test_trust_path.py`, `test_compose_boundaries.py`). |
| Is the ranking fair and explainable? | Names, contact details and photos are hidden while scoring; the score is a deterministic formula; every point has a quote checked against the CV; scores replay; the name-swap eval shows no change. |
| Can one candidate's data leak into another's reply? | The drafter receives only that file; a test refuses drafts that mention another candidate. |
| What if the model is down? | Provider fallback (Groq); the reranker falls back to fused order; security checks fail closed. |
| Multi-company / data isolation? | Postgres RLS on every table, tenant fixed in the signed session; cross-tenant tests return 404. |
| Who did what, provably? | Hash-chained audit log, `POST /trust/audit/verify`; DecisionRecords with evidence. |
| Real volumes? | **Not yet proven.** A load test is on the to-do list. |
| Personal data law / deletion? | **Not yet built.** Erasure and retention are on the to-do list. |
| Double booking? | Postgres exclusion constraint plus slot holds; re-checked at booking. |
| Cost? | About $0.018 per screening run on Haiku; budgets per run and per tenant per day. |
