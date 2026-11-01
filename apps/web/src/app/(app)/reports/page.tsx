"use client";

import { useMemo } from "react";
import { type AgentRun, get, type InboxStats } from "@/lib/api";
import { downloadCsv, loadCandidates, stageCounts } from "@/lib/hiring";
import { HBars } from "@/ui/charts";
import { agentById } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Button, ErrorNote, Loading, PageHeader, Panel, titleCase, useLoad } from "@/ui/kit";

interface KnowledgeStats {
  questions: number;
  answered_by_assistant: number;
  answered_by_hr: number;
  helpful: number;
  not_helpful: number;
}

function Funnel({ steps }: { steps: { label: string; value: number }[] }) {
  const top = Math.max(1, steps[0]?.value ?? 1);
  return (
    <ol className="space-y-1.5">
      {steps.map((step, index) => {
        const previous = steps[index - 1]?.value;
        return (
          <li key={step.label} className="group grid grid-cols-[120px_1fr_100px] items-center gap-3">
            <span className="text-ink-soft group-hover:text-ink">{step.label}</span>
            <span className="h-7 rounded-md bg-sunken">
              <span className="flex h-full items-center rounded-md bg-door px-2 text-[13px] font-[560] text-white transition-[width] duration-500" style={{ width: `${Math.max(6, (step.value / top) * 100)}%` }}>{step.value}</span>
            </span>
            <span className="tabular text-right text-[13px] text-ink-soft">{previous ? `${Math.round((step.value / previous) * 100)}% moved on` : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default function ReportsPage() {
  const { data, error } = useLoad(async () => {
    const [hiring, runs, inbox, knowledge] = await Promise.all([
      loadCandidates(),
      get<AgentRun[]>("/ai/runs?limit=200").catch(() => [] as AgentRun[]),
      get<InboxStats>("/comms/stats").catch(() => null),
      get<KnowledgeStats>("/knowledge/stats").catch(() => null),
    ]);
    return { hiring, runs, inbox, knowledge };
  }, []);

  const byAgent = useMemo(() => {
    const totals = new Map<string, number>();
    for (const run of data?.runs ?? []) totals.set(run.agent, (totals.get(run.agent) ?? 0) + Number(run.cost_usd));
    return [...totals.entries()].map(([agent, value]) => ({ label: agentById(agent).name, value })).filter((row) => row.value > 0).sort((a, b) => b.value - a.value);
  }, [data]);

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Loading rows={8} />;

  const { hiring, runs, inbox, knowledge } = data;
  const counts = stageCounts(hiring.candidates);
  const applied = hiring.candidates.length;
  const funnel = [
    { label: "Ranked", value: applied },
    { label: "Shortlisted", value: (counts.shortlisted ?? 0) + (counts.interview ?? 0) + (counts.hired ?? 0) },
    { label: "Interview", value: (counts.interview ?? 0) + (counts.hired ?? 0) },
    { label: "Hired", value: counts.hired ?? 0 },
  ];
  const flagged = hiring.candidates.filter((candidate) => candidate.flagged).length;
  const failed = runs.filter((run) => run.status === "failed").length;
  const accuracy = inbox?.classified_messages ? 1 - inbox.corrected_by_a_person / inbox.classified_messages : null;
  const spend = runs.reduce((sum, run) => sum + Number(run.cost_usd), 0);

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="How hiring, the inbox and the agents are doing, from live data."
        action={<Button variant="secondary" onClick={() => downloadCsv("hiring-report.csv", [["Stage", "Candidates"], ...Object.entries(counts).map(([stage, value]) => [stage, value])])}><Icon name="download" size={14} /> Export</Button>}
      />
      <div className="grid grid-cols-2 divide-x divide-line rounded-xl border border-line bg-surface shadow-soft lg:grid-cols-4">
        {[
          ["Attacks caught in CVs", String(flagged)],
          ["Sorting kept by people", accuracy === null ? "n/a" : `${Math.round(accuracy * 100)}%`],
          ["Agent runs that failed", `${failed} of ${runs.length}`],
          ["AI spend, last runs", `$${spend.toFixed(2)}`],
        ].map(([label, value]) => (
          <div key={label} className="px-4 py-3.5">
            <p className="text-ink-soft">{label}</p>
            <p className="tabular mt-1 text-[26px] leading-none font-[520] tracking-tight">{value}</p>
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel title="Hiring funnel"><Funnel steps={funnel} /></Panel>
        <Panel title="AI spend by agent">
          {byAgent.length ? <HBars rows={byAgent} format={(value) => `$${value.toFixed(3)}`} /> : <p className="py-6 text-center text-ink-soft">No paid runs yet.</p>}
        </Panel>
        <Panel title="Inbox by type">
          <HBars rows={Object.entries(inbox?.open_messages_by_type ?? {}).map(([label, value]) => ({ label: titleCase(label), value })).sort((a, b) => b.value - a.value)} />
        </Panel>
        <Panel title="Policy questions">
          <dl className="divide-y divide-line">
            {[
              ["Questions asked", knowledge?.questions ?? 0],
              ["Answered by Hela, with citations", knowledge?.answered_by_assistant ?? 0],
              ["Answered by HR", knowledge?.answered_by_hr ?? 0],
              ["Marked helpful", knowledge?.helpful ?? 0],
              ["Marked not helpful", knowledge?.not_helpful ?? 0],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between py-2 first:pt-0 last:pb-0">
                <dt className="text-ink-soft">{label}</dt>
                <dd className="tabular font-[560]">{value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </>
  );
}
