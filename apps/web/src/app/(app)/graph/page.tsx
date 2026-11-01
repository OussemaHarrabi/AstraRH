"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { type Employee, get, type GraphData, type JobDetail, type OrgReference } from "@/lib/api";
import { loadCandidates } from "@/lib/hiring";
import { agentById, Face } from "@/ui/Face";
import { ForceGraph, type GraphEdge, type GraphNode } from "@/ui/ForceGraph";
import { Icon } from "@/ui/Icon";
import { Button, ErrorNote, Loading, PageHeader, percent, Tabs, titleCase, useLoad } from "@/ui/kit";

type View = "hiring" | "agents" | "company";

const COLORS: Record<string, string> = {
  Job: "#4254db",
  Criterion: "#1b8fa0",
  Candidate: "#9a6fd8",
  Attack: "#c43a80",
  Event: "#9aa3ea",
  Agent: "#4254db",
  Proposal: "#d0902f",
  Human: "#1f7a55",
  Execution: "#2d9f75",
  Team: "#4254db",
  Position: "#1b8fa0",
  Person: "#9a6fd8",
};

const LEGENDS: Record<View, string[]> = {
  hiring: ["Job", "Criterion", "Candidate", "Attack"],
  agents: ["Event", "Agent", "Proposal", "Human", "Execution"],
  company: ["Team", "Position", "Person"],
};

const CAPTIONS: Record<View, string> = {
  hiring: "Each line means a sentence in that CV proves that criterion. Thicker lines mean stronger evidence.",
  agents: "The real path of work: an event wakes an agent, the agent proposes, a person decides, the executor acts.",
  company: "Teams, positions and people, drawn from the employee records.",
};

