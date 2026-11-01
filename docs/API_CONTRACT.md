# AstraRH API contract

**Source:** `contracts/openapi.json` (generated from the merged `integration/final` API)  
**Generated:** 2026-11-01 03:44 UTC  
**Operations:** 122 across 111 paths  
**TypeScript:** `contracts/openapi.d.ts` (generated with `openapi-typescript`)

This is the detailed contract for building the dashboard interfaces. The machine-readable
source is the OpenAPI document; this page explains conventions, roles, every route and the
cross-service data flow.

## Contract files

| File | Purpose |
|---|---|
| `contracts/openapi.json` | OpenAPI 3.1 paths, parameters, request bodies, security schemes |
| `contracts/openapi.d.ts` | Generated TypeScript path and request types |
| `docs/API.md` | Short operator-facing API guide |
| `docs/API_CONTRACT.md` | This detailed contract |

Regenerate after any route, request or auth change:

```bash
python astra.py export-api
npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts
```

## Authentication and transport

- **Base URL:** `http://127.0.0.1:8080/api` through Caddy. OpenAPI paths omit `/api`.
- **Session:** `POST /auth/login` sets an HttpOnly `astra_session` cookie.
- **CSRF:** login also sets a readable `astra_csrf` cookie. Every `POST`, `PUT`, `PATCH` and
  `DELETE` must send `x-csrf-token` with that value.
- **Tenant:** selected by the tenant slug at login; it comes from the signed session and can
  never be chosen by the client afterwards.
- **Errors:** `{"error": "code", "message": "..."}`. FastAPI validation errors use
  `{"detail": [...]}`.
- **Request IDs:** not yet in the error envelope; use the `trace_id` returned by audit/agent
  resources when correlating.
- **Content types:** JSON except CV upload and calendar import, which are multipart.

## Roles

| Role | Meaning |
|---|---|
| `admin` | Platform administration; can read/approve across packs |
| `hr` | HR operations, policy documents and HR ticket queue |
| `recruiter` | Recruitment operations; cannot approve R3 rejection/hire |
| `manager` | Scoped by `org_unit`; sees/approves own team where targets carry `org_unit` |
| `finance` | Payroll, engagements and finance reads |
| `employee` | Self-service; own plans/check-ins/questions |
| `auditor` | Read-only audit and compliance views |
| `mediator` | Reserved for confidential case mediation; not used on main |

R2/R3 approval is payload-bound. R3 also requires a second person and a fresh password
confirmation (`POST /auth/step-up`). Manifest roles are discovery hints; the API remains the
enforcement point.

## Shared conventions

| Item | Contract |
|---|---|
| IDs | UUID strings |
| Times | ISO 8601 with timezone |
| Money, weights, scores | Decimal strings (exact); counts are integers |
| Success lists | Mostly bare arrays; inbox threads use `{items, next_before}` |
| Delete | HTTP 204 where declared; otherwise explicit status |
| Pagination | Inbox has cursor paging; most admin lists accept `limit`; no global standard yet |
| Idempotency | Trust proposals use an idempotency key; other create endpoints rely on natural keys |
| Optimistic concurrency | Proposals expose `revision`; other resources do not yet expose ETags |

## Route inventory

Every operation below is in the OpenAPI contract. `session` means the session cookie;
`session + CSRF` means the session cookie plus `x-csrf-token`. `public` means no auth
(login/health).

### Platform

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/healthz` | Healthz | `—` | `—` | public |
| `GET` | `/readyz` | Readyz | `—` | `—` | public |

### Identity

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `POST` | `/auth/login` | Login | `LoginBody` | `—` | public |
| `POST` | `/auth/logout` | Logout | `—` | `—` | public |
| `GET` | `/auth/me` | Me | `—` | `—` | session |
| `POST` | `/auth/step-up` | Step Up | `PasswordBody` | `—` | session + CSRF |

### People

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/people/employees` | List Employees | `—` | `—` | session |
| `POST` | `/people/employees` | Create Employee | `EmployeeBody` | `—` | session + CSRF |
| `GET` | `/people/org` | Org Reference | `—` | `—` | session |

