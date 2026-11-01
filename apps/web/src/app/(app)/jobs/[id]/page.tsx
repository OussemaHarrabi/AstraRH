"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { type ChangeEvent, type DragEvent, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { type ApiError, type Criterion, type CvStatus, get, type Interview, type JobDetail, post, type RankedCandidate, type Shortlist, upload } from "@/lib/api";
import { downloadCsv } from "@/lib/hiring";
import { EMPTY_MAP, useLocal } from "@/lib/local";
import { CandidateDrawer, flagText } from "@/ui/CandidateDrawer";
import { EvidenceStrip } from "@/ui/EvidenceStrip";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Avatar, Button, dayLabel, EmptyState, ErrorNote, Field, Loading, percent, Tabs, Tag, timeLabel, titleCase, useLoad, withoutCitations } from "@/ui/kit";
import { useToast } from "@/ui/Shell";

const POLL_MS = 2500;
type Tab = "ranked" | "pipeline" | "criteria" | "cvs" | "posting";

const COLUMNS = [
  { id: "applied", label: "Applied" },
  { id: "screen", label: "Phone screen" },
  { id: "shortlisted", label: "Shortlisted" },
  { id: "interview", label: "Interview" },
  { id: "offer", label: "Offer" },
];

function Ranked({ list, interviews, rankingActive, ready, onOpen, compare, setCompare }: { list: Shortlist | null; interviews: Interview[]; rankingActive: boolean; ready: number; onOpen: (candidate: RankedCandidate) => void; compare: string[]; setCompare: (ids: string[]) => void }) {
  const [query, setQuery] = useState("");
  const [mustOnly, setMustOnly] = useState(false);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const candidates = list?.candidates ?? [];
  const rows = candidates.filter(
    (candidate) =>
      (!query || (candidate.name ?? "").toLowerCase().includes(query.toLowerCase())) &&
      (!mustOnly || candidate.meets_must_haves) &&
      (!flaggedOnly || candidate.flagged),
  );
  if (candidates.length === 0) {
    return (
      <div className="mt-4 rounded-xl border border-line bg-surface">
        {rankingActive ? (
          <EmptyState title="Nour is ranking" art={<Face agent={agentById("ranking")} size={64} mood="working" />}>Scoring by formula and writing an explanation for each candidate.</EmptyState>
        ) : (
          <EmptyState title={ready ? "Ready to rank" : "No CVs read yet"} art={<Face agent={agentById("ranking")} size={64} mood="idle" track />}>
            {ready ? "Rank the CVs to see who best fits the approved criteria." : "Upload CVs and Idris will read them."}
          </EmptyState>
        )}
      </div>
    );
  }
  return (
    <>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1 sm:max-w-xs">
          <Icon name="search" size={14} className="absolute top-2.5 left-2.5 text-ink-faint" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search candidates" placeholder="Search candidates" className="field !pl-8" />
        </div>
        <label className="flex h-8.5 items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5"><input type="checkbox" checked={mustOnly} onChange={(event) => setMustOnly(event.target.checked)} className="accent-[var(--door)]" /> Meets all must-haves</label>
        <label className="flex h-8.5 items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5"><input type="checkbox" checked={flaggedOnly} onChange={(event) => setFlaggedOnly(event.target.checked)} className="accent-[var(--door)]" /> Attacks flagged</label>
        <Button variant="secondary" className="ml-auto" onClick={() => downloadCsv("shortlist.csv", [["Rank", "Name", "Score", "Stage", "Must-haves met"], ...rows.map((row) => [row.rank, row.name, percent(row.score), row.stage, row.meets_must_haves ? "yes" : "no"])])}>
          <Icon name="download" size={14} /> Export
        </Button>
      </div>
      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
        <ul>
          {rows.map((candidate) => {
            const warnings = flagText(candidate.flags);
            const interview = interviews.find((item) => item.application_id === candidate.application_id);
            const comparing = compare.includes(candidate.application_id);
            return (
              <motion.li layout key={candidate.application_id} className="group row-hover flex items-center gap-3 border-b border-line px-3.5 py-3 last:border-0">
                <input
                  type="checkbox"
                  checked={comparing}
                  aria-label={`Compare ${candidate.name}`}
                  onChange={() => setCompare(comparing ? compare.filter((id) => id !== candidate.application_id) : [...compare, candidate.application_id].slice(-3))}
                  className={`accent-[var(--door)] transition-opacity ${comparing ? "" : "opacity-0 group-hover:opacity-100 focus:opacity-100"}`}
                />
                <span className="tabular w-5 text-right text-ink-faint">{candidate.rank}</span>
                <Avatar name={candidate.name ?? "?"} size={32} />
                <button type="button" onClick={() => onOpen(candidate)} className="min-w-0 flex-1 text-left">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="font-[520] group-hover:text-door">{candidate.name ?? "Unnamed candidate"}</span>
                    {candidate.stage !== "applied" ? <Tag tone={candidate.stage === "rejected" ? "bad" : "good"}>{titleCase(candidate.stage)}</Tag> : null}
                    {candidate.parse_method === "ocr" ? <Tag>Scanned</Tag> : null}
                    {!candidate.meets_must_haves ? <Tag tone="warn">Missing {candidate.missing_must_haves[0]}</Tag> : null}
                    {warnings.length ? <Tag tone="bloom">Attack removed</Tag> : null}
                    {interview?.status === "booked" && interview.starts_at ? <Tag tone="info">{dayLabel(interview.starts_at)}, {timeLabel(interview.starts_at)}</Tag> : null}
                    {interview?.status === "slots_proposed" ? <Tag tone="info">Times held</Tag> : null}
                  </span>
                  {candidate.narrative ? <span className="mt-0.5 line-clamp-1 block text-ink-soft">{withoutCitations(candidate.narrative)}</span> : null}
                  <span className="mt-1.5 block max-w-xl"><EvidenceStrip factors={candidate.factors} /></span>
                </button>
                <span className="tabular w-10 text-right text-[20px] font-[520] tracking-tight">{percent(candidate.score)}</span>
              </motion.li>
            );
          })}
          {rows.length === 0 ? <li className="p-8 text-center text-ink-soft">No candidates match these filters.</li> : null}
        </ul>
      </div>
    </>
  );
}

