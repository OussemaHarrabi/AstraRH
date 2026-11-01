"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { type AgentRun, type AgentRunDetail, get, type Proposal } from "@/lib/api";
import { moodsFrom } from "@/lib/hiring";
import { AGENTS, type Agent, agentById, Face, type Mood } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { ago, Button, Drawer, ErrorNote, Loading, PageHeader, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";

const MOOD_TEXT: Record<Mood, { label: string; tone: Tone }> = {
  idle: { label: "Ready", tone: "neutral" },
  working: { label: "Working", tone: "info" },
  waiting: { label: "Waiting for you", tone: "bloom" },
  alert: { label: "Needs a look", tone: "bad" },
  asleep: { label: "No runs yet", tone: "neutral" },
  happy: { label: "Done", tone: "good" },
};

const STATUS_TONE: Record<string, Tone> = { succeeded: "good", failed: "bad", running: "info", pending: "info" };

function RunDetail({ id }: { id: string }) {
  const { data, error } = useLoad(() => get<AgentRunDetail>(`/ai/runs/${id}`), [id]);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Loading rows={3} />;
  const longest = Math.max(1, ...data.steps.map((step) => step.latency_ms));
  return (
    <div className="space-y-2 bg-plaster px-3 py-3">
      {data.error ? <p className="text-brick">{data.error}</p> : null}
      <ol className="space-y-1.5">
        {data.steps.map((step, index) => (
          <li key={`${step.name}-${index}`} className="grid grid-cols-[1fr_auto] items-center gap-x-3">
            <p className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-[500]">{titleCase(step.name)}</span>
              {step.model ? <span className="truncate text-[13px] text-ink-soft">{step.model}</span> : <span className="text-[13px] text-ink-faint">no model</span>}
              {step.cached ? <Tag>Cached</Tag> : null}
              {step.fallback ? <Tag tone="warn">Fallback</Tag> : null}
            </p>
            <p className="tabular text-[13px] text-ink-soft">{step.latency_ms} ms{step.input_tokens ? `, ${step.input_tokens + step.output_tokens} tokens` : ""}</p>
            <span className="col-span-2 mt-0.5 block h-1 rounded-full bg-sunken">
              <span className="block h-full rounded-full bg-door" style={{ width: `${Math.max(2, (step.latency_ms / longest) * 100)}%` }} />
            </span>
          </li>
        ))}
      </ol>
      {data.trace_id ? <p className="tabular text-[13px] text-ink-faint">Trace {data.trace_id.slice(0, 16)}</p> : null}
    </div>
  );
}

function AgentDrawer({ agent, runs, mood, onClose }: { agent: Agent; runs: AgentRun[]; mood: Mood; onClose: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const spent = runs.reduce((sum, run) => sum + Number(run.cost_usd), 0);
  const tokens = runs.reduce((sum, run) => sum + run.input_tokens + run.output_tokens, 0);
  const failed = runs.filter((run) => run.status === "failed").length;
  return (
    <Drawer open onClose={onClose} label={agent.name} width={600}>
      <div className="relative overflow-hidden border-b border-line p-5" style={{ background: `linear-gradient(160deg, oklch(0.94 0.04 ${agent.hue}), transparent 70%)` }}>
        <Button variant="quiet" size="sm" aria-label="Close" onClick={onClose} className="absolute top-3 right-3"><Icon name="close" size={14} /></Button>
        <Face agent={agent} size={84} mood={mood} track />
        <h2 className="mt-3 text-[24px] font-[520]">{agent.name}</h2>
        <p className="text-ink-soft">{agent.role}</p>
        <p className="mt-2 max-w-md text-[15px] leading-snug">{agent.does}</p>
      </div>
      <div className="grid grid-cols-3 divide-x divide-line border-b border-line">
        {[["Runs", String(runs.length)], ["Tokens", tokens.toLocaleString("en-GB")], ["Cost", `$${spent.toFixed(3)}`]].map(([label, value]) => (
          <div key={label} className="px-5 py-3">
            <p className="text-ink-soft">{label}</p>
            <p className="tabular text-[20px] font-[520]">{value}</p>
          </div>
        ))}
      </div>
      <div className="space-y-2.5 border-b border-line p-5">
        <p className="font-[560]">What keeps {agent.name} in check</p>
        <ul className="space-y-1.5">
          {[
            ["bot", "Reads untrusted text with no tools, so a CV or email can't make it do anything."],
            ["check", "Everything it returns is validated against a strict schema first."],
            ["stamp", "It can only propose. A person approves, and a separate process acts."],
          ].map(([icon, text]) => (
            <li key={text} className="flex gap-2 text-ink-soft"><Icon name={icon} className="mt-0.5 text-door" /> {text}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="flex items-center justify-between px-5 pt-4 pb-2 font-[560]">Recent runs {failed ? <Tag tone="bad">{failed} failed</Tag> : null}</p>
        <ul className="border-t border-line">
          {runs.slice(0, 30).map((run) => (
            <li key={run.id} className="border-b border-line">
              <button type="button" aria-expanded={open === run.id} onClick={() => setOpen(open === run.id ? null : run.id)} className="row-hover flex w-full items-center gap-2.5 px-5 py-2 text-left">
                <motion.span animate={{ rotate: open === run.id ? 90 : 0 }} className="inline-flex text-ink-faint"><Icon name="chevron" size={13} /></motion.span>
                <span className="flex-1">{ago(run.started_at)}</span>
                <span className="tabular text-[13px] text-ink-soft">${Number(run.cost_usd).toFixed(4)}</span>
                <Tag tone={STATUS_TONE[run.status] ?? "neutral"}>{titleCase(run.status)}</Tag>
              </button>
              <AnimatePresence initial={false}>
                {open === run.id ? (
                  <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
                    <RunDetail id={run.id} />
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </li>
          ))}
          {runs.length === 0 ? <li className="p-6 text-center text-ink-soft">{agent.name} hasn&rsquo;t run yet.</li> : null}
        </ul>
      </div>
    </Drawer>
  );
}

function AgentsInner() {
  const params = useSearchParams();
  const [openId, setOpenId] = useState<string | null>(params.get("agent"));
  const { data, error } = useLoad(async () => {
    const [runs, proposals] = await Promise.all([
      get<AgentRun[]>("/ai/runs?limit=200"),
      get<Proposal[]>("/trust/proposals?status=pending_approval").catch(() => [] as Proposal[]),
    ]);
    return { runs, proposals };
  }, []);

  const moods = useMemo(() => (data ? moodsFrom(data.runs, data.proposals) : {}), [data]);
  const stats = useMemo(() => {
    const map = new Map<string, { runs: AgentRun[]; cost: number; last: string | null }>();
    for (const run of data?.runs ?? []) {
      const entry = map.get(run.agent) ?? { runs: [], cost: 0, last: null };
      entry.runs.push(run);
      entry.cost += Number(run.cost_usd);
      if (!entry.last || run.started_at > entry.last) entry.last = run.started_at;
      map.set(run.agent, entry);
    }
    return map;
  }, [data]);

  const total = data?.runs.reduce((sum, run) => sum + Number(run.cost_usd), 0) ?? 0;
  const feed = (data?.runs ?? []).slice(0, 12);
  const open = openId ? agentById(openId) : null;
  const moodOf = (agent: Agent): Mood => (stats.has(agent.id) ? (moods[agent.id] ?? "idle") : "asleep");

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle={`Eleven agents, each with one job. They have spent $${total.toFixed(2)} on the last ${data?.runs.length ?? 0} runs.`}
        action={<Link href="/graph" className="flex h-8.5 items-center gap-1.5 rounded-lg border border-line-strong bg-surface px-3 font-[520] shadow-soft transition-colors hover:bg-plaster"><Icon name="graph" size={14} /> See how they connect</Link>}
      />
      <ErrorNote message={error} />
      {!data && !error ? <Loading rows={8} /> : null}
      {data ? (
        <div className="grid items-start gap-5 lg:grid-cols-[1fr_320px]">
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {AGENTS.map((agent) => {
              const mood = moodOf(agent);
              const entry = stats.get(agent.id);
              return (
                <li key={agent.id}>
                  <button
                    type="button"
                    onClick={() => setOpenId(agent.id)}
                    className="group flex h-full w-full flex-col rounded-xl border border-line bg-surface p-3.5 text-left shadow-soft transition-[box-shadow,border-color,transform] duration-150 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lift"
                  >
                    <span className="flex items-start justify-between gap-2">
                      <Face agent={agent} mood={mood} size={52} track />
                      <Tag tone={MOOD_TEXT[mood].tone}>{MOOD_TEXT[mood].label}</Tag>
                    </span>
                    <span className="mt-2.5 text-[15px] font-[560]">{agent.name}</span>
                    <span className="text-ink-soft">{agent.role}</span>
                    <span className="tabular mt-2.5 text-[13px] text-ink-faint">
                      {entry ? `${entry.runs.length} runs, $${entry.cost.toFixed(3)}, ${ago(entry.last as string)}` : "No runs yet"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <section className="rounded-xl border border-line bg-surface shadow-soft lg:sticky lg:top-16">
            <h2 className="border-b border-line px-4 py-2.5 font-[560]">Live activity</h2>
            <ul>
              {feed.map((run) => {
                const agent = agentById(run.agent);
                return (
                  <li key={run.id}>
                    <button type="button" onClick={() => setOpenId(run.agent)} className="row-hover flex w-full items-center gap-2.5 border-b border-line px-4 py-2 text-left last:border-0">
                      <Face agent={agent} size={24} mood={run.status === "running" ? "working" : run.status === "failed" ? "alert" : "idle"} />
                      <span className="min-w-0 flex-1 truncate"><span className="font-[520]">{agent.name}</span> <span className="text-ink-soft">{run.status === "failed" ? "hit a problem" : run.status === "running" ? "is working" : "finished"}</span></span>
                      <span className="shrink-0 text-[13px] text-ink-faint">{ago(run.started_at)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      ) : null}
      {open ? <AgentDrawer agent={open} runs={stats.get(open.id)?.runs ?? []} mood={moodOf(open)} onClose={() => setOpenId(null)} /> : null}
    </>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AgentsInner />
    </Suspense>
  );
}
