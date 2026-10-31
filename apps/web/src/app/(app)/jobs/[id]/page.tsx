"use client";

import { useParams } from "next/navigation";
import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type ApiError,
  type CvStatus,
  get,
  type JobDetail,
  post,
  type RankedCandidate,
  type Shortlist,
  upload,
} from "@/lib/api";
import { EvidenceStrip } from "@/ui/EvidenceStrip";
import { WhyPanel } from "@/ui/WhyPanel";
import {
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  Tag,
  percent,
  withoutCitations,
} from "@/ui/kit";

const POLL_MS = 2500;

const FLAG_TEXT: Record<string, string> = {
  "hidden_text:invisible_colour": "Hidden white text was found and removed",
  "hidden_text:microscopic_font": "Microscopic text was found and removed",
  "hidden_text:off_page": "Text placed off the page was found and removed",
  "hidden_text:docx_hidden_run": "Hidden text was found and removed",
  instruction_override: "Contains instructions aimed at the AI",
  role_manipulation: "Tries to change the AI's role",
  ranking_manipulation: "Asks to be ranked higher",
  exfiltration: "Tries to extract or send data",
  tool_invocation: "Tries to trigger an action",
};

function flagText(flags: string[]): string[] {
  return [...new Set(flags.map((flag) => FLAG_TEXT[flag]).filter(Boolean))];
}