export default function GraphPage() {
  const [view, setView] = useState<View>("hiring");
  const [picked, setPicked] = useState<GraphNode | null>(null);
  const [jobIndex, setJobIndex] = useState(0);

  const hiring = useLoad(async () => {
    const { jobs, candidates } = await loadCandidates();
    const details = await Promise.all(jobs.map((job) => get<JobDetail>(`/packs/talent/jobs/${job.id}`)));
    return { jobs: details, candidates };
  }, []);
  const mesh = useLoad(() => get<GraphData>("/graph/agent_mesh"), []);
  const company = useLoad(async () => {
    const [employees, org] = await Promise.all([get<Employee[]>("/people/employees"), get<OrgReference>("/people/org")]);
    return { employees, org };
  }, []);

  const hiringGraph = useMemo(() => {
    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];
    const data = hiring.data;
    if (!data) return { nodes, edges };
    const ranked = data.jobs.filter((job) => data.candidates.some((candidate) => candidate.job_id === job.id));
    const job = ranked[jobIndex % Math.max(1, ranked.length)] ?? data.jobs[0];
    if (!job) return { nodes, edges };
    nodes.push({ id: job.id, label: job.title, kind: "Job", size: 18, ring: 0, data: { href: `/jobs/${job.id}` } });
    const rubric = job.rubrics.find((item) => item.id === job.active_rubric_id) ?? job.rubrics[0];
    for (const criterion of rubric?.criteria ?? []) {
      nodes.push({ id: `c:${criterion.id}`, label: criterion.label, kind: "Criterion", size: 9 + Number(criterion.weight) * 20, ring: 130, data: { weight: `${Math.round(Number(criterion.weight) * 100)} of 100`, must: criterion.must_have ? "Must-have" : "Nice to have" } });
      edges.push({ from: job.id, to: `c:${criterion.id}` });
    }
    const candidates = data.candidates.filter((candidate) => candidate.job_id === job.id).slice(0, 24);
    for (const candidate of candidates) {
      const score = Number(candidate.score ?? 0);
      nodes.push({
        id: candidate.application_id,
        label: candidate.name ?? "Candidate",
        kind: candidate.flagged ? "Attack" : "Candidate",
        size: 3 + score * 5.500,
        ring: 280,
        data: { score: percent(candidate.score), rank: candidate.rank, stage: titleCase(candidate.stage), href: `/jobs/${job.id}` },
      });
      for (const factor of candidate.factors) {
        if (factor.key === "job_match" || Number(factor.value) < 0.5) continue;
        edges.push({ from: candidate.application_id, to: `c:${factor.key}`, weight: Number(factor.value) });
      }
    }
    return { nodes, edges };
  }, [hiring.data, jobIndex]);

  const agentGraph = useMemo(() => {
    const nodes = new Map<string, GraphNode>();
    const edges: GraphEdge[] = [];
    const data = mesh.data;
    if (!data) return { nodes: [], edges };
    const alias = new Map<string, string>();
    for (const node of data.nodes) {
      if (node.label === "AgentRun") {
        const agent = agentById(node.props.agent ?? "agent");
        const id = `agent:${agent.id}`;
        alias.set(node.id, id);
        const previous = nodes.get(id);
        const runs = Number(previous?.data?.runs ?? 0) + 1;
        nodes.set(id, { id, label: agent.name, kind: "Agent", size: Math.min(24, 13 + runs / 4), hue: agent.hue, face: true, data: { role: agent.role, runs, agent: agent.id } });
      } else {
        const text = node.props.type ?? node.props.action ?? node.props.status ?? node.label;
        nodes.set(node.id, { id: node.id, label: titleCase(String(text)), kind: node.label, size: node.label === "Human" ? 11 : 5, data: node.props });
      }
    }
    const seen = new Set<string>();
    for (const edge of data.edges) {
      const from = alias.get(edge.from) ?? edge.from;
      const to = alias.get(edge.to) ?? edge.to;
      const key = `${from}>${to}`;
      if (from === to || seen.has(key)) continue;
      seen.add(key);
      edges.push({ from, to, label: edge.type });
    }
    // Keep the picture legible: every agent and person, then the most recent work.
    const keep = [...nodes.values()];
    const priority = keep.filter((node) => node.kind === "Agent" || node.kind === "Human");
    const rest = keep.filter((node) => node.kind !== "Agent" && node.kind !== "Human" && edges.some((edge) => edge.from === node.id || edge.to === node.id)).slice(-110);
    return { nodes: [...priority, ...rest], edges };
  }, [mesh.data]);

  const companyGraph = useMemo(() => {
    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];
    const data = company.data;
    if (!data) return { nodes, edges };
    for (const unit of data.org.org_units) nodes.push({ id: unit.id, label: unit.name, kind: "Team", size: 14 });
    const positions = new Set(data.employees.map((employee) => employee.position_id));
    for (const position of data.org.positions) {
      if (positions.has(position.id)) nodes.push({ id: position.id, label: position.title, kind: "Position", size: 7 });
    }
    for (const employee of data.employees) {
      nodes.push({ id: employee.id, label: employee.display_name, kind: "Person", size: 5.500, data: { since: employee.start_date, status: titleCase(employee.status) } });
      edges.push({ from: employee.org_unit_id, to: employee.id });
      edges.push({ from: employee.position_id, to: employee.id });
      if (employee.manager_id) edges.push({ from: employee.manager_id, to: employee.id, weight: 0.7 });
    }
    return { nodes, edges };
  }, [company.data]);

  const graph = view === "hiring" ? hiringGraph : view === "agents" ? agentGraph : companyGraph;
  const failure = view === "hiring" ? hiring.error : view === "agents" ? mesh.error : company.error;
  const ready = view === "hiring" ? hiring.data : view === "agents" ? mesh.data : company.data;
  const select = useCallback((node: GraphNode | null) => setPicked(node), []);
  const connected = picked ? graph.edges.filter((edge) => edge.from === picked.id || edge.to === picked.id).length : 0;
  const rankedJobs = hiring.data?.jobs.filter((job) => hiring.data?.candidates.some((candidate) => candidate.job_id === job.id)) ?? [];
  const agentId = picked?.data?.agent as string | undefined;

  return (
    <>
      <PageHeader title="Graph" subtitle="How your jobs, people, agents and decisions connect." />
      <Tabs
        value={view}
        onChange={(next) => { setView(next); setPicked(null); }}
        tabs={[
          { id: "hiring", label: "Evidence" },
          { id: "agents", label: "Agents and decisions" },
          { id: "company", label: "Company" },
        ]}
      />
      <ErrorNote message={failure} />
      <section className="relative mt-4 overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2.5">
          <p className="min-w-0 flex-1 text-ink-soft">{CAPTIONS[view]}</p>
          {view === "hiring" && rankedJobs.length > 1 ? (
            <select aria-label="Job" className="field !w-auto" value={jobIndex} onChange={(event) => setJobIndex(Number(event.target.value))}>
              {rankedJobs.map((job, index) => <option key={job.id} value={index}>{job.title}</option>)}
            </select>
          ) : null}
          <ul className="flex flex-wrap gap-3 text-[13px] text-ink-soft">
            {LEGENDS[view].map((kind) => (
              <li key={kind} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full" style={{ background: COLORS[kind] }} /> {kind === "Attack" ? "Attack removed" : kind}
              </li>
            ))}
          </ul>
        </div>
        {!ready && !failure ? (
          <div className="p-6"><Loading rows={8} /></div>
        ) : graph.nodes.length === 0 ? (
          <p className="p-16 text-center text-ink-soft">{view === "hiring" ? "Rank a job to see its evidence graph." : "Nothing to draw yet."}</p>
        ) : (
          <ForceGraph key={`${view}-${jobIndex}`} nodes={graph.nodes} edges={graph.edges} colors={COLORS} height={600} selected={picked?.id} onSelect={select} labelFrom={view === "company" ? 7 : 9} />
        )}
        <p className="absolute right-3 bottom-2.5 text-[13px] text-ink-faint">Drag to move, scroll to zoom</p>
        <AnimatePresence>
          {picked ? (
            <motion.aside initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} className="absolute top-14 right-3 w-64 rounded-xl border border-line bg-surface p-3.5 shadow-float">
              <div className="flex items-start gap-2.5">
                {agentId ? <Face agent={agentById(agentId)} size={36} track /> : <span className="mt-1 size-3 shrink-0 rounded-full" style={{ background: COLORS[picked.kind] }} />}
                <div className="min-w-0 flex-1">
                  <p className="font-[560] break-words">{picked.label}</p>
                  <p className="text-[13px] text-ink-soft">{picked.kind}, {connected} connections</p>
                </div>
                <Button variant="quiet" size="sm" aria-label="Close" onClick={() => setPicked(null)} className="!px-1"><Icon name="close" size={13} /></Button>
              </div>
              <dl className="mt-2 space-y-0.5">
                {Object.entries(picked.data ?? {}).filter(([key, value]) => key !== "href" && key !== "agent" && value !== null && value !== "").slice(0, 6).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-3">
                    <dt className="text-ink-soft">{titleCase(key)}</dt>
                    <dd className="truncate font-[500]">{String(value)}</dd>
                  </div>
                ))}
              </dl>
              {typeof picked.data?.href === "string" ? <Link href={picked.data.href} className="mt-2 block font-[520] text-door hover:underline">Open the job</Link> : null}
              {agentId ? <Link href={`/agents?agent=${agentId}`} className="mt-2 block font-[520] text-door hover:underline">See this agent</Link> : null}
            </motion.aside>
          ) : null}
        </AnimatePresence>
      </section>
    </>
  );
}
