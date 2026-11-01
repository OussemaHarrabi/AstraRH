"use client";

import { type FormEvent, useState } from "react";
import { type ApiError, get, type Interview, post, type RankedCandidate, type Rubric } from "@/lib/api";
import { EMPTY_LIST, EMPTY_MAP, newId, type Note, type Scorecard, useLocal } from "@/lib/local";
import { agentById, Face } from "./Face";
import { Icon } from "./Icon";
import { ago, Avatar, Button, dayLabel, Drawer, ErrorNote, Field, Loading, Modal, percent, Tabs, Tag, timeLabel, titleCase, useLoad } from "./kit";
import { useMe, useToast } from "./Shell";
import { WhyBody } from "./WhyPanel";

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

export function flagText(flags: string[]): string[] {
  return [...new Set(flags.map((flag) => FLAG_TEXT[flag]).filter(Boolean))];
}

interface Profile {
  blind_text: string | null;
  profile: { skills?: { name: string; years: number | null }[]; roles?: { title: string; start_year?: number; end_year?: number }[] } | null;
  removed_spans: unknown[];
  hidden_text_chars: number | null;
  flags: string[];
}

export type Tab = "evidence" | "cv" | "notes" | "scorecards";

const RATING_AREAS = ["Technical depth", "Problem solving", "Communication", "Team fit"];
const VERDICTS = { advance: { label: "Move forward", tone: "good" }, hold: { label: "Unsure", tone: "warn" }, no: { label: "Don't move forward", tone: "bad" } } as const;

function Notes({ id }: { id: string }) {
  const me = useMe();
  const [notes, setNotes] = useLocal<Record<string, Note[]>>("candidate.notes", EMPTY_MAP);
  const list = notes[id] ?? EMPTY_LIST;
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const text = String(new FormData(form).get("text")).trim();
    if (!text) return;
    setNotes((all) => ({ ...all, [id]: [{ id: newId(), author: me?.display_name ?? "You", text, at: new Date().toISOString() }, ...(all[id] ?? [])] }));
    form.reset();
  }
  return (
    <div className="space-y-3">
      <form onSubmit={add} className="space-y-2">
        <textarea name="text" rows={3} required aria-label="Add a note" placeholder="Add a note for your team" className="field" />
        <Button type="submit" size="sm">Add note</Button>
      </form>
      <ul className="space-y-2">
        {list.map((note) => (
          <li key={note.id} className="rounded-lg bg-plaster p-3">
            <p className="flex items-center gap-2 text-[13px] text-ink-soft"><Avatar name={note.author} size={18} /> {note.author}, {ago(note.at)}</p>
            <p className="mt-1 whitespace-pre-wrap">{note.text}</p>
          </li>
        ))}
        {list.length === 0 ? <li className="py-4 text-center text-ink-soft">No notes yet.</li> : null}
      </ul>
    </div>
  );
}

