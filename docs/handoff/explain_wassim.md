# Why I am building these exact things — `journey` (Wassim)

**For the team.** This is the short version of `docs/handoff/journey-design.md` (v2.0). Read this first; open the long doc only when you need the schema, events or payloads.

**My one sentence:** I own the `journey` pack — onboarding, follow-up, skill gaps and training tied to KPIs — inside the AstraRH kernel. I do not own a second RAG, a second approval service, a second mailer or a second scheduler.

---

## The one slice, in one picture

```
talent.candidate.hired.v1
  → plan 30/60/90 drafted from the role profile + the hire's own screening gaps
  → HR (EMP-006) approves or edits it                        [R2, hash-bound]
  → tasks + buddy (EMP-009) assigned
  → day 7/30/60/90 check-ins, structured pulse
  → support flag with facts (never a “flight risk” score)
  → human confirms a skill gap, with evidence
  → training recommendation: cost + capability + the KPI it should move   [R2]
  → enrollment → verification → level changes only after a human confirms
  → impact measured before/after, stated as a hypothesis
```

If this works end to end, the pack is done. Four half-built modules is the failure mode.

---

## The eight focus points, and why each one

| # | Focus | What ships | Why this, and not something else |
|---|---|---|---|
| 1 | **Hire event → plan → human approval** | `journey.plan.activate` as an R2 proposal with a DecisionRecord; approve/edit/reject in the shared Approval Center | This is the wedge and the golden rule in one flow. The plan is the moment the agent does real work and a human decides about a person. If this is stubbed, nothing else matters |
| 2 | **30/60/90 with owners and evidence** | `onboarding_template` + `template_task` → `onboarding_plan` + `onboarding_task`; every task names who owns it and what proof closes it | “Completed” without evidence is a checkbox. Evidence is what makes onboarding measurable, and it is what the manager actually needs at day 30/60/90 |
| 3 | **Check-ins as structured self-report, factual flags** | `checkin`, `pulse_survey`, `pulse_response`, `support_flag` with `kind` + `facts` + `reason_code` | The repo forbids emotion/sentiment inference and individual flight-risk scores. A structured answer (“access ready: 2/5”) plus a missed task is defensible; “the agent thinks she is unhappy” is not. The flag is a prompt for a conversation, not a verdict |
| 4 | **Gap = required − current, with evidence** | `skill_requirement`, `skill_gap`; deterministic severity/confidence; “No evidence found”, never “lacks” | The arithmetic is the IP, and it must be reproducible. Evidence-backed wording protects against bias claims and is exactly what `<WhyPanel>` shows. Self-declaration is capped at 0.25 confidence and never sufficient alone |
| 5 | **Training tied to money and a KPI** | `course`, `training_recommendation`, `enrollment`, `impact_measure`; cost, hours, `KPI-MTTR` hypothesis, mentor alternative; before/after with a caveat | “We bought a course” is not a result. Cost per closed gap and an observed before/after is the number a CFO and an L&D buyer understand. Attendance is not adoption, and we say so |
| 6 | **Reuse the kernel — one spine** | `trust`, `explain`, `ai`, `knowledge`, `jobs`, `people`; no local copies | The fastest way to lose 15 hours is four approvals, four RAGs and four mailers. The kernel already has hash-bound approvals, DecisionRecords, the model gateway, RAG and durable timers. My job is to call them correctly |
| 7 | **Security as a mechanism** | R-classes in `manifest.yaml`; no direct send; untrusted text never in a system prompt; injection tests; RLS; audit | “Secure” is a judged axis and the brief's non-negotiable. A blocked injection and a verified audit chain are demo-able proof, not adjectives. The pack must fail closed, never fall back to a second service |
| 8 | **CDS seed + a 20-second beat** | `seed/journey/` with the locked hero story; 8 journeys; offline reproducible | The demo must not depend on the network or on live typing. Yasmine's story joins `talent → journey → finance → workforce` with the same IDs, so the cascade is credible |

---

## What I deliberately do **not** build (and why)

