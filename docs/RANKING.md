# How AstraRH ranks CVs

The answer to the jury's question: "You ranked these candidates. Based on what?"

**In one sentence:** the recruiter approves weighted job criteria, the AI only reads CVs and writes explanations, and a transparent formula decides the order, so the same inputs always produce the same ranking.

## Who does what

| Step | Done by | Why |
|---|---|---|
| Propose job criteria | AI drafts, **recruiter edits and approves** | A human owns what "good" means. Ranking refuses to run without approved criteria |
| Remove hidden text | Code, in a sandbox with no network | White text and tiny fonts are dropped before any AI sees the file |
| Remove identity | Code, before any AI | Name, contact details, age, gender, nationality and address never reach the model or the score |
| Read the CV into facts | AI (Claude Haiku), with no tools | It returns structured facts and exact quotes. It can't act on anything |
| Check the AI's quotes | Code | A quote not found in the CV is deleted, and the skill it supported goes with it |
| Measure similarity | Local embedding model + pgvector | Finds relevant wording when the exact term is missing |
| **Compute the score and rank** | **Formula. No AI** | Reproducible and auditable, and can't be talked into anything |
| Write the justification | AI, from numbers only | It never sees CV text, and any wrong number or uncited sentence is rejected |
| Move candidates forward | **A person approves** | The golden rule |

## The formula

For each criterion, the candidate earns a value from 0 to 1, taken from their **strongest** evidence:

| Evidence | Value | Example |
|---|---|---|
| Proven, with enough years | 1.00 | "6 years of Python" where 3 are required |
| Proven, with fewer years | 0.60 + 0.40 × (years ÷ required) | 2 years where 4 are required = 0.80 |
| Proven, no duration given | 0.60 | "Experience with Docker" |
| Related skill | up to 0.40 | Docker counts partly toward Kubernetes |
| Similar wording only | up to 0.35 | No exact term, but a passage means the same |
| Only in a keyword list | 0.30 | "Keywords: Python Docker Kubernetes..." |
| Nothing found | 0 | Reported as "no evidence found", never as "lacks" |

Then:

```
score = sum of (criterion weight × value)     weights are approved by the recruiter and sum to 1
```

**Order:** candidates who meet every must-have come first, then highest score. Ties break on the file's content hash, so order never depends on upload order or identity.

Nobody is removed. The recruiter sees everyone, along with what is missing.

The whole formula is in [`scoring.py`](../packages/packs/talent/scoring.py), about 130 lines. A test confirms this file can't import a database table or a model client.

### Why these evidence values?

They encode one rule: **proof beats suggestion**. Direct proof with any duration (0.60) always beats the best possible similar wording (0.35). A duration is only believed if the number is in a verified quote, or computed by our code from dated roles that really name the skill.

These values are product judgement, not learned from data. They are fixed and versioned (`talent.rubric@1`), and every decision records the version.

## Worked example

Backend Engineer, candidate with 6 years of Python, 5 of PostgreSQL, 4 of FastAPI, 3 of Docker, and nothing on Kubernetes or observability:

| Criterion | Weight | Value | Contribution |
|---|---:|---:|---:|
| Python | 0.25 | 1.00 | 0.2500 |
| SQL databases | 0.15 | 1.00 | 0.1500 |
| FastAPI | 0.15 | 1.00 | 0.1500 |
| Docker | 0.10 | 1.00 | 0.1000 |
| Kubernetes | 0.10 | 0.20 (related: Docker) | 0.0200 |
| Observability | 0.10 | 0.00 | 0.0000 |
| API design | 0.10 | similarity-based | varies |
| Collaboration | 0.05 | similarity-based | varies |

The "Why?" panel shows these exact numbers, each one's quote from the CV, and what would change the result: "With full evidence for Observability, rank would be 2."

## Why it is reproducible

The AI isn't deterministic, so it's kept away from the decision:

1. **The AI reads once, and its output is frozen.** Re-ranking reuses the stored facts.
2. **Embeddings come from a fixed local model** baked into a container, and similarities are stored rounded.
3. **Everything the formula needs is saved with the decision.** "Verify" recomputes the score from those inputs and compares it digit by digit.
4. **Exact decimal arithmetic.** No floating-point drift.
5. **Criteria are versioned.** Editing creates a new version, and old results can still name exactly what produced them.

## Measured results

From [`docs/evals/screening.json`](evals/screening.json), produced by `python astra.py evals` with the real model. One full run on 42 CVs costs about $0.016 and reads them in about 21 seconds.

| Test | Result |
|---|---|
| Ranking quality, all 42 CVs (NDCG@10) | 1.0 |
| Ranking quality, harder 12 CVs (NDCG@12) | 1.0 |
| Re-ranking gives an identical result | Yes |
| Decisions that replay to the same score | 42/42 |
| Reading everything again from scratch: rank correlation | 1.0 (top 5 overlap: 5/5) |
| Hidden white text: score vs the same CV without it | Identical |
| Same CV under another name | Identical score |
| AI quotes confirmed present in the source | 170/170 |
| Keyword-stuffed CV | Rank 27 of 42 |
| CVs containing written instructions to the AI | Flagged, ranks 32 and 34 of 42 |

### What these numbers do and don't prove

**Be honest about this if asked.** A perfect score here doesn't mean the system is perfect:

- **We wrote these CVs and their labels ourselves**, including the "harder" set. They test the design on known cases. They are not an independent benchmark, and real CVs are messier.
- **The rule-based attack detector can miss new phrasings.** That's why detection isn't the defence: the model has no tools, the score is arithmetic, and hidden text is removed before reading. An attack that goes unflagged still can't change a score through the instruction.
- **The fairness tests cover identity removal only.** They don't prove the absence of indirect bias, such as career gaps or the wording people use. The tested set contains no real demographic data, and selection-rate monitoring needs real data.
- **The criteria themselves can carry bias.** That's why a person approves them.

The next real step is to label a set of CVs by independent recruiters.

## Questions a jury may ask

**"Isn't the AI biased?"** The AI doesn't rank. It never sees the name, gender, age or origin, and the score is arithmetic. We test that swapping a name doesn't move a score. We don't claim zero bias: indirect signals in a CV can remain, and a person makes every decision.

**"What if someone hides text in their CV?"** It's removed before any AI reads the file, and flagged for the recruiter. We test that the score equals the same CV without the hidden text.

**"What if the CV tells the AI to rank it first?"** The reader has no tools and returns only structured facts. Even if it were fooled, it can't set a score, and its claims need a quote that exists in the file. The attempt is flagged for the recruiter.

**"Could I game it with keywords?"** A keyword list earns 0.30 at most and can't satisfy a must-have. Repeating a word earns nothing extra.

**"Why not just ask the AI to rank them?"** Ask twice and you can get two answers, with no way to show why. Here, every point of every score can be traced to a weight the recruiter approved and a quote from the CV.

**"Why this similarity model?"** It covers French, English and Arabic, runs locally so CVs don't leave for it, and is small enough to run on CPU. Similarity is capped low because "sounds similar" isn't proof.

**"What if the AI misreads a CV?"** Its quotes are checked against the file, the recruiter sees exactly what it read, and can correct any criterion with a recorded reason. Corrections apply to the next ranking.
