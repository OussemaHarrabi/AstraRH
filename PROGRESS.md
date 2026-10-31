# AstraRH progress log

**Single running log of the build.** Updated after every completed step, so work can resume at any moment, including after a context reset.

## Resume here

**If you are resuming after a context reset, read in this order:** this section → `docs/PLAN.md` (the approved plan, full detail) → `docs/ARCHITECTURE.md` → `docs/SETUP.md`.

- **Current phase:** P5 Communication and P6 Knowledge, backend first. Built, tested and committed in small steps (see the P5/P6 log). **Next: fill the remaining backend APIs the UI needs** (slot holds, ICS invites, ticket handling, inbox listing), then one browser pass.
- **Priority, set by Oussema on 2026-10-31:** ship the hackathon brief's six axes deep and solid first. Teammates' services and team tooling wait until that is done. Ship fast, and test in one final pass rather than retesting at each step.
- **Original P5/P6 plan.** Steps 1 to 3 and 5 are built (see the log); step 4 still lacks slot holds and ICS:
  1. **Inbox and digest** (`packages/kernel/comms/`, schema `comms`): thread, message, classification, digest, digest_item, template. Fictional email seed (about 40) in `data/demo/emails.json` covering applications, reschedules, salary, visa, legal threats and spam, linked to demo candidates. LangGraph agent: classify each message through `ctx.read_untrusted` (type, urgency, needs-human with reason), then a daily digest grouped by type and urgency. Web page `/inbox`.
  2. **Replies** (`packs/talent`): a LangGraph drafter that receives only that candidate's file and validated facts, never another candidate's. Proposes `kernel.email.send` (R2) with a DecisionRecord. Web: edit and approve in `/approvals`, with a proper email form instead of JSON. Test cross-candidate leakage.
  3. **Follow-ups:** durable timers on the `default` queue (`kernel/jobs.py`), cadence limits, stop on reply, reject or hire. Proposes reminders (R2).
  4. **Calendar** (`packages/kernel/calendar/`, schema `calendar`): availability from seed, slot holds, booking, ICS. Scheduler agent proposes 3 real slots from the recruiter's calendar (R2), re-checked at booking, no double booking. Adapter `calendar.book` runs in the executor. Web page for slots.
  5. **Then P6 Knowledge** (Employee Questions): `knowledge` schema with pgvector, hybrid search reused from `packs/talent/signals.py`, ACL before search, cited answers, refusal plus escalation ticket. Policy docs in `data/demo/policies/`. Web chat page.
  6. **Then** dashboards (Trust Center, Agent Run Explorer, Grafana), P7 AstraGraph UI, P8 proof (drills, load test, README, demo script), and after that team handoff: `_example` pack, CI, CODEOWNERS, agent prompts.
- **Migration note for new kernel tables:** `python astra.py makemigration kernel "msg"` scopes to kernel schemas. Add `enable_rls` for each table in a follow-up revision. A test fails otherwise.
- **Patching tip:** on this machine, multi-line Python through the Bash heredoc breaks on quotes. Write patch scripts to the scratchpad and run them with `.venv\Scripts\python.exe -I`.
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
| P3 `platform-v0` | Web shell and seed **done**. Team tooling (`_example`, CI, prompts) moved to the end |
| P4 Screening | **Done** |
| P5 Communication | **In progress**: inbox, replies, follow-ups, booking, slot holds, invites, cancel/reschedule and inbox listing/handled/corrections built and tested. Backend done; UI pass left |
| P6 Knowledge | **In progress**: cited answers, refusal, ticket handling, answer feedback and policy versions built and tested. UI pass left |
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

