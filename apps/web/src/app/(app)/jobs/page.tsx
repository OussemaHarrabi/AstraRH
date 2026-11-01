"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type ApiError, get, type Job } from "@/lib/api";
import { EmptyState, ErrorNote, Loading, PageHeader, Tag } from "@/ui/kit";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Job[]>("/packs/talent/jobs")
      .then(setJobs)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeader
        title="Recruitment"
        subtitle="Upload CVs for a job, and get a ranked list where every score can be checked."
      />
      <ErrorNote message={error} />
      {!jobs && !error ? <Loading /> : null}
      {jobs?.length === 0 ? (
        <EmptyState title="No jobs yet">Run the demo seed to load sample jobs.</EmptyState>
      ) : null}
      <ul className="divide-y divide-line border-y border-line">
        {jobs?.map((job) => {
          const total = Object.values(job.cv_counts).reduce((sum, n) => sum + n, 0);
          return (
            <li key={job.id} className="py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <Link href={`/jobs/${job.id}`} className="font-display text-xl font-semibold text-door hover:underline">
                  {job.title}
                </Link>
                <span className="flex items-center gap-3">
                  {job.active_rubric_id ? null : <Tag tone="warn">Criteria not approved</Tag>}
                  <span className="tabular text-ink-soft">{total} CVs</span>
                </span>
              </div>
              <p className="mt-1 max-w-3xl text-ink-soft">{job.description}</p>
            </li>
          );
        })}
      </ul>
    </>
  );
}
