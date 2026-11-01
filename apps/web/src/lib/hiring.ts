"use client";

import { type AgentRun, get, type Interview, type Job, type Proposal, type RankedCandidate, type Shortlist } from "./api";
import type { Mood } from "@/ui/Face";

export interface CandidateRow extends RankedCandidate {
  job_id: string;
  job_title: string;
}

/** Every ranked candidate across open jobs. The API has per-job lists only. */
export async function loadCandidates(): Promise<{ jobs: Job[]; candidates: CandidateRow[]; interviews: Interview[] }> {
  const jobs = await get<Job[]>("/packs/talent/jobs");
  const lists = await Promise.all(
    jobs.map(async (job) => {
      const [list, interviews] = await Promise.all([
        get<Shortlist>(`/packs/talent/jobs/${job.id}/shortlist`),
        get<Interview[]>(`/packs/talent/jobs/${job.id}/interviews`),
      ]);
      return {
        interviews,
        candidates: list.candidates.map((candidate) => ({ ...candidate, job_id: job.id, job_title: job.title })),
      };
    }),
  );
  return {
    jobs,
    candidates: lists.flatMap((item) => item.candidates),
    interviews: lists.flatMap((item) => item.interviews),
  };
}

export function stageCounts(candidates: { stage: string }[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const candidate of candidates) counts[candidate.stage] = (counts[candidate.stage] ?? 0) + 1;
  return counts;
}

/** A face's mood is the agent's real state: runs in progress, failures, proposals waiting. */
export function moodsFrom(runs: AgentRun[], proposals: Proposal[]): Record<string, Mood> {
  const moods: Record<string, Mood> = {};
  const byId = new Map(runs.map((run) => [run.id, run]));
  for (const run of [...runs].reverse()) {
    if (!moods[run.agent]) moods[run.agent] = "idle";
    const age = Date.now() - new Date(run.started_at).getTime();
    if (run.status === "failed" && age < 3_600_000) moods[run.agent] = "alert";
  }
  for (const proposal of proposals) {
    const run = proposal.agent_run_id ? byId.get(proposal.agent_run_id) : undefined;
    if (run) moods[run.agent] = "waiting";
  }
  for (const run of runs) {
    if (run.status === "running" || run.status === "pending") moods[run.agent] = "working";
  }
  return moods;
}

export function downloadCsv(filename: string, rows: (string | number | null | undefined)[][]) {
  const text = rows
    .map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
