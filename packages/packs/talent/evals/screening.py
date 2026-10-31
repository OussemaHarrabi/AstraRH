"""Measures the real screening pipeline on the labelled CVs, with the real model.

Every number shown to a jury must come from here. Run with: python astra.py evals
Uses throwaway tenants and deletes them afterwards. Costs about a cent.
"""

import contextvars
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text

from kernel import explain, ml_client
from kernel.ai.graphs import run_agent_graph
from kernel.ai.models import AgentStep
from kernel.db import global_session, tenant_session, use_database
from kernel.identity.models import Tenant
from kernel.registry import import_all_models
from packs.talent import scoring, service
from packs.talent.agents import cv_reader, ranking
from packs.talent.models import CvDocument, ExtractedProfile, Job, RankingRun, Score
from packs.talent.seed import seed

ROOT = Path(__file__).resolve().parents[4]
WORLD = json.loads((ROOT / "data" / "world.json").read_text(encoding="utf-8"))
CV_DIR = ROOT / "data" / "demo" / "cvs"
LABELS = json.loads((ROOT / "data" / "demo" / "labels.json").read_text(encoding="utf-8"))
JOB = "JOB-BE-01"
PARALLEL_READS = 6
RESULT_MARKER = "EVAL_RESULT_JSON:"


def _owner(fn):
    with use_database(os.environ["TEST_OWNER_URL"]):
        return fn()


def make_tenant() -> tuple[UUID, UUID]:
    def create():
        with global_session() as session:
            tenant = Tenant(slug=f"eval-{uuid4().hex[:10]}", name="Eval", active=False)
            session.add(tenant)
            session.flush()
            tenant_id = tenant.id
        with tenant_session(tenant_id) as session:
            seed(session, tenant_id, WORLD)
        with tenant_session(tenant_id) as session:
            return tenant_id, session.scalar(select(Job.id).where(Job.external_id == JOB))

    return _owner(create)


def delete_tenant(tenant_id: UUID) -> None:
    url = os.environ["TEST_SUPERUSER_URL"].replace("postgresql://", "postgresql+psycopg://")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        tables = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.columns "
                "WHERE column_name = 'tenant_id' "
                "AND table_schema NOT IN ('pg_catalog','information_schema')"
            )
        ).all()
        for schema, table in tables:
            conn.execute(
                text(f'DELETE FROM "{schema}"."{table}" WHERE tenant_id = :t'), {"t": tenant_id}
            )
        conn.execute(text("DELETE FROM core.tenant WHERE id = :t"), {"t": tenant_id})
    engine.dispose()


def read_one(tenant_id: UUID, job_id: UUID, filename: str, data: bytes) -> None:
    with tenant_session(tenant_id) as session:
        cv = service.add_cv(session, tenant_id, job_id, filename, data)
        event = {
            "cv_id": str(cv.id),
            "job_id": str(job_id),
            "application_id": str(cv.application_id),
        }
    run = run_agent_graph(
        "cv_reader", "talent", cv_reader.build(), tenant_id, event=event, event_id=uuid4()
    )
    if run.status != "succeeded":
        raise RuntimeError(f"{filename}: {run.error}")


def read_all(tenant_id: UUID, job_id: UUID, items: list[tuple[str, bytes]]) -> None:
    with ThreadPoolExecutor(PARALLEL_READS) as pool:
        futures = []
        for filename, data in items:
            context = contextvars.copy_context()
            futures.append(pool.submit(context.run, read_one, tenant_id, job_id, filename, data))
        for future in futures:
            future.result()


def run_ranking(tenant_id: UUID, job_id: UUID) -> RankingRun:
    with tenant_session(tenant_id) as session:
        row = service.request_ranking(session, tenant_id, job_id)
        event = {"ranking_id": str(row.id), "job_id": str(job_id)}
    run = run_agent_graph(
        "ranking", "talent", ranking.build(), tenant_id, event=event, event_id=uuid4()
    )
    if run.status != "succeeded":
        raise RuntimeError(f"Ranking failed: {run.error}")
    with tenant_session(tenant_id) as session:
        return session.get(RankingRun, row.id)


def results(tenant_id: UUID, ranking_id: UUID) -> dict[str, Score]:
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(CvDocument.filename, Score)
            .join(Score, Score.application_id == CvDocument.application_id)
            .where(Score.ranking_id == ranking_id)
        ).all()
    return {filename: score for filename, score in rows}


