# Send this to the team now

Paste the message below into your team chat, and attach these files:
- `docs/handoff/DEMO_WORLD.md` and `docs/ARCHITECTURE.md`, to everyone.
- `docs/handoff/journey.md`, to Wassim.
- `docs/handoff/finance.md`, to the finance owner.
- `docs/handoff/workforce.md`, to the workforce owner.

---

Team, here's the plan. Our product is **AstraRH**: one HR ecosystem from hire to retain, where AI does the work and humans decide about people.

**Who owns what**
- **Oussema:** the platform core and everything in the hackathon brief (recruitment, inbox, replies, scheduling, policy answers).
- **Wassim:** onboarding, follow-up, skill gaps, and training linked to KPIs.
- **Finance owner:** payroll, budget, forecasts, and the cost of losing people.
- **Workforce owner:** workforce tracking, conflict management, and the shared design system.

**What to do right now, without waiting for the repo**
1. Read `ARCHITECTURE.md`, especially "The ten invariants" and "What we will not build".
2. Read `DEMO_WORLD.md`. We all use the same fictional company and the same IDs, so our services connect in the demo.
3. Read your own brief and start its "Start now" section: fictional seed data and acceptance scenarios. Your coding agent will build from these, so they matter.
4. Workforce owner: start the design tokens first, and share `employees.csv` early, since it's the master list.

**Don't start coding your service yet.** The foundation (`platform-v0`) comes first, so we don't each invent our own login, database setup and approvals. When it's ready you'll get the repo link and a ready-to-paste prompt for your coding agent, and you'll work in your own folders.

**Three rules from now on**
- Only fictional data. No real CVs or real people.
- AI proposes, a human approves anything that affects a person, and every decision can be explained.
- Install now: Docker Desktop, Git, Python 3.12+, Node 22+.

Questions about scope or data shape: ask Oussema before building around them.
