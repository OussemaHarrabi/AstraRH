# AstraRH

**The agents do the work. You make the calls.**

*Built by Team 7ezb Stage for the Astropreneur SupCom hackathon.*

[![AstraRH demo: click to watch the full film](docs/screenshots/demo-preview.gif)](apps/web/public/demo.mp4)

**[▶ Watch the full demo film](apps/web/public/demo.mp4)** (about 4 minutes, with voice-over and captions, recorded from the running app)

## HR shouldn't stop at the interview

Most HR tools treat a person as a file that closes the day the contract is signed. We think that's where the real story starts.

**We're Team 7ezb Stage, and our goal is to move the HR department beyond recruitment.** Instead of only running interviews, AstraRH follows each person all along the way, from the first contact to the last one with the company:

```text
First email -> CV read -> Shortlist -> Interview -> Hire -> Contract and payroll
            -> Onboarding -> Skills and training -> Every question along the way
```

One platform, one memory and one trust layer across the whole journey. AI agents take on the repetitive work: reading CVs, sorting the inbox, drafting replies, finding interview times, planning onboarding, answering policy questions. That leaves HR free for the part only people can do: making the decisions and looking after people.

**One rule holds everywhere: the agent executes, the human decides about people.** Agents prepare work and propose. A person approves the exact content. A separate process with its own network and database role performs the action. Everything lands in a hash-chained audit log.

CDS Tunis, the company in the demo, is fictional, and so are its people, CVs and emails.

![AstraRH landing page](docs/screenshots/landing-hero.png)

## Contents

