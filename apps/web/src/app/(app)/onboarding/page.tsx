"use client";

import { motion } from "motion/react";
import { type FormEvent, useMemo, useState } from "react";
import { type ApiError, type Employee, get, type OrgReference, type Plan, type PlanDetail, post, type SkillGap } from "@/lib/api";
import { Ring } from "@/ui/charts";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Avatar, Button, dayLabel, Drawer, ErrorNote, Field, Loading, Modal, PageHeader, Panel, Tabs, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";
import { useToast } from "@/ui/Shell";

const PHASES = ["preboarding", "week1", "day30", "day60", "day90", "completed"];
const PHASE_LABEL: Record<string, string> = { preboarding: "Before day 1", week1: "Week 1", day30: "Day 30", day60: "Day 60", day90: "Day 90", completed: "Done" };
const SEVERITY: Record<string, Tone> = { high: "bad", medium: "warn", low: "neutral" };

function PlanDrawer({ plan, name, onClose, onChanged }: { plan: Plan; name: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, error, reload } = useLoad(() => get<PlanDetail>(`/packs/journey/plans/${plan.id}`), [plan.id]);
  const tasks = useMemo(() => data?.tasks ?? [], [data]);
  const done = tasks.filter((task) => task.status === "completed" || task.status === "done").length;

  async function complete(taskId: string, title: string) {
    const summary = window.prompt(`What shows that "${title}" is done?`);
    if (!summary) return;
    try {
      await post(`/packs/journey/plans/${plan.id}/tasks/${taskId}/complete`, { summary, evidence: { note: summary } });
      toast("Task recorded with its evidence.");
      void reload();
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  const phases = PHASES.filter((phase) => tasks.some((task) => task.phase === phase));

  return (
    <Drawer open onClose={onClose} label={`Plan for ${name}`} width={640}>
      <div className="flex items-center gap-3 border-b border-line p-5">
        <Avatar name={name} size={44} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[19px] font-[560]">{name}</h2>
          <p className="text-ink-soft">Started {dayLabel(plan.start_date)}, fully ramped by {dayLabel(plan.target_ramp_date)}</p>
        </div>
        {tasks.length ? <Ring value={done / tasks.length} size={48} label={`${done} of ${tasks.length} tasks done`} /> : null}
        <Button variant="quiet" size="sm" aria-label="Close" onClick={onClose}><Icon name="close" size={14} /></Button>
      </div>
      <div className="space-y-5 p-5">
        <ErrorNote message={error} />
        {!data && !error ? <Loading rows={6} /> : null}
        {data?.flags?.length ? (
          <div className="rounded-lg bg-bloom-wash p-3 text-bloom">
            <p className="font-[560]">Support flags</p>
            <ul className="mt-1 space-y-0.5">{data.flags.map((flag, index) => <li key={flag.id ?? index}>{flag.message ?? flag.reason ?? flag.kind}</li>)}</ul>
          </div>
        ) : null}
        {phases.map((phase) => (
          <section key={phase}>
            <h3 className="mb-1.5 font-[560]">{PHASE_LABEL[phase] ?? titleCase(phase)}</h3>
            <ul className="overflow-hidden rounded-xl border border-line">
              {tasks.filter((task) => task.phase === phase).map((task) => {
                const finished = task.status === "completed" || task.status === "done";
                return (
                  <li key={task.id} className="group row-hover flex items-center gap-2.5 border-b border-line px-3 py-2 last:border-0">
                    <button type="button" aria-label={`Mark ${task.title} done`} disabled={finished} onClick={() => complete(task.id, task.title)} className={`flex size-4.5 shrink-0 items-center justify-center rounded-full border transition-colors ${finished ? "border-olive bg-olive text-white" : "border-line-strong hover:border-door"}`}>
                      {finished ? <Icon name="check" size={11} /> : null}
                    </button>
                    <span className="min-w-0 flex-1">
                      <span className={`block ${finished ? "text-ink-soft line-through" : "font-[500]"}`}>{task.title}</span>
                      <span className="block truncate text-[13px] text-ink-soft">{titleCase(task.owner_role)}{task.evidence_required ? `, needs: ${task.evidence_required}` : ""}</span>
                    </span>
                    {!finished && new Date(task.due_at) < new Date() ? <Tag tone="warn">Overdue</Tag> : <span className="text-[13px] text-ink-faint">{dayLabel(task.due_at)}</span>}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </Drawer>
  );
}

function NewEmployee({ org, onClose, onDone }: { org: OrgReference; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await post("/people/employees", {
        person_id: crypto.randomUUID(),
        display_name: form.get("name"),
        email: form.get("email"),
        org_unit_id: form.get("org"),
        position_id: form.get("position"),
        start_date: form.get("start"),
      });
      toast("Employee added. Aziz is preparing the onboarding plan for your approval.");
      onDone();
      onClose();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <Modal open onClose={onClose} label="Add an employee" width={440}>
      <form onSubmit={save} className="space-y-3 p-5">
        <div className="flex items-center gap-3">
          <Face agent={agentById("onboarding_planner")} size={40} track />
          <div>
            <h2 className="text-[17px] font-[560]">Add an employee</h2>
            <p className="text-ink-soft">Aziz drafts a 30/60/90 plan as soon as they&rsquo;re added.</p>
          </div>
        </div>
        <Field label="Full name"><input name="name" required className="field" /></Field>
        <Field label="Work email"><input name="email" type="email" required className="field" /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Team"><select name="org" className="field">{org.org_units.map((unit) => <option key={unit.id} value={unit.id}>{unit.name}</option>)}</select></Field>
          <Field label="Position"><select name="position" className="field">{org.positions.map((position) => <option key={position.id} value={position.id}>{position.title}</option>)}</select></Field>
        </div>
        <Field label="First day"><input name="start" type="date" required className="field" /></Field>
        <div className="flex gap-2">
          <Button type="submit">Add employee</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

export default function OnboardingPage() {
  const [tab, setTab] = useState<"plans" | "skills">("plans");
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const { data, error, reload } = useLoad(async () => {
    const [plans, employees, org, gaps] = await Promise.all([
      get<Plan[]>("/packs/journey/plans"),
      get<Employee[]>("/people/employees").catch(() => [] as Employee[]),
      get<OrgReference>("/people/org").catch(() => ({ org_units: [], positions: [], skills: [], kpis: [] }) as OrgReference),
      get<SkillGap[]>("/packs/journey/gaps").catch(() => [] as SkillGap[]),
    ]);
    return { plans, employees, org, gaps };
  }, []);

  const nameOf = (id: string) => data?.employees.find((employee) => employee.id === id)?.display_name ?? "New joiner";
  const skillOf = (id: string) => data?.org.skills.find((skill) => skill.id === id)?.name ?? "Skill";
  const open = data?.plans.find((plan) => plan.id === openId);

  return (
    <>
      <PageHeader
        title="Onboarding"
        subtitle="30/60/90 plans for new joiners, and the skills they need next."
        action={<Button onClick={() => setAdding(true)} disabled={!data}><Icon name="plus" size={14} /> Add employee</Button>}
      />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "plans", label: "Plans", count: data?.plans.length }, { id: "skills", label: "Skill gaps", count: data?.gaps.length }]} />
      <ErrorNote message={error} />
      {!data && !error ? <Loading rows={6} /> : null}
      {data && tab === "plans" ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
          <div className="grid min-w-[720px] grid-cols-[200px_1fr] border-b border-line text-[13px] text-ink-soft">
            <span className="px-4 py-2.5">New joiner</span>
            <span className="grid grid-cols-6 py-2.5 pr-4">{PHASES.map((phase) => <span key={phase}>{PHASE_LABEL[phase]}</span>)}</span>
          </div>
          <ul className="min-w-[720px]">
            {data.plans.map((plan) => {
              const position = Math.max(0, PHASES.indexOf(plan.phase));
              return (
                <li key={plan.id}>
                  <button type="button" onClick={() => setOpenId(plan.id)} className="group row-hover grid w-full grid-cols-[200px_1fr] items-center border-b border-line text-left">
                    <span className="flex items-center gap-2.5 px-4 py-2.5">
                      <Avatar name={nameOf(plan.employee_id)} size={26} />
                      <span className="min-w-0">
                        <span className="block truncate font-[520] group-hover:text-door">{nameOf(plan.employee_id)}</span>
                        {plan.status === "draft" ? <Tag tone="info">Waiting for approval</Tag> : null}
                      </span>
                    </span>
                    <span className="relative grid grid-cols-6 pr-4">
                      <span className="absolute top-1/2 left-1 right-8 h-1 -translate-y-1/2 rounded-full bg-sunken" />
                      <motion.span
                        initial={{ width: 0 }}
                        animate={{ width: `calc((100% - 16px) * ${position / 6})` }}
                        transition={{ duration: 0.6, ease: "easeOut" }}
                        className="absolute top-1/2 left-1 h-1 -translate-y-1/2 rounded-full bg-door"
                      />
                      {PHASES.map((phase, index) => (
                        <span key={phase} className={`relative z-[1] size-2.5 rounded-full ring-2 ring-surface ${index <= position ? "bg-door" : "bg-line-strong"}`} />
                      ))}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {data && tab === "skills" ? (
        <Panel className="mt-4" flush>
          <ul>
            {data.gaps.map((gap) => (
              <li key={gap.id} className="row-hover flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                <Avatar name={nameOf(gap.employee_id)} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block font-[520]">{nameOf(gap.employee_id)}, {skillOf(gap.skill_id)}</span>
                  <span className="block text-ink-soft">{gap.message}</span>
                </span>
                <span className="flex items-center gap-[3px]" role="img" aria-label={`Level ${gap.current_level} of ${gap.required_level} required`}>
                  {Array.from({ length: Math.max(gap.required_level, 5) }, (_, index) => (
                    <span key={index} className={`h-3 w-1.5 rounded-sm ${index < gap.current_level ? "bg-door" : index < gap.required_level ? "bg-bloom opacity-60" : "bg-sunken"}`} />
                  ))}
                </span>
                <Tag tone={SEVERITY[gap.severity] ?? "neutral"}>{titleCase(gap.severity)}</Tag>
                <Tag>{titleCase(gap.status)}</Tag>
              </li>
            ))}
            {data.gaps.length === 0 ? <li className="p-10 text-center text-ink-soft">No skill gaps have been raised.</li> : null}
          </ul>
        </Panel>
      ) : null}
      {open ? <PlanDrawer plan={open} name={nameOf(open.employee_id)} onClose={() => setOpenId(null)} onChanged={() => void reload()} /> : null}
      {adding && data ? <NewEmployee org={data.org} onClose={() => setAdding(false)} onDone={() => void reload()} /> : null}
    </>
  );
}