### Registry

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/registry/packs` | List Packs | `—` | `—` | session |

### Trust and audit

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/trust/audit` | Audit Timeline | `—` | `proposal_id, limit` | session |
| `POST` | `/trust/audit/verify` | Audit Verify | `—` | `—` | session + CSRF |
| `GET` | `/trust/proposals` | List Proposals | `—` | `status, limit` | session |
| `GET` | `/trust/proposals/{proposal_id}` | Get Proposal | `—` | `—` | session |
| `POST` | `/trust/proposals/{proposal_id}/approve` | Approve Proposal | `kernel__web__ReasonBody` | `—` | session + CSRF |
| `POST` | `/trust/proposals/{proposal_id}/edit` | Edit Proposal | `EditBody` | `—` | session + CSRF |
| `POST` | `/trust/proposals/{proposal_id}/reject` | Reject Proposal | `kernel__web__RejectBody` | `—` | session + CSRF |

### Explainability

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/explain/{record_id}` | Why | `—` | `—` | session |
| `POST` | `/explain/{record_id}/verify` | Verify Decision | `—` | `—` | session + CSRF |

### Agent runs

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/ai/runs` | List Runs | `—` | `limit` | session |
| `GET` | `/ai/runs/{run_id}` | Get Run | `—` | `—` | session |

### Graph

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/graph/decision/{decision_id}` | Graph Decision | `—` | `—` | session |
| `GET` | `/graph/{view}` | Graph View | `—` | `—` | session |

### Inbox

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/comms/digest` | Today's digest, grouped by type, most urgent first | `—` | `—` | session |
| `POST` | `/comms/digest` | Rebuild today's digest with the latest messages | `—` | `—` | session + CSRF |
| `PUT` | `/comms/messages/{message_id}/sorting` | Correct the type, urgency or needs-a-person flag the assistant gave an email | `CorrectionBody` | `—` | session + CSRF |
| `GET` | `/comms/stats` | Inbox counts for a dashboard, plus the sorting vocabulary | `—` | `—` | session |
| `GET` | `/comms/threads` | Conversations, newest first, with their latest sorting | `—` | `status, needs_human, type, q, before, limit` | session |
| `GET` | `/comms/threads/{thread_id}` | One conversation, with any reply awaiting approval | `—` | `—` | session |
| `POST` | `/comms/threads/{thread_id}/handled` | Mark a conversation as dealt with | `HandledBody` | `—` | session + CSRF |
| `POST` | `/comms/threads/{thread_id}/reopen` | Put a conversation back in the open list | `—` | `—` | session + CSRF |

### Knowledge

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/knowledge/documents` | Policy documents you may read | `—` | `include_superseded` | session |
| `POST` | `/knowledge/documents` | Publish a policy, or a new version of one. The older version stops being cited. | `kernel__knowledge__api__DocumentBody` | `—` | session + CSRF |
| `GET` | `/knowledge/documents/{document_id}` | One policy document, section by section | `—` | `—` | session |
| `GET` | `/knowledge/questions` | Your recent questions | `—` | `—` | session |
| `POST` | `/knowledge/questions` | Ask a question about company policy | `AskBody` | `—` | session + CSRF |
| `GET` | `/knowledge/questions/{question_id}` | One of your questions | `—` | `—` | session |
| `POST` | `/knowledge/questions/{question_id}/feedback` | Say whether the answer helped. If it didn't, HR gets the question. | `FeedbackBody` | `—` | session + CSRF |
| `GET` | `/knowledge/stats` | How the assistant is doing: answered, passed on, rated | `—` | `—` | session |
| `GET` | `/knowledge/tickets` | Questions passed to HR | `—` | `status, mine, limit` | session |
| `GET` | `/knowledge/tickets/{ticket_id}` | One passed-on question, with what the assistant found | `—` | `—` | session |
| `POST` | `/knowledge/tickets/{ticket_id}/answer` | Answer the employee yourself | `TicketAnswerBody` | `—` | session + CSRF |
| `POST` | `/knowledge/tickets/{ticket_id}/claim` | Take this question, so others know | `—` | `—` | session + CSRF |
| `POST` | `/knowledge/tickets/{ticket_id}/close` | Close a question that needs no answer | `TicketCloseBody` | `—` | session + CSRF |
| `POST` | `/knowledge/tickets/{ticket_id}/release` | Give the question back to the queue | `—` | `—` | session + CSRF |

### Calendar

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/calendar/bookings` | Bookings | `—` | `participant, from, to, include_cancelled` | session |
| `GET` | `/calendar/busy` | Busy | `—` | `participant, from, to` | session |
| `POST` | `/calendar/busy` | Add Busy | `BusyBody` | `—` | session + CSRF |
| `DELETE` | `/calendar/busy/{busy_id}` | Remove Busy | `—` | `—` | session + CSRF |
| `GET` | `/calendar/free` | Free | `—` | `participants, minutes, count` | session |
| `POST` | `/calendar/import` | Import Calendar | `Body_import_calendar_calendar_import_post (multipart)` | `—` | session + CSRF |