1. [Quick start](#quick-start) and [Try it](#try-it)
2. [The product, page by page](#the-product-page-by-page)
3. [How the six core features work](#how-the-six-core-features-work)
4. [Architecture](#architecture)
5. [Every service](#every-service)
6. [How everything connects](#how-everything-connects)
7. [The kernel](#the-kernel)
8. [Service packs](#service-packs)
9. [The agents](#the-agents)
10. [The frontend](#the-frontend)
11. [APIs](#apis)
12. [Data](#data)
13. [Multi-tenancy](#multi-tenancy)
14. [Security](#security)
15. [Infrastructure](#infrastructure)
16. [Scalability](#scalability)
17. [Observability](#observability)
18. [Testing and evaluation](#testing-and-evaluation)
19. [Configuration](#configuration)
20. [Commands](#commands)
21. [Repository layout](#repository-layout)
22. [What's next](#whats-next)
23. [Further documentation](#further-documentation)

---

## Quick start

You need Docker with at least 8 GB of memory (16 GB is more comfortable), Git and Python 3.12+. `astra.py` has no Python dependencies.

```bash
git clone https://github.com/OussemaHarrabi/AstraRH.git
```

```bash
cd AstraRH
```

```bash
python astra.py init
```

`init` creates `.env` and generates every password and secret. Add your `ANTHROPIC_API_KEY` and `GROQ_API_KEY` to it, then:

```bash
python astra.py up
```

```bash
python astra.py seed
```

```bash
python tools/demo_state.py
```

`seed` loads the company, demo CVs, policies and inbox through the real pipeline. `demo_state.py` then ranks candidates, adds your CV corpus as a second job, books interviews and calculates a payroll run, all through the real API and approvals. Together they cost a few cents in model calls.

Open **http://127.0.0.1:8080** and log in with company `cds`. The password is `DEMO_PASSWORD` in `.env`.

| Account | Role | Good for seeing |
|---|---|---|
| `nadia@cds.example.test` | Recruiter | Jobs, candidates, inbox, interviews, approvals |
| `leila@cds.example.test` | HR | Everything above, plus onboarding, audit and HR tickets |
| `sami@cds.example.test` | Finance | Payroll, rule sets, calculator |
| `karim@cds.example.test` | Manager | Team-scoped views |
| `mehdi@cds.example.test` | Employee | Ask HR, own onboarding plan |
| `audit@cds.example.test` | Auditor | Read-only audit and decisions |
| `admin@cds.example.test` | Admin | Everything, including second approvals |

Local tools in development mode, all on loopback only:

| Tool | Address |
|---|---|
| AstraRH | http://127.0.0.1:8080 |
| API docs (Swagger) | http://127.0.0.1:8080/api/docs |
| Grafana | http://127.0.0.1:3001 |
| Mailpit, the sandbox mailbox | http://127.0.0.1:8025 |
| Neo4j browser | http://127.0.0.1:7474 |
| MinIO console | http://127.0.0.1:9001 |
| PostgreSQL | `127.0.0.1:55432`, database `astra` |

---

## Try it

**Live platform: https://civic-jobs-abroad-train.trycloudflare.com**

| Company | Email | Password | Role |
|---|---|---|---|
| `cds` | `nadia@cds.example.test` | In our submission form | Recruiter, the best place to start |
| `cds` | `leila@cds.example.test` | Same | HR |
| `cds` | `sami@cds.example.test` | Same | Finance |
| `cds` | `karim@cds.example.test` | Same | Manager |
| `cds` | `mehdi@cds.example.test` | Same | Employee |
| `cds` | `audit@cds.example.test` | Same | Auditor |
| `cds` | `admin@cds.example.test` | Same | Admin |

All the people and data in this demo company are fictional. Please don't enter real personal data.

There are three ways in, depending on what you want.

| You want to | Do this | You need |
|---|---|---|
| **Test the platform right away** | Open the live link above and log in with an account from the table | A browser and the password |
| **Run your own copy** | [Run it with Docker](#run-it-with-docker) | Docker and an LLM key |
| **Publish your own copy** | [Public link](#public-link) | Docker and an LLM key |

---

## The product, page by page

### Landing and sign-in

A scroll-driven dusk over the Gulf of Tunis leads into a live product window, then six animated product demos, the agents, and a hidden-text attack you can reveal by dragging.

| Feature demos | The crew |
|---|---|
| ![Feature demos](docs/screenshots/landing-features.png) | ![The crew](docs/screenshots/landing-crew.png) |

| Hidden-text attack demo | Log in |
|---|---|
| ![Attack demo](docs/screenshots/landing-attack.png) | ![Login](docs/screenshots/login.png) |

### Overview

The recruiter's morning: the crew with each agent's real state, decisions waiting, upcoming interviews, hiring pipeline per job, inbox by type, agent activity, new joiners, and a one-click check of the audit chain. Ctrl K opens search and actions from anywhere. The app also has a dark theme and phone layouts.

![Overview](docs/screenshots/overview.png)

| Command palette | Dark theme | Phone |
|---|---|---|
| ![Palette](docs/screenshots/command-palette.png) | ![Dark](docs/screenshots/overview-dark.png) | ![Phone](docs/screenshots/phone-overview.png) |

### Approvals

Everything an agent prepared, with who proposed it and its risk class. A person can edit an email, read why it was suggested, approve or reject. Editing creates a new version and voids any earlier approval. Filter by one approver or two people, and move through the list with J and K.

| Review a draft | Why this suggestion |
|---|---|
| ![Approvals](docs/screenshots/approvals.png) | ![Why](docs/screenshots/approvals-why.png) |

### Inbox

Today's digest grouped by type and sorted by urgency, a needs-a-person queue, all open and handled conversations, search, and filters. Each message shows Salem's sorting and reasoning. A person can correct it, and the model's first answer is kept so accuracy stays measurable.

![Inbox](docs/screenshots/inbox.png)

### Jobs

Create a job, optionally from a template, and Mira drafts its criteria. Each job has five tabs: ranked candidates, a pipeline board, criteria, CVs and the job post.

| Jobs | Create a job |
|---|---|
| ![Jobs](docs/screenshots/jobs.png) | ![New job](docs/screenshots/job-new.png) |

| Ranked candidates | Corpus job: separating fits from the rest |
|---|---|
| ![Ranked](docs/screenshots/job-ranked.png) | ![Security Analyst](docs/screenshots/job-corpus.png) |

| Criteria a person approves | Upload and processing |
|---|---|
| ![Criteria](docs/screenshots/job-criteria.png) | ![CVs](docs/screenshots/job-cvs.png) |

| Pipeline board | Job post |
|---|---|
| ![Pipeline](docs/screenshots/job-pipeline.png) | ![Job post](docs/screenshots/job-post.png) |

### Candidate file

Every score opens to its proof: points per criterion, the exact quote, what would change the result, what wasn't considered, and a button that recalculates the score from stored facts. The same drawer shows what the AI read with identity hidden, any attack found, and team notes and scorecards. It's also where a recruiter proposes interview times, a hire or a rejection.

| Why this score | An attack CV, caught |
|---|---|
| ![Why this score](docs/screenshots/candidate-why.png) | ![Attack](docs/screenshots/candidate-attack.png) |

### Candidates

Everyone across all jobs: search by name, job or tag, filter by job and stage, sort, star, bulk-tag and export to CSV.

![Candidates](docs/screenshots/candidates.png)

### Interviews

A week view of busy time, held offers and booked interviews, with a live "now" line. Block out time by hand or import an `.ics` file from Google, Outlook or Apple.

![Interviews](docs/screenshots/interviews.png)

### Onboarding, skills and training

30/60/90 plans with progress for each new joiner, tasks that need evidence to complete, and skill gaps with their reasoning. Adding an employee makes Aziz draft a plan for HR to approve.

| Plans | One plan |
|---|---|
| ![Onboarding](docs/screenshots/onboarding.png) | ![Plan](docs/screenshots/onboarding-plan.png) |

![Skill gaps](docs/screenshots/skill-gaps.png)

### Payroll

Payroll runs with their steps, payslips line by line, a gross-to-net calculator, and rule sets. It's calculated by code, never by a model.

| Runs | Payslips in a run |
|---|---|
| ![Payroll](docs/screenshots/payroll.png) | ![Run](docs/screenshots/payroll-run.png) |

### Ask HR

Employees get answers from policies they may read, with the exact sentence as the source. Anything else goes to HR. HR works a queue of passed-on questions and publishes policy versions.

| Cited answer and refusal | Questions passed to HR | Policies |
|---|---|---|
| ![Ask](docs/screenshots/ask.png) | ![Tickets](docs/screenshots/hr-tickets.png) | ![Policies](docs/screenshots/policies.png) |

### Agents

Each agent has a face that reflects its real state. Opening one shows its runs, every step, the model used, tokens, latency and cost.

| The crew | A run, step by step |
|---|---|
| ![Agents](docs/screenshots/agents.png) | ![Run](docs/screenshots/agent-run.png) |

### Graph

Three live views, with moving light along connections, hover highlighting, zoom and pan.

| Evidence: job, criteria, candidates | Agents and decisions | Company |
|---|---|---|
| ![Evidence graph](docs/screenshots/graph-evidence.png) | ![Agent graph](docs/screenshots/graph-agents.png) | ![Company graph](docs/screenshots/graph-company.png) |

### Audit log, reports and settings

Every action with its hash and the link to the entry before it. One button recomputes the whole chain. Reports show the hiring funnel, AI spend per agent, inbox mix and policy question outcomes. Settings shows the approval rules read directly from each module's manifest.

| Audit log | Reports |
|---|---|
| ![Audit](docs/screenshots/audit.png) | ![Reports](docs/screenshots/reports.png) |

| Approval rules | Data and privacy |
|---|---|
| ![Rules](docs/screenshots/settings-rules.png) | ![Privacy](docs/screenshots/settings-privacy.png) |

---

## How the six core features work

### 1. A ranked shortlist with evidence

```mermaid
flowchart LR
  U[CV upload or email] --> G[Upload gate]
  G --> S[(MinIO)]
  S --> P[ml: remove hidden text, parse with Docling]
  P --> B[Hide name, contact, photo lines]
  B --> R[cv_reader: model with no tools]
  R --> Q[Check every quote word for word]
  Q --> E[(Frozen profile)]
  E --> F[Formula: 70 evidence + 30 job match]
  F --> J[Model writes the explanation from numbers only]
  J --> L[Shortlist proposal]
  L --> H{Person approves}
```

- **Parsing:** hidden text (invisible render mode, white, transparent, under 3 pt or off-page) is deleted from the PDF itself with pypdfium2, then Docling converts it to Markdown. Scanned files go through OCR. DOCX and HTML drop hidden runs, comments, scripts and hidden elements.
- **Blinding:** names, contact details and photo lines are removed before any model reads the text, so the model never sees them.
- **Reading:** Haiku returns structured facts, each with a quote. A quote not found in the CV is deleted, along with the skill it supported.
- **Scoring:** `score = 70 points of evidence + 30 points of job match`. Evidence is `weight x how much the CV proved` per approved criterion. Job match is 40% vector similarity, 30% BM25 and 30% cross-encoder reranker. It falls back to 50/50 if the reranker is down, and the record says so.
- **Ordering:** candidates meeting every must-have come first, then highest score. Ties break on the file's content hash, so identity and upload order can't affect the order.
- **Replay:** the score uses exact decimals and the inputs are stored with the decision, so "Recalculate score" reproduces it digit by digit. Versioned scorers (`talent.rubric@2`, `@3`) keep old results reproducible.

Full method: [docs/RANKING.md](docs/RANKING.md).

### 2. A daily digest of the HR inbox

The executor polls the HR mailbox every 5 seconds and stores the raw message. The worker parses it and ingests it, and `inbox_triage` reads it through the no-tools reader to produce type, urgency, needs-a-person and a reason.

Code rules then force a person for legal matters, complaints, discrimination, harassment, salary, offers, visas, health and personal data requests, whatever the model said. The digest is rebuilt daily at 07:00 or on demand. Attachments pass the same upload gate as a recruiter upload, and a CV naming a job reference in the subject becomes an application.

### 3. Replies drafted from one candidate's file

`reply_drafter` finds the candidate by sender address and receives only that candidate's file. Deterministic checks reject promises only a person can make, and any other candidate's name or email. The candidate's name is filled in after the model, so the model doesn't see it. The result is an R2 proposal with a decision record.

### 4. Follow-ups for candidates who go quiet

`due_followups` is deterministic code, run by a durable job every 30 minutes: every 3 days, 2 reminders at most, only in the applied, shortlisted or interview stages. It stops on a reply, a rejection or a hire. A unique `(application_id, sequence)` constraint means a reminder can't be created twice. Each reminder is an R2 proposal.

### 5. Interview slots from real calendars

1. `scheduler` takes an advisory lock on each participant's calendar, finds free working-hours slots on separate days, at least 24 hours ahead, and holds three for 72 hours.
2. A person approves the offer email.
3. When the candidate replies, `slot_picker` reads it through the no-tools reader. It can only return an offered slot's number and a quote, and code checks both. This works in French, English and Arabic.
4. Anything unclear gets a normal reply draft, so a person answers.
5. A person approves the booking. The slot is checked again, and a Postgres exclusion constraint makes a double booking impossible.
6. The confirmation goes out with an RFC 5545 invite. Cancelling sends a matching CANCEL invite, and rescheduling opens a new offer.

`.ics` import keeps only when someone is busy. Titles, places and guests are dropped on purpose.

### 6. Policy answers with citations

`policy_answers` runs: injection guard, forced-human topics, role-filtered hybrid search (pgvector and full text fused by rank, then reranked), a minimum similarity, then a cited answer. Every sentence must cite a passage and every quote must appear in it word for word, or the question becomes an HR ticket.

The role filter sits inside the search's `WHERE` clause, so restricted text can't even be ranked. A new policy version supersedes the old one, and a unique partial index allows one active version per policy.

---

## Architecture

A modular monolith, split into processes only at trust boundaries.

```mermaid
flowchart TB
  U[Browser] --> CADDY[caddy: edge, headers, body limit]
  CADDY --> WEB[web: Next.js]
  CADDY -->|/api| API[api: FastAPI, kernel + packs]

  API --> PG[(PostgreSQL 17 + pgvector, row-level security)]
  API --> MINIO[(MinIO: files)]
  API -->|named queries only| NEO[(Neo4j: read model)]

  WORKER[worker: agents, jobs, event relay] --> PG
  WORKER --> MINIO
  WORKER -->|projects events| NEO
  WORKER --> ML[ml: parsing, embeddings, reranker. No internet]
  WORKER -->|llm_egress: the only internet route| LLM[Anthropic, Groq]

  EXEC[executor: only sender of mail] --> PG
  EXEC --> MAIL[Mailpit / SMTP]

  MIGRATE[migrate: one-shot, owner role] --> PG

  API & WORKER & EXEC & ML -->|OTLP| OTEL[otel-lgtm: Grafana, Tempo, Loki, Prometheus]
```

The life of one decision:

```mermaid
sequenceDiagram
  participant E as Event
  participant A as Agent (worker)
  participant T as Trust ledger (Postgres)
  participant H as Person (api)
  participant X as Executor or worker
  participant L as Audit chain
  E->>A: Trigger through the outbox
  A->>T: Proposal + payload hash + DecisionRecord
  T-->>H: Appears in Approvals
  H->>T: Approve (role, target, hash, step-up for R3)
  T->>X: Picked up after approval
  X->>T: Re-check, then run once (idempotent)
  X->>L: Hash-chained audit entry
  X->>E: trust.action.executed.v1
```

### The ten invariants

| # | Rule | Enforced by |
|---|---|---|
| 1 | Agents propose, humans approve, the executor acts | DB roles, networks, `test_only_the_executor_can_send`, `test_trust_path.py` |
| 2 | Every action declares a risk class; undeclared actions can't run | Manifests and the action catalogue |
| 3 | Approvals bind to a payload hash; editing voids them | `trust`, tests |
| 4 | No explanation, no proposal | `trust.propose`, tests |
| 5 | LLMs never compute decisions or money | `scoring.py`, payroll `calc`, a test that `scoring.py` can't import a model client |
| 6 | Untrusted text reaches a model only with no tools | `ctx.read_untrusted`; the gateway has no tools parameter |
| 7 | Packs call models by tier through the gateway | `test_only_the_gateway_calls_model_providers` |
| 8 | Foreign keys point only into `core` | Review, contracts and events between packs |
| 9 | Every tenant table has `tenant_id` under RLS; no LLM writes Cypher | `test_every_tenant_table_has_rls_forced`, query templates |
| 10 | Security checks fail closed | Guard, reader, `SecurityCheckUnavailable` |

### Risk classes

| Class | Meaning | Rule | Examples |
|---|---|---|---|
| R0 | Read or derive | Automatic, logged | Sort an email, read a CV |
| R1 | Internal, low risk | Automatic, logged | Correct a sorting, publish a policy |
| R2 | Affects a person or leaves the system | One authorised person approves the exact payload | Send an email, book an interview, move to shortlist |
| R3 | Serious or irreversible | Two different people, a fresh password, no self-approval | Hire, reject, activate payroll rules, approve payroll |

### What we refuse to build

For legal and ethical reasons (EU AI Act Art. 5(1)(f) and Annex III): emotion or sentiment inference about workers, reading private messages for HR signals, webcam, keystroke or screen tracking, individual "flight risk" scores presented as fact, and automated decisions about people without a human approver.

---

## Every service

Defined in [`ops/compose.yaml`](ops/compose.yaml). `ops/compose.dev.yaml` adds live reload, loopback tool ports and the test runner. Third-party images are pinned by digest.

| Service | Technology | Role | Networks | Memory limit |
|---|---|---|---|---|
| `caddy` | Caddy 2.10 | Edge proxy | `edge_public`, `edge_internal` | 64 MB |
| `web` | Next.js 16, React 19 | User interface | `edge_internal` | 768 MB |
| `api` | FastAPI, Uvicorn | HTTP API | `edge_internal`, `data`, `graph`, `files`, `telemetry` | 512 MB |
| `worker` | Procrastinate, LangGraph | Agents, jobs, events | `data`, `graph`, `files`, `ml`, `telemetry`, `llm_egress` | 768 MB |
| `executor` | Python | External actions | `data`, `mail`, `telemetry` | 256 MB |
| `ml` | FastAPI, Docling, fastembed | Parsing and models | `ml`, `telemetry` | 4 GB |
| `postgres` | PostgreSQL 17, pgvector | Source of truth | `data` | 1 GB |
| `neo4j` | Neo4j 5.26 Community | Graph read model | `graph` | 1 GB |
| `minio` | MinIO (Chainguard build) | File storage | `files` | 512 MB |
| `mailpit` | Mailpit 1.27 | Sandbox mail | `mail` | 64 MB |
| `otel-lgtm` | Grafana, Tempo, Loki, Prometheus | Telemetry | `telemetry`, `telemetry_ui` | 1.5 GB |
| `migrate` | Alembic | One-shot migrations | `data` | 256 MB |
| `minio-volume-init` | One-shot | Fixes volume ownership | None | None |
| `tunnel` | Cloudflare `cloudflared` | Public link, in public mode only | `edge_public` | 128 MB |

The long-running services' limits add up to about 10.4 GB, without the tunnel.

Python services run read-only, with all capabilities dropped and `no-new-privileges`.

### `caddy`

The single entry point, bound to `127.0.0.1:8080`. It routes `/api/*` to `api` and everything else to `web`, and removes the `Server` header. It caps request bodies at 25 MB and sets `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and `Cross-Origin-Opener-Policy`. Its admin API is off.

### `web`

The Next.js app. Pages are client components that call the API on the same origin with the session cookie and CSRF header, so the browser never talks to anything but Caddy. Its network has no route to data stores. Production uses a standalone build. See [The frontend](#the-frontend).

### `api`

Serves the kernel and pack routers. It records approvals but can't send mail, call a model or reach `ml`: it has no LLM keys, no agent libraries (`test_api_loads_without_agent_libraries.py` proves it starts without them) and no route to those networks. Uploads go to MinIO and publish an event, and the worker does the rest.

- `/healthz`: the process is alive.
- `/readyz`: requires Postgres and files. Losing Neo4j reports `graph: degraded` and stays ready.
- Swagger and `openapi.json` are served in development only.

### `worker`

Runs three things:

- **Event relay loop:** for each active tenant under its own RLS scope, it processes pending inbound mail, delivers outbox events to consumers, and runs approved internal actions.
- **Durable jobs (Procrastinate, in Postgres):** agent runs at a concurrency of 4, follow-up sweeps every 30 minutes, and the daily digest at 07:00. The schedule survives restarts.
- **Agents (LangGraph):** every node commits by itself and checkpoints go to Postgres, so a crash resumes without repeating paid model calls.

It's the only service with LLM keys and the only one with internet access. Its database role can't write approvals, and it holds no mail credentials.

### `executor`

The only process that can send anything. Every second, it picks up approved external proposals for each tenant and runs them through `trust.execute`, which checks them again and calls the adapter. Every 5 seconds it polls the inbound mailbox, and every 30 seconds it reconciles interrupted executions.

Its database role sees only the trust schema, plus INSERT on `comms.inbound_mail`. It can't read CVs, salaries or pack data, even by mistake. Its network reaches only data, mail and telemetry. A deterministic Message-ID makes reconciliation safe, so a crash after sending can't send twice.

### `ml`

Handles untrusted files on a network with no internet. Models are baked into the image and run offline (`HF_HUB_OFFLINE`).

| Endpoint | Does |
|---|---|
| Parse | Hidden-text scan and removal (pdfplumber, pypdfium2), Docling to Markdown, Tesseract OCR for scans, visible lines for blinding. About 1.2 s per CV once warm |
| Embed | `paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions, rounded to 6 decimals so similarities stay stable. Up to 128 texts |
| Rerank | `BAAI/bge-reranker-v2-m3` int8 cross-encoder, up to 32 passages |

### `postgres`

The only source of truth: business data, vectors, the event outbox, jobs and agent checkpoints. Four login roles exist, none a superuser and none with BYPASSRLS. See [Data](#data).

| Role | Used by | Can |
|---|---|---|
| `astra_owner` | `migrate` only | Own schemas, run migrations |
| `astra_api` | `api` | Read and write app tables; the only role that can insert an approval |
| `astra_worker` | `worker` | Read and write app tables; record executions, not approvals |
| `astra_executor` | `executor` | Trust schema only, plus insert raw inbound mail |

### `neo4j`

A read model rebuilt from the event log, never a source of truth. `python astra.py graph-rebuild` recreates it. Reads use named query templates only (`agent_mesh`, `decision_chain`, `skills_graph`, `bus_factor`, `learning_path`), with `tenant_id` injected by the kernel. Writes come from declarative projections in the manifests, with labels checked against strict patterns and values passed as parameters, so text from a CV stays inert. Salaries, emails, phones and CV text are forbidden in the graph by code. If it goes down, only the graph features degrade.

### `minio`

S3-compatible storage for CVs, attachments and policies. Keeping to the S3 API makes it cheap to replace. The executor has no route to it.

### `mailpit`

A sandbox SMTP server and mailbox, so the demo can never email a real person. Its API stands in for IMAP or Microsoft Graph on the inbound side. Only the executor's network reaches it.

### `otel-lgtm`

A single container with Grafana, Tempo (traces), Loki (logs) and Prometheus (metrics), receiving OTLP from the Python services. See [Observability](#observability).

### `tunnel`

Only in public mode, from `ops/compose.public.yaml`. It runs `cloudflared` with a read-only filesystem, all capabilities dropped and no secrets, and forwards visitors to Caddy. See [Public link](#public-link).

### `migrate`

Runs Alembic per schema and syncs the action catalogue, then exits. It's the only process holding the owner password.

---

## How everything connects

Modules talk through contracts or versioned events in a **transactional outbox**. An event is written in the same transaction as the change, so neither can happen without the other. The relay delivers each event to each consumer in isolation, with retries and a dead-letter state, so one failing consumer can't block the others.

Main cross-module flows:

```text
talent.candidate.hired.v1
  -> finance: creates a hire notice, HR completes it into an engagement

POST /people/employees -> core.employee.created.v1
  -> journey: onboarding_planner proposes the 30/60/90 plan

finance.engagement.activated.v1
  -> journey: fallback trigger for the onboarding plan

comms.message.received.v1
  -> inbox_triage -> comms.message.classified.v1
  -> reply_drafter or slot_picker -> proposal

talent.cv.uploaded.v1 -> cv_reader -> talent.cv.processed.v1
talent.ranking.requested.v1 -> ranking -> talent.ranking.completed.v1 -> shortlist proposal
talent.interview.requested.v1 -> scheduler -> offer proposal
trust.proposal.rejected.v1 -> talent frees the held slots
trust.action.executed.v1 -> inbox marks the conversation handled, graph projects it
```

Events by module:

- **Talent:** `job.created`, `cv.uploaded`, `cv.processed`, `ranking.requested`, `ranking.completed`, `application.stage_changed`, `candidate.hired`, `followup.due`, `interview.requested`, `interview.booked`, `interview.cancelled`
- **Journey:** `plan.activated`, `checkin.due`, `pulse.submitted`, `evidence.recorded`, `skill_gap.confirmed`, `training.completed`, `onboarding.completed`
- **Finance:** `engagement.validated`, `engagement.activated`, `engagement.amended`, `engagement.ending_soon`, `civp.activated`, `civp.payment_due`, `civp.payment_reconciled`, `civp.completed`, `payroll.inputs_validated`, `payroll.calculation_requested`, `payroll.calculated`, `payroll.approved`, `payroll.rejected`, `payroll.closed`, `payment.submitted`, `payment.reconciled`

---

## The kernel

`packages/kernel/` holds what every pack shares.

| Module | Does |
|---|---|
| `identity` | Users, roles, Argon2 passwords, lockout, sessions, step-up |
| `authz` | Scoped roles and the two-person check |
| `db`, `rls`, `migrate` | Tenant-scoped sessions, RLS helper, per-schema Alembic |
| `people` | Persons, employees, org units, positions, skills with relations and evidence, KPIs |
| `trust` | Action catalogue, proposals, hash-bound approvals, gated execution, crash reconciliation, audit chain |
| `explain` | DecisionRecords: factors that sum exactly, evidence, counterfactuals by real re-scoring, scorer registry, replay, narrative validator |
| `events`, `jobs` | Outbox, consumers, dead-letter; Procrastinate setup |
| `ai` | Gateway, providers, sanitizer, injection guard, identifier masking, quarantined reader, agent runtime, LangGraph checkpoints |
| `graph` | Neo4j projections and query templates |
| `comms` | Threads, messages, sorting, digest, corrections, inbound mail and attachments |
| `schedule` | Busy time, holds, bookings, slot finding (Africa/Tunis), ICS rendering and import, calendar locks |
| `knowledge` | Policy versions, role-filtered hybrid search, cited answers, HR tickets, feedback |
| `adapters` | Mail sending, mailbox polling |
| `files` | Upload gate (type by magic bytes, UTF-8 checks, 20 MB per file) and MinIO |
| `ml_client` | Client for parse, embed and rerank |
| `registry` | Loads pack manifests, mounts routers, wires agents and consumers, runs internal actions |
| `obs`, `heartbeat` | Telemetry setup, process liveness |

### The AI gateway

Packs ask for a tier (`fast`, `standard`), never a provider or model. Haiku (`claude-haiku-5-5`) serves both tiers, with Groq (`openai/gpt-oss-20b`) as automatic fallback on provider failure.

The gateway enforces strict JSON schemas, a budget of 40,000 tokens per run and 2,000,000 per tenant per day, caching, and token, cost and latency tracking per step. It has no tools parameter by design.

---

## Service packs

Each pack in `packages/packs/<pack>/` has a manifest declaring its actions with their risk class, its agents, the events it publishes and its graph projections, plus its own schema and routes.

### `talent`: recruitment

Jobs, rubrics, CV pipeline, two-layer ranking, overrides with reasons, replies, follow-ups, interviews, hire and reject. Actions: `talent.shortlist.confirm`, `talent.interview.book` and `talent.interview.cancel` (R2); `talent.application.reject` and `talent.application.hire` (R3).

### `journey`: onboarding and training

- 30/60/90 plans from role templates, with tasks that record evidence, day 7/30/60/90 check-ins, a buddy, and factual support flags.
- Skill gaps from evidence against role requirements, each with severity, confidence, factors and a decision record, confirmed by a person.
- Training recommendations tied to a KPI, with cost, hours, an internal mentor alternative and the expected effect.
- Observed impact, with its method and caveat stated. Team heatmaps suppress any group under 5 people, for privacy.
- A Day-90 review pack that never records a decision.

### `finance`: Tunisian payroll

- **Rule sets:** versioned definitions with hand-checked examples. Activating one is R3. An active rule set can't change, even for the owner role, by a database rule.
- **Engagements:** CDI, CDD and CIVP contracts, with a document checklist and blocking validation. Activation is R2.
- **Inputs:** approved hours, absences, bonuses, allowances and reimbursements by CSV or JSON, with rejections and conflict checks.
- **Runs:** deterministic calculation per payslip (CNSS, IRPP, solidarity contribution), exceptions, submission, R3 approval, and replay that checks every payslip and the run's hash.
- **Calculator:** gross to net, line by line, with the rule behind each line. Nothing is stored.
- **Hire notices** from `talent`.

See [docs/FINANCE_INDEX.md](docs/FINANCE_INDEX.md).

---

## The agents

Eleven agents. Each has one job and can only propose. The names are the faces shown in the app.

| Face | Agent id | Module | Trigger | Does |
|---|---|---|---|---|
| Mira | `rubric_builder` | talent | `talent.job.created.v1` | Drafts job criteria for a person to approve |
| Idris | `cv_reader` | talent | `talent.cv.uploaded.v1` | Reads a CV with no identity and no tools, and verifies quotes |
| Nour | `ranking` | talent | `talent.ranking.requested.v1` | Scores by formula, explains, proposes a shortlist |
| Salem | `inbox_triage` | kernel | `comms.message.received.v1` | Sorts email, flags what needs a person |
| Yara | `reply_drafter` | talent | `comms.message.classified.v1` | Drafts from one candidate's file; reads replies about times |
| Tarek | `followup` | talent | `talent.followup.due.v1` | Prepares reminders, within the limit |
| Dali | `scheduler` | talent | `talent.interview.requested.v1` | Holds real free times and prepares the offer |
| Hela | `policy_answers` | kernel | `knowledge.question.asked.v1` | Cited answers, or passes it to HR |
| Aziz | `onboarding_planner` | journey | `core.employee.created.v1` | Drafts the 30/60/90 plan |
| Rym | `skill_gap_analyst` | journey | `journey.plan.activated.v1`, `journey.evidence.recorded.v1` | Proposes gaps with a decision record |
| Malek | `training_planner` | journey | `journey.skill_gap.confirmed.v1` | Proposes training and a mentor alternative |

Agents are LangGraph graphs running as durable Procrastinate jobs. A run ends at a proposal rather than an `interrupt()`: approval is a separate step in the trust ledger, so nothing waits in memory.

---

## The frontend

`apps/web`: Next.js 16 App Router, React 19, TypeScript, Tailwind 4, Motion for animation and d3-force for the graph. Instrument Sans is self-hosted through npm, so it needs no external requests.

| Route | Page | Main APIs |
|---|---|---|
| `/` | Landing | None |
| `/login` | Log in | `/auth/login` |
| `/signup` | Request access | Browser store |
| `/demo` | Demo film | Static file |
| `/overview` | Morning dashboard | Proposals, runs, stats, jobs, bookings, plans |
| `/approvals` | Review and decide | `/trust/proposals`, `/explain`, `/auth/step-up` |
| `/inbox` | Digest and conversations | `/comms/*` |
| `/jobs`, `/jobs/[id]` | Jobs, ranking, criteria, CVs | `/packs/talent/jobs/*` |
| `/candidates` | Everyone across jobs | Per-job shortlists |
| `/interviews` | Calendar | `/calendar/*`, interviews |
| `/onboarding` | Plans and gaps | `/packs/journey/*`, `/people/*` |
| `/payroll` | Runs, calculator, rules | `/packs/finance/*` |
| `/ask` | Questions, tickets, policies | `/knowledge/*` |
| `/agents` | Crew and runs | `/ai/runs` |
| `/graph` | Three graphs | `/graph/*`, shortlists, `/people/*` |
| `/audit` | Hash chain | `/trust/audit`, `/trust/audit/verify` |
| `/reports` | Analytics | Runs, stats, shortlists |
| `/settings` | Account, team, rules, templates, privacy | `/registry/packs` |

Shared pieces in `src/ui`:

- `Shell`: sidebar, command palette, notifications, toasts, theme.
- `Face`: agent faces. Mood comes from real run and proposal state, through `moodsFrom` in `lib/hiring.ts`.
- `ForceGraph`: canvas graph.
- `WhyPanel`: explanations.
- `CandidateDrawer`, `EvidenceStrip`, `charts`, `kit`.

`lib/api.ts` is the typed client. It adds the CSRF header and normalises errors.

**Recruiter workspace data.** Notes, scorecards, tags, stars, the working pipeline board, job publishing, private drafts, email templates, invitations, notification choices, the retention setting and deletion requests are saved in the browser through `lib/local.ts` in this version, separate from official records. They can't send anything or change a decision, so the approval rule holds. [docs/FRONTEND_ONLY.md](docs/FRONTEND_ONLY.md) maps each one to its planned API.

---

## APIs

- **Base URL:** `http://127.0.0.1:8080/api`
- **Size:** 122 operations across 111 paths, OpenAPI 3.1
- **Contract:** [`contracts/openapi.json`](contracts/openapi.json), generated types in [`contracts/openapi.d.ts`](contracts/openapi.d.ts)
- **Full guide, with every route and body:** [docs/API_CONTRACT.md](docs/API_CONTRACT.md)

Conventions: session cookie plus `x-csrf-token` on every write. Errors are `{"error", "message"}`. Times are ISO 8601 with a timezone. Money, weights and scores are decimal strings.

| Group | Paths | Purpose |
|---|---|---|
| Platform | `/healthz`, `/readyz`, `/registry/packs` | Health, installed modules, declared actions |
| Identity | `/auth/login`, `/logout`, `/me`, `/step-up` | Sessions and password re-check |
| People | `/people/employees`, `/people/org` | Employees and reference data |
| Trust | `/trust/proposals` (list, get, approve, reject, edit), `/trust/audit`, `/trust/audit/verify` | The decision ledger |
| Explain | `/explain/{id}`, `/explain/{id}/verify` | Decision records and replay |
| Agents | `/ai/runs`, `/ai/runs/{id}` | Runs with steps, tokens, cost |
| Graph | `/graph/{view}`, `/graph/decision/{id}` | Read-model views |
| Inbox | `/comms/digest`, `/stats`, `/threads`, `/threads/{id}`, `/handled`, `/reopen`, `/messages/{id}/sorting` | Digest and conversations |
| Knowledge | `/knowledge/questions`, `/tickets`, `/documents`, `/stats` | Questions, HR queue, policies |
| Calendar | `/calendar/busy`, `/import`, `/free`, `/bookings` | Availability and bookings |
| Talent | `/packs/talent/jobs`, `/cvs`, `/rubrics`, `/rankings`, `/shortlist`, `/interviews`; `/applications/{id}/profile`, `/overrides`, `/reject`, `/hire`; `/interviews/{id}/book`, `/cancel`; `/followups/check` | Recruitment |
| Journey | `/packs/journey/plans`, `/plans/me`, `/tasks/{id}/complete`, `/checkins/{id}/submit`, `/dossier`, `/gaps`, `/heatmap`, `/impact`, `/recommendations` | Onboarding and skills |
| Finance | `/packs/finance/rule-sets`, `/engagements`, `/hire-notices`, `/input-batches`, `/payroll-runs`, `/payslips`, `/issues`, `/documents`, `/calculator/net`, `/calculator/compare` | Payroll |

Regenerate the contract after a route change:

```bash
python astra.py export-api
```

```bash
npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts
```

---

## Data

### Stores

| Store | Holds | If it's down |
|---|---|---|
| PostgreSQL | Everything authoritative, plus vectors, outbox, jobs, checkpoints | The platform stops safely |
| MinIO | Original files | Uploads are denied |
| Neo4j | Rebuildable graph | Graph views degrade, everything else works |

### Schemas

| Schema | Tables | Holds |
|---|---|---|
| `core` | 16 | Tenants, users, roles, login attempts, people, org, skills, KPIs, event outbox and deliveries |
| `trust` | 10 | Action catalogue, proposals, approvals, executions, audit chain, decision records, factors, evidence, counterfactuals |
| `ai` | 6 | Agent runs and steps, prompt versions, LLM cache, security events, eval results |
| `comms` | 7 | Threads, messages, classifications, digests, inbound mail, attachments |
| `calendar` | 4 | Busy blocks, holds, bookings, seats |
| `knowledge` | 4 | Documents, chunks with vectors, questions, tickets |
| `talent` | 14 | Jobs, rubrics, candidates, identities (kept apart), applications, CV documents and chunks, profiles, rankings, scores, overrides, stage events, follow-ups, interviews |
| `journey` | 15 | Templates, plans, tasks, check-ins, pulses, buddies, flags, requirements, gaps, courses, enrolments, recommendations, impact |
| `finance` | 23 | Rule sets, engagements, pay items, CIVP, documents, input batches, runs, payslips and lines, issues, payments |
| `jobs`, `agent_ckpt` | 4 each | Procrastinate queues and LangGraph checkpoints |

Candidate identity lives in its own table, separate from the blinded CV text the agents read.

### Demo data

| Path | Contents |
|---|---|
| `data/world.json` | The fictional company: 40 employees, 6 org units, 12 positions, 19 skills, 6 KPIs, 7 users |
| `data/demo/cvs/` | 42 labelled CVs, including white-text, visible-instruction, French-instruction, keyword-stuffing and scanned attacks, and a hard set |
| `data/cvs/` | 30 anonymised tech CVs in PDF, DOCX, HTML, Markdown and text, from a CC0 dataset paired with fictional identities |
| `data/jobs/` | 12 job descriptions |
| `data/demo/emails.json` | 22 inbox emails: applications, reschedules, salary, visa, legal threats, spam, injections |
| `data/demo/policies/` | Leave, remote work, expenses, conduct, and restricted salary bands |
| `data/demo/finance/` | The Tunisian payroll rule set |

---

## Multi-tenancy

Isolation is enforced by the database, not by remembering a `WHERE` clause.

1. **The tenant comes from the signed session.** It's chosen at login by company slug and never accepted from the client afterwards.
2. **Each transaction sets it.** `tenant_session()` calls `set_config`, and `core.current_tenant()` reads it back.
3. **Every tenant table has a forced policy.** `ENABLE` and `FORCE ROW LEVEL SECURITY`, with `USING` and `WITH CHECK` on `tenant_id = core.current_tenant()`. Reads and writes are both covered, including for the table owner.
4. **No application role can bypass it.** None is a superuser or has BYPASSRLS.
5. **Background processes keep the scope.** The worker and executor loop over active tenants, each in its own RLS session.
6. **Neo4j is scoped too.** Every node has `tenant_id`, and the kernel injects it into every query template.
7. **Budgets are per tenant,** so one company can't use up another's model allowance.
8. **Tests enforce it.** `test_every_tenant_table_has_rls_forced` fails on a new table without RLS, `test_no_application_role_can_bypass_rls` checks the roles, and API tests confirm another tenant's data returns 404.

A few tables are deliberately global: `core.tenant`, `core.alembic_version`, the action catalogue `trust.action_type` and `trust.policy_version`. The `jobs` and `agent_ckpt` schemas hold runtime queue and checkpoint state.

Roles are also scoped. A manager's grant covers their own `org_unit`, checked against the target recorded on each proposal.

---

## Security

The brief judges three fronts: AI, the system and the web app.

### AI: prompt injection and model misuse

Untrusted text passes through one path, `kernel/ai/reader.py`:

```text
untrusted text -> sanitize -> guard -> model with NO tools -> strict schema -> quote check
```

| Layer | Does | Why it matters |
|---|---|---|
| File cleaning | Deletes hidden text from the file before reading | The attack never reaches a model |
| Sanitizer | Normalises and caps the text | Removes tricks based on encoding |
| Injection guard | Multilingual patterns (EN, FR, AR), with an optional remote classifier that fails closed | Flags attempts for people. It's one layer, not the defence |
| No tools | The gateway has no tools parameter | A fooled model has nothing to call |
| Strict schema | Pydantic validation of every answer | Only structured data leaves |
| Quote check | Every quote must exist in the source | Invented evidence is removed |
| Deterministic decisions | Scores and pay are code | Nobody can talk a formula into anything |
| Number-checked narration | Explanations see numbers only, and a wrong number or uncited sentence is rejected | Text can't drift from the facts |
| Isolation per candidate | The drafter gets one file; drafts mentioning another candidate are refused | No leaks between people |

### The system

- **Network boundaries as controls.** Only `worker` has internet egress and LLM keys. Only `executor` reaches mail. `ml` is on internal networks only. The executor can't reach files or the graph. `tests/test_compose_boundaries.py` checks all of this.
- **Database roles as controls.** Only `api` can insert an approval. The executor sees only the trust schema. A bug in application code can't get around these.
- **Hardened containers.** Read-only filesystems, all capabilities dropped, `no-new-privileges`, memory limits, digest-pinned images.
- **The approval gate.** Bound to a payload hash, with role and target checks, a second person and fresh password for R3, and no self-approval. Execution re-checks and is idempotent, and crash reconciliation prevents double sends.
- **Tamper-evident audit.** Each entry hashes the one before it. `POST /trust/audit/verify` recomputes the chain, and editing, removing or reordering any row is detected.
- **Secrets.** Generated by `astra.py init` into a git-ignored `.env`. Development mounts named folders only, so `.env` never enters a container.
- **Telemetry hygiene.** Traces, logs and metrics carry hashes, IDs and counts, never CV, email or policy text.
- **Fail closed.** If a security check can't run, the answer is deny, or the input is flagged for a person.

### The web app

| Control | Implementation |
|---|---|
| Passwords | Argon2 |
| Sessions | HS256 JWT in an `HttpOnly`, `SameSite=Strict` cookie, valid 8 hours, `Secure` outside development |
| CSRF | Double-submit: `astra_csrf` cookie compared in constant time to the `x-csrf-token` header on every write |
| Brute force | Lockout after 5 failures in 5 minutes for an email and IP pair |
| Step-up | Password re-check valid for 5 minutes, required for R3 |
| Authorization | Checked on every route by the API. The UI only hides what you can't use |
| Uploads | Allowed types verified by magic bytes, UTF-8 checks on text, 20 MB per file, 200 files per upload, 25 MB per request at the edge |
| Headers | CSP, `frame-ancestors 'none'`, nosniff, referrer and permissions policies, COOP |
| ICS safety | Strict patterns stop an address or UID from injecting lines |
| Search | LIKE input is escaped, and all queries are parameterised |

---

## Infrastructure

The whole platform is containerised. Every process and data store runs in Docker, so one machine with Docker can run all of it.

### Run it with Docker

You don't need Python packages, Node or a database on your machine: only Docker with at least 8 GB of memory (16 GB is more comfortable), Git and Python 3.12+ to run the small `astra.py` task runner.

```bash
git clone https://github.com/OussemaHarrabi/AstraRH.git
```

```bash
cd AstraRH
```

```bash
python astra.py init
```

Add `ANTHROPIC_API_KEY` and `GROQ_API_KEY` to the new `.env`. Then start the stack and load the demo data:

```bash
python astra.py up
```

```bash
python astra.py seed
```

```bash
python tools/demo_state.py
```

Open http://127.0.0.1:8080. To stop it:

```bash
python astra.py down
```

Data stays in Docker volumes across restarts. `python astra.py down --wipe` deletes it.

The first build takes a while, because the `ml` image downloads its AI models and bakes them in, so it can run with no internet afterwards.

### Images

| Image | Built from | Runs |
|---|---|---|
| `astrarh-web` | `ops/docker/web.Dockerfile`, multi-stage (development target, or a standalone production build as a non-root user) | `web` |
| `astrarh-python` | `ops/docker/python.Dockerfile`, non-root user `astra` | `api`, `executor`, `migrate` |
| `astrarh-worker` | Same file, with the agent and LLM libraries | `worker` |
| `astrarh-ml` | Same file, with Docling, Tesseract and the baked-in models | `ml` |
| Pinned by digest | Official images | `caddy`, `postgres` (pgvector), `neo4j`, `minio`, `mailpit`, `otel-lgtm`, `tunnel` |

Only the worker image installs agent and LLM libraries, and only the `ml` image contains the models and OCR.

### Modes

`astra.py` works the same on Windows, macOS and Linux, and makes `.env` win over shell variables. Each mode is a set of Compose files in `ops/`.

| Mode | Command | Differences |
|---|---|---|
| Development | `python astra.py up` | Live reload, loopback tool ports, test runner |
| Public | `python astra.py public` | Production settings and build, plus a public HTTPS link. See [Public link](#public-link) |
| Hardened | `python astra.py up --secure` | No tool ports, production web build. Set `ASTRA_ENV` to anything but `dev` to turn off API docs and turn on secure cookies |

The networks, which are the core of the deployment design:

| Network | Internal | Connects |
|---|---|---|
| `edge_public` | No | `caddy`, `tunnel` |
| `edge_internal` | Yes | `caddy`, `web`, `api` |
| `data` | Yes | `api`, `worker`, `executor`, `migrate`, `postgres` |
| `graph` | Yes | `api`, `worker`, `neo4j` |
| `files` | Yes | `api`, `worker`, `minio` |
| `ml` | Yes | `worker`, `ml` |
| `mail` | Yes | `executor`, `mailpit` |
| `telemetry` | Yes | Python services, `otel-lgtm` |
| `telemetry_ui` | No | `otel-lgtm` |
| `llm_egress` | No | `worker` |

### Public link

```bash
python astra.py public
```

This starts the production stack and prints a public HTTPS link. The whole platform stays running in Docker on the host, and visitors reach it through that link:

```mermaid
flowchart LR
  V[Visitor's browser] -->|HTTPS| CF[Cloudflare edge]
  CF -->|outbound tunnel| T[tunnel container]
  T --> C[caddy]
  C --> W[web]
  C -->|/api| A[api]
  A --> D[(Postgres, MinIO, Neo4j)]
```

- **No port is opened on the host.** The `tunnel` container makes an outbound connection, so nothing needs configuring on the router or firewall.
- **It reaches only Caddy.** The tunnel sits on the edge network alone and holds no secrets. `test_tunnel_reaches_only_the_edge_and_holds_no_secrets` checks this.
- **The frontend and API share one address.** That keeps the `SameSite=Strict` session cookie and CSRF protection working as designed.
- **Production settings apply.** Secure cookies are on, API docs are off, and the web app is a production build. Mailpit, Neo4j and MinIO have no published ports. Grafana stays on the host's loopback only.
- **It restarts itself.** Every container uses `restart: unless-stopped`. The link keeps working while the host and Docker are running.

The link is a Cloudflare quick tunnel, so it needs no account. It changes if the tunnel container is recreated: run `python astra.py public` again to see the current one. `python astra.py down` closes it.

### Deploying to a server

Deploying without a tunnel needs a Linux host with at least 16 GB of memory and 4 vCPUs, plus a domain with HTTPS. Caddy currently listens on HTTP behind loopback with `auto_https off`, so a public deployment changes the site address to the domain and turns automatic HTTPS and HSTS on. Secure cookies switch on with `ASTRA_ENV`.

To use real mail, replace `SMTP_HOST` and the `mailbox` adapter's provider with SMTP and IMAP or Microsoft Graph. To use real storage, point the S3 settings at any S3-compatible service.

---

## Scalability

**What was designed for it:**

| Part | How it scales |
|---|---|
| `api` | Stateless: sessions are signed cookies and state is in Postgres, so more replicas behind Caddy is enough |
| `web` | Stateless |
| Agent work | Durable jobs in Postgres. Raise `AGENT_CONCURRENCY` (now 4) or add workers. Event deliveries are claimed with `FOR UPDATE SKIP LOCKED`, so parallel relays don't take the same row |
| `ml` | Stateless, models baked in. Replicas can be added, and it can be sized separately from the rest of the platform |
| Model cost | Per-run and per-tenant-per-day budgets, caching, and frozen CV readings, so re-ranking doesn't call the model again |
| Heavy steps | LLM calls and parsing happen out of band; the API returns 202 and the UI polls |
| Files | S3 API, so storage is replaceable |
| Graph | Rebuildable from events, and optional for core features |
| Modules | The modular monolith can split a pack out later, since packs talk through contracts and events |

**What has been measured:**

| Measure | Result |
|---|---|
| Reading 42 CVs with the real model | About 66 seconds, or 1.6 s per CV |
| Parsing one CV once warm | About 1.2 s |
| Screening run cost | About $0.018 |
| Reranker | About 50 ms per short pair on CPU |

**How it grows next:**

- **Event relay and executor:** run more of them per group of tenants, since deliveries are already claimed safely.
- **Vector search:** exact today, chosen for repeatable scores. Policy search can add an HNSW index without affecting ranking.
- **Postgres:** scale up first, then move the queue and vectors to their own instances.
- **Neo4j:** rebuildable from events, so it can be replaced or upgraded without risk to the data.
- **Hosting:** Compose on one host today. Moving to an orchestrator keeps the same network rules.

---

## Observability

| Signal | Where | Details |
|---|---|---|
| Traces | Tempo | FastAPI and HTTPX auto-instrumentation in `astra-api`, `astra-worker`, `astra-executor`, `astra-ml`. Spans for heartbeat, mailbox and reconcile. `trace_id` is stored on audit entries and agent runs, so a decision links back to its trace |
| Metrics | Prometheus | `astra.llm.tokens`, `astra.llm.cost`, `astra.llm.calls`, `astra.llm.latency` (labelled by cache and fallback), `astra.security.flagged`, plus standard HTTP metrics |
| Logs | Loki | Python logging over OTLP |
| Health | Compose and API | `/healthz`, `/readyz` with per-dependency status; heartbeat file checks on `worker` and `executor`, which Docker reports as unhealthy if stale for 90 seconds |
| Business view | The app | `/agents` (runs, steps, tokens, cost, fallback, cache), `/audit`, `/reports`, inbox correction rate, `ai.security_event` |

### Grafana

The `otel-lgtm` container bundles Grafana with Tempo, Loki and Prometheus, and is part of every mode. Open **http://127.0.0.1:3001** on the machine running the stack and go to Explore:

- **Tempo:** search traces by service, such as `astra-worker`, and follow a request across steps. A `trace_id` from the audit log or an agent run finds the matching trace.
- **Prometheus:** chart `astra.llm.cost`, `astra.llm.tokens`, `astra.llm.latency` and `astra.security.flagged`.
- **Loki:** read each service's logs.

It's bound to loopback, so it's never reachable through the public link. Telemetry is configured through standard `OTEL_*` variables, so it can point at any OTLP backend.

---

## Testing and evaluation

```bash
python astra.py check
```

Runs ruff and pytest inside the tests container, against the real database with real roles. **Last full run: 868 passed, 2 skipped.** The two skips are the live-stack test and the live model call, which run through these separately:

```bash
python astra.py smoke
```

```bash
python astra.py live
```

`smoke` verifies health, network isolation, credential isolation, database permissions and telemetry, and runs one real end-to-end flow: nothing is sent before approval, then the real executor sends to the mailbox, the chain verifies, and the worker projects it into Neo4j.

| Test file | Proves |
|---|---|
| `test_architecture.py` | Only the executor sends; only the gateway calls providers; RLS forced everywhere; no role bypasses it |
| `test_compose_boundaries.py` | Only the worker has LLM keys and internet; only the executor reaches mail; `ml` is internal |
| `test_trust_path.py` | Editing voids approval; duplicate execution calls once; crash after send doesn't resend; audit tampering is detected |
| `test_explain.py` | No record, no proposal; factors sum exactly; replay reproduces; counterfactuals match real re-scoring |
| `test_talent_scoring.py`, `test_talent_pipeline.py`, `test_talent_hire.py` | The formula, the pipeline, R3 flows |
| `test_ai.py`, `test_parsing.py`, `test_rerank.py` | Reader, guard, hidden-text variants, reranker |
| `test_communications.py`, `test_inbox_api.py`, `test_inbound_mail.py` | Replies, follow-ups, holds, invites, inbox, live mail round trip |
| `test_calendar_api.py`, `test_knowledge_api.py` | Calendars, ICS import, policy answers, tickets, versions |
| `test_graph.py`, `test_events.py` | Loss and rebuild of Neo4j, tenant separation, inert malicious text, event delivery |
| `test_finance_*.py` | Calculation, rules, engagements, inputs, runs, schema protections |
| `packs/journey/tests/` | Gaps, planning, contracts |
| `test_employee_flow.py`, `test_web.py`, `test_api_loads_without_agent_libraries.py` | Cross-module flows, web routes, process boundaries |

### Real-model evaluations

```bash
python astra.py evals
```

Calls the real model for about 3 cents, and writes [`docs/evals/screening.json`](docs/evals/screening.json) and [`docs/evals/communications.json`](docs/evals/communications.json).

| Area | Measure | Result |
|---|---|---|
| Screening | Ranking quality, 42 CVs (NDCG@10) | 1.0 |
| | Harder set (NDCG@12) | 1.0 |
| | Strong candidates in the top 10 | 10 of 10 |
| | Quotes found word for word | 177 of 177 |
| | Scores that replay exactly | 42 of 42 |
| | Hidden-text attack vs clean twin | Same score |
| | Same CV under another name | Same score |
| Inbox | Type correct | 17 to 18 of 20 |
| | "Needs a person" caught / false alarms | 8 of 8 / 0 of 12 |
| Policy answers | Right document / correctly passed to HR | 8 of 8 / 6 of 6 |
| | Restricted documents leaked | 0 |
| Slot picking | Read correctly (EN, FR, AR, "option 1", injection) | 8 of 8 |
| | Wrong bookings / unclear left to a person | 0 / 4 of 4 |

---

## Configuration

`python astra.py init` creates `.env` from `.env.example` and generates secrets. It's git-ignored.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | Model providers. Only the worker receives them |
| `LLM_FAST_MODEL`, `LLM_STANDARD_MODEL` | Models behind each tier |
| `LLM_FALLBACK_MODEL` | Used on provider failure |
| `LLM_GUARD_MODEL`, `GUARD_REMOTE` | Optional remote injection classifier, off by default |
| `LLM_TENANT_DAILY_TOKENS` | Tenant budget, 2,000,000 by default |
| `POSTGRES_PASSWORD`, `ASTRA_OWNER_PASSWORD`, `ASTRA_API_PASSWORD`, `ASTRA_WORKER_PASSWORD`, `ASTRA_EXECUTOR_PASSWORD` | One database credential per process |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | File storage |
| `NEO4J_PASSWORD` | Graph |
| `SESSION_SECRET` | Signs session tokens |
| `DEMO_PASSWORD` | Password of the seeded demo accounts |
| `ASTRA_ENV` | `dev`, or any other value for production behaviour: controls secure cookies and API docs |

---

## Commands

| Command | Does |
|---|---|
| `python astra.py init` | Create `.env` with generated secrets |
| `python astra.py up [--secure]` | Build and start, and run migrations |
| `python astra.py public` | Production stack plus a public HTTPS link |
| `python astra.py down [--wipe]` | Stop, optionally deleting all data |
| `python astra.py ps`, `logs [service]` | Status and logs |
| `python astra.py seed [--no-cvs]` | Load the demo company through the real pipeline |
| `python tools/demo_state.py` | Prepare the full demo state through the API |
| `python astra.py check [tests/...]` | Ruff and pytest |
| `python astra.py evals` | Real-model evaluations |
| `python astra.py smoke` | End-to-end stack verification |
| `python astra.py live` | One real model call |
| `python astra.py makemigration <kernel\|pack> "message"` | New migration. Add `enable_rls` for each new table in a follow-up revision, or a test fails |
| `python astra.py export-api` | Regenerate `contracts/openapi.json` |
| `python astra.py graph-rebuild` | Rebuild Neo4j from the event log |

On Windows with the development stack, run `docker restart astrarh-web-1` after editing `apps/web/src`, since file changes don't reach the dev server through the Docker mount.

---

## Repository layout

```text
apps/
  api/        FastAPI entry point
  worker/     Relay, jobs, agents
  executor/   External actions, mailbox polling
  ml/         Parsing, embeddings, reranker
  web/        Next.js app (src/app routes, src/ui components, src/lib client)
packages/
  kernel/     Shared platform (see "The kernel")
  packs/
    talent/   Recruitment
    journey/  Onboarding, skills, training
    finance/  Tunisian payroll
contracts/    OpenAPI document and generated TypeScript types
data/         Demo company, CVs, jobs, emails, policies, rule set
docs/         Plan, architecture, ranking, API, finance, evals, screenshots
ops/          Compose files, Caddy, Dockerfiles, Postgres init
tests/        Architecture, boundaries, trust, packs
tools/        Data generators, demo state, demo film scripts
astra.py      Task runner
```

---

## What's next

| Feature | What it brings |
|---|---|
| Voice interviews | A LiveKit interview in the applicant's own account, with an animated agent while talking and a report for HR that quotes the transcript |
| Candidate skills gap | Candidate against job, from CV evidence and interview answers |
| Training page | Training suggestions and assignment in the app, on top of the existing recommendations |
| Server-side workspace | The workspace features as server APIs, listed in [docs/FRONTEND_ONLY.md](docs/FRONTEND_ONLY.md) |
| Data rights | Candidate erasure and retention jobs, for GDPR and Tunisian law 2004-63 |
| Invitations | Account creation by invitation |
| Dashboards | Custom Grafana boards, and `GET /overview` and `GET /candidates` endpoints |
| Payments | Payment batches on top of payroll runs |
| `workforce` | The workforce planning pack |

---

## Further documentation

| Document | Covers |
|---|---|
| [docs/HANDOFF.md](docs/HANDOFF.md) | Full project handoff |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Short engineering reference |
| [docs/PLAN.md](docs/PLAN.md) | Approved plan, demo script, phases, verification |
| [docs/SETUP.md](docs/SETUP.md) | Setup and troubleshooting |
| [docs/RANKING.md](docs/RANKING.md) | Ranking method and results |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | Every route, body and response |
| [docs/INTEGRATION_REPORT.md](docs/INTEGRATION_REPORT.md) | How the packs were merged |
| [docs/FINANCE_INDEX.md](docs/FINANCE_INDEX.md) | Payroll documentation |
| [docs/FRONTEND_ONLY.md](docs/FRONTEND_ONLY.md) | Workspace features and their planned APIs |
| [PROGRESS.md](PROGRESS.md) | Build log with what was verified at each step |
