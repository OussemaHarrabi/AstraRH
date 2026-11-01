"use client";

import { AnimatePresence, motion } from "motion/react";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { type AgentRun, type ApiError, get, post, type Proposal, type Shortlist } from "@/lib/api";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { ago, Button, EmptyState, ErrorNote, Field, Loading, Modal, PageHeader, RiskTag, Tabs, Tag, titleCase, useLoad } from "@/ui/kit";
import { useToast } from "@/ui/Shell";
import { WhyBody } from "@/ui/WhyPanel";

const STATUS_TABS = [
  { id: "pending_approval", label: "Waiting" },
  { id: "approved", label: "Approved" },
  { id: "executed", label: "Done" },
  { id: "rejected", label: "Rejected" },
] as const;

function isEmail(payload: Record<string, unknown>): boolean {
  return typeof payload.to === "string" && typeof payload.body === "string";
}

function EmailEditor({ proposal, onSaved }: { proposal: Proposal; onSaved: () => void }) {
  const toast = useToast();
  const payload = proposal.payload as { to: string; subject: string; body: string; invite?: Record<string, unknown> };
  const [editing, setEditing] = useState(false);
  const pending = proposal.status === "pending_approval";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await post(`/trust/proposals/${proposal.id}/edit`, {
        payload: { ...proposal.payload, subject: form.get("subject"), body: form.get("body") },
        reason: "Edited by a person before approval",
      });
      setEditing(false);
      toast("Saved as a new version. Any earlier approval no longer applies.");
      onSaved();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  if (editing) {
    return (
      <form onSubmit={save} className="space-y-2.5 rounded-xl border border-door p-3.5 shadow-[0_0_0_3px_var(--door-wash)]">
        <p className="text-[13px] text-ink-soft">To {payload.to}</p>
        <Field label="Subject">
          <input name="subject" required defaultValue={payload.subject} className="field" />
        </Field>
        <Field label="Message">
          <textarea name="body" required rows={9} defaultValue={payload.body} className="field leading-relaxed" dir="auto" />
        </Field>
        <div className="flex gap-2">
          <Button type="submit">Save changes</Button>
          <Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </form>
    );
  }
  return (
    <div className="group relative rounded-xl border border-line p-3.5">
      <p className="text-[13px] text-ink-soft">To {payload.to}</p>
      <p className="mt-0.5 font-[560]">{payload.subject}</p>
      <p className="mt-2.5 whitespace-pre-wrap leading-relaxed" dir="auto">{payload.body}</p>
      {payload.invite ? (
        <p className="mt-2.5 flex items-center gap-1.5 text-[13px] text-ink-soft"><Icon name="calendar" size={14} /> Calendar invite attached</p>
      ) : null}
      {proposal.revision > 1 ? <p className="mt-2 text-[13px] text-ink-soft">Edited by a person, version {proposal.revision}.</p> : null}
      {pending ? (
        <Button variant="secondary" size="sm" className="absolute top-3 right-3" onClick={() => setEditing(true)}>Edit</Button>
      ) : null}
    </div>
  );
}