### Talent

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `POST` | `/packs/talent/applications/{application_id}/hire` | Propose hiring a shortlisted or interviewed candidate. A different HR person decides. | `HireBody` | `—` | session + CSRF |
| `POST` | `/packs/talent/applications/{application_id}/interviews` | Find free times in the calendars and prepare the email | `InterviewBody` | `—` | session + CSRF |
| `POST` | `/packs/talent/applications/{application_id}/overrides` | Correct one criterion, with a reason. Applies on the next ranking. | `OverrideBody` | `—` | session + CSRF |
| `GET` | `/packs/talent/applications/{application_id}/profile` | What the AI read from this CV | `—` | `—` | session |
| `POST` | `/packs/talent/applications/{application_id}/reject` | Propose a rejection. A different HR person must approve it. | `packs__talent__api__RejectBody` | `—` | session + CSRF |
| `POST` | `/packs/talent/followups/check` | Check now for candidates who went quiet | `—` | `—` | session + CSRF |
| `GET` | `/packs/talent/interviews/{interview_id}` | One interview, with its offered times | `—` | `—` | session |
| `POST` | `/packs/talent/interviews/{interview_id}/book` | Propose booking one of the offered times. A person approves it. | `BookBody` | `—` | session + CSRF |
| `POST` | `/packs/talent/interviews/{interview_id}/cancel` | Propose cancelling, or rescheduling, an interview. A person approves it. | `CancelBody` | `—` | session + CSRF |
| `GET` | `/packs/talent/jobs` | List jobs with CV processing counts | `—` | `—` | session |
| `POST` | `/packs/talent/jobs` | Create a job. An agent drafts its criteria. | `JobBody` | `—` | session + CSRF |
| `GET` | `/packs/talent/jobs/{job_id}` | A job with its rubric versions | `—` | `—` | session |
| `GET` | `/packs/talent/jobs/{job_id}/cvs` | CV processing status | `—` | `—` | session |
| `POST` | `/packs/talent/jobs/{job_id}/cvs` | Upload CVs (PDF, DOCX, HTML, Markdown or TXT) | `Body_upload_cvs_packs_talent_jobs__job_id__cvs_post (multipart)` | `—` | session + CSRF |
| `POST` | `/packs/talent/jobs/{job_id}/cvs/from-email` | Use a CV that arrived by email for this job | `AttachmentBody` | `—` | session + CSRF |
| `GET` | `/packs/talent/jobs/{job_id}/interviews` | Interviews for this job | `—` | `—` | session |
| `POST` | `/packs/talent/jobs/{job_id}/rankings` | Rank the ready CVs | `—` | `—` | session + CSRF |
| `POST` | `/packs/talent/jobs/{job_id}/rubrics` | Save edited criteria as a new draft | `RubricBody` | `—` | session + CSRF |
| `POST` | `/packs/talent/jobs/{job_id}/rubrics/{rubric_id}/activate` | Approve criteria. Ranking uses only an approved rubric. | `—` | `—` | session + CSRF |
| `GET` | `/packs/talent/jobs/{job_id}/shortlist` | The latest ranked list, with reasons | `—` | `—` | session |

