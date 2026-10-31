# How AstraRH ranks CVs

The answer to the jury's question: "You ranked these candidates. Based on what?"

**In one sentence:** two layers score every CV, hybrid search for how close it is to the job, and evidence for what it proves against the criteria a recruiter approved. A transparent formula combines them, so the same inputs always give the same ranking.

## The two layers

```
score (out of 100) = 70 points of evidence + 30 points of job match

Layer 1, job match (30)   hybrid search across the whole CV
                          50% vector similarity (meaning) + 50% BM25 (exact terms)

Layer 2, evidence (70)    each approved criterion:  weight x how much the CV proved
```

| Layer | Answers | Good at | Weak at, and why the other layer is there |
|---|---|---|---|
| **Hybrid search** | How close is this CV to the job overall? | Finding fit in different words, languages and wording | "Sounds similar" isn't proof, so it is capped at 30 points |
| **Evidence** | What does this CV prove, criterion by criterion? | Exact, quotable, and tied to what the recruiter asked for | Could miss experience described in unexpected terms, which hybrid search still catches |

**Order:** candidates who meet every must-have come first, then highest score. Ties break on the file's content hash, so order never depends on upload order or identity. Nobody is removed: the recruiter sees everyone, and what is missing.

## Who does what

| Step | Done by | Why |
|---|---|---|
| Propose job criteria | AI drafts, **recruiter edits and approves** | A person owns what "good" means. Ranking refuses to run without approved criteria |
| Remove hidden text | Code, in a sandbox with no network | White text and tiny fonts are dropped before any AI sees the file |
| Remove identity | Code, before any AI | Name, contact details, age, gender, nationality and address never reach the model or the score |
| Read the CV into facts | AI (Claude Haiku), with no tools | It returns structured facts and exact quotes. It can't act on anything |
| Check the AI's quotes | Code | A quote not found in the CV is deleted, and the skill it supported goes with it |
| Vector similarity | Local multilingual model + pgvector | Meaning, in French, English and Arabic, on the CV's identity-free text |
| BM25 | Code | Exact terms. Keyword-list lines are excluded |
| **Compute the score and rank** | **Formula. No AI** | Reproducible and auditable, and can't be talked into anything |
| Write the justification | AI, from numbers only | It never sees CV text, and any wrong number or uncited sentence is rejected |
| Move candidates forward | **A person approves** | The golden rule |

## Layer 1: job match

- **Vector similarity:** each criterion is embedded, and pgvector finds the CV's closest passage by cosine similarity. The result is the criterion-weighted average of those similarities. The search is exact rather than approximate, so it's repeatable.
- **BM25:** the classic ranking function for exact terms, computed over this job's CVs with the job offer and criteria as the query. It is scaled so the best CV in the run is 1. Word repetition saturates, and lines that are only keyword lists don't count.

BM25 is relative to the CVs in the run, so adding CVs can shift scores slightly. That's why every decision stores the values it used: replay always reproduces the original.

## Layer 2: evidence

For each criterion, the candidate earns a value from 0 to 1, from their **strongest** evidence:

| Evidence | Value | Example |
|---|---|---|
| Proven, with enough years | 1.00 | "6 years of Python" where 3 are required |
| Proven, with fewer years | 0.60 + 0.40 × (years ÷ required) | 2 years where 4 are required = 0.80 |
| Proven, no duration given | 0.60 | "Experience with Docker" |
| Related skill | up to 0.40 | Docker counts partly toward Kubernetes |
| Similar wording only | up to 0.35 | No exact term, but a passage means the same |
| Only in a keyword list | 0.30, and can't satisfy a must-have | "Keywords: Python Docker Kubernetes..." |
| Nothing found | 0 | Reported as "no evidence found", never as "lacks" |

**Years are only believed if verified.** Either the number is in a quote that really exists in the CV, or our code computes it from dated roles that name the skill, counting overlapping roles once. The arithmetic is ours, not the model's.

These values encode one rule, **proof beats suggestion**: any direct proof (0.60) beats the best similar wording (0.35). They are product judgement, not learned from data. They are versioned (`talent.rubric@2`), and each decision records its version.

All of this is in [`scoring.py`](../packages/packs/talent/scoring.py). A test confirms that file can't import a database table or a model client.

## Worked example, from the running system

Yasmine Trabelsi, Backend Engineer, rank 3 of 42:

| Line | Points available | Earned | Why |
|---|---:|---:|---|
| Python | 17.5 | 17.5 | "Worked with Python for 6 years..." |
| SQL databases | 10.5 | 10.5 | "5 years of PostgreSQL..." |
| FastAPI | 10.5 | 10.5 | "4 years of FastAPI..." |
| Docker | 7 | 7.0 | "...using Docker for 3 years" |
| Kubernetes | 7 | 1.4 | Related skill: Docker |
| Observability | 7 | 0.0 | No evidence found |
| API design | 7 | 7.0 | "Designed REST APIs used by 40 internal teams" |
| Collaboration and mentoring | 3.5 | 3.5 | "...mentored two junior engineers" |
| **Overall match with the job** | 30 | 21.5 | Hybrid search |
| **Score** | | **79** | |

The system also computes: "With full evidence for Observability: rank 1, score 86." That comes from re-scoring, not from an estimate.

## Why it is reproducible

The AI isn't deterministic, so it's kept away from the decision:

1. **The AI reads once, and its output is frozen.** Re-ranking reuses the stored facts.
2. **The embedding model is fixed** and baked into a container, with vectors and similarities rounded.
3. **Everything the formula needs is saved with the decision.** "Recalculate score" recomputes it and compares it digit by digit.
4. **Exact decimal arithmetic.** No floating-point drift.
5. **Criteria are versioned.** Editing creates a new version, and old results still name what produced them.

## Measured results

From [`docs/evals/screening.json`](evals/screening.json), produced by `python astra.py evals` with the real model. One full run on 42 CVs costs about $0.017 and reads them in about 27 seconds.

| Test | Result |
|---|---|
| Ranking quality, all 42 CVs (NDCG@10) | 1.0 |
| Ranking quality, harder 12 CVs (NDCG@12) | 0.9994 |
| Strong candidates in the top positions | 10/10 |
| Every good candidate above every no-fit candidate | Yes |
| Re-ranking gives an identical result | Yes |
| Decisions that replay to the same score | 42/42 |
| Reading everything again from scratch: rank correlation | 1.0 (top 5 overlap: 5/5) |
| Hidden white text: score vs the same CV without it | Identical, ranks 35 of 42 |
| Same CV under another name | Identical score |
| AI quotes confirmed present in the source | 170/170 |
| Keyword-stuffed CV | Rank 27 of 42 |
| CVs with written instructions to the AI | Flagged, ranks 33 and 42 of 42 |

### What these numbers do and don't prove

**Be honest about this if asked.** High scores here don't mean the system is perfect:

- **We wrote these CVs and their labels ourselves**, including the "harder" set. They test the design on known cases. They are not an independent benchmark, and real CVs are messier.
- **The fresh re-read result is on short, clear CVs.** Longer, messier CVs would probably vary more between readings. That's why the reading is frozen.
- **The rule-based attack detector can miss new phrasings.** Detection isn't the defence: the model has no tools, the score is arithmetic, and hidden text is removed before reading. An unflagged attack still can't change a score through its instruction.
- **The fairness tests cover identity removal only.** They don't prove the absence of indirect bias, such as career gaps or wording style. The tested set has no real demographic data, and selection-rate monitoring needs real data.
- **The criteria can carry bias.** That's why a person approves them.

The next real step is to have independent recruiters label a set of CVs.

## Questions a jury may ask

**"Isn't the AI biased?"** The AI doesn't rank. It never sees the name, gender, age or origin, and the score is arithmetic. We test that swapping a name doesn't move a score. We don't claim zero bias: indirect signals in a CV can remain, and a person makes every decision.

**"Why two layers?"** Similarity alone can't prove anything: a CV can sound right and show nothing. Evidence alone can miss experience described in other words. Together, proof carries most of the score and meaning catches what exact matching misses.

**"Why hybrid, not only vectors?"** Vectors capture meaning but can blur specific terms. BM25 is exact but blind to meaning. Technical hiring needs both.

**"What if someone hides text in their CV?"** It's removed before any AI reads the file, and flagged for the recruiter. We test that the score equals the same CV without the hidden text.

**"What if the CV tells the AI to rank it first?"** The reader has no tools and returns only structured facts. Even if fooled, it can't set a score, and its claims need a quote that exists in the file. The attempt is flagged.

**"Could I game it with keywords?"** Keyword-list lines are excluded from BM25, earn 0.30 at most as evidence, and can't satisfy a must-have. Repeating a word earns almost nothing.

**"Why not just ask the AI to rank them?"** Ask twice and you can get two answers, with no way to show why. Here, every point can be traced to a weight the recruiter approved, a quote from the CV, or a similarity measurement.

**"What if the AI misreads a CV?"** Its quotes are checked against the file, the recruiter sees what it read, and can correct any criterion with a recorded reason. Corrections apply to the next ranking.

**"Why is it 70/30?"** A product judgement: proof should outweigh resemblance. The split is one versioned setting, and a real deployment should tune it against recruiter-labelled data.
