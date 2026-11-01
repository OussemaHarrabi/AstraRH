"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";
import { type ApiError, get, type Job, post } from "@/lib/api";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Button, EmptyState, ErrorNote, Field, Loading, Modal, PageHeader, Tag, useLoad } from "@/ui/kit";
import { useToast } from "@/ui/Shell";

const TEMPLATES = [
  { title: "Security Analyst", org: "ORG-ENG", description: "Monitor and investigate security alerts, run SIEM detections, lead incident response and report on risks to the engineering leadership." },
  { title: "Network and Cloud Engineer", org: "ORG-ENG", description: "Design and operate our network and cloud infrastructure, automate with Terraform and keep services available and secure." },
  { title: ".NET Web Developer", org: "ORG-ENG", description: "Build and maintain web applications in C# and ASP.NET Core, with SQL Server and modern front-end practices." },
];

function NewJob({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const job = await post<{ id: string }>("/packs/talent/jobs", { title, description, org_unit: form.get("org") || null });
      toast("Job created. Mira is drafting its criteria.");
      router.push(`/jobs/${job.id}?tab=criteria`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} label="Create a job" width={560}>
      <form onSubmit={create} className="space-y-3 p-5">
        <div className="flex items-center gap-3">
          <Face agent={agentById("rubric_builder")} size={40} track />
          <div>
            <h2 className="text-[17px] font-[560]">Create a job</h2>
            <p className="text-ink-soft">Mira drafts the criteria from your description. You approve them before anything is ranked.</p>
          </div>
        </div>
        <ErrorNote message={error} />
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[13px] text-ink-soft">Start from</span>
          {TEMPLATES.map((template) => (
            <button key={template.title} type="button" onClick={() => { setTitle(template.title); setDescription(template.description); }} className="h-6 rounded-md bg-sunken px-1.5 text-xs font-[520] text-ink-soft transition-colors hover:text-ink">
              {template.title}
            </button>
          ))}
        </div>
        <Field label="Job title">
          <input value={title} onChange={(event) => setTitle(event.target.value)} required autoFocus className="field" />
        </Field>
        <Field label="Job description">
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} required rows={7} className="field" />
        </Field>
        <Field label="Team">
          <select name="org" className="field" defaultValue="ORG-ENG">
            <option value="ORG-ENG">Engineering</option>
            <option value="ORG-SAL">Sales</option>
            <option value="">No team yet</option>
          </select>
        </Field>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create job"}</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

function JobsInner() {
  const params = useSearchParams();
  const [creating, setCreating] = useState(params.get("new") === "1");
  const { data: jobs, error } = useLoad(() => get<Job[]>("/packs/talent/jobs"), []);
  return (
    <>
      <PageHeader title="Jobs" subtitle="Each job has its approved criteria, its ranked candidates and its pipeline." action={<Button onClick={() => setCreating(true)}><Icon name="plus" size={14} /> New job</Button>} />
      <ErrorNote message={error} />
      {!jobs && !error ? <Loading /> : null}
      {jobs?.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface">
          <EmptyState title="No jobs yet" art={<Face agent={agentById("rubric_builder")} size={56} track />}>Create your first job and Mira will draft its criteria.</EmptyState>
        </div>
      ) : null}
      {jobs && jobs.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
          <table className="w-full min-w-[640px] text-left">
            <thead className="text-[13px] text-ink-soft">
              <tr className="border-b border-line">
                <th className="px-4 py-2.5 font-[500]">Job</th>
                <th className="px-4 py-2.5 font-[500]">Team</th>
                <th className="px-4 py-2.5 font-[500]">Criteria</th>
                <th className="px-4 py-2.5 text-right font-[500]">CVs read</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const total = Object.values(job.cv_counts).reduce((sum, value) => sum + value, 0);
                return (
                  <tr key={job.id} className="group row-hover relative border-b border-line last:border-0">
                    <td className="px-4 py-3">
                      <Link href={`/jobs/${job.id}`} className="font-[520] after:absolute after:inset-0 group-hover:text-door">{job.title}</Link>
                    </td>
                    <td className="px-4 py-3 text-ink-soft">{job.org_unit?.replace("ORG-", "") ?? "None"}</td>
                    <td className="px-4 py-3">{job.active_rubric_id ? <Tag tone="good">Approved</Tag> : <Tag tone="warn">Waiting for you</Tag>}</td>
                    <td className="tabular px-4 py-3 text-right">{job.cv_counts.ready ?? 0} of {total}</td>
                    <td className="pr-3"><Icon name="chevron" size={14} className="text-ink-faint opacity-0 transition-opacity group-hover:opacity-100" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {creating ? <NewJob onClose={() => setCreating(false)} /> : null}
    </>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <JobsInner />
    </Suspense>
  );
}