| 2026-10-31 | **Hackathon requirements first; team services and handoff wait** | Oussema's instruction: a solid foundation even if teammates don't ship |
| 2026-10-31 | **Two-layer ranking: 30 points hybrid search (vector + BM25), 70 points evidence** | Oussema's instruction. Full reasoning in `docs/RANKING.md` |
| 2026-10-31 | **All agents are LangGraph graphs running as durable jobs**; every node commits on its own | Crash resumes without repeating paid calls. `kernel/ai/graphs.py`, `kernel/ai/runner.py` |
| 2026-10-31 | **pdfplumber + Tesseract instead of Docling. NEEDS OUSSEMA'S CONFIRMATION** | pdfplumber exposes text colour and size, which is what catches hidden text. No torch, so the 7.8 GB host and speed are fine. Handles scanned PDFs through OCR. Docling would add table and layout quality if real CVs need it |
| 2026-10-31 | **No cross-encoder reranker. NEEDS OUSSEMA'S CONFIRMATION** | The multilingual one is about 1 GB on CPU, and results on the labelled set don't call for it. The order comes from the formula, so a reranker would add latency and a less explainable step. Can be added to `ml` if real data shows a need |
| 2026-10-31 | **Name removal is local heuristics plus regex, not Presidio. NEEDS OUSSEMA'S CONFIRMATION** | The model then never sees the name at all. Weakness: names elsewhere in a CV can survive unless they repeat the header name. Presidio stays a production upgrade |
| 2026-10-31 | **Self-hosted fonts through npm** | `next/font/google` needs internet at runtime in dev, and the web container has none |

## Log

### P5 Communication and P6 Knowledge: 2026-10-31

Committed in small steps. Each step below is one commit.

1. **Test CV corpus and the 6.2 GB zip fix.**
   - Added Oussema's corpus: `data/cvs/` (30 CVs, each in PDF, DOCX, HTML, MD, TXT and JSON; 2 scanned; `index.csv`, `applications.csv`, `ground_truth.json`) and `data/jobs/` (12 job descriptions, J01–J12). Generator: `tools/build_cv_corpus.py`, profiles in `tools/demo_data.py`.
   - Bug: the generator zipped `data/cvs` into `data/cvs/tech_cv_corpus.zip`, so the zip contained itself and grew to 6.2 GB (corrupt). Every Docker build uploaded it, which made `astra.py check` fail with `bake: exit status 143`. The zip now goes to `data/tech_cv_corpus.zip`. Zips and `data/source/` (Kaggle `Resume.csv`) are ignored by git and Docker.
   - The corrupt zip is still on disk at `data/cvs/tech_cv_corpus.zip` and safe to delete.
   - Not wired into the seed yet: `load_demo` still loads the 42 generated CVs in `data/demo/cvs` (those carry the eval labels).
2. **Kernel: inbox, calendar and policy answers.**
   - `kernel/comms/` (schema `comms`: thread, message, classification, digest, digest_item). The `inbox_triage` LangGraph agent reads each inbound email through `ctx.read_untrusted` and records type, urgency and needs-a-person with a reason. Rules force a person for legal or complaints, discrimination or harassment, salary or offers, visas, health and personal data requests, whatever the model says. Daily digest grouped by type, most urgent first. `record_outbound` keeps approved replies in the same thread even when the subject was edited (the bug the lost session found).
   - `kernel/schedule/` (schema `calendar`: busy_block, booking, booking_seat). One seat row per person and slot, under a unique constraint, so a double booking fails in the database, not just in code. Seed adds busy mornings for Nadia and Karim for the next 14 days.
   - `kernel/knowledge/` (schema `knowledge`: document, chunk, question, ticket). One passage per section. Hybrid search (pgvector + full-text, fused by rank), with the role filter inside the WHERE of both searches, so restricted text can't even be ranked. The `policy_answers` agent: injection guard, forced-human topics, then a minimum similarity, then a cited answer. Every sentence must cite a passage and every quote must appear in it word for word, or the question goes to HR as a ticket.
   - **Bug fixed today:** the citation check split `"...per year. [C1]"` into two sentences, so correct answers were refused (eval: 1/8 answered). A trailing citation now belongs to the sentence before it, and the prompt asks for `"... [C1]."`. Regression cases added to `test_check_answer_rules`.
   - Demo data: `data/demo/emails.json` (22 fictional emails, written by `tools/generate_demo_data.py`) and `data/demo/policies/` (leave, remote, expenses, conduct, and salary bands restricted to hr/admin/finance). Loaded by `astra.py seed`.
   - Migrations, with RLS in their own revisions: `ae38104e4ebd`, `kernel_0003_comms_calendar_rules`, `b83efbe1d77d`, `kernel_0005_knowledge_rules`.
   - API: `GET/POST /comms/digest`, `GET /comms/threads/{id}`, `POST/GET /knowledge/questions`, `GET /knowledge/questions/{id}`, `GET /knowledge/tickets`.