function PayloadSummary({ proposal }: { proposal: Proposal }) {
  const jobId = proposal.payload.job_id as string | undefined;
  const ids = proposal.payload.application_ids as string[] | undefined;
  const { data: names } = useLoad(async () => {
    if (!jobId || !ids) return null;
    const list = await get<Shortlist>(`/packs/talent/jobs/${jobId}/shortlist`);
    const byId = new Map(list.candidates.map((c) => [c.application_id, c.name ?? "Unnamed"]));
    return ids.map((id) => byId.get(id) ?? "Earlier ranking");
  }, [jobId, ids?.join()]);
  if (names) {
    return (
      <ol className="list-decimal space-y-0.5 rounded-xl border border-line py-3 pr-3 pl-8">
        {names.map((name) => <li key={name}>{name}</li>)}
      </ol>
    );
  }
  if (typeof proposal.payload.reason === "string") {
    return <p className="rounded-xl border border-line p-3.5">Reason given: {proposal.payload.reason}</p>;
  }
  const facts = Object.entries(proposal.payload).filter(([, value]) => typeof value === "string" || typeof value === "number").slice(0, 8);
  if (!facts.length) return null;
  return (
    <dl className="divide-y divide-line rounded-xl border border-line">
      {facts.map(([key, value]) => (
        <div key={key} className="flex gap-4 px-3.5 py-2">
          <dt className="w-32 shrink-0 text-ink-soft">{titleCase(key)}</dt>
          <dd className="min-w-0 break-words">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Review({ proposal, agentId, onChanged }: { proposal: Proposal; agentId?: string; onChanged: (id: string) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stepUp, setStepUp] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const agent = agentById(agentId ?? "agent");
  const pending = proposal.status === "pending_approval";

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await post(`/trust/proposals/${proposal.id}/approve`);
      toast(proposal.risk === "R3" ? "Your approval is recorded." : "Approved. It will run within seconds.");
      onChanged(proposal.id);
    } catch (e) {
      const failure = e as ApiError;
      if (failure.code === "step_up_required") setStepUp(true);
      else setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const password = new FormData(event.currentTarget).get("password");
    setBusy(true);
    setError(null);
    try {
      await post("/auth/step-up", { password });
      setStepUp(false);
      await approve();
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  async function reject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = new FormData(event.currentTarget).get("reason");
    setBusy(true);
    try {
      await post(`/trust/proposals/${proposal.id}/reject`, { reason });
      toast("Rejected. Nothing was sent.");
      setRejecting(false);
      onChanged(proposal.id);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto p-5">
        <div className="flex items-start gap-3">
          <Face agent={agent} size={40} mood={pending ? "waiting" : "happy"} track />
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-[560]">{proposal.summary}</h2>
            <p className="text-[13px] text-ink-soft">{agent.name}, {agent.role.toLowerCase()}, {ago(proposal.created_at)}</p>
          </div>
          <RiskTag risk={proposal.risk} />
        </div>
        <div className="mt-4">
          <ErrorNote message={error} />
          {isEmail(proposal.payload) ? <EmailEditor proposal={proposal} onSaved={() => onChanged("")} /> : <PayloadSummary proposal={proposal} />}
        </div>
        {proposal.risk === "R3" && pending ? (
          <p className="mt-3 flex items-center gap-2 rounded-lg bg-bloom-wash px-3 py-2 text-bloom">
            <Icon name="users" /> Needs two different people and a fresh password. The person who proposed it can&rsquo;t approve it.
          </p>
        ) : null}
        <button
          type="button"
          onClick={() => setShowWhy((value) => !value)}
          className="mt-5 flex items-center gap-1.5 font-[520] text-door hover:underline"
          aria-expanded={showWhy}
        >
          <motion.span animate={{ rotate: showWhy ? 90 : 0 }} className="inline-flex"><Icon name="chevron" size={14} /></motion.span>
          Why this suggestion?
        </button>
        <AnimatePresence initial={false}>
          {showWhy ? (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="pt-3"><WhyBody decisionId={proposal.decision_record_id} /></div>
            </motion.div>
          ) : null}
        </AnimatePresence>
        {proposal.payload_hash ? (
          <p className="tabular mt-5 flex items-center gap-1.5 text-[13px] text-ink-soft" title={proposal.payload_hash}>
            <Icon name="lock" size={13} /> Approval binds to this exact content: {proposal.payload_hash.slice(0, 12)}
          </p>
        ) : null}
      </div>
      {pending ? (
        <div className="border-t border-line bg-surface p-3">
          {rejecting ? (
            <form onSubmit={reject} className="flex flex-wrap items-end gap-2">
              <label className="min-w-56 flex-1">
                <span className="mb-1 block font-[520]">Why are you rejecting this?</span>
                <input name="reason" required autoFocus className="field" />
              </label>
              <Button type="submit" variant="danger" disabled={busy}>Reject</Button>
              <Button variant="secondary" onClick={() => setRejecting(false)}>Cancel</Button>
            </form>
          ) : (
            <div className="flex gap-2">
              <Button onClick={approve} disabled={busy}><Icon name="check" size={14} /> {busy ? "Approving…" : "Approve"}</Button>
              <Button variant="secondary" onClick={() => setRejecting(true)} disabled={busy}>Reject</Button>
            </div>
          )}
        </div>
      ) : null}
      <Modal open={stepUp} onClose={() => setStepUp(false)} label="Confirm your password" width={400}>
        <form onSubmit={confirmPassword} className="space-y-3 p-5">
          <h2 className="text-[17px] font-[560]">Confirm it&rsquo;s you</h2>
          <p className="text-ink-soft">This decision affects someone&rsquo;s job, so it needs your password again.</p>
          <ErrorNote message={error} />
          <Field label="Password">
            <input name="password" type="password" required autoFocus autoComplete="current-password" className="field" />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>Confirm and approve</Button>
            <Button variant="secondary" onClick={() => setStepUp(false)}>Cancel</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function ApprovalsInner() {
  const params = useSearchParams();
  const [status, setStatus] = useState<(typeof STATUS_TABS)[number]["id"]>("pending_approval");
  const [risk, setRisk] = useState<"all" | "R2" | "R3">("all");
  const [selected, setSelected] = useState<string | null>(params.get("id"));
  const { data, error, reload } = useLoad(async () => {
    const [proposals, runs] = await Promise.all([
      get<Proposal[]>(`/trust/proposals?status=${status}&limit=100`),
      get<AgentRun[]>("/ai/runs?limit=200").catch(() => [] as AgentRun[]),
    ]);
    return { proposals, agents: new Map(runs.map((run) => [run.id, run.agent])) };
  }, [status]);

  const visible = useMemo(
    () => (data?.proposals ?? []).filter((proposal) => risk === "all" || proposal.risk === risk),
    [data, risk],
  );
  const current = visible.find((proposal) => proposal.id === selected) ?? visible[0];

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
      if (event.key !== "j" && event.key !== "k") return;
      const index = visible.findIndex((proposal) => proposal.id === current?.id);
      const next = visible[index + (event.key === "j" ? 1 : -1)];
      if (next) setSelected(next.id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, current]);

  function changed(id: string) {
    if (id) {
      const index = visible.findIndex((proposal) => proposal.id === id);
      setSelected(visible[index + 1]?.id ?? visible[index - 1]?.id ?? null);
    }
    reload();
  }

  return (
    <>
      <PageHeader title="Approvals" subtitle="Agents can only suggest. Nothing here happens until a person approves it." />
      <Tabs tabs={STATUS_TABS.map((tab) => ({ id: tab.id, label: tab.label }))} value={status} onChange={(id) => { setStatus(id); setSelected(null); }} />
      <ErrorNote message={error} />
      <div className="mt-4 grid overflow-hidden rounded-xl border border-line bg-surface shadow-soft lg:h-[calc(100vh-232px)] lg:min-h-[520px] lg:grid-cols-[360px_1fr]">
        <div className="flex min-h-0 flex-col border-b border-line lg:border-r lg:border-b-0">
          <div className="flex items-center gap-1 border-b border-line p-2">
            {(["all", "R2", "R3"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRisk(value)}
                className={`h-7 rounded-md px-2 text-[13px] font-[520] transition-colors ${risk === value ? "bg-door-wash text-door-deep" : "text-ink-soft hover:bg-sunken"}`}
              >
                {value === "all" ? "All" : value === "R2" ? "One approver" : "Two people"}
              </button>
            ))}
            <span className="tabular ml-auto pr-1.5 text-[13px] text-ink-soft">{visible.length}</span>
          </div>
          <ul className="max-h-72 flex-1 overflow-y-auto lg:max-h-none">
            {!data ? <li className="p-4"><Loading /></li> : null}
            <AnimatePresence initial={false}>
              {visible.map((proposal) => {
                const agentId = data?.agents.get(proposal.agent_run_id ?? "");
                return (
                  <motion.li key={proposal.id} layout exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.18 }}>
                    <button
                      type="button"
                      onClick={() => setSelected(proposal.id)}
                      aria-current={current?.id === proposal.id}
                      className={`flex w-full gap-2.5 border-b border-line px-3 py-2.5 text-left transition-colors ${current?.id === proposal.id ? "bg-door-wash" : "hover:bg-plaster"}`}
                    >
                      <Face agent={agentById(agentId ?? "agent")} size={26} />
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-2 font-[500]">{proposal.summary}</span>
                        <span className="mt-1 flex items-center gap-1.5 text-[13px] text-ink-soft">
                          {proposal.risk === "R3" ? <Tag tone="bloom">Two people</Tag> : null}
                          {ago(proposal.created_at)}
                        </span>
                      </span>
                    </button>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        </div>
        <div className="min-h-0 min-w-0">
          {current ? (
            <Review key={`${current.id}-${current.revision}`} proposal={current} agentId={data?.agents.get(current.agent_run_id ?? "")} onChanged={changed} />
          ) : data ? (
            <EmptyState title={status === "pending_approval" ? "You're all caught up" : "Nothing here yet"} art={<Face agent={agentById("reply_drafter")} mood="happy" size={56} />}>
              {status === "pending_approval" ? "New suggestions from the agents appear here." : "Decisions appear here once they're made."}
            </EmptyState>
          ) : null}
        </div>
      </div>
      <p className="mt-2 hidden text-[13px] text-ink-soft lg:block">Press J and K to move through the list.</p>
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ApprovalsInner />
    </Suspense>
  );
}