### Journey

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `GET` | `/packs/journey/gaps` | Skill gaps, filtered by role | `—` | `employee_id, skill_id` | session |
| `GET` | `/packs/journey/heatmap` | Team x skill heatmap, k >= 5 only | `—` | `org_unit_id, skill_id` | session |
| `GET` | `/packs/journey/impact` | Observed training impact | `—` | `—` | session |
| `GET` | `/packs/journey/plans` | Plans visible to the signed-in user | `—` | `—` | session |
| `GET` | `/packs/journey/plans/me` | The signed-in employee's own plan | `—` | `—` | session |
| `GET` | `/packs/journey/plans/{plan_id}` | A plan with tasks, check-ins and flags | `—` | `—` | session |
| `POST` | `/packs/journey/plans/{plan_id}/checkins/{checkin_id}/submit` | Submit a structured pulse | `CheckinBody` | `—` | session + CSRF |
| `GET` | `/packs/journey/plans/{plan_id}/dossier` | Day-90 review pack | `—` | `—` | session |
| `POST` | `/packs/journey/plans/{plan_id}/tasks/{task_id}/complete` | Record task evidence | `EvidenceBody` | `—` | session + CSRF |
| `GET` | `/packs/journey/recommendations` | Training recommendations, filtered by role | `—` | `employee_id` | session |

### Finance