def dcg(relevances: list[int]) -> float:
    return sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(relevances))


def ndcg(ordered: list[int], k: int) -> float:
    ideal = dcg(sorted(ordered, reverse=True)[:k])
    return dcg(ordered[:k]) / ideal if ideal else 0.0


def spearman(a: dict[str, int], b: dict[str, int]) -> float:
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n < 2:
        return 1.0
    diffs = sum((a[k] - b[k]) ** 2 for k in keys)
    return 1 - (6 * diffs) / (n * (n**2 - 1))


def relevance(filename: str) -> int:
    return LABELS[filename][JOB]


def main() -> None:
    import_all_models()
    os.environ.setdefault("AGENTS_INLINE", "1")
    worker_url = os.environ["TEST_WORKER_URL"]
    os.environ["DATABASE_URL"] = worker_url
    tenants: list[UUID] = []
    report: dict = {}
    started = time.monotonic()
    try:
        with use_database(worker_url):
            tenant_a, job_a = make_tenant()
            tenants.append(tenant_a)
            items = [(name, (CV_DIR / name).read_bytes()) for name in sorted(LABELS)]
            read_started = time.monotonic()
            read_all(tenant_a, job_a, items)
            read_seconds = time.monotonic() - read_started

            first = run_ranking(tenant_a, job_a)
            scores = results(tenant_a, first.id)
            ordered = sorted(scores, key=lambda name: scores[name].rank)
            rels = [relevance(name) for name in ordered]

            # 1. Accuracy against the known labels.
            report["candidates_ranked"] = len(scores)
            report["ndcg_at_5"] = round(ndcg(rels, 5), 4)
            report["ndcg_at_10"] = round(ndcg(rels, 10), 4)
            total_strong = sum(1 for r in rels if r == 3)
            top_strong = sum(1 for r in rels[:total_strong] if r == 3)
            report["strong_candidates_in_top_positions"] = f"{top_strong}/{total_strong}"
            good = [i for i, r in enumerate(rels) if r >= 2]
            no_fit = [i for i, r in enumerate(rels) if r == 0]
            report["every_good_candidate_above_every_no_fit"] = max(good) < min(no_fit)
            # The harder, messier CVs alone: dates instead of durations, synonyms and traps.
            hard = [name for name in ordered if LABELS[name]["kind"] == "hard"]
            hard_rels = [relevance(name) for name in hard]
            report["hard_set_size"] = len(hard)
            report["hard_set_ndcg_at_5"] = round(ndcg(hard_rels, 5), 4)
            report["hard_set_ndcg_at_12"] = round(ndcg(hard_rels, 12), 4)
            report["hard_set_order"] = [
                {
                    "rank_in_set": position,
                    "true_relevance": relevance(name),
                    "score": str(round(scores[name].score, 4)),
                    "meets_must_haves": scores[name].meets_must_haves,
                }
                for position, name in enumerate(hard, start=1)
            ]
            report["top_5"] = [
                {
                    "rank": scores[name].rank,
                    "score": str(scores[name].score),
                    "true_relevance": relevance(name),
                    "kind": LABELS[name]["kind"],
                }
                for name in ordered[:5]
            ]

            # 2. Reproducibility: the same stored facts rank identically, again and again.
            second = run_ranking(tenant_a, job_a)
            third = run_ranking(tenant_a, job_a)
            report["rerank_identical"] = first.order_hash == second.order_hash == third.order_hash

            # 3. Replay: every recorded decision recomputes to the same score.
            with tenant_session(tenant_a) as session:
                checks = [
                    explain.verify(session, s.decision_record_id)["match"] for s in scores.values()
                ]
            report["decisions_replayed"] = f"{sum(checks)}/{len(checks)}"

            # 4. Hidden text: the attack CV scores the same as its clean twin.
            attack = next(n for n, label in LABELS.items() if label["kind"] == "attack_white_text")
            visible = ml_client.parse(attack, (CV_DIR / attack).read_bytes()).text
            read_one(tenant_a, job_a, "clean_twin.txt", visible.encode("utf-8"))

            # 5. Name swap: same CV, another name, across traditionally gendered names.
            hero = next(n for n, label in LABELS.items() if label["kind"] == "hero")
            hero_text = ml_client.parse(hero, (CV_DIR / hero).read_bytes()).text
            swapped = re.sub(r"Yasmine", "Mohamed", hero_text)
            swapped = re.sub(r"yasmine", "mohamed", swapped)
            read_one(tenant_a, job_a, "name_swap.txt", swapped.encode("utf-8"))

            after = run_ranking(tenant_a, job_a)
            scores_after = results(tenant_a, after.id)
            report["hidden_text_score_equals_clean_twin"] = (
                scores_after[attack].score == scores_after["clean_twin.txt"].score
            )
            report["name_swap_score_unchanged"] = (
                scores_after[hero].score == scores_after["name_swap.txt"].score
            )

            # 6. Attacks: where each one landed.
            report["attacks"] = {
                LABELS[name]["kind"]: {
                    "rank": scores[name].rank,
                    "of": len(scores),
                    "score": str(scores[name].score),
                    "flagged": _flagged(tenant_a, name),
                }
                for name in ordered
                if LABELS[name]["kind"].startswith("attack")
            }

            # 7. Quote fidelity: every stored quote really is in the CV's own text.
            total_quotes, valid_quotes, removed = 0, 0, 0
            with tenant_session(tenant_a) as session:
                rows = session.execute(
                    select(ExtractedProfile, CvDocument.blind_text).join(
                        CvDocument, CvDocument.id == ExtractedProfile.cv_id
                    )
                ).all()
            for profile, blind_text in rows:
                source = _norm(blind_text or "")
                removed += len(profile.removed_spans)
                for claim in profile.data["skills"]:
                    total_quotes += 1
                    valid_quotes += _norm(claim["evidence"]["quote"]) in source
            report["quotes_verified_in_source"] = f"{valid_quotes}/{total_quotes}"
            report["invented_quotes_removed"] = removed

            # 8. Sensitivity: read everything again from scratch, with no cache. The model isn't
            # deterministic, so this measures how much that can move the ranking.
            tenant_b, job_b = make_tenant()
            tenants.append(tenant_b)
            read_all(tenant_b, job_b, items)
            fresh = run_ranking(tenant_b, job_b)
            scores_b = results(tenant_b, fresh.id)
            ranks_a = {name: s.rank for name, s in scores.items()}
            ranks_b = {name: s.rank for name, s in scores_b.items()}
            report["fresh_reread_rank_correlation"] = round(spearman(ranks_a, ranks_b), 4)
            top5_a = {n for n, r in ranks_a.items() if r <= 5}
            top5_b = {n for n, r in ranks_b.items() if r <= 5}
            report["fresh_reread_top5_overlap"] = f"{len(top5_a & top5_b)}/5"
            deltas = [abs(scores[n].score - scores_b[n].score) for n in scores if n in scores_b]
            report["fresh_reread_max_score_change"] = str(round(max(deltas), 4))

            # 9. Cost and speed.
            with tenant_session(tenant_a) as session:
                steps = session.scalars(select(AgentStep).where(AgentStep.model.is_not(None))).all()
            paid = [s for s in steps if not s.cached]
            report["llm_calls"] = len(paid)
            report["llm_cache_hits"] = len(steps) - len(paid)
            report["llm_input_tokens"] = sum(s.input_tokens for s in paid)
            report["llm_output_tokens"] = sum(s.output_tokens for s in paid)
            report["llm_cost_usd_one_full_run"] = str(sum(s.cost_usd for s in paid))
            report["models"] = sorted({s.model for s in paid})
            report["seconds_to_read_all_cvs"] = round(read_seconds, 1)
            report["scorer"] = f"{scoring.SCORER}@{scoring.SCORER_VERSION}"
            report["total_seconds"] = round(time.monotonic() - started, 1)
    finally:
        for tenant_id in tenants:
            delete_tenant(tenant_id)
    print(json.dumps(report, indent=2))
    print(RESULT_MARKER + json.dumps(report))


def _flagged(tenant_id: UUID, filename: str) -> bool:
    with tenant_session(tenant_id) as session:
        return bool(
            session.scalar(select(CvDocument.flagged).where(CvDocument.filename == filename))
        )


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


if __name__ == "__main__":
    main()