function CandidateRow({
  candidate,
  onWhy,
}: {
  candidate: RankedCandidate;
  onWhy: (candidate: RankedCandidate) => void;
}) {
  const warnings = flagText(candidate.flags);
  return (
    <li className="grid grid-cols-[2.5rem_1fr] gap-x-3 py-5 md:grid-cols-[3rem_1fr_7rem]">
      <p className="font-display text-2xl font-bold text-ink-soft tabular">{candidate.rank}</p>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold">{candidate.name ?? "Unnamed candidate"}</h3>
          {candidate.stage === "shortlisted" ? <Tag tone="good">Shortlisted</Tag> : null}
          {candidate.stage === "rejected" ? <Tag tone="bad">Rejected</Tag> : null}
          {candidate.parse_method === "ocr" ? <Tag>Scanned, read with OCR</Tag> : null}
        </div>
        <div className="mt-2">
          <EvidenceStrip factors={candidate.factors} />
        </div>
        {candidate.narrative ? <p className="mt-2 max-w-2xl">{withoutCitations(candidate.narrative)}</p> : null}
        {candidate.missing_must_haves.length > 0 ? (
          <p className="mt-1 text-ochre">
            Must-have without proof: {candidate.missing_must_haves.join(", ")}
          </p>
        ) : null}
        {warnings.map((warning) => (
          <p key={warning} className="mt-1 font-medium text-brick">
            {warning}
          </p>
        ))}
      </div>
      <div className="col-start-2 mt-3 flex items-center gap-4 md:col-start-3 md:mt-0 md:flex-col md:items-end md:gap-1">
        <p className="font-display text-3xl font-bold tabular">{percent(candidate.score)}</p>
        <Button
          variant="quiet"
          className="!px-0"
          disabled={!candidate.decision_record_id}
          onClick={() => onWhy(candidate)}
        >
          Why this score?
        </Button>
      </div>
    </li>
  );
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [cvs, setCvs] = useState<CvStatus[]>([]);
  const [list, setList] = useState<Shortlist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState<RankedCandidate | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const [nextCvs, nextList] = await Promise.all([
      get<CvStatus[]>(`/packs/talent/jobs/${id}/cvs`),
      get<Shortlist>(`/packs/talent/jobs/${id}/shortlist`),
    ]);
    setCvs(nextCvs);
    setList(nextList);
  }, [id]);

  useEffect(() => {
    get<JobDetail>(`/packs/talent/jobs/${id}`)
      .then(setJob)
      .catch((e: ApiError) => setError(e.message));
    refresh().catch((e: ApiError) => setError(e.message));
  }, [id, refresh]);

  const reading = cvs.filter((cv) => cv.status === "uploaded").length;
  const ready = cvs.filter((cv) => cv.status === "ready").length;
  const quarantined = cvs.filter((cv) => cv.status === "quarantined");
  const rankingActive = list?.ranking?.status === "requested" || list?.ranking?.status === "running";

  useEffect(() => {
    if (!reading && !rankingActive) return;
    const timer = setInterval(() => refresh().catch(() => undefined), POLL_MS);
    return () => clearInterval(timer);
  }, [reading, rankingActive, refresh]);

  async function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files?.length) return;
    const form = new FormData();
    for (const file of Array.from(files)) form.append("files", file);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await upload<{
        accepted: unknown[];
        rejected: { filename: string; reason: string }[];
      }>(`/packs/talent/jobs/${id}/cvs`, form);
      setNotice(`${result.accepted.length} uploaded. Reading them now.`);
      if (result.rejected.length) setError(result.rejected.map((r) => r.reason).join(" "));
      await refresh();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function startRanking() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await post(`/packs/talent/jobs/${id}/rankings`);
      await refresh();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (!job && !error) return <Loading />;
  const rubric = job?.rubrics.find((r) => r.id === job.active_rubric_id);
  const candidates = list?.candidates ?? [];

  return (
    <>
      <PageHeader
        title={job?.title ?? "Job"}
        subtitle={job?.description}
        action={
          <div className="flex flex-wrap gap-2">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept=".pdf,.docx,.txt"
              onChange={onFiles}
              className="sr-only"
              aria-label="Choose CV files"
            />
            <Button variant="secondary" disabled={busy} onClick={() => fileInput.current?.click()}>
              Upload CVs
            </Button>
            <Button disabled={busy || rankingActive || ready === 0} onClick={startRanking}>
              {rankingActive ? "Ranking…" : candidates.length ? "Rank again" : "Rank CVs"}
            </Button>
          </div>
        }
      />
      <ErrorNote message={error} />
      {notice ? (
        <p role="status" className="mb-4 rounded-md bg-door-wash px-3 py-2 text-door-deep">
          {notice}
        </p>
      ) : null}

      {rubric ? (
        <section aria-labelledby="criteria" className="mb-8">
          <h2 id="criteria" className="text-xl font-semibold">
            What counts for this job
          </h2>
          <p className="text-ink-soft">
            Approved criteria, version {rubric.version}, are worth 70 of the 100 points. The other 30 come from how closely the whole CV matches the job, by meaning and by exact terms.
          </p>
          <div className="mt-3 flex w-full gap-[3px]">
            {rubric.criteria.map((criterion) => (
              <div
                key={criterion.id}
                className="min-w-0"
                style={{ flexGrow: Number(criterion.weight), flexBasis: 0 }}
              >
                <div className={`h-3 rounded-[3px] ${criterion.must_have ? "bg-door-deep" : "bg-door"}`} />
                <p className="mt-1 truncate text-sm font-medium" title={criterion.label}>
                  {criterion.label}
                </p>
                <p className="tabular text-sm text-ink-soft">
                  {Math.round(Number(criterion.weight) * 100)}
                  {criterion.must_have ? ", required" : ""}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section aria-labelledby="ranked">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="ranked" className="text-xl font-semibold">
            Ranked candidates
          </h2>
          <p role="status" className="tabular text-ink-soft">
            {reading > 0 ? `Reading ${reading} of ${cvs.length} CVs… ` : `${ready} CVs read. `}
            {rankingActive ? "Ranking…" : ""}
          </p>
        </div>

        {candidates.length === 0 && !rankingActive ? (
          <div className="mt-4">
            <EmptyState title={ready ? "Ready to rank" : "No CVs read yet"}>
              {ready
                ? "Rank the CVs to see who best fits the approved criteria."
                : "Upload CVs to get started."}
            </EmptyState>
          </div>
        ) : null}

        <ul className={`mt-2 divide-y divide-line ${candidates.length ? "border-y border-line" : ""}`}>
          {candidates.map((candidate) => (
            <CandidateRow key={candidate.application_id} candidate={candidate} onWhy={setWhy} />
          ))}
        </ul>

        {quarantined.length > 0 ? (
          <div className="mt-6">
            <h3 className="font-semibold">Could not be read</h3>
            <ul className="mt-1 space-y-1">
              {quarantined.map((cv) => (
                <li key={cv.id}>
                  {cv.filename}: {cv.status_reason}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {why?.decision_record_id ? (
        <WhyPanel
          decisionId={why.decision_record_id}
          title={why.name ?? "Candidate"}
          onClose={() => setWhy(null)}
        />
      ) : null}
    </>
  );
}