| Not built | Why |
|---|---|
| A second RAG / “Ask Onward” index | `kernel.knowledge` owns retrieval, ACL, citations and refusal. I add only the plan/phase context and record escalations |
| A second approval service, audit log or mailer | `kernel.trust` + `executor`. Journey creates proposals; it never sends |
| A second scheduler | `kernel.jobs` (Procrastinate). No cron side-channel, even for the demo |
| Sentiment / emotion scoring, “engagement” scores | Prohibited at work (EU AI Act Art. 5(1)(f)); and it would poison every other claim we make |
| An individual “flight risk” or “who will quit” score | The repo's “will not build” list. We show facts and a reason, never a prediction presented as fact |
| Performance ranking, promotion, hiring/firing signals | Not in the risk model at all. Deliberately not wired. The probation dossier is assembled, never decided |
| The Horizon lane (cohort campaigns, adoption telemetry) in the MVP | Its tables are not in the frozen `journey` schema. Faking them in JSON breaks auditability. Documented and deferred with a 3-table contract path |
| A design system, a graph page, an ask UI | Owned by workforce and Oussema. I consume `apps/web/src/ui` and the shared surfaces |
| Doc-debt detection, team map, glossary | Kernel/knowledge concerns. Journey may raise a doc-feedback flag at most |

---

## New ideas that fit the repo without creating conflict

Small, cheap, inside my folders, no schema change:

1. **Probation dossier (computed).** A day-90 export of milestones, evidence, check-ins and verified skills for the manager's review. No new table; it is a read view. In Tunisia the trial period is a legal milestone, so this is a real artefact, not decoration.
2. **Manager pre-start checklist.** Template tasks with `owner_role=manager`, due D-7: access requested, first task defined, calendar blocked, buddy briefed. The #1 onboarding failure is an unprepared manager.
3. **First-win ladder.** Three escalating tasks tagged `first_win` in the template. Demo-able and it gives the new hire a real early contribution instead of a doc dump.
4. **Doc-feedback flag.** “This doc is wrong / this step was useless” from the portal becomes a `support_flag` for HR (V2). Cheap reverse feedback loop; the knowledge owner decides what to do with the doc.
5. **Day-90 verified baseline.** `journey.onboarding.completed.v1` carries verified skills, so the same employee can enter a future Horizon lane with no re-learning. It is one event and it makes the two-lane story real later.
6. **Cohort display, not a table.** Group new hires by start date and org unit for the portal. Pure read; no new model.

These are additive. None of them changes a frozen table, event or folder.

---

## What I need from Oussema (blocking, in order)

1. **`talent.candidate.hired.v1` shape** — are the screening gaps included, and what `employee_id` is emitted for `CAND-001`? My default: `EMP-041`, gaps re-derived from `core` evidence if absent.
2. **`trust.propose` / `explain.record` signatures** and the manifest action schema. My default: copy `_example` exactly.
3. **`kernel.jobs` enqueue/cancel API** for D7/30/60/90 timers. I will not build a fallback scheduler.
4. **Route convention** for pack APIs (`/journey` vs `/api/journey`) and how the typed client is generated.
5. **Horizon lane: yes or no by H6.** Default is no; if yes, I need three tables approved in a contract-change issue, not a workaround.

Also useful early: the approval-card payload/diff contract, and whether I may add columns to my own 15 tables (my assumption: yes, table list frozen, columns pack-owned).

---

## The 20-second demo beat

Open Yasmine's journey. The attention card says: **“Day-7 pulse: staging access not ready; first task blocked”** — with the facts, no score. Open the gap card: **Kubernetes required 3, evidence 1 — 14 PRs touched manifests, zero deployment ownership**. The recommendation: **`CRS-K8S-01`, 6 h, 0 TND internal, should move `KPI-MTTR`**, plus `EMP-009` as mentor. Approve.

That is the whole thesis in one screen: the agent did the reading and the arithmetic; the human decided about a person; the audit log can prove it.

---

## Timeline I am planning against

| Hours | What |
|---|---|
| H0–H1 | `seed/journey/` complete; read kernel contracts |
| H1–H2 | pack skeleton from `_example`; manifest; models; migration; seed |
| H2–H4 | hire → plan proposal → approval → tasks + buddy |
| H4–H6 | portal + plan detail + evidence |
| H6–H8 | check-ins + pulse + flags + timers |
| H8–H9 | gaps + training + enrollment + verification |
| H9–H10 | **integration gate:** real event, real trust/executor/audit, real knowledge |
| H10–H12 | impact, dossier, evals, polish |
| H12 | freeze; record backup |
| H12–H15 | demo blockers only, README section, rehearsal, buffer |

**Cut order if behind:** dossier → LLM briefing prose → first-win variants → free-text topics → buddy cadence UI → mentor alternative. **Never cut:** plan→approval→tasks, gap evidence, training + KPI, audit/approval, no-sentiment, offline seed.

---

## The one sentence to remember

> **AstraRH's `journey` pack owns the 90 days after the offer and the skills after that: it drafts, evidences and proposes; a human approves every action that touches a person's record.**
