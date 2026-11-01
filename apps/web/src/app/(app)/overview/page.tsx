"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  type AgentRun,
  type Booking,
  get,
  type InboxStats,
  type Plan,
  post,
  type Proposal,
} from "@/lib/api";
import { loadCandidates, moodsFrom, stageCounts } from "@/lib/hiring";
import { HBars, STAGE_COLORS, StackedBar, AreaLine } from "@/ui/charts";
import { AGENTS, agentById, Crew, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { ago, Button, dayLabel, ErrorNote, Loading, Panel, RiskTag, timeLabel, titleCase, useLoad } from "@/ui/kit";
import { useMe, useToast } from "@/ui/Shell";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const quiet = <T,>(promise: Promise<T>, fallback: T) => promise.catch(() => fallback);

function Metric({ label, value, href, hint }: { label: string; value: React.ReactNode; href: string; hint?: string }) {
  return (
    <Link href={href} className="group row-hover block px-4 py-3.5 first:rounded-l-xl last:rounded-r-xl">
      <p className="flex items-center justify-between text-ink-soft">
        {label}
        <Icon name="chevron" size={13} className="text-ink-faint opacity-0 transition-opacity group-hover:opacity-100" />
      </p>
      <p className="tabular mt-1 text-[26px] leading-none font-[520] tracking-tight">{value}</p>
      {hint ? <p className="mt-1.5 text-[13px] text-ink-soft">{hint}</p> : null}
    </Link>
  );
}

function ChainStrip() {
  const toast = useToast();
  const [state, setState] = useState<"idle" | "busy" | "ok" | "bad">("idle");
  const [count, setCount] = useState<number | null>(null);
  async function verify() {
    setState("busy");
    try {
      const result = await post<{ ok: boolean; length: number }>("/trust/audit/verify");
      const fine = result.ok;
      setCount(result.length);
      setState(fine ? "ok" : "bad");
      toast(fine ? "Audit chain verified" : "The audit chain has a break", fine ? "ok" : "bad");
    } catch {
      setState("idle");
      toast("Only admin, HR and auditors can verify the chain", "bad");
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 shadow-soft">
      <span className={`flex size-7 items-center justify-center rounded-lg ${state === "bad" ? "bg-brick-wash text-brick" : "bg-olive-wash text-olive"}`}>
        <Icon name="shield" />
      </span>
      <p className="min-w-0 flex-1">
        <span className="font-[560]">Nothing leaves without a person.</span>{" "}
        <span className="text-ink-soft">
          {state === "ok"
            ? `Audit chain verified${count ? `: ${count} entries, every hash intact` : ""}.`
            : state === "bad"
              ? "The audit chain does not match."
              : "Every action is written to a chain of hashes you can check."}
        </span>
      </p>
      <Button variant="secondary" size="sm" onClick={verify} disabled={state === "busy"}>
        {state === "busy" ? "Checking…" : "Verify the chain"}
      </Button>
    </div>
  );
}

export default function OverviewPage() {
  const router = useRouter();
  const me = useMe();
  const toast = useToast();
  const { data, error, reload } = useLoad(async () => {
    const [proposals, runs, stats, hiring, bookings, plans, runsPay] = await Promise.all([
      quiet(get<Proposal[]>("/trust/proposals?status=pending_approval"), []),
      quiet(get<AgentRun[]>("/ai/runs?limit=200"), []),
      quiet(get<InboxStats | null>("/comms/stats"), null),
      quiet(loadCandidates(), { jobs: [], candidates: [], interviews: [] }),
      quiet(get<{ items: Booking[] }>("/calendar/bookings"), { items: [] }),
      quiet(get<Plan[]>("/packs/journey/plans"), []),
      quiet(get<{ status: string }[]>("/packs/finance/payroll-runs"), []),
    ]);
    return { proposals, runs, stats, hiring, bookings: bookings.items, plans, runsPay, loadedAt: Date.now() };
  }, []);

  const moods = useMemo(() => (data ? moodsFrom(data.runs, data.proposals) : {}), [data]);
  const [resolved, setResolved] = useState<string[]>([]);

  const activity = useMemo(() => {
    if (!data) return [];
    // The last twelve hours, with quiet hours shown as quiet.
    const hour = 3_600_000;
    const end = Math.ceil(data.loadedAt / hour) * hour;
    const points = Array.from({ length: 12 }, (_, index) => ({
      label: `${new Date(end - (11 - index) * hour).getHours()}:00`,
      value: 0,
    }));
    for (const run of data.runs) {
      const slot = 11 - Math.floor((end - new Date(run.started_at).getTime()) / hour);
      if (slot >= 0 && points[slot]) points[slot].value += 1;
    }
    return points;
  }, [data]);

  if (error) return <ErrorNote message={error} />;
  if (!data || !me) return <Loading rows={6} />;

  const { proposals, runs, stats, hiring, bookings, plans } = data;
  const queue = proposals.filter((proposal) => !resolved.includes(proposal.id));
  const byRun = new Map(runs.map((run) => [run.id, run.agent]));
  const spent = runs.reduce((sum, run) => sum + Number(run.cost_usd), 0);
  const byType = Object.entries(stats?.open_messages_by_type ?? {})
    .map(([label, value]) => ({ label: titleCase(label), value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
  const live = plans.filter((plan) => plan.status === "in_progress");

  async function quickApprove(proposal: Proposal) {
    setResolved((list) => [...list, proposal.id]);
    try {
      await post(`/trust/proposals/${proposal.id}/approve`);
      toast("Approved. The executor will take it from here.");
      reload();
    } catch (failure) {
      setResolved((list) => list.filter((id) => id !== proposal.id));
      toast((failure as Error).message, "bad");
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <p className="text-ink-soft">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</p>
        <h1 className="mt-0.5 text-[28px] font-[520]">
          {greeting()}, {me.display_name.split(" ")[0]}
        </h1>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Link href="/jobs?new=1" className="flex h-8 items-center gap-1.5 rounded-full bg-door px-3 font-[520] text-white shadow-soft transition-colors hover:bg-door-deep">
            <Icon name="plus" size={14} /> New job
          </Link>
          {[
            ["/jobs", "upload", "Upload CVs"],
            ["/inbox", "inbox", "Today's digest"],
            ["/interviews", "calendar", "My calendar"],
            ["/ask", "chat", "Ask a policy question"],
          ].map(([href, icon, label]) => (
            <Link key={label} href={href} className="flex h-8 items-center gap-1.5 rounded-full border border-line bg-surface px-3 font-[500] shadow-soft transition-colors hover:bg-plaster">
              <Icon name={icon} size={14} className="text-ink-soft" /> {label}
            </Link>
          ))}
        </div>
      </header>

      <section aria-label="Your agents" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-3 shadow-soft">
        <div>
          <p className="font-[560]">Your crew</p>
          <p className="text-[13px] text-ink-soft">
            {Object.values(moods).filter((mood) => mood === "waiting").length} waiting for a decision, {runs.length} runs recently
          </p>
        </div>
        <Crew moods={moods} onPick={(agent) => router.push(`/agents?agent=${agent.id}`)} />
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] grid-cols-2 divide-x divide-line rounded-xl border border-line bg-surface shadow-soft lg:grid-cols-5">
        <Metric label="Decisions waiting" value={queue.length} href="/approvals" />
        <Metric label="Open jobs" value={hiring.jobs.length} href="/jobs" />
        <Metric label="Candidates ranked" value={hiring.candidates.length} href="/candidates" />
        <Metric label="Emails needing you" value={stats?.open_needing_a_person ?? 0} href="/inbox" />
        <Metric label="AI spend, recent runs" value={`$${spent.toFixed(2)}`} href="/agents" />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[1.55fr_1fr]">
        <Panel
          flush
          title="Waiting for your decision"
          action={<Link href="/approvals" className="text-[13px] font-[520] text-door hover:underline">See all {queue.length}</Link>}
        >
          {queue.length === 0 ? (
            <p className="p-6 text-center text-ink-soft">Nothing is waiting. Your crew will bring you the next thing.</p>
          ) : (
            <ul>
              <AnimatePresence initial={false}>
                {queue.slice(0, 6).map((proposal) => {
                  const agentId = proposal.agent_run_id ? byRun.get(proposal.agent_run_id) : undefined;
                  return (
                    <motion.li
                      key={proposal.id}
                      layout
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                      className="group row-hover flex items-center gap-3 border-b border-line px-4 py-2.5 last:border-0"
                    >
                      <Face agent={agentById(agentId ?? "agent")} size={28} mood="waiting" />
                      <Link href={`/approvals?id=${proposal.id}`} className="min-w-0 flex-1">
                        <p className="truncate font-[500]">{proposal.summary}</p>
                        <p className="text-[13px] text-ink-soft">{agentId ? `${agentById(agentId).name} proposed` : "Prepared after a person's action,"} {ago(proposal.created_at)}</p>
                      </Link>
                      <span className="group-hover:hidden"><RiskTag risk={proposal.risk} /></span>
                      <span className="hidden gap-1.5 group-hover:flex">
                        <Link href={`/approvals?id=${proposal.id}`} className="flex h-7 items-center rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-[520] hover:bg-plaster">Review</Link>
                        {proposal.risk === "R2" ? <Button size="sm" onClick={() => quickApprove(proposal)}>Approve</Button> : null}
                      </span>
                    </motion.li>
                  );
                })}
              </AnimatePresence>
            </ul>
          )}
        </Panel>

        <Panel title="Coming up" flush action={<Link href="/interviews" className="text-[13px] font-[520] text-door hover:underline">Calendar</Link>}>
          {bookings.length === 0 ? (
            <div className="flex flex-col items-center px-4 py-10 text-center">
              <Face agent={agentById("scheduler")} size={48} mood="idle" track />
              <p className="mt-2 text-ink-soft">No interviews booked yet. Shortlist someone and Dali will find times.</p>
            </div>
          ) : (
            <ol className="p-2">
              {bookings.slice(0, 6).map((booking) => (
                <li key={booking.id} className="row-hover flex gap-3 rounded-lg px-2 py-2">
                  <span className="tabular w-16 shrink-0 text-ink-soft">
                    {dayLabel(booking.starts_at).split(",")[0]}
                    <br />
                    {timeLabel(booking.starts_at)}
                  </span>
                  <span className="min-w-0 border-l-2 border-door pl-3">
                    <span className="block truncate font-[500]">{booking.title ?? "Interview"}</span>
                    <span className="block truncate text-[13px] text-ink-soft">{booking.participants?.join(", ")}</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-3">
        <Panel title="Hiring pipeline" className="lg:col-span-2">
          {hiring.jobs.length === 0 ? (
            <p className="py-6 text-center text-ink-soft">Create a job to see its pipeline here.</p>
          ) : (
            <>
              <ul className="space-y-3.5">
                {hiring.jobs.map((job) => {
                  const counts = stageCounts(hiring.candidates.filter((candidate) => candidate.job_id === job.id));
                  const total = Object.values(counts).reduce((sum, value) => sum + value, 0) || Object.values(job.cv_counts).reduce((sum, value) => sum + value, 0);
                  return (
                    <li key={job.id}>
                      <Link href={`/jobs/${job.id}`} className="group block">
                        <p className="mb-1.5 flex justify-between">
                          <span className="font-[500] group-hover:text-door">{job.title}</span>
                          <span className="tabular text-ink-soft">{total}</span>
                        </p>
                      </Link>
                      <StackedBar
                        parts={Object.keys(STAGE_COLORS).map((stage) => ({
                          key: stage,
                          label: titleCase(stage),
                          value: counts[stage] ?? 0,
                          color: STAGE_COLORS[stage],
                        }))}
                      />
                    </li>
                  );
                })}
              </ul>
              <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-soft">
                {Object.entries(STAGE_COLORS).map(([stage, color]) => (
                  <li key={stage} className="flex items-center gap-1.5">
                    <span className="size-2 rounded-sm" style={{ background: color }} /> {titleCase(stage)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
        <Panel title="Open inbox by type" action={<Link href="/inbox" className="text-[13px] font-[520] text-door hover:underline">Inbox</Link>}>
          {stats && stats.open_needing_a_person > 0 ? (
            <Link href="/inbox?view=human" className="mb-3 flex items-center gap-2 rounded-lg bg-bloom-wash px-2.5 py-1.5 text-[13px] font-[520] text-bloom hover:underline">
              <Icon name="alert" size={14} /> {stats.open_needing_a_person} need a person
            </Link>
          ) : null}
          <HBars rows={byType} />
        </Panel>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
        <Panel title="Agent activity" action={<Link href="/agents" className="text-[13px] font-[520] text-door hover:underline">{AGENTS.length} agents</Link>}>
          {activity.length > 1 ? <AreaLine points={activity} unit=" runs" /> : <p className="py-6 text-center text-ink-soft">Runs will show here as agents work.</p>}
        </Panel>
        <Panel title="New joiners" action={<Link href="/onboarding" className="text-[13px] font-[520] text-door hover:underline">Onboarding</Link>}>
          <ul className="space-y-2.5">
            {["week1", "day30", "day60", "completed"].map((phase) => {
              const count = plans.filter((plan) => plan.phase === phase).length;
              return (
                <li key={phase} className="flex items-center gap-3">
                  <span className="w-20 text-ink-soft">{phase === "week1" ? "Week 1" : phase === "completed" ? "Completed" : `Day ${phase.slice(3)}`}</span>
                  <span className="flex flex-1 gap-[3px]">
                    {Array.from({ length: Math.max(count, 1) }, (_, index) => (
                      <span key={index} className={`h-2 max-w-12 flex-1 rounded-full ${count ? "bg-door" : "bg-sunken"}`} />
                    ))}
                  </span>
                  <span className="tabular w-5 text-right font-[520]">{count}</span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-[13px] text-ink-soft">{live.length} plans in progress</p>
        </Panel>
      </div>

      <ChainStrip />
    </div>
  );
}