3. **Talent: replies, follow-ups and interview booking** (`packs/talent/communications.py`).
   - `reply_drafter` (on `comms.message.classified.v1`): finds the candidate by sender address, gives the model only that candidate's file, and proposes `kernel.email.send` (R2) with a DecisionRecord. Before anyone sees a draft, deterministic checks reject promises only a person can make and any other candidate's name or email. The name is filled in after the model, so the model never sees it. No draft for spam, internal or policy questions.
   - `followup`: `due_followups` is deterministic. Every 3 days, at most 2 reminders, only in applied/shortlisted/interview, and it stops when the candidate replies or is rejected or hired. Unique `(application_id, sequence)`, so a reminder can't be sent twice. Runs as a durable Procrastinate periodic job every 30 minutes (`talent.followups.sweep`). The daily digest runs at 07:00 (`comms.digest.daily`).
   - `scheduler`: proposes 3 real free slots from the recruiter's and interviewer's calendars and drafts the email. `talent.interview.book` (R2, internal) re-checks the slot at booking with the row locked, then proposes the confirmation email.
   - Decision: booking is an internal action run by the worker, not an executor adapter, because the calendar is our own tables. It becomes an executor adapter once a real external calendar is connected.
   - Models: `talent.followup`, `talent.interview` (migrations `5d85161ca2dc`, `talent_0004_security`). Events: `talent.followup.due.v1`, `talent.interview.requested.v1`, `talent.interview.booked.v1`.
   - API: `POST /packs/talent/applications/{id}/interviews` (request slots), `GET /packs/talent/jobs/{id}/interviews`, `POST /packs/talent/interviews/{id}/book`, `POST /packs/talent/followups/check`.
   - `astra.py seed` now also loads policies and emails. `astra.py evals` runs both evals.
   - **Verified:** `astra.py check tests/test_communications.py` ruff clean, **43 passed**. Real Haiku evals (`docs/evals/communications.json`): inbox type 18/20, needs-a-person caught 8/8 with 0/12 false alarms; policy answers 8/8 from the right document, 6/6 correctly passed to a person, 0 restricted-document leaks. Screening re-run unchanged: NDCG@10 1.0, hard set 0.9994, 42/42 replayed, 170/170 quotes found in source, $0.017 a run.
4. **First-pass web pages for inbox, policy questions, interview slots and email approval** (written in the lost session).
   - `/inbox` (digest and thread view), `/ask` (policy questions with citations), interview slot request and booking on the job page, and an email form (subject and body) in `/approvals` instead of raw JSON. Editing creates a new version, so the old approval no longer applies.
   - **Verified:** `tsc --noEmit` clean for `src/`. ESLint flags one `set-state-in-effect` on the job page, already present in the P4 commit.
   - **Not verified yet:** a browser run. Backend APIs come first (Oussema, 2026-10-31); the UI gets a full pass later.
5. **Slot holds** (2026-11-01).
   - New `calendar.hold` table (migration `d168b9f5912c`, RLS in `kernel_0006_hold_rules`). When the scheduler offers 3 slots it holds them for 72 hours (`schedule.HOLD_TTL`) under the owner `talent.interview:{id}`, so the same times aren't offered to another candidate. Free-slot search counts busy blocks, bookings and live holds; a holder's own holds don't block its own booking.
   - Booking releases the interview's other held slots. If a person rejects the slots email, `talent.release_rejected_slots` (on `trust.proposal.rejected.v1`) frees the holds and sets the interview to `slots_declined`. Expired holds simply stop counting.
   - The slots proposal target now includes `interview_id`, and its explanation states when the hold expires.
   - **Verified:** ruff clean, `tests/test_communications.py` **46 passed**. New tests: held slots aren't offered to a second candidate, booking frees the other two, and rejecting the offer frees all three.
