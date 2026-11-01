# API

- **Interactive docs:** `http://127.0.0.1:8080/api/docs` (dev mode; disabled in `--secure`).
- **Machine contract:** [`contracts/openapi.json`](../contracts/openapi.json).
- **Generated TypeScript types:** [`contracts/openapi.d.ts`](../contracts/openapi.d.ts).
- Regenerate both from the running API:

```bash
python astra.py export-api
npx --yes openapi-typescript@7 contracts/openapi.json -o contracts/openapi.d.ts
```

The contract is generated from the merged `main` API. Do not hand-merge a pack's copy of
`contracts/openapi.json`; regenerate it after every merge.

## Conventions

- **Base path:** `/api`, through the edge.
- **Sign in:** `POST /api/auth/login` sets an HttpOnly `astra_session` cookie and a readable
  `astra_csrf` cookie.
- **GET/HEAD/OPTIONS:** send the session cookie only.
- **State-changing calls:** also send `x-csrf-token` with the `astra_csrf` value.
- **Tenant:** comes from the signed session. A client cannot choose it.
- **Errors:** `{"error": "code", "message": "What happened"}`. FastAPI validation errors use
  `{"detail": [...]}`; a client should handle both.
- **IDs:** UUID strings. **Timestamps:** ISO 8601 with timezone. **Money/weights/scores:**
  decimal strings; counts are integers.
- **Roles:** `admin`, `hr`, `recruiter`, `manager`, `finance`, `employee`, `auditor`, `mediator`.
- **Approval:** agents and people propose; a human approves; only then does an action execute.
  R3 needs a second person and a fresh password confirmation.

The OpenAPI document declares two security schemes:

| Scheme | In | Name | Used by |
|---|---|---|---|
| `sessionCookie` | cookie | `astra_session` | every authenticated call |
| `csrfHeader` | header | `x-csrf-token` | POST/PUT/PATCH/DELETE |

## Service map

### Platform kernel

| Area | Main routes | Who |
|---|---|---|
| Auth | `POST /auth/login`, `/auth/logout`, `/auth/step-up`; `GET /auth/me` | anyone signed in |
| Registry | `GET /registry/packs` — service, UI route, roles, actions and agents | anyone signed in |
| Trust | `GET /trust/proposals`, `/trust/proposals/{id}`; `POST .../approve`, `/reject`, `/edit` | view/approver roles |
| Audit | `GET /trust/audit`; `POST /trust/audit/verify` | admin, hr, auditor |
| Explain | `GET /explain/{decision_id}`; `POST /explain/{decision_id}/verify` | roles on the decision |
| AI runs | `GET /ai/runs`, `/ai/runs/{id}` — tokens, cost, steps, trace | admin, hr, recruiter, auditor |
| Graph | `GET /graph/{view}`, `/graph/decision/{id}` — 503 if Neo4j is down | view-specific roles |
| People | `GET /people/employees`, `/people/org` | people roles |
| Inbox | `GET/POST /comms/digest`; `GET /comms/stats`; `GET /comms/threads`; `GET /comms/threads/{id}`; `POST .../handled`, `/reopen`; `PUT /comms/messages/{id}/sorting` | admin, hr, recruiter |
| Knowledge | `POST/GET /knowledge/questions`; `GET /knowledge/questions/{id}`; `POST .../feedback`; HR ticket queue and actions; `GET/POST /knowledge/documents`; `GET /knowledge/stats` | everyone; HR for queue/docs |
| Calendar | `GET/POST /calendar/busy`; `DELETE /calendar/busy/{id}`; `POST /calendar/import`; `GET /calendar/free`; `GET /calendar/bookings` | admin, hr, recruiter |

### Recruitment (`talent`)

- `GET/POST /packs/talent/jobs`, `GET /packs/talent/jobs/{id}`
- `POST /packs/talent/jobs/{id}/rubrics`, `POST .../rubrics/{rubric_id}/activate`
- `GET/POST /packs/talent/jobs/{id}/cvs`, `POST .../cvs/from-email`
- `POST /packs/talent/jobs/{id}/rankings`, `GET .../shortlist`
- `GET /packs/talent/applications/{id}/profile`
- `POST /packs/talent/applications/{id}/overrides`, `/reject`, `/interviews`, `/hire`
- `GET /packs/talent/jobs/{id}/interviews`
- `POST /packs/talent/interviews/{id}/book`, `/cancel`; `GET /packs/talent/interviews/{id}`
- `POST /packs/talent/followups/check`

### Journey (`journey`)

- `GET /packs/journey/plans`, `/plans/me`, `/plans/{id}`, `/plans/{id}/dossier`
- `POST /packs/journey/plans/{id}/tasks/{task_id}/complete`
- `POST /packs/journey/plans/{id}/checkins/{checkin_id}/submit`
- `GET /packs/journey/gaps`, `/recommendations`, `/impact`, `/heatmap`

### Finance (`finance`)

- Calculator: `POST /packs/finance/calculator/net`, `/compare`
- Rule sets: `GET/POST /rule-sets`, `GET /rule-sets/{id}`, `POST .../test`, `/activate`
- Engagements: `GET/POST /engagements`, `GET /engagements/{id}`, `POST .../pay-items`,
  `/validate`, `/documents`, `/activate`, `/amendments`; issues and documents
- Hire notices: `GET /hire-notices`, `POST /hire-notices/{id}/engagement`
- Payroll inputs: `POST/GET /input-batches`, `POST /input-batches/rows`, batch rows,
  rejections, issues, validate; `POST /payroll-inputs/{id}/withdraw`
- Payroll runs: `GET/POST /payroll-runs`, `GET /payroll-runs/{id}`, `/payslips`, `/issues`;
  `POST .../calculate`, `/verify`, `/submit`, `/recall`; payslip verify

## Data flow across services

```text
talent.candidate.hired.v1
  -> finance.record_hire (creates a hire notice for HR)
  -> journey.onboarding_planner (waits for an employee; it can also start from
     finance.engagement.activated.v1, which carries the employee UUID and start date)

finance.engagement.activated.v1
  -> journey.onboarding_planner (draft 30/60/90 plan)

talent / finance / journey / workforce actions
  -> trust.proposal -> approval -> execution -> audit
  -> trust.action.executed.v1 (any consumer)
```

The shared records are `core.person`, `employee`, `org_unit`, `position`, `skill`,
`kpi_*`; the shared trust tables are `trust.proposal`, `approval`, `execution`,
`audit_event`, `decision_record`; every pack uses the same `events` outbox and `jobs`.

## Contract caveats for the frontend

- `contracts/openapi.d.ts` is generated and frozen for request paths, bodies, enums and
  operation names.
- Many successful responses are still declared as open objects because the backend returns
  dictionaries. The domain shapes are in `apps/web/src/lib/api.ts` until response DTOs are
  added. Add a DTO and regenerate before changing a response shape used by the UI.
- List endpoints are not uniform yet: inbox uses `{items, next_before}`; most other lists are
  bare arrays. Treat this as the current contract, not a promise of global pagination.
- Do not build a sidebar from hardcoded role lists. Use `/registry/packs` plus the roles on
  `/auth/me`. Do not expose a pack route that has no page.
