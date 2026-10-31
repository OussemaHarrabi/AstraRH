# API

- **Interactive docs:** http://127.0.0.1:8080/api/docs (dev mode; disabled in `--secure`).
- **Full specification:** [`contracts/openapi.json`](../contracts/openapi.json). Regenerate it with `python astra.py export-api`.

## Conventions

- **Base path:** `/api`, through the edge.
- **Sign in:** `POST /api/auth/login` sets an httpOnly session cookie and a readable `astra_csrf` cookie.
- **State-changing calls** must send the header `x-csrf-token` with the `astra_csrf` value.
- **Errors** look like `{"error": "code", "message": "What happened"}`.
- **Tenant** comes from the signed session. A client can't choose it.

## Main routes

| Method and path | Does | Who |
|---|---|---|
| `POST /auth/login`, `/auth/logout`, `/auth/step-up` | Sign in, sign out, confirm password for a serious action | Anyone signed in |
| `GET /auth/me` | The current user and roles | Anyone signed in |
| `GET /registry/packs` | The services and agents, for the dashboard | Anyone signed in |
| `GET /trust/proposals` | Suggestions you may see | Filtered by role |
| `POST /trust/proposals/{id}/approve`, `/reject`, `/edit` | Decide on a suggestion. Editing voids an earlier approval | Approver roles |
| `GET /trust/audit`, `POST /trust/audit/verify` | History, and the tamper check | admin, auditor, hr |
| `GET /explain/{id}`, `POST /explain/{id}/verify` | Why a decision came out this way, and recalculate it | Roles on the decision |
| `GET /graph/{view}`, `/graph/decision/{id}` | Graph views. 503 if Neo4j is down | By role |
| `GET /ai/runs`, `/ai/runs/{id}` | Agent runs and their steps, tokens and cost | admin, auditor, hr, recruiter |
| `GET /people/employees`, `/people/org` | Shared people records | People roles |
| `GET`, `POST /packs/talent/jobs` | List or create jobs. An agent drafts a new job's criteria | Recruitment roles |
| `GET /packs/talent/jobs/{id}` | A job and its criteria versions | Recruitment roles |
| `POST /packs/talent/jobs/{id}/rubrics`, `/rubrics/{rid}/activate` | Save edited criteria, approve them | Recruitment roles |
| `POST`, `GET /packs/talent/jobs/{id}/cvs` | Upload CVs (PDF, DOCX, TXT), see reading status | Recruitment roles |
| `POST /packs/talent/jobs/{id}/rankings` | Rank the CVs that are ready | Recruitment roles |
| `GET /packs/talent/jobs/{id}/shortlist` | The ranked list with scores and reasons | Recruitment roles |
| `GET /packs/talent/applications/{id}/profile` | What the AI read from a CV | Recruitment roles |
| `POST /packs/talent/applications/{id}/overrides` | Correct one criterion, with a reason | Recruitment roles |
| `POST /packs/talent/applications/{id}/reject` | Propose a rejection. A second person must approve | Recruitment roles |