6. **Calendar invites, cancelling and rescheduling** (2026-11-01).
   - `kernel/schedule/ics.py` renders RFC 5545 invites (REQUEST or CANCEL). The proposal stores the invite as plain fields (uid, title, times, attendees, method, sequence), so the approval hash covers exactly what is sent; the `.ics` file is only rendered at send time. Strict patterns stop an address or UID from adding lines to the file.
   - The mail adapter now has `build()` (checks plus message, no network) and `send()`. It attaches `invite.ics` as `text/calendar; method=...` and refuses an invite that doesn't list the recipient.
   - The booking confirmation carries a REQUEST invite. One UID per interview (`interview-{id}@astrarh.example.test`), so a cancellation replaces the event in the candidate's calendar.
   - New action `talent.interview.cancel` (R2, internal, approved by admin/hr/recruiter). It frees the holds and the booked seats, sets `calendar.booking.status` to cancelled (migration `656f9f6580d8`), and publishes `talent.interview.cancelled.v1`. If the interview was booked, it proposes a cancellation email with a CANCEL invite (sequence 1). With `reschedule: true` it opens a new interview request, so the scheduler offers fresh times.
   - API: `GET /packs/talent/interviews/{id}`, and `POST /packs/talent/interviews/{id}/cancel` with `{reason, reschedule}`, which proposes the cancellation. Interview JSON now includes `ends_at`, `booking_id` and `created_at`.
   - **Verified:** ruff clean, `tests/test_communications.py` **55 passed**. New tests: the invite is valid and folded, injection attempts are refused, the attachment goes only to listed attendees, cancelling frees the calendar and prepares a CANCEL invite, a repeat cancel does nothing, rescheduling opens a new request, and cancelling an unbooked interview sends nothing.
7. **HR ticket handling, answer feedback and policy versions** (2026-11-01).
   - Tickets now have a lifecycle: open → claimed (assignee) → answered or closed. Only the assignee can answer a claimed ticket. An HR answer goes back to the employee's question (`answered_by: hr`, no citations, since a person wrote it). Closing sets the question to closed. Each resolution publishes `knowledge.ticket.resolved.v1` and writes an audit entry (`kernel.ticket.answer`, `kernel.ticket.close`, both R1).
   - Employees rate an answer (`kernel.question.feedback`, R0). Not helpful opens one ticket carrying their comment and the assistant's answer, so HR sees what went wrong.
   - Policy versions: a document is `processing`, `active`, `superseded` or `failed`. Publishing a new version supersedes the old one and deactivates its passages, so search only ranks current text. A unique partial index (`one_active_version`) means the database allows one active version per policy. HR publishes markdown through the API; the worker indexes it on `knowledge.document.submitted.v1`, so the API still never calls a model or embedder.
   - Migration `4d6882bacaaa`. Manifest adds `kernel.document.publish` (R1).
   - API: `GET /knowledge/tickets?status=active|open|claimed|answered|closed|all&mine=`, `GET /knowledge/tickets/{id}`, `POST /knowledge/tickets/{id}/claim|release|answer|close`, `POST /knowledge/questions/{id}/feedback`, `GET /knowledge/stats` (HR), `GET /knowledge/documents` (readable to the caller only), `GET /knowledge/documents/{id}` (sections), `POST /knowledge/documents` (HR, 202).
   - **Verified:** ruff clean. New `tests/test_knowledge_api.py` over real HTTP plus `tests/test_communications.py`: **63 passed**. Covers claim conflicts, HR-only queue, closing, one ticket per unhelpful answer, feedback only after an answer, new version replacing the old in search, the database refusing two active versions, and HR publishing with the worker indexing and role filtering the listing.