| Method | Path | Purpose | Request | Query | Auth |
|---|---|---|---|---|---|
| `POST` | `/packs/finance/calculator/compare` | Several gross-to-net scenarios side by side | `CompareBody` | `—` | session + CSRF |
| `POST` | `/packs/finance/calculator/net` | Gross to net, line by line. Nothing is stored. | `NetBody` | `—` | session + CSRF |
| `POST` | `/packs/finance/documents/{document_id}/review` | Verify or reject a document | `DocumentReviewBody` | `—` | session + CSRF |
| `POST` | `/packs/finance/employees/{employee_id}/engagements` | Create an engagement as a draft. The same request id returns the same engagement. | `EngagementBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/engagements` | Engagements. Pay amounts are shown only to finance roles. | `—` | `employee_id` | session |
| `GET` | `/packs/finance/engagements/{engagement_id}` | One engagement with its documents checklist | `—` | `—` | session |
| `POST` | `/packs/finance/engagements/{engagement_id}/activate` | Propose activating a validated engagement. A person must approve it. | `—` | `—` | session + CSRF |
| `POST` | `/packs/finance/engagements/{engagement_id}/amendments` | Propose a change from a date. A person must approve it. | `AmendBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/engagements/{engagement_id}/documents` | Documents and the checklist | `—` | `—` | session |
| `POST` | `/packs/finance/engagements/{engagement_id}/documents` | Record a document | `packs__finance__api__DocumentBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/engagements/{engagement_id}/issues` | Every issue raised for an engagement | `—` | `—` | session |
| `POST` | `/packs/finance/engagements/{engagement_id}/pay-items` | Add a pay item | `PayItemBody` | `—` | session + CSRF |
| `POST` | `/packs/finance/engagements/{engagement_id}/validate` | Run the checks again | `—` | `—` | session + CSRF |
| `GET` | `/packs/finance/hire-notices` | Candidates who reached hired and still need their terms | `—` | `status` | session |
| `POST` | `/packs/finance/hire-notices/{notice_id}/engagement` | Complete a hire notice with the employee and the terms | `ConvertBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/input-batches` | Input batches, newest first | `—` | `—` | session |
| `POST` | `/packs/finance/input-batches` | Import a CSV of approved hours, absences, bonuses, allowances and reimbursements | `Body_import_input_csv_packs_finance_input_batches_post (multipart)` | `—` | session + CSRF |
| `POST` | `/packs/finance/input-batches/rows` | Send input rows as JSON. The same content returns the same batch. | `InputRowsBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/input-batches/{batch_id}` | One input batch with its counts | `—` | `—` | session |
| `GET` | `/packs/finance/input-batches/{batch_id}/issues` | Issues raised on a batch's inputs | `—` | `status` | session |
| `GET` | `/packs/finance/input-batches/{batch_id}/rejections` | Rows that were not stored, and why | `—` | `—` | session |
| `GET` | `/packs/finance/input-batches/{batch_id}/rows` | The inputs stored from a batch | `—` | `status` | session |
| `POST` | `/packs/finance/input-batches/{batch_id}/validate` | Check the batch again | `—` | `—` | session + CSRF |
| `POST` | `/packs/finance/issues/{issue_id}/resolve` | Decide a review item, with a reason | `packs__finance__api__ReasonBody` | `—` | session + CSRF |
| `POST` | `/packs/finance/payroll-inputs/{input_id}/withdraw` | Withdraw an input, with a reason | `packs__finance__api__ReasonBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/payroll-runs` | Payroll runs with their totals. HR sees totals only. | `—` | `—` | session |
| `POST` | `/packs/finance/payroll-runs` | Create a payroll run for a period. The same request id returns the same run. | `RunBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/payroll-runs/{run_id}` | One payroll run with its totals and open issues | `—` | `—` | session |
| `POST` | `/packs/finance/payroll-runs/{run_id}/calculate` | Ask the worker to calculate every payslip. Poll the run for the result. | `—` | `—` | session + CSRF |
| `GET` | `/packs/finance/payroll-runs/{run_id}/issues` | Exceptions and anomalies on a run | `—` | `status` | session |
| `GET` | `/packs/finance/payroll-runs/{run_id}/payslips` | The payslips of a run | `—` | `—` | session |
| `POST` | `/packs/finance/payroll-runs/{run_id}/recall` | Take a submitted run back before approval | `—` | `—` | session + CSRF |
| `POST` | `/packs/finance/payroll-runs/{run_id}/submit` | Submit a calculated run for approval. A different person must approve it. | `—` | `—` | session + CSRF |
| `POST` | `/packs/finance/payroll-runs/{run_id}/verify` | Replay every payslip and check the run's hash | `—` | `—` | session + CSRF |
| `GET` | `/packs/finance/payslips/{payslip_id}` | One payslip with every line and the rule it used | `—` | `—` | session |
| `POST` | `/packs/finance/payslips/{payslip_id}/verify` | Replay a payslip from its stored inputs | `—` | `—` | session + CSRF |
| `GET` | `/packs/finance/rule-sets` | Rule sets, without their full definitions | `—` | `—` | session |
| `POST` | `/packs/finance/rule-sets` | Save a new rule set as a draft | `RuleSetBody` | `—` | session + CSRF |
| `GET` | `/packs/finance/rule-sets/{record_id}` | One rule set with its full definition | `—` | `—` | session |
| `POST` | `/packs/finance/rule-sets/{record_id}/activate` | Propose activating a rule set. A different person must approve it. | `—` | `—` | session + CSRF |
| `POST` | `/packs/finance/rule-sets/{record_id}/test` | Run the rule set's hand-checked examples | `—` | `—` | session + CSRF |

## Request bodies

Fields marked `*` are required. Generated names are retained from FastAPI; `union` means a
nullable or multi-type field. Full constraints are in `contracts/openapi.json`.