function Scorecards({ id }: { id: string }) {
  const me = useMe();
  const toast = useToast();
  const [cards, setCards] = useLocal<Record<string, Scorecard[]>>("candidate.scorecards", EMPTY_MAP);
  const list = cards[id] ?? EMPTY_LIST;
  const [ratings, setRatings] = useState<Record<string, number>>({});
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const card: Scorecard = {
      id: newId(),
      author: me?.display_name ?? "You",
      ratings,
      verdict: data.get("verdict") as Scorecard["verdict"],
      summary: String(data.get("summary")),
      at: new Date().toISOString(),
    };
    setCards((all) => ({ ...all, [id]: [card, ...(all[id] ?? [])] }));
    setRatings({});
    form.reset();
    toast("Scorecard saved. It informs the decision and never changes the AI score.");
  }
  return (
    <div className="space-y-4">
      <form onSubmit={add} className="space-y-3 rounded-xl border border-line p-3.5">
        <p className="font-[560]">Interview scorecard</p>
        {RATING_AREAS.map((area) => (
          <div key={area} className="flex items-center justify-between gap-3">
            <span>{area}</span>
            <span className="flex gap-1">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-label={`${area}: ${value} of 5`}
                  onClick={() => setRatings((all) => ({ ...all, [area]: value }))}
                  className={`size-6 rounded-md text-[13px] font-[520] transition-colors ${(ratings[area] ?? 0) >= value ? "bg-door text-white" : "bg-sunken text-ink-soft hover:bg-line"}`}
                >
                  {value}
                </button>
              ))}
            </span>
          </div>
        ))}
        <Field label="Your recommendation">
          <select name="verdict" className="field" defaultValue="advance">
            {Object.entries(VERDICTS).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
          </select>
        </Field>
        <Field label="Summary">
          <textarea name="summary" rows={2} required className="field" />
        </Field>
        <Button type="submit" size="sm">Save scorecard</Button>
      </form>
      <ul className="space-y-2">
        {list.map((card) => (
          <li key={card.id} className="rounded-lg bg-plaster p-3">
            <p className="flex items-center gap-2 text-[13px] text-ink-soft">
              <Avatar name={card.author} size={18} /> {card.author}, {ago(card.at)}
              <span className="ml-auto"><Tag tone={VERDICTS[card.verdict].tone}>{VERDICTS[card.verdict].label}</Tag></span>
            </p>
            <p className="mt-1">{card.summary}</p>
            <p className="tabular mt-1 text-[13px] text-ink-soft">{Object.entries(card.ratings).map(([area, value]) => `${area} ${value}/5`).join(", ")}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CvText({ id }: { id: string }) {
  const { data, error } = useLoad(() => get<Profile>(`/packs/talent/applications/${id}/profile`), [id]);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Loading rows={6} />;
  const warnings = flagText(data.flags);
  return (
    <div className="space-y-4">
      {warnings.map((warning) => (
        <p key={warning} className="flex items-center gap-2 rounded-lg bg-bloom-wash px-3 py-2 font-[520] text-bloom"><Icon name="alert" /> {warning}</p>
      ))}
      {data.hidden_text_chars ? <p className="text-ink-soft">{data.hidden_text_chars} hidden characters were deleted from the file before reading.</p> : null}
      {data.profile?.skills?.length ? (
        <section>
          <h3 className="font-[560]">Skills the AI found, each with a quote</h3>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {data.profile.skills.map((skill) => <Tag key={skill.name}>{skill.name}{skill.years ? `, ${skill.years}y` : ""}</Tag>)}
          </div>
        </section>
      ) : null}
      {data.profile?.roles?.length ? (
        <section>
          <h3 className="font-[560]">Roles</h3>
          <ul className="mt-1.5 space-y-0.5">
            {data.profile.roles.map((role) => (
              <li key={`${role.title}-${role.start_year}`} className="flex justify-between gap-3"><span>{role.title}</span><span className="tabular text-ink-soft">{role.start_year} to {role.end_year ?? "now"}</span></li>
            ))}
          </ul>
        </section>
      ) : null}
      <section>
        <h3 className="flex items-center gap-1.5 font-[560]"><Face agent={agentById("cv_reader")} size={20} /> What Idris read, with identity hidden</h3>
        <pre className="mt-1.5 max-h-96 overflow-y-auto rounded-lg bg-plaster p-3 font-sans leading-relaxed whitespace-pre-wrap" dir="auto">{data.blind_text}</pre>
      </section>
    </div>
  );
}

function OverrideForm({ candidate, rubric, onDone, onClose }: { candidate: RankedCandidate; rubric?: Rubric; onDone: () => void; onClose: () => void }) {
  const toast = useToast();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await post(`/packs/talent/applications/${candidate.application_id}/overrides`, {
        criterion_id: form.get("criterion"),
        value: Number(form.get("value")) / 100,
        reason: form.get("reason"),
      });
      toast("Correction saved. It applies on the next ranking.");
      onDone();
      onClose();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  const criteria = candidate.factors.filter((factor) => factor.key !== "job_match");
  return (
    <Modal open onClose={onClose} label="Correct a criterion" width={420}>
      <form onSubmit={save} className="space-y-3 p-5">
        <h2 className="text-[17px] font-[560]">Correct a criterion</h2>
        <p className="text-ink-soft">You know something the CV doesn&rsquo;t say. Your correction and reason stay in the record.</p>
        <Field label="Criterion">
          <select name="criterion" className="field">
            {criteria.map((factor) => <option key={factor.key} value={factor.key}>{rubric?.criteria.find((c) => c.id === factor.key)?.label ?? factor.label}</option>)}
          </select>
        </Field>
        <Field label="Proven, in percent">
          <input name="value" type="number" min={0} max={100} defaultValue={100} required className="field" />
        </Field>
        <Field label="Reason">
          <input name="reason" required className="field" placeholder="Confirmed during the phone call" />
        </Field>
        <div className="flex gap-2">
          <Button type="submit">Save correction</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

function DecisionForm({ kind, candidate, onDone, onClose }: { kind: "reject" | "hire"; candidate: RankedCandidate; onDone: () => void; onClose: () => void }) {
  const toast = useToast();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = new FormData(event.currentTarget).get("reason");
    try {
      await post(`/packs/talent/applications/${candidate.application_id}/${kind}`, { reason });
      toast(`Proposal created. A second person must approve this ${kind === "hire" ? "hire" : "rejection"}.`);
      onDone();
      onClose();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <Modal open onClose={onClose} label={kind === "hire" ? "Propose hiring" : "Propose rejection"} width={420}>
      <form onSubmit={save} className="space-y-3 p-5">
        <h2 className="text-[17px] font-[560]">{kind === "hire" ? "Propose hiring" : "Propose rejecting"} {candidate.name}</h2>
        <p className="text-ink-soft">This decision takes two people. It goes to Approvals, where a different HR person confirms it with their password.</p>
        <Field label="Reason">
          <textarea name="reason" rows={3} required className="field" />
        </Field>
        <div className="flex gap-2">
          <Button type="submit" variant={kind === "hire" ? "primary" : "danger"}>{kind === "hire" ? "Propose hiring" : "Propose rejection"}</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

function InterviewCard({ interview, onChanged }: { interview: Interview; onChanged: () => void }) {
  const toast = useToast();
  async function book(slot: { starts_at: string; ends_at: string }) {
    try {
      await post(`/packs/talent/interviews/${interview.id}/book`, slot);
      toast("Booking sent to Approvals.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  async function cancel(reschedule: boolean) {
    try {
      await post(`/packs/talent/interviews/${interview.id}/cancel`, { reason: reschedule ? "Rescheduled by the recruiter" : "Cancelled by the recruiter", reschedule });
      toast(reschedule ? "Move sent to Approvals." : "Cancellation sent to Approvals.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-center gap-2">
        <Face agent={agentById("scheduler")} size={24} mood={interview.status === "requested" ? "working" : "idle"} />
        <p className="flex-1 font-[520]">
          {interview.status === "booked" && interview.starts_at
            ? `Interview on ${dayLabel(interview.starts_at)} at ${timeLabel(interview.starts_at)}`
            : interview.status === "requested"
              ? "Dali is looking for free times"
              : interview.status === "slots_proposed"
                ? "Three times held for 72 hours"
                : titleCase(interview.status)}
        </p>
      </div>
      {interview.status === "slots_proposed" ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {interview.slots.map((slot) => (
            <Button key={slot.starts_at} variant="secondary" size="sm" onClick={() => book(slot)}>{dayLabel(slot.starts_at)}, {timeLabel(slot.starts_at)}</Button>
          ))}
        </div>
      ) : null}
      {interview.status === "booked" ? (
        <div className="mt-2 flex gap-1.5">
          <Button variant="secondary" size="sm" onClick={() => cancel(true)}>Reschedule</Button>
          <Button variant="quiet" size="sm" onClick={() => cancel(false)}>Cancel interview</Button>
        </div>
      ) : null}
    </div>
  );
}

export function CandidateDrawer({
  candidate,
  jobTitle,
  interview,
  rubric,
  onClose,
  onChanged,
}: {
  candidate: RankedCandidate | null;
  jobTitle?: string;
  interview?: Interview;
  rubric?: Rubric;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("evidence");
  const [decision, setDecision] = useState<"reject" | "hire" | null>(null);
  const [override, setOverride] = useState(false);
  const [stars, setStars] = useLocal<string[]>("candidate.stars", EMPTY_LIST);
  const [tags, setTags] = useLocal<Record<string, string[]>>("candidate.tags", EMPTY_MAP);

  if (!candidate) return <Drawer open={false} onClose={onClose} label="Candidate">{null}</Drawer>;
  const id = candidate.application_id;
  const starred = stars.includes(id);
  const myTags = tags[id] ?? EMPTY_LIST;
  const closed = candidate.stage === "rejected" || candidate.stage === "hired";

  async function requestInterview() {
    try {
      await post(`/packs/talent/applications/${id}/interviews`, {});
      toast("Dali is finding free times. The invitation will come to Approvals.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  return (
    <Drawer open onClose={onClose} label={candidate.name ?? "Candidate"} width={680}>
      <div className="sticky top-0 z-10 border-b border-line bg-surface px-5 pt-4">
        <div className="flex items-start gap-3">
          <Avatar name={candidate.name ?? "Candidate"} size={44} />
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-1.5 text-[19px] font-[560]">
              {candidate.name ?? "Unnamed candidate"}
              <button type="button" aria-pressed={starred} aria-label="Star this candidate" onClick={() => setStars((all) => (starred ? all.filter((value) => value !== id) : [...all, id]))} className={`rounded p-0.5 ${starred ? "text-ochre" : "text-ink-faint hover:text-ink"}`}>
                <Icon name="star" size={15} className={starred ? "fill-current" : ""} />
              </button>
            </h2>
            <p className="text-ink-soft">
              {jobTitle ? `${jobTitle}, ` : ""}rank {candidate.rank}, {titleCase(candidate.stage)}
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              {myTags.map((tag) => (
                <button key={tag} type="button" title="Remove tag" onClick={() => setTags((all) => ({ ...all, [id]: myTags.filter((value) => value !== tag) }))}>
                  <Tag tone="info">{tag}</Tag>
                </button>
              ))}
              <input
                aria-label="Add a tag"
                placeholder="Add tag"
                className="h-5 w-16 rounded bg-transparent px-1 text-xs outline-none placeholder:text-ink-faint focus:w-24 focus:bg-sunken"
                onKeyDown={(event) => {
                  const value = event.currentTarget.value.trim();
                  if (event.key === "Enter" && value) {
                    setTags((all) => ({ ...all, [id]: [...new Set([...(all[id] ?? []), value])] }));
                    event.currentTarget.value = "";
                  }
                }}
              />
            </div>
          </div>
          <p className="tabular text-[30px] leading-none font-[520] tracking-tight">{percent(candidate.score)}</p>
          <Button variant="quiet" size="sm" aria-label="Close" onClick={onClose}><Icon name="close" size={14} /></Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {!closed && !interview ? <Button size="sm" onClick={requestInterview}><Icon name="calendar" size={13} /> Propose interview times</Button> : null}
          {!closed ? <Button size="sm" variant="secondary" onClick={() => setDecision("hire")}>Propose hire</Button> : null}
          {!closed ? <Button size="sm" variant="danger" onClick={() => setDecision("reject")}>Propose rejection</Button> : null}
          <Button size="sm" variant="quiet" onClick={() => setOverride(true)}>Correct a criterion</Button>
        </div>
        <div className="mt-2">
          <Tabs
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "evidence", label: "Why this score" },
              { id: "cv", label: "CV as read" },
              { id: "notes", label: "Notes" },
              { id: "scorecards", label: "Scorecards" },
            ]}
          />
        </div>
      </div>
      <div className="space-y-4 p-5">
        {interview ? <InterviewCard interview={interview} onChanged={onChanged} /> : null}
        {flagText(candidate.flags).map((warning) => (
          <p key={warning} className="flex items-center gap-2 rounded-lg bg-bloom-wash px-3 py-2 font-[520] text-bloom"><Icon name="alert" /> {warning}</p>
        ))}
        {tab === "evidence" ? (candidate.decision_record_id ? <WhyBody decisionId={candidate.decision_record_id} /> : <p className="text-ink-soft">No explanation is recorded for this candidate yet.</p>) : null}
        {tab === "cv" ? <CvText id={id} /> : null}
        {tab === "notes" ? <Notes id={id} /> : null}
        {tab === "scorecards" ? <Scorecards id={id} /> : null}
      </div>
      {decision ? <DecisionForm kind={decision} candidate={candidate} onDone={onChanged} onClose={() => setDecision(null)} /> : null}
      {override ? <OverrideForm candidate={candidate} rubric={rubric} onDone={onChanged} onClose={() => setOverride(false)} /> : null}
    </Drawer>
  );
}
