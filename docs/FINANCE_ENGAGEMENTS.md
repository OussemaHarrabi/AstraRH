# Finance pack: engagements, validation, documents and the hire flow

Reference for how an engagement is created, checked, documented, activated and amended. Part of the [finance documentation](FINANCE_INDEX.md). The use cases are A1 to A6 in [FINANCE_USE_CASES.md](FINANCE_USE_CASES.md).

**Everything marked [verify] is configuration that stands in for a legal rule and has not been checked against the labour code, ANETI or CNSS texts.** The system checks fields and documents. Whether a contract is legally valid is always a human decision.

## 1. Files

| File | What |
|---|---|
| `packages/packs/finance/validation/engagement.py` | The checks. Pure: no database, no clock, no model |
| `packages/packs/finance/engagements.py` | Create, validate, issues, documents, activation and amendment requests, hire notices |
| `packages/packs/finance/handlers.py` | The effects of approved actions: `activate_engagement`, `amend_engagement` |
| `packages/packs/finance/consumers.py` | The hire event consumer |
| `packages/packs/talent/handlers.py`, `events.py`, `api.py`, `manifest.yaml` | The hire action, its event and its endpoint (section 7). Changed in the kernel owner's pack at the owner's request |
| `packages/packs/finance/api.py` | The routes |
| `packages/packs/finance/proposals.py` | Shared rule for asking again after a rejection or expiry |
| `packages/packs/finance/migrations/versions/finance_0004_engagement_guards.py` | Row-level security for hire notices and the engagement and pay guards |
| `tests/test_finance_validation.py`, `tests/test_finance_engagements.py`, `tests/test_finance_schema.py` | Tests |

## 2. Lifecycle

```
draft ⇄ pending_review ⇄ approved  ──(approved action)──▶ active ──▶ completed | terminated
```

- **Before activation** the status is not chosen by anyone. It follows the open issues: any open blocking issue gives `draft`, otherwise any open review issue gives `pending_review`, otherwise `approved`. Every change that could affect an issue re-runs the checks.
- **`active`, `completed` and `terminated`** are reached only through an approved action, which the worker applies. The database enforces it (section 8).
- Once active, an engagement is not re-validated, and its documents and pay are not edited through the normal routes.
- `completed` and `terminated` have no code path yet (use cases A8, A9 and the CIVP completion).

## 3. Validation rules

Each rule gives an issue with a code, a severity, the field, a message, a next action and an owner role. **Blocking** means it cannot proceed until the cause is fixed. **Review** needs a named person's decision, recorded with a reason.

| Code | Severity | Raised when | Owner |
|---|---|---|---|
| `ENGAGEMENT_TYPE_UNKNOWN` | blocking | Type is not CDI, CDD or CIVP. Nothing else is checked | HR |
| `JOB_TITLE_MISSING` | blocking | Job title is empty | HR |
| `START_DATE_MISSING` | blocking | No start date | HR |
| `DATES_INVALID` | blocking | End date before start date | HR |
| `CDI_HAS_END_DATE` | blocking | An open-ended contract has an end date | HR |
| `CDD_END_DATE_MISSING`, `CIVP_END_DATE_MISSING` | blocking | A CDD or CIVP has no end date | HR |
| `CIVP_DURATION_REVIEW` | review | A CIVP is longer than 12 months **[verify with ANETI]** | HR |
| `CDD_REASON_REVIEW` | review | A CDD's reason is missing or not on the local list | HR_LEGAL |
| `WEEKLY_HOURS_MISSING` | blocking | Hours missing or not above zero | HR |
| `WEEKLY_HOURS_REVIEW` | review | More than 48 weekly hours **[verify]** | HR |
| `NO_BASE_SALARY` | blocking | No `BASE_SALARY` pay item in force on the start date (not asked of a CIVP, whose allowance is a ledger) | FINANCE |
| `DOCUMENT_NOT_VERIFIED` | blocking | A required document is not verified (one issue per document, field `documents.<type>`) | HR |

**Recognised CDD reasons (placeholder, not the labour code) [verify]:** `REPLACEMENT`, `SEASONAL`, `TEMPORARY_INCREASE`, `PROJECT`. Matching ignores case and spaces. Anything else, including nothing, goes to a person.