function CompareTray({ list, ids, onClear, onOpen }: { list: Shortlist | null; ids: string[]; onClear: () => void; onOpen: () => void }) {
  return (
    <AnimatePresence>
      {ids.length > 0 ? (
        <motion.div initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 60, opacity: 0 }} className="fixed bottom-5 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2.5 rounded-2xl bg-night px-3 py-2 text-white shadow-float">
          {ids.map((id) => {
            const name = list?.candidates.find((candidate) => candidate.application_id === id)?.name ?? "?";
            return <Avatar key={id} name={name} size={24} />;
          })}
          <span>{ids.length} selected</span>
          <button type="button" onClick={onOpen} disabled={ids.length < 2} className="h-7 rounded-lg bg-[#5468f0] px-2.5 font-[520] disabled:opacity-50">Compare</button>
          <button type="button" onClick={onClear} className="text-white/70 hover:text-white">Clear</button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function Compare({ list, ids, onClose }: { list: Shortlist | null; ids: string[]; onClose: () => void }) {
  const chosen = ids.map((id) => list?.candidates.find((candidate) => candidate.application_id === id)).filter(Boolean) as RankedCandidate[];
  const keys = chosen[0]?.factors ?? [];
  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="font-[560]">Side by side</h2>
        <Button variant="quiet" size="sm" onClick={onClose}>Close</Button>
      </div>
      <table className="w-full min-w-[560px] text-left">
        <thead>
          <tr className="border-b border-line">
            <th className="px-4 py-2 font-[500] text-ink-soft">Criterion</th>
            {chosen.map((candidate) => <th key={candidate.application_id} className="px-4 py-2 font-[560]">{candidate.name} <span className="tabular font-[400] text-ink-soft">{percent(candidate.score)}</span></th>)}
          </tr>
        </thead>
        <tbody>
          {keys.map((factor) => (
            <tr key={factor.key} className="row-hover border-b border-line last:border-0">
              <td className="px-4 py-2 text-ink-soft">{factor.label}</td>
              {chosen.map((candidate) => {
                const value = Number(candidate.factors.find((item) => item.key === factor.key)?.value ?? 0);
                return (
                  <td key={candidate.application_id} className="px-4 py-2">
                    <span className="flex items-center gap-2">
                      <span className="relative h-1.5 w-20 rounded-full bg-sunken"><span className="absolute inset-y-0 left-0 rounded-full bg-door" style={{ width: `${value * 100}%` }} /></span>
                      <span className="tabular text-[13px]">{Math.round(value * 100)}%</span>
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pipeline({ list, onOpen }: { list: Shortlist | null; onOpen: (candidate: RankedCandidate) => void }) {
  const toast = useToast();
  const [placed, setPlaced] = useLocal<Record<string, string>>("pipeline.columns", EMPTY_MAP);
  const [over, setOver] = useState<string | null>(null);
  const candidates = (list?.candidates ?? []).filter((candidate) => candidate.stage !== "rejected" && candidate.stage !== "hired");
  const columnOf = (candidate: RankedCandidate) => {
    const own = placed[candidate.application_id];
    if (own) return own;
    return COLUMNS.some((column) => column.id === candidate.stage) ? candidate.stage : "applied";
  };
  function drop(event: DragEvent, column: string) {
    event.preventDefault();
    setOver(null);
    const id = event.dataTransfer.getData("text/plain");
    if (!id) return;
    setPlaced((all) => ({ ...all, [id]: column }));
    toast(`Moved to ${COLUMNS.find((item) => item.id === column)?.label}. Saved on this device.`);
  }
  return (
    <>
      <p className="mt-4 text-ink-soft">Drag people across your own working board. Official changes such as hire or reject still go through Approvals.</p>
      <div className="mt-3 flex gap-3 overflow-x-auto pb-3">
        {COLUMNS.map((column) => {
          const cards = candidates.filter((candidate) => columnOf(candidate) === column.id);
          return (
            <div
              key={column.id}
              onDragOver={(event) => { event.preventDefault(); setOver(column.id); }}
              onDragLeave={() => setOver(null)}
              onDrop={(event) => drop(event, column.id)}
              className={`w-64 shrink-0 rounded-xl border p-2 transition-colors ${over === column.id ? "border-door bg-door-wash" : "border-line bg-sunken/60"}`}
            >
              <p className="flex items-center justify-between px-1.5 pb-2 font-[560]">{column.label}<span className="tabular font-[400] text-ink-soft">{cards.length}</span></p>
              <ul className="max-h-[56vh] space-y-1.5 overflow-y-auto">
                {cards.map((candidate) => (
                  <li
                    key={candidate.application_id}
                    draggable
                    onDragStart={(event) => event.dataTransfer.setData("text/plain", candidate.application_id)}
                    onClick={() => onOpen(candidate)}
                    className="cursor-grab rounded-lg border border-line bg-surface p-2.5 shadow-soft transition-shadow hover:shadow-lift active:cursor-grabbing"
                  >
                    <span className="flex items-center gap-2">
                      <Avatar name={candidate.name ?? "?"} size={22} />
                      <span className="min-w-0 flex-1 truncate font-[520]">{candidate.name}</span>
                      <span className="tabular font-[560]">{percent(candidate.score)}</span>
                    </span>
                    <span className="mt-2 block"><EvidenceStrip factors={candidate.factors} /></span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </>
  );
}

function Criteria({ job, onChanged }: { job: JobDetail; onChanged: () => void }) {
  const toast = useToast();
  const latest = job.rubrics[0];
  const active = job.rubrics.find((rubric) => rubric.id === job.active_rubric_id);
  const base = latest ?? active;
  const [draft, setDraft] = useState<Criterion[] | null>(null);
  const criteria = draft ?? base?.criteria ?? [];
  const sum = criteria.reduce((total, criterion) => total + Number(criterion.weight), 0);

  if (!base) {
    return (
      <div className="mt-4 rounded-xl border border-line bg-surface">
        <EmptyState title="Mira is drafting the criteria" art={<Face agent={agentById("rubric_builder")} size={64} mood="working" />}>They appear here for you to edit and approve.</EmptyState>
      </div>
    );
  }

  function update(index: number, patch: Partial<Criterion>) {
    setDraft(criteria.map((criterion, position) => (position === index ? { ...criterion, ...patch } : criterion)));
  }

  async function save() {
    try {
      await post(`/packs/talent/jobs/${job.id}/rubrics`, { criteria });
      setDraft(null);
      toast("Saved as a new draft. Approve it to use it for ranking.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  async function activate() {
    try {
      await post(`/packs/talent/jobs/${job.id}/rubrics/${base.id}/activate`);
      toast("Criteria approved. Ranking will use this version.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-line bg-surface shadow-soft">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <Face agent={agentById("rubric_builder")} size={32} track />
        <div className="min-w-0 flex-1">
          <p className="font-[560]">Version {base.version}, {base.status === "active" ? "approved" : "draft"}</p>
          <p className="text-ink-soft">These are worth 70 of 100 points. The other 30 come from how closely the whole CV matches the job.</p>
        </div>
        {draft ? (
          <>
            <span className={`tabular text-[13px] ${Math.abs(sum - 1) > 0.001 ? "text-brick" : "text-ink-soft"}`}>Weights total {Math.round(sum * 100)}%</span>
            <Button onClick={save} disabled={Math.abs(sum - 1) > 0.001}>Save as draft</Button>
            <Button variant="secondary" onClick={() => setDraft(null)}>Discard</Button>
          </>
        ) : base.status !== "active" ? (
          <Button onClick={activate}><Icon name="check" size={14} /> Approve criteria</Button>
        ) : <Tag tone="good">In use</Tag>}
      </div>
      <div className="flex gap-[2px] px-4 pt-3">
        {criteria.map((criterion) => (
          <div key={criterion.id} title={criterion.label} className={`h-2 rounded-[3px] ${criterion.must_have ? "bg-door-deep" : "bg-door opacity-60"}`} style={{ flexGrow: Number(criterion.weight), flexBasis: 0 }} />
        ))}
      </div>
      <ul className="p-2">
        {criteria.map((criterion, index) => (
          <li key={criterion.id} className="row-hover grid grid-cols-[minmax(0,1fr)] items-center gap-3 rounded-lg px-2 py-2 md:grid-cols-[1fr_190px_110px]">
            <div className="min-w-0">
              <p className="font-[520]">{criterion.label}</p>
              {criterion.description ? <p className="truncate text-ink-soft">{criterion.description}</p> : null}
            </div>
            <label className="flex items-center gap-2">
              <span className="sr-only">Weight of {criterion.label}</span>
              <input type="range" min={0} max={50} step={1} value={Math.round(Number(criterion.weight) * 100)} onChange={(event) => update(index, { weight: (Number(event.target.value) / 100).toFixed(2) })} className="w-full accent-[var(--door)]" />
              <span className="tabular w-9 text-right">{Math.round(Number(criterion.weight) * 100)}%</span>
            </label>
            <label className="flex items-center gap-1.5 justify-self-end">
              <input type="checkbox" checked={Boolean(criterion.must_have)} onChange={(event) => update(index, { must_have: event.target.checked })} className="accent-[var(--door)]" /> Must-have
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CvList({ cvs, busy, onFiles, onPicked }: { cvs: CvStatus[]; busy: boolean; onFiles: (files: FileList) => void; onPicked: (event: ChangeEvent<HTMLInputElement>) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div className="mt-4 space-y-4">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(event) => { event.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => { event.preventDefault(); setOver(false); onFiles(event.dataTransfer.files); }}
        disabled={busy}
        className={`flex w-full flex-col items-center rounded-xl border border-dashed p-8 transition-colors ${over ? "border-door bg-door-wash" : "border-line-strong bg-surface hover:border-door"}`}
      >
        <Face agent={agentById("cv_reader")} size={48} mood={busy ? "working" : "idle"} track />
        <span className="mt-2 font-[560]">{busy ? "Uploading…" : "Drop CVs here, or click to choose"}</span>
        <span className="text-ink-soft">PDF, DOCX, HTML, Markdown or text, up to 20 MB each</span>
      </button>
      <input ref={input} type="file" multiple accept=".pdf,.docx,.html,.md,.txt" onChange={onPicked} className="sr-only" aria-label="Choose CV files" />
      <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
        <ul>
          {cvs.map((cv) => (
            <li key={cv.id} className="row-hover flex items-center gap-2.5 border-b border-line px-4 py-2 last:border-0">
              <Icon name="file" className="text-ink-faint" />
              <span className="min-w-0 flex-1 truncate">{cv.filename}</span>
              {cv.status_reason ? <span className="truncate text-ink-soft">{cv.status_reason}</span> : null}
              {cv.flagged ? <Tag tone="bloom">Attack removed</Tag> : null}
              <Tag tone={cv.status === "ready" ? "good" : cv.status === "quarantined" ? "bad" : "info"}>{cv.status === "uploaded" ? "Reading" : titleCase(cv.status)}</Tag>
            </li>
          ))}
          {cvs.length === 0 ? <li className="p-8 text-center text-ink-soft">No CVs uploaded yet.</li> : null}
        </ul>
      </div>
    </div>
  );
}

function Posting({ job }: { job: JobDetail }) {
  const toast = useToast();
  const [live, setLive] = useLocal<Record<string, boolean>>("job.published", EMPTY_MAP);
  const published = Boolean(live[job.id]);
  const link = typeof window === "undefined" ? "" : `${window.location.origin}/careers/${job.id}`;
  return (
    <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[1fr_320px]">
      <article className="rounded-xl border border-line bg-surface p-6 shadow-soft">
        <p className="text-ink-soft">CDS Tunis</p>
        <h2 className="mt-1 text-[24px] font-[520]">{job.title}</h2>
        <p className="mt-4 max-w-prose text-[15px] leading-relaxed whitespace-pre-wrap">{job.description}</p>
        <p className="mt-5 rounded-lg bg-plaster p-3 text-ink-soft">Apply by emailing your CV to hr@cds.example.test with {job.external_id ?? job.title} in the subject. Idris reads it automatically.</p>
      </article>
      <aside className="h-fit space-y-3 rounded-xl border border-line bg-surface p-4 shadow-soft">
        <p className="font-[560]">Publishing</p>
        <label className="flex items-center justify-between gap-3">
          <span>{published ? "Shown on the careers page" : "Not published"}</span>
          <input type="checkbox" role="switch" checked={published} onChange={(event) => { setLive((all) => ({ ...all, [job.id]: event.target.checked })); toast(event.target.checked ? "Marked as published on this device." : "Unpublished."); }} className="size-4 accent-[var(--door)]" />
        </label>
        <Field label="Share link" hint="A preview until the careers page is connected.">
          <input readOnly value={link} className="field text-ink-soft" onFocus={(event) => event.target.select()} />
        </Field>
        <Button variant="secondary" className="w-full" onClick={() => { void navigator.clipboard?.writeText(link); toast("Link copied."); }}>Copy link</Button>
      </aside>
    </div>
  );
}

function JobInner() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) ?? "ranked");
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const jobLoad = useLoad(() => get<JobDetail>(`/packs/talent/jobs/${id}`), [id]);
  const { data, error, reload } = useLoad(async () => {
    const [cvs, list, interviews] = await Promise.all([
      get<CvStatus[]>(`/packs/talent/jobs/${id}/cvs`),
      get<Shortlist>(`/packs/talent/jobs/${id}/shortlist`),
      get<Interview[]>(`/packs/talent/jobs/${id}/interviews`),
    ]);
    return { cvs, list, interviews };
  }, [id]);

  const job = jobLoad.data;
  const cvs = useMemo(() => data?.cvs ?? [], [data]);
  const list = data?.list ?? null;
  const interviews = useMemo(() => data?.interviews ?? [], [data]);
  const reading = cvs.filter((cv) => cv.status === "uploaded").length;
  const ready = cvs.filter((cv) => cv.status === "ready").length;
  const rankingActive = list?.ranking?.status === "requested" || list?.ranking?.status === "running";
  const needsPolling = reading > 0 || rankingActive || interviews.some((item) => item.status === "requested");

  useEffect(() => {
    if (!needsPolling) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [needsPolling, reload]);

  useEffect(() => {
    if (job && job.rubrics.length === 0) {
      const timer = setInterval(() => void jobLoad.reload(), POLL_MS);
      return () => clearInterval(timer);
    }
  }, [job, jobLoad]);

  async function sendFiles(files: FileList) {
    if (!files.length) return;
    const form = new FormData();
    for (const file of Array.from(files)) form.append("files", file);
    setBusy(true);
    try {
      const result = await upload<{ accepted: unknown[]; rejected: { filename: string; reason: string }[] }>(`/packs/talent/jobs/${id}/cvs`, form);
      toast(`${result.accepted.length} uploaded. Idris is reading them.`);
      if (result.rejected.length) toast(result.rejected.map((item) => item.reason).join(" "), "bad");
      await reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function startRanking() {
    setBusy(true);
    try {
      await post(`/packs/talent/jobs/${id}/rankings`);
      toast("Nour is ranking. Scores come from the formula, not from the model.");
      setTab("ranked");
      await reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function checkFollowups() {
    try {
      await post("/packs/talent/followups/check");
      toast("Tarek checked for quiet candidates. Any reminders are in Approvals.");
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  if (jobLoad.error) return <ErrorNote message={jobLoad.error} />;
  if (!job) return <Loading rows={6} />;

  const open = list?.candidates.find((candidate) => candidate.application_id === openId) ?? null;
  const rubric = job.rubrics.find((item) => item.id === job.active_rubric_id);

  return (
    <>
      <Link href="/jobs" className="text-ink-soft hover:text-ink">Jobs</Link>
      <header className="mt-1 mb-4 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] font-[520]">{job.title}</h1>
          <p role="status" className="tabular mt-0.5 text-ink-soft">
            {reading > 0 ? `Idris is reading ${reading} of ${cvs.length} CVs` : `${ready} CVs read`}
            {list?.candidates.length ? `, ${list.candidates.length} ranked` : ""}
            {rankingActive ? ", Nour is ranking" : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={checkFollowups}>Check for quiet candidates</Button>
          <Button disabled={busy || rankingActive || ready === 0 || !job.active_rubric_id} onClick={startRanking}>
            <Icon name="sparkle" size={14} /> {rankingActive ? "Ranking…" : list?.candidates.length ? "Rank again" : "Rank CVs"}
          </Button>
        </div>
      </header>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "ranked", label: "Ranked", count: list?.candidates.length },
          { id: "pipeline", label: "Pipeline" },
          { id: "criteria", label: "Criteria" },
          { id: "cvs", label: "CVs", count: cvs.length },
          { id: "posting", label: "Job post" },
        ]}
      />
      <ErrorNote message={error} />
      {comparing ? <Compare list={list} ids={compare} onClose={() => setComparing(false)} /> : null}
      {tab === "ranked" ? <Ranked list={list} interviews={interviews} rankingActive={rankingActive} ready={ready} onOpen={(candidate) => setOpenId(candidate.application_id)} compare={compare} setCompare={setCompare} /> : null}
      {tab === "pipeline" ? <Pipeline list={list} onOpen={(candidate) => setOpenId(candidate.application_id)} /> : null}
      {tab === "criteria" ? <Criteria key={job.rubrics.length} job={job} onChanged={() => void jobLoad.reload()} /> : null}
      {tab === "cvs" ? <CvList cvs={cvs} busy={busy} onFiles={sendFiles} onPicked={(event) => { if (event.target.files) void sendFiles(event.target.files); event.target.value = ""; }} /> : null}
      {tab === "posting" ? <Posting job={job} /> : null}
      <CompareTray list={list} ids={comparing ? [] : compare} onClear={() => setCompare([])} onOpen={() => setComparing(true)} />
      <CandidateDrawer
        candidate={open}
        jobTitle={job.title}
        rubric={rubric}
        interview={interviews.find((item) => item.application_id === openId)}
        onClose={() => setOpenId(null)}
        onChanged={() => void reload()}
      />
    </>
  );
}

export default function JobPage() {
  return (
    <Suspense fallback={<Loading />}>
      <JobInner />
    </Suspense>
  );
}