8. **Inbox listing, handled state and sorting corrections** (2026-11-01).
   - Threads are `open` or `handled`, with who handled them, when, and a note. An approved reply sent from the thread marks it handled ("Approved reply sent"). A new inbound email reopens it, so nothing falls silently out of the queue.
   - A person can correct the assistant's sorting of a message (type, urgency, needs a person, reason). The model's first values are kept in `model_values`, so the correction rate is measurable. Each correction publishes `comms.classification.corrected.v1` and writes an audit entry. Digest items show `corrected` and `thread_status`.
   - New actions `kernel.email.handle` and `kernel.email.correct` (both R1). Migration `40a1419fcb48`. The type and urgency vocabulary moved to `kernel/comms/vocabulary.py`, so the API does not import LangGraph (the API image does not install it; this broke API start-up once).
   - API: `GET /comms/threads?status=open|handled|all&needs_human=&type=&q=&before=&limit=` (newest first, cursor paging, `q` escaped for LIKE), `GET /comms/threads/{id}` (each message carries its sorting), `POST /comms/threads/{id}/handled` and `/reopen` (409 if already in that state), `PUT /comms/messages/{id}/sorting`, `GET /comms/stats` (open, handled, needing a person, by type, flagged, correction count).
   - **Verified:** ruff clean. New `tests/test_inbox_api.py` covers filters, LIKE escaping, paging, handled/reopen with audit, corrections keeping model values, role checks and cross-tenant 404s. **Full suite: 322 passed, 2 skipped.**

### Screening, web shell and two-layer ranking: 2026-10-31

**Built**
- `packages/packs/talent/`: `scoring.py` (pure formula, `talent.rubric@2`), `signals.py` (evidence, verified years, dated roles, BM25, keyword-list detection), `blind.py` (identity separation), agents `cv_reader`, `ranking`, `rubric_builder` (LangGraph), `handlers.py`, `service.py`, `api.py`, `seed.py`, `load_demo.py`, `evals/screening.py`, migrations.
- Kernel: `ai/graphs.py` (durable nodes), `ai/runner.py` (events to jobs), `files.py` (MinIO + upload gate), `ml_client.py`, `seed.py`, `trust.supersede`.
- `apps/ml/`: parsing with hidden-text removal, OCR, embeddings. Model baked into the image, no network at runtime.
- `tools/generate_demo_data.py` writes `data/world.json`, 42 CVs and `labels.json`.
- `apps/web/`: login, Today dashboard, jobs, job page with **evidence strip**, `<WhyPanel>`, approvals with step-up, History with tamper check. Design tokens in `globals.css`, kit in `src/ui/`.
- `astra.py`: `seed`, `evals`, `export-api`, `live`. Docs: `docs/RANKING.md`, `docs/API.md`, `contracts/openapi.json`, `docs/evals/screening.json`.

**Verified**
- `python astra.py check`: ruff clean, **253 passed, 2 skipped**.
- `python astra.py evals` with real Haiku: see `docs/RANKING.md`. Results come from labelled CVs we wrote, and the doc says so.
- In the browser on a clean database, as Nadia: signed in, ranked 42 CVs with the real worker, opened Why, recalculated to an exact match, approved the shortlist. 5 candidates moved to shortlisted through the real worker, with the execution recorded.
- API docs route responds and OpenAPI exports with 32 paths.

**Real bugs tests and real runs caught, all fixed**
- Quotes nested inside a skill weren't checked against the CV.
- The strict schema code deleted real fields named `title`.
- Replacing a name inside an email address broke the email mask.
- Candidate IDs collided in the same millisecond, breaking bulk upload.
- Parallel agents collided recording prompt versions.
- A login form with no `method` put the password in the URL when scripts failed. It's now POST, and that demo password was rotated.
- Migration autogenerate tried to recreate other schemas' tables.

**Not done or not verified**
- History page and step-up in a browser (covered by API tests only). `--secure` mode wasn't rerun after these changes.
- Mobile layout not checked, and light mode not checked (the browser ran in dark mode).
- Hidden-text detection for DOCX has no test with a real DOCX file.
- Interactive API docs page: route returns 200, but Swagger UI was not opened in a browser.
- Rubric editing has an API but no web page yet. New jobs can't be created from the web yet.
- Grafana has no custom dashboards yet.
- Web service telemetry not added.

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