**Required documents by type [verify]:**

| Type | Documents |
|---|---|
| CDI | identity, contract |
| CDD | identity, contract |
| CIVP | identity, diploma, ANETI approval, contract |

## 4. Issues

| State | Meaning |
|---|---|
| `open` | Raised and not settled |
| `resolved` | A person decided a **review** item and gave a reason of at least 3 characters. The decision survives later re-validation |
| `cleared` | The cause was fixed, so the system closed it. If the problem returns, a new issue is raised |

- A **blocking** issue cannot be resolved by a person. The route answers 409 "fix its cause".
- Re-validating never reopens a resolved review item and never loses one, and the same code and field never produces two open issues.
- Who may resolve: `admin`, `finance`, `hr`.

## 5. Creating and documenting

- **Create:** `POST /employees/{employee_id}/engagements`. Roles `admin`, `finance`, `hr`. The engagement starts as a draft and is validated at once.
- **Idempotent:** the same `external_request_id` for the same employee returns the same engagement (200 instead of 201). The same id for a different employee gives 409. An unknown employee gives 404.
- **Pay items:** sent at creation or added with `POST /engagements/{id}/pay-items`. Only `admin` and `finance` may set pay. A period that overlaps an existing one for the same code gives 409, an amount of zero or with more than 3 decimals gives 422.
- **Who sees pay:** `admin`, `finance` and `auditor` see pay items. **`hr` sees the engagement but `pay_items` is null.** Recruiters, managers and employees get 403 on every engagement route.
- **Documents:** `POST /engagements/{id}/documents` records a document (type, optional note, optional MinIO file key). `POST /documents/{id}/review` verifies or rejects it. Only verified documents satisfy the checklist. `GET /engagements/{id}/documents` returns the checklist with `present` and `verified` for each required type.

## 6. Activation and amendment

Both are **R2** actions: a person proposes, a person approves, the worker applies. Approvers are `admin`, `finance`, `hr`, and the proposal can be viewed by `auditor` too. No password confirmation or second-person rule applies (that is R3).

**Activation** (`finance.engagement.activate`)
- Proposed only when the engagement is `approved`, otherwise 409 naming what is still open.
- The payload binds a hash of the exact terms (employee, type, dates, title, hours, reason, family data and pay items). The handler recomputes it and re-runs the checks when it executes. A change after approval makes the action fail and the engagement stay `approved`.
- The decision record lists the review items a person decided and their reasons, the number of verified documents and the limits. **It never contains pay amounts.**
- Sets `active`, `activated_by` (the approver) and `activated_at`, and publishes `finance.engagement.activated.v1` with IDs, type and start date only.

**Amendment** (`finance.engagement.amend`)
- Only an `active` engagement. Fields: `base_salary`, `weekly_hours`, `job_title`, `work_location`, and `ends_on` (CDD only; a CIVP will use an extension request). Anything else is refused.
- Effective-dated: it cannot start before the engagement does, and a reason is required. History is kept, never overwritten.
- A pay change ends the current `BASE_SALARY` period the day before the effective date and starts a new one. It is refused when the effective date already has a change or a later change exists. An amendment of pay needs `admin` or `finance`.
- The previous value, the new value, the requester and the proposal are stored in `engagement_amendment`. `finance.engagement.amended.v1` carries only the engagement and the date.
- Closed pay periods are not touched. Adjustments for earlier periods come with payroll runs (use case D7).

**Asking again.** A rejected, failed or expired request can be made again. An expired one is marked superseded. While one is open, a second request gets 409.

## 7. The hire flow, from talent to an engagement

```
recruiter proposes ──▶ HR approves (R3) ──▶ talent moves the candidate to `hired`
      ──▶ event talent.candidate.hired.v1 (IDs only) ──▶ finance records a hire notice
      ──▶ HR completes the notice with the terms ──▶ a draft engagement
```

