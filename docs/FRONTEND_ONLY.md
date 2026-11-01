# Front-only features

These work in the web app for the demo, but have no backend yet. Everything here is saved in the
browser's local storage (`apps/web/src/lib/local.ts`), on one device, and is never sent anywhere.
None of them can send anything or change an official record, so the approval rule still holds.

| Feature | Where | Storage key | Backend it needs |
|---|---|---|---|
| Request access | `/signup` | `access.requests` | `POST /auth/signup` or an invitation flow |
| Candidate notes | Candidate drawer | `candidate.notes` | `POST /packs/talent/applications/{id}/notes` |
| Interview scorecards | Candidate drawer | `candidate.scorecards` | `POST /packs/talent/interviews/{id}/scorecards` |
| Tags and stars | Candidate drawer, Candidates | `candidate.tags`, `candidate.stars` | Fields on the application |
| Working pipeline board | Job, Pipeline tab | `pipeline.columns` | Non-official stages on the application |
| Job post and publishing | Job, Job post tab | `job.published` | Careers page and a publish action |
| Private inbox drafts | Inbox | `inbox.drafts` | Draft replies that enter the approval flow |
| Team invitations | Settings, Team | `settings.invites` | User administration API |
| Team list | Settings, Team | Fixed list in the page | `GET /people/users` |
| Email templates | Settings, Templates | `settings.templates` | Template API |
| Notification choices | Settings, Account | `settings.notify` | Preferences API |
| Retention period | Settings, Data and privacy | `settings.retention` | Retention job |
| Deletion requests | Settings, Data and privacy | `settings.erasures` | Candidate erasure API |
| Theme | Header, Settings | `theme` | None needed |

The candidate list across jobs, reports and the Evidence graph are real data, but the browser
assembles them from per-job endpoints. `GET /overview` and `GET /candidates` would replace that.

The landing page's product films are animations with sample data, not recordings.
