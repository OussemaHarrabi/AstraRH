"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type ApiError, get, type Job, type Pack, type Proposal } from "@/lib/api";
import { useMe } from "@/ui/Shell";
import { ErrorNote, Loading, PageHeader, RiskTag, Tag } from "@/ui/kit";

export default function TodayPage() {
  const me = useMe();
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Proposal[]>("/trust/proposals?status=pending_approval")
      .then(setProposals)
      .catch((e: ApiError) => setError(e.message));
    get<Job[]>("/packs/talent/jobs")
      .then(setJobs)
      .catch(() => setJobs([]));
    get<Pack[]>("/registry/packs")
      .then(setPacks)
      .catch(() => setPacks([]));
  }, []);

  const firstName = me?.display_name.split(" ")[0];
  return (
    <>
      <PageHeader title={`Good day, ${firstName}`} subtitle="Here is what is waiting for you." />
      <ErrorNote message={error} />

      <section aria-labelledby="waiting">
        <h2 id="waiting" className="text-xl font-semibold">
          Waiting for your decision
        </h2>
        {proposals === null ? (
          <Loading />
        ) : proposals.length === 0 ? (
          <p className="mt-2 text-ink-soft">Nothing is waiting. The agents are not holding anything for you.</p>
        ) : (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {proposals.slice(0, 5).map((proposal) => (
              <li key={proposal.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <span className="font-medium">{proposal.summary}</span>
                <span className="flex items-center gap-3">
                  <RiskTag risk={proposal.risk} />
                  <Link href="/approvals" className="font-semibold text-door hover:underline">
                    Review
                  </Link>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {jobs && jobs.length > 0 ? (
        <section aria-labelledby="hiring" className="mt-10">
          <h2 id="hiring" className="text-xl font-semibold">
            Open jobs
          </h2>
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {jobs.map((job) => {
              const total = Object.values(job.cv_counts).reduce((sum, n) => sum + n, 0);
              return (
                <li key={job.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <Link href={`/jobs/${job.id}`} className="font-medium text-door hover:underline">
                    {job.title}
                  </Link>
                  <span className="tabular text-ink-soft">
                    {total} {total === 1 ? "CV" : "CVs"}, {job.cv_counts.ready ?? 0} read
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="features" className="mt-10">
        <h2 id="features" className="text-xl font-semibold">
          What AstraRH does for you
        </h2>
        <div className="mt-3 grid gap-x-10 gap-y-6 md:grid-cols-2">
          {packs.flatMap((pack) =>
            pack.agents.map((agent) => (
              <div key={`${pack.id}.${agent.id}`}>
                <p className="flex items-center gap-2 font-semibold">
                  {agent.title}
                  {pack.status === "preview" ? <Tag tone="neutral">Preview</Tag> : null}
                </p>
                <p className="text-ink-soft">{agent.description}</p>
              </div>
            )),
          )}
        </div>
      </section>
    </>
  );
}
