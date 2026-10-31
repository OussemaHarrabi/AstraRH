# Why this scope — `journey` (Wassim)

**The what is `docs/handoff/journey-design.md` v3.2. This file is the why.** The scope is frozen; there are no open questions. The branch is synced with `main`'s P1 infra + P2 kernel; P3 `_example` and the stub packs are next. If you need the schema, events, routes, hours or conflict rules, read the v3 doc. If you want the argument in five minutes, read this.

**My one sentence:** I own the `journey` pack — onboarding, follow-up, skill gaps and training tied to KPIs — inside the AstraRH kernel. I do not own a second RAG, a second approval service, a second mailer or a second scheduler.

---

## The one slice

```
talent.candidate.hired.v1
  -> plan 30/60/90 from the role + the gaps found while hiring
  -> HR (EMP-006) approves or edits it                    [R2, hash-bound]
  -> tasks + buddy (EMP-009) assigned
  -> day 7/30/60/90 check-ins, structured pulse
  -> support flag with facts (never a "flight risk" score)
  -> human confirms a skill gap, with evidence
  -> training: cost + capability + the KPI it should move [R2]
  -> enrollment -> verification -> level changes only after a human confirms
  -> impact measured before/after, stated as a hypothesis
  -> day 90: verified baseline, dossier for the manager
```

If this works end to end, the pack is done. Four half-built modules is the failure mode.

---

## The six things that make us different

| # | Differentiator | What the judge sees |
|---|---|---|
| 1 | **Hiring gaps seed the onboarding plan** | Yasmine's K8s/OBS gaps from screening become day-30 tasks and a training recommendation. The two halves of HR connect. |
| 2 | **Evidence-first gap math, and "No evidence found"** | Requirement vs evidence, confidence, the exact signals. We never say "lacks". |
| 3 | **Approval bound to the payload hash** | Edit one milestone after approval and the approval is void. The golden rule as a mechanism. |
| 4 | **A mentor before a course** | `EMP-009` already has the skill. The recommendation offers mentoring at 0 TND next to the paid course. |
| 5 | **Probation dossier (Day 90)** | In Tunisia the trial period is a legal artifact. The agent assembles; a human decides. |
| 6 | **Impact measured, not assumed** | Before/after on the same cohort, a comparison group where possible, cost per closed gap, and the caveat. |

Two supporting stories: the **team gap heatmap** (the Horizon lane, read-only, `k >= 5`) and the **deliberate no**: no sentiment, no ranking, no flight-risk score.

---

## What actually wins

The judges are not scoring code volume; everyone will have AI-written code. They score **security, system design, reliability and human-in-the-loop**. So:

- We demo the **mechanism**, not a CRUD tour: edit voids the approval, `<WhyPanel>`, audit verify.
- We show **one failure mode**: a poisoned check-in note does not move the plan or the gap.
- We put the **numbers in the README**: red-team pass rate, journey tests, RLS/cross-tenant tests — from a run, never invented.
- If time is short, **cut Tier 2 features; never cut the proof moments**.
- We say the legal line out loud: no sentiment, no ranking, no flight-risk score, no R3 decision.

---

## What ships — the catalogue in one table

| Tier | What it contains | Why this tier |
|---|---|---|
| **T1 — spine** | J1 plan proposal, J2 activation + buddy, J3 portal, J4 evidence, J5 check-ins, J6 flags, J7 gap + confirmation, J8 training + mentor, J9 verification, J10 impact, J11 D90 baseline, J12 attention | The demo path. If one of these is missing, the pack is not done |
| **T2 — differentiators** | D1 probation dossier, D2 manager readiness + first-win ladder, D3 team heatmap, D4 WhyPanel/evidence drawer, D5 manager briefing, D6 reverse doc feedback, D7 mentor alternative, D8 FR/EN + accessibility | Cheap, high-value, and mostly data or shared-UI reuse. Ship after T1 is green |
| **T3 — roadmap** | Horizon campaigns, adoption telemetry, skill decay, question -> gap loop, certification expiry, Arabic, journey graph view, LMS/xAPI | Real work, but they need schema or kernel changes. Not in the 15 h |

The full table, with tables, risk class, size and demo proof, is §5 of the v3 doc.

---

## The new ideas — now part of the work, not a wish list

1. **Probation dossier.** A computed Day-90 export: milestones, evidence, check-ins, verified skills, missing items. No new table. The legal artifact, assembled by the agent, decided by the manager.
2. **Manager readiness pack.** Pre-start checklist (access, first task, calendar, buddy briefed) plus a **first-win ladder** of three escalating tasks. The #1 onboarding failure is an unprepared manager.
3. **Team gap heatmap (Horizon preview).** Aggregate confirmed gaps by team and skill at `k >= 5`. "9 of 14 backend engineers have a K8s gap." The workforce-wide story without the campaign tables we do not have.
4. **Reverse doc feedback.** "This doc is wrong / this step was useless" becomes a `support_flag(kind=doc_feedback)` for HR; the knowledge owner decides. A feedback loop nobody builds.
5. **Day-90 verified baseline.** `journey.onboarding.completed.v1` carries verified skills, so the same employee can enter a future Horizon lane without re-learning.
6. **Cohort display, not a table.** Group new hires by start date and team in the portal. Pure read; no new model.

