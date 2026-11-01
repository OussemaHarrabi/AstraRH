"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { downloadCsv, loadCandidates } from "@/lib/hiring";
import { EMPTY_LIST, EMPTY_MAP, useLocal } from "@/lib/local";
import { CandidateDrawer, flagText } from "@/ui/CandidateDrawer";
import { EvidenceStrip } from "@/ui/EvidenceStrip";
import { Icon } from "@/ui/Icon";
import { Avatar, Button, ErrorNote, Loading, PageHeader, percent, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";

const STAGE_TONE: Record<string, Tone> = { applied: "neutral", shortlisted: "info", interview: "info", hired: "good", rejected: "bad" };
type Sort = "score" | "name" | "job";

export default function CandidatesPage() {
  const { data, error, reload } = useLoad(loadCandidates, []);
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("all");
  const [jobId, setJobId] = useState("all");
  const [sort, setSort] = useState<Sort>("score");
  const [onlyStarred, setOnlyStarred] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [stars] = useLocal<string[]>("candidate.stars", EMPTY_LIST);
  const [tags, setTags] = useLocal<Record<string, string[]>>("candidate.tags", EMPTY_MAP);

  const rows = useMemo(() => {
    const list = (data?.candidates ?? []).filter((candidate) => {
      const text = `${candidate.name ?? ""} ${candidate.job_title} ${(tags[candidate.application_id] ?? []).join(" ")}`.toLowerCase();
      return (
        (!query || text.includes(query.toLowerCase())) &&
        (stage === "all" || candidate.stage === stage) &&
        (jobId === "all" || candidate.job_id === jobId) &&
        (!onlyStarred || stars.includes(candidate.application_id))
      );
    });
    return [...list].sort((a, b) => {
      if (sort === "name") return (a.name ?? "").localeCompare(b.name ?? "");
      if (sort === "job") return a.job_title.localeCompare(b.job_title) || a.rank - b.rank;
      return Number(b.score) - Number(a.score);
    });
  }, [data, query, stage, jobId, sort, onlyStarred, stars, tags]);

  const stages = [...new Set((data?.candidates ?? []).map((candidate) => candidate.stage))];
  const open = data?.candidates.find((candidate) => candidate.application_id === openId) ?? null;

  function bulkTag() {
    const value = window.prompt("Tag for the selected candidates");
    if (!value?.trim()) return;
    setTags((all) => {
      const next = { ...all };
      for (const id of selected) next[id] = [...new Set([...(next[id] ?? []), value.trim()])];
      return next;
    });
    setSelected([]);
  }

  return (
    <>
      <PageHeader
        title="Candidates"
        subtitle="Everyone across all open jobs."
        action={
          <Button variant="secondary" onClick={() => downloadCsv("candidates.csv", [["Name", "Job", "Rank", "Score", "Stage"], ...rows.map((row) => [row.name, row.job_title, row.rank, percent(row.score), row.stage])])}>
            <Icon name="download" size={14} /> Export
          </Button>
        }
      />
      <ErrorNote message={error} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-xs">
          <Icon name="search" size={14} className="absolute top-2.5 left-2.5 text-ink-faint" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search by name, job or tag" placeholder="Search by name, job or tag" className="field !pl-8" />
        </div>
        <select aria-label="Filter by job" value={jobId} onChange={(event) => setJobId(event.target.value)} className="field !w-auto">
          <option value="all">All jobs</option>
          {data?.jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
        </select>
        <select aria-label="Filter by stage" value={stage} onChange={(event) => setStage(event.target.value)} className="field !w-auto">
          <option value="all">All stages</option>
          {stages.map((name) => <option key={name} value={name}>{titleCase(name)}</option>)}
        </select>
        <select aria-label="Sort" value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="field !w-auto">
          <option value="score">Highest score</option>
          <option value="name">Name</option>
          <option value="job">Job</option>
        </select>
        <button type="button" aria-pressed={onlyStarred} onClick={() => setOnlyStarred((value) => !value)} className={`flex h-8.5 items-center gap-1.5 rounded-lg border px-2.5 transition-colors ${onlyStarred ? "border-ochre bg-ochre-wash text-ochre" : "border-line-strong bg-surface hover:bg-plaster"}`}>
          <Icon name="star" size={14} /> Starred
        </button>
        <span className="tabular ml-auto text-ink-soft">{rows.length} people</span>
      </div>
      {selected.length > 0 ? (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-door-wash px-3 py-1.5">
          <span className="font-[520] text-door-deep">{selected.length} selected</span>
          <Button variant="secondary" size="sm" onClick={bulkTag}>Add tag</Button>
          <Button variant="quiet" size="sm" onClick={() => setSelected([])}>Clear</Button>
        </div>
      ) : null}
      {!data && !error ? <Loading rows={8} /> : null}
      {data ? (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
          <table className="w-full min-w-[820px] text-left">
            <thead className="text-[13px] text-ink-soft">
              <tr className="border-b border-line">
                <th className="w-9 py-2.5 pl-3.5"><input type="checkbox" aria-label="Select all" checked={selected.length > 0 && selected.length === rows.length} onChange={(event) => setSelected(event.target.checked ? rows.map((row) => row.application_id) : [])} className="accent-[var(--door)]" /></th>
                <th className="px-3 py-2.5 font-[500]">Candidate</th>
                <th className="px-3 py-2.5 font-[500]">Job</th>
                <th className="px-3 py-2.5 font-[500]">Stage</th>
                <th className="w-52 px-3 py-2.5 font-[500]">Evidence</th>
                <th className="px-4 py-2.5 text-right font-[500]">Score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.application_id} className="group row-hover cursor-pointer border-b border-line last:border-0" onClick={() => setOpenId(row.application_id)}>
                  <td className="py-2.5 pl-3.5" onClick={(event) => event.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${row.name}`} checked={selected.includes(row.application_id)} onChange={(event) => setSelected((list) => (event.target.checked ? [...list, row.application_id] : list.filter((id) => id !== row.application_id)))} className="accent-[var(--door)]" />
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="flex items-center gap-2.5">
                      <Avatar name={row.name ?? "?"} size={26} />
                      <span className="font-[520] group-hover:text-door">{row.name ?? "Unnamed"}</span>
                      {stars.includes(row.application_id) ? <Icon name="star" size={13} className="fill-current text-ochre" /> : null}
                      {flagText(row.flags).length ? <Tag tone="bloom">Attack removed</Tag> : null}
                      {(tags[row.application_id] ?? []).map((tag) => <Tag key={tag} tone="info">{tag}</Tag>)}
                    </span>
                  </td>
                  <td className="px-3 py-2.5" onClick={(event) => event.stopPropagation()}>
                    <Link href={`/jobs/${row.job_id}`} className="text-ink-soft hover:text-door">{row.job_title}</Link>
                  </td>
                  <td className="px-3 py-2.5"><Tag tone={STAGE_TONE[row.stage] ?? "neutral"}>{titleCase(row.stage)}</Tag></td>
                  <td className="px-3 py-2.5"><EvidenceStrip factors={row.factors} /></td>
                  <td className="tabular px-4 py-2.5 text-right text-[15px] font-[560]">{percent(row.score)}</td>
                </tr>
              ))}
              {rows.length === 0 ? <tr><td colSpan={6} className="p-10 text-center text-ink-soft">{data.candidates.length ? "Nobody matches these filters." : "Rank a job to see candidates here."}</td></tr> : null}
            </tbody>
          </table>
        </div>
      ) : null}
      <CandidateDrawer candidate={open} jobTitle={open?.job_title} interview={data?.interviews.find((item) => item.application_id === openId)} onClose={() => setOpenId(null)} onChanged={() => void reload()} />
    </>
  );
}