| Schema | Fields |
|---|---|
| `AmendBody` | `field`:string[base_salary, weekly_hours, job_title, work_location, ends_on]*, `new_value`:string*, `effective_from`:string*, `reason`:string* |
| `AskBody` | `question`:string* |
| `AttachmentBody` | `attachment_id`:string* |
| `Body_import_calendar_calendar_import_post` | `file`:string*, `participant`:union |
| `Body_import_input_csv_packs_finance_input_batches_post` | `period_start`:string*, `period_end`:string*, `file`:string* |
| `Body_upload_cvs_packs_talent_jobs__job_id__cvs_post` | `files`:array* |
| `BookBody` | `starts_at`:string*, `ends_at`:string* |
| `BusyBody` | `participant`:union, `starts_at`:string*, `ends_at`:string*, `label`:string |
| `CancelBody` | `reason`:string*, `reschedule`:boolean |
| `CheckinBody` | `answers`:object* |
| `CompareBody` | `on`:union, `scenarios`:array* |
| `ConvertBody` | `type`:string[CDI, CDD, CIVP]*, `starts_on`:string*, `ends_on`:union, `job_title`:string*, `work_location`:union, `weekly_hours`:union, `cdd_reason_code`:union, `head_of_family`:boolean, `children`:array, `external_request_id`:union, `pay_items`:array, `employee_id`:union |
| `CorrectionBody` | `type`:union, `urgency`:union, `needs_human`:union, `reason`:union |
| `DocumentReviewBody` | `decision`:string[verified, rejected]*, `note`:union |
| `EditBody` | `payload`:object*, `reason`:union |
| `EmployeeBody` | `person_id`:string*, `display_name`:string*, `email`:string*, `org_unit_id`:string*, `position_id`:string*, `manager_id`:union, `start_date`:string*, `external_id`:union |
| `EngagementBody` | `type`:string[CDI, CDD, CIVP]*, `starts_on`:string*, `ends_on`:union, `job_title`:string*, `work_location`:union, `weekly_hours`:union, `cdd_reason_code`:union, `head_of_family`:boolean, `children`:array, `external_request_id`:union, `pay_items`:array |
| `EvidenceBody` | `evidence`:object, `summary`:union |
| `FeedbackBody` | `helpful`:boolean*, `comment`:string |
| `HandledBody` | `note`:union |
| `HireBody` | `reason`:string* |
| `InputRowBody` | `employee`:string*, `kind`:string*, `effective_date`:string*, `quantity`:union, `amount`:union, `reference`:union |
| `InputRowsBody` | `source`:string[manual, time, leave, compensation], `period_start`:string*, `period_end`:string*, `rows`:array* |
| `InterviewBody` | `interviewer_email`:union |
| `JobBody` | `title`:string*, `description`:string*, `org_unit`:union |
| `LoginBody` | `tenant`:string*, `email`:string*, `password`:string* |
| `NetBody` | `gross`:union*, `head_of_family`:boolean, `children`:array, `on`:union |
| `OverrideBody` | `criterion_id`:string*, `value`:union*, `reason`:string* |
| `PasswordBody` | `password`:string* |
| `PayItemBody` | `code`:string*, `amount`:union*, `valid_from`:string*, `valid_to`:union, `frequency`:string |
| `RubricBody` | `criteria`:array* |
| `RuleSetBody` | `definition`:object* |
| `RunBody` | `period_start`:string*, `period_end`:string*, `pay_date`:string*, `regime_id`:string, `input_batch_ids`:array, `external_request_id`:union |
| `TicketAnswerBody` | `answer`:string* |
| `TicketCloseBody` | `reason`:string* |
| `kernel__knowledge__api__DocumentBody` | `external_id`:string*, `title`:string*, `version`:string, `effective_date`:union, `audience_roles`:array, `markdown`:string* |
| `kernel__web__ReasonBody` | `reason`:union |
| `kernel__web__RejectBody` | `reason`:string* |
| `packs__finance__api__DocumentBody` | `doc_type`:string*, `note`:union, `file_key`:union |
| `packs__finance__api__ReasonBody` | `reason`:string* |
| `packs__talent__api__RejectBody` | `reason`:string* |

## Response shapes

Successful responses are currently open JSON objects for most endpoints. The exact fields
are produced by the serializer functions in the owning module. This is the current contract:

| Area | Main response objects | Where the shape is defined |
|---|---|---|
| Identity | `user_id`, `display_name`, `email`, `roles`, `step_up_fresh` | `kernel/web.py` `me()` |
| Registry | `id`, `name`, `owner`, `status`, `description`, `route`, `nav_label`, `roles`, `actions`, `agents` | `kernel/registry.py` `pack_listing()` |
| Trust | `id`, `action_type`, `status`, `risk`, `summary`, `payload`, `payload_hash`, `target`, `decision_record_id`, `revision`, `agent_run_id`, `expires_at`, `created_at` | `kernel/web.py` `_proposal_json()` |
| Audit | `seq`, `at`, `actor_type`, `actor_id`, `action`, `result`, `reason`, `proposal_id`, `trace_id`, `hash`, `prev_hash` | `kernel/web.py` `audit_timeline()` |
| Explain | decision, factors, evidence, counterfactuals, not-considered, limits, versions, human decisions | `kernel/explain/__init__.py` `why()` |
| Inbox | digest totals/groups; thread head; messages with sorting, attachments and pending reply IDs | `kernel/comms/api.py` |
| Knowledge | question with citations/feedback; ticket with status/assignee; document with sections/audience | `kernel/knowledge/api.py` |
| People | employee fields plus org/positions/skills/KPIs reference lists | `kernel/web.py` |
| Talent | job, rubric, CV status, shortlist/candidate factors, application profile, interview | `packs/talent/api.py` |
| Journey | plan, tasks, check-ins, support flags, gaps, recommendations, impact, heatmap | `packs/journey/api.py` |
| Finance | engagement, document, issue, hire notice, input batch/row/rejection, payroll run, payslip | `packs/finance/api.py` |
| Agent runs | run totals plus ordered steps (tokens, cost, latency, cache/fallback) | `kernel/web.py` `get_run()` |
| Graph | `{nodes, edges, rows}`; node IDs/labels/props | `kernel/graph/__init__.py` |

## Cross-service data flow

```text
talent.candidate.hired.v1
  -> finance.record_hire: creates a hire notice awaiting HR terms
  -> journey.onboarding_planner: no-op until an employee exists

core.employee.created.v1
  -> journey.onboarding_planner: proposes the 30/60/90 plan
  -> HR marks the person as an employee as soon as terms are known

finance.engagement.activated.v1
  -> journey.onboarding_planner: fallback trigger for an active engagement;
     the payload carries the employee UUID and start date

trust.proposal.created/approved/rejected/executed
  -> trust ledger, audit chain and any pack consumers
```

The employee creation bridge is `POST /people/employees` (HR/admin). It emits
`core.employee.created.v1` with IDs and start date only. Finance consumes
`talent.candidate.hired.v1` and creates a hire notice; HR then converts the notice to an
engagement through `POST /packs/finance/hire-notices/{notice_id}/engagement`.

## Approval contract

Every R2/R3 action follows:

```text
proposal (hash-bound payload) -> human approval (role + target + optional step-up)
-> execution (internal worker or external executor) -> audit event
```

Important fields:

- `target` is the authorization scope. Scoped manager grants work only when the target
  includes their `org_unit`.
- `revision` changes when a person edits a proposal; editing voids earlier approvals.
- `payload_hash` binds the approval to the exact payload.
- R3 additionally requires step-up and no self-approval.

## Contract freeze rules

- The OpenAPI file is the source of truth for paths, request bodies and auth.
- Generate `openapi.d.ts`; do not hand-edit it.
- A response shape that the UI consumes must get a named DTO before it changes.
- Do not merge a pack's copy of `contracts/openapi.json`; regenerate from the merged API.
- Add a route, request field or auth change only with the matching frontend type update.

## Known gaps before the UI phase

1. Most successful responses are open objects, not named OpenAPI schemas. The UI therefore
   needs domain DTOs for the screens it builds.
2. List pagination is not uniform; inbox is cursor-based, most other lists are bare arrays.
3. No error `request_id`; `trace_id` is available on audit and agent-run resources.
4. No ETag/If-Match on non-proposal resources.
5. Workforce is not part of this contract; its branch lacks an API, handlers, agents and RLS.