None of them changes a frozen table, event or folder. All of them are inside `packages/packs/journey/` or `apps/web/src/modules/journey/`.

---

## What I deliberately do **not** build

| Not built | Why |
|---|---|
| A second RAG / Ask index | `kernel.knowledge` owns retrieval, ACL, citations and refusal. I add plan/phase context only |
| A second approval service, audit log or mailer | `kernel.trust` + `executor`. Journey proposes; it never sends |
| A second scheduler | `kernel.jobs` (Procrastinate). No cron side-channel, even for the demo |
| Sentiment / emotion / "engagement" scoring | Prohibited at work (EU AI Act Art. 5(1)(f)); it would poison every other claim |
| An individual "flight risk" or "who will quit" score | The repo's "will not build" list. Facts and a reason, never a prediction presented as fact |
| Performance ranking, promotion, hiring/firing signals | Not in the risk model at all. The probation dossier is assembled, never decided |
| Horizon campaigns and adoption telemetry in the MVP | No tables in the frozen schema; the heatmap is the honest preview |
| A design system, a graph page, an ask UI | Owned by workforce and Oussema. I consume `apps/web/src/ui` and the shared surfaces |
| Doc-debt detection, team map, glossary | Kernel/knowledge concerns. Journey may raise a doc-feedback flag at most |

---

## Decisions are locked — including the 12 contracts

The 12 questions from v2 are decided in §19 of the v3 doc, with a fallback for each. The three that matter most:

1. **`candidate.hired` must carry `employee_id` and `hired_gaps[]`; `CAND-001 -> EMP-041`.** If the event has no gaps, we re-derive from `core` evidence with confidence `<= 0.5` and label the source.
2. **API is `/api/packs/journey`, pages are `/journey`.** The pack router is mounted at `/packs/journey`; Caddy strips `/api`. One adapter module `services/kernel.py`; never fork trust/explain.
3. **Kernel jobs only for D7/30/60/90.** If timers are late, a manual "run due check-ins" action keeps the demo; timers go `preview`. No second scheduler.

The rest: in-app check-ins primary, email optional R2 series; levels 1–4; no prerequisite DAG; KPI read + event, no direct write; columns pack-owned, no new tables; Horizon campaigns cut, heatmap ships.

---

## The 20-second demo beat

Open Yasmine's journey. The attention card says: **"Day-7 pulse: staging access not ready; first task blocked"** — with the facts, no score. Open the gap card: **Kubernetes required 3, evidence 1 — 14 PRs touched manifests, zero deployment ownership**. The recommendation: **`CRS-K8S-01`, 6 h, 0 TND internal, should move `KPI-MTTR`**, plus `EMP-009` as mentor. Approve.

Then the dossier: **"Day 90: 14 of 15 milestones with evidence; 1 missing"** — and a human decides. That is the thesis in two screens.

---

## Timeline I am planning against

| Hours | What |
|---|---|
| H0–H1 | `seed/journey/` complete; read kernel contracts |
| H1–H2 | pack skeleton from `_example`; manifest; models; migration; seed |
| H2–H4 | hire -> plan proposal -> approval -> tasks + buddy |
| H4–H6 | portal + plan detail + evidence |
| H6–H8 | check-ins + pulse + flags + timers |
| H8–H9 | gaps + training + enrollment + verification |
| H9–H10 | **integration gate:** real event, trust/executor/audit, knowledge |
| H10–H11 | impact + D90 event + dossier |
| H11–H12 | heatmap + WhyPanel/evidence drawer + doc feedback + evals |
| H12 | freeze; record backup |
| H12–H15 | proof pack (failure drills, audit verify), demo blockers, README, rehearsal, buffer |

**Cut order:** D5 briefing -> D8 accessibility -> D1 dossier polish -> D6 doc feedback -> D2 first-win variants -> D3 heatmap -> J10 impact. **Never cut:** J1/J2/J7/J8, approval/audit, no-sentiment, seed, offline demo.

---

## If something breaks, read §22 first

The conflict register at the end of the v3 doc lists 18 places where this pack can collide with the kernel, another pack, the shared UI, the demo data or the law — with the cause, the early signal, the pre-agreed resolution and the owner. The short version: **the shared service wins, the pack adapts, and we never fork or fake for the demo.**

---

> **AstraRH's `journey` pack owns the 90 days after the offer and the skills after that: it drafts, evidences and proposes; a human approves every action that touches a person's record.**
