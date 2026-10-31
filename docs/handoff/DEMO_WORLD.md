# Demo world: the fictional company everyone shares

All seed data describes this one company, so the four services join up in the demo.
**Everything is invented. The brief forbids real personal data.** Never use real CVs, real people or real payslips.

## Company

- **Name:** Carthage Demo Systems (CDS), a fictional software company in Tunis with about 40 employees.
- **Currency:** TND. **Languages:** French, English, some Arabic.
- **Email domain:** `cds.example.test`. Candidates use `@mail.example.test`. These domains are reserved and can never reach a real inbox.

## Stable IDs: use these exactly

### Org units

| ID | Name | Head |
|---|---|---|
| `ORG-ENG` | Engineering | `EMP-002` |
| `ORG-PRD` | Product & Design | `EMP-003` |
| `ORG-SAL` | Sales | `EMP-004` |
| `ORG-OPS` | Operations & Support | `EMP-005` |
| `ORG-HR` | People | `EMP-006` |
| `ORG-FIN` | Finance | `EMP-007` |

### Positions

`POS-BE` Backend Engineer, `POS-FE` Frontend Engineer, `POS-DATA` Data Engineer, `POS-PM` Product Manager, `POS-DES` Product Designer, `POS-AE` Account Executive, `POS-SUP` Support Specialist, `POS-REC` Recruiter, `POS-HRBP` HR Business Partner, `POS-ACC` Accountant, `POS-MGR` Team Manager, `POS-CEO` Chief Executive.

### People who appear in the demo

| ID | Name | Role |
|---|---|---|
| `EMP-001` | Salma Gharbi | CEO |
| `EMP-002` | Karim Mansour | Engineering manager |
| `EMP-003` | Ines Ben Salah | Product manager |
| `EMP-004` | Walid Jebali | Sales manager |
| `EMP-005` | Rim Chaabane | Operations manager |
| `EMP-006` | Leila Haddad | HR business partner, approves HR actions |
| `EMP-007` | Sami Ferchichi | Finance manager, approves payroll |
| `EMP-008` | Nadia Bouzid | Recruiter, the main demo user |
| `EMP-009` | Mehdi Sassi | Senior backend engineer, the new hire's buddy |

Remaining employees are `EMP-010` to `EMP-040`. Spread them across org units in `workforce/employees.csv`.

### The hero story

- **Open job:** `JOB-BE-01`, Backend Engineer in `ORG-ENG`, reporting to `EMP-002`.
- **Hero candidate:** `CAND-001` Yasmine Trabelsi, who gets hired. Strong in Python, SQL, FastAPI. Screening finds **gaps in Kubernetes and observability**.
- **The cascade when she is hired:**
  - `journey` proposes a 30-60-90 plan with `EMP-009` as buddy, including the Kubernetes gap.
  - `journey` recommends `CRS-K8S-01`, tied to KPI `KPI-MTTR`.
  - `finance` updates the Engineering cost forecast.
  - `workforce` updates Engineering capacity.
- **Bus-factor story for the Skills Graph:** `EMP-009` is the only person in Engineering with `SKILL-OBS`.

### Skills

`SKILL-PY` Python, `SKILL-SQL` SQL, `SKILL-FASTAPI` FastAPI, `SKILL-K8S` Kubernetes, `SKILL-DOCKER` Docker, `SKILL-OBS` Observability, `SKILL-REACT` React, `SKILL-TS` TypeScript, `SKILL-DATA` Data pipelines, `SKILL-PM` Product management, `SKILL-UX` UX design, `SKILL-NEG` Negotiation, `SKILL-CRM` CRM, `SKILL-SUPPORT` Customer support, `SKILL-RECRUIT` Recruiting, `SKILL-LABOR` Labour policy, `SKILL-ACCT` Accounting, `SKILL-LEAD` Team leadership, `SKILL-COMM` Communication.

Related pairs: `SKILL-K8S`↔`SKILL-DOCKER`, `SKILL-FASTAPI`↔`SKILL-PY`, `SKILL-REACT`↔`SKILL-TS`, `SKILL-DATA`↔`SKILL-SQL`.

### KPIs

| ID | Name | Owner pack |
|---|---|---|
| `KPI-MTTR` | Mean time to restore (hours) | `journey` |
| `KPI-RAMP` | Days to full productivity | `journey` |
| `KPI-90D` | 90-day new-hire retention (%) | `journey` |
| `KPI-TTH` | Time to hire (days) | `talent` |
| `KPI-COST` | People cost against budget (%) | `finance` |
| `KPI-OVERTIME` | Team overtime (hours) | `workforce` |

**Need a new ID?** Add it in your own data with your pack's prefix, and tell Oussema if another pack will use it.