**In talent** (added 2026-11-01 at the owner's request, in the kernel owner's pack, to be reviewed):
- There was no way to hire. The stages were applied, shortlisted, interview and rejected, so nothing ever reached `hired`.
- New action **`talent.application.hire`**, risk **R3** like rejecting: a second person must approve it, with a fresh password confirmation, and the requester cannot approve it. Approvers are `admin` and `hr`, so a recruiter can propose but not decide.
- Only a **shortlisted or interviewed** candidate can be hired, checked when it is proposed and again when it runs. Any other stage makes the action fail and changes nothing. Hiring someone already hired does nothing and announces nothing twice.
- On success the handler moves the application to `hired`, records the stage change, and publishes **`talent.candidate.hired.v1`** with the application, job, candidate and person IDs and nothing else (no name, e-mail or pay).
- `POST /packs/talent/applications/{id}/hire` (reason of at least 3 characters) proposes it. It has its own decision record, so it does not depend on a ranking existing. A rejected or expired request can be asked again, and while one is open a second gets 409.

**In finance:**
- The consumer `finance.record_hire` listens to `talent.candidate.hired.v1` and records **one hire notice per application**, however many times the event arrives. A bare stage change to `hired` creates nothing.
- The notice keeps the candidate and person IDs. It is needed because the event has no employee, salary or start date.
- `GET /hire-notices` lists notices (filter by `status`). `POST /hire-notices/{id}/engagement` completes one: HR gives the terms and either names the employee or **leaves the employee out, and finance finds the one that belongs to the hired person**. It refuses with 409 when no employee record exists for that person yet, or when the named employee is a different person. A second completion gives 409.
- The worker imports `packs.finance.consumers` (one line in `apps/worker/main.py`, the pattern `talent` uses), so the consumer is registered in a running system. A test checks both the import and the registration.

**What is still missing:**
- **Creating the employee.** Nothing in the platform creates an employee record from a hired person (the people routes are read-only). Until something does, the employee must already exist for a notice to be completed.
- **Proposing over HTTP (K9).** The hire endpoint exists, but the API role cannot insert proposals yet, so a person cannot propose over HTTP. A strict expected-failure test covers it, and the tests propose through the worker.
- **No offer stage.** Candidates go from interview straight to hired. An offer step and its terms are not modelled.

**A separate bug found and fixed on the way (K13).** The API process has no agent libraries by design, but `talent/api.py` imported `communications`, which imported `langgraph` at module level. So **on the kernel owner's current `main`, the whole talent pack failed to load in the running API**: jobs, CVs, rankings and the hire endpoint were all missing, with only a log line to show for it. The tests did not notice because they run in an image that has `langgraph`. The import now happens inside the three functions that need it, and a new test loads every pack's API module with those libraries blocked (it fails without the fix, with the original error).

## 8. What the database enforces

These hold even if application code has a bug (migration `finance_0004`, tested in `tests/test_finance_schema.py`).

| Rule | Detail |
|---|---|
| New engagement is a draft | Except when the owner role seeds data |
| Activation | Only the worker (applying an approved action) or the owner can set `active`, `completed` or `terminated` |
| Status path | `draft ⇄ pending_review ⇄ approved`, `approved → active`, `active → completed` or `terminated`. Any other move is refused, for every role |
| Active engagements | Only the worker or the owner can change one. The API role cannot, even for the job title |
| Deleting | Only a draft engagement can be deleted |
| Pay of an active engagement | Only the worker or the owner can insert, change, delete or move a pay item onto it |
| Hire notices | Row-level security on, one per application per tenant |

## 9. Not built yet

| Item | Why |
|---|---|
| Ending-soon reminder for CDD and CIVP (A8) | Needs a scheduled worker task. `main` now has the pattern (the daily digest) |
| Terminating or completing an engagement (A9) | Next phase, with final pay |
| Editing a draft's terms | Drafts can gain documents and pay items. Other terms are fixed at creation, so a mistake means a new request id |
| Minimum-wage check on pay changes | The value is not decided (open question in the use cases) |
| AI extraction of contract fields (A7) | AI is paused (decision D14). A person enters and verifies documents by hand |
| CIVP placement records | Phase 6 |
| Proposing over HTTP (`POST .../activate`, `POST .../amendments`, and talent's `POST .../hire`) | Blocked by kernel request K9. The routes exist and are covered by strict expected-failure tests. The service functions work, and the tests propose through the worker |
