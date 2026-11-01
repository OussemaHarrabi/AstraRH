"use client";

import { motion } from "motion/react";
import { type FormEvent, useState } from "react";
import { type ApiError, get, post } from "@/lib/api";
import { Icon } from "@/ui/Icon";
import { Button, dayLabel, Drawer, ErrorNote, Field, Loading, PageHeader, Panel, Tabs, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";
import { useToast } from "@/ui/Shell";

interface Run {
  id: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: string;
  calculation_state: string;
  totals: Record<string, string | number> | null;
  open_issues: Record<string, number> | null;
  notice: string | null;
}

interface Slip {
  id: string;
  employee: string;
  gross: string;
  income_tax: string;
  employee_deductions: string;
  net_pay: string;
  employer_cost: string;
  status: string;
}

interface RuleSet {
  id: string;
  rule_id: string;
  version: string | number;
  status: string;
  valid_from: string;
  is_demo: boolean;
}

interface NetResult {
  gross: string;
  lines: { code: string; label: string; kind: string; amount: string; rate: string | null }[];
  totals: { employee_deductions: string; income_tax: string; solidarity: string; net_pay: string; employer_cost: string };
  rule_set: { id: string; version?: string | number; is_demo?: boolean };
  notice?: string | null;
}

const STEPS = ["draft", "calculated", "submitted", "approved"];
const STATUS_TONE: Record<string, Tone> = { draft: "neutral", calculated: "info", submitted: "info", approved: "good", rejected: "bad", active: "good" };
const money = (value: string | number | undefined | null) =>
  value === null || value === undefined ? "n/a" : `${Number(value).toLocaleString("en-GB", { minimumFractionDigits: 3, maximumFractionDigits: 3 })}`;

function Calculator() {
  const [result, setResult] = useState<NetResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [children, setChildren] = useState(0);
  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      setResult(
        await post<NetResult>("/packs/finance/calculator/net", {
          gross: String(form.get("gross")),
          head_of_family: form.get("head") === "on",
          children: Array.from({ length: children }, () => "child"),
        }),
      );
    } catch (e) {
      setResult(null);
      setError((e as ApiError).message);
    }
  }
  return (
    <div className="mt-4 grid items-start gap-5 lg:grid-cols-[340px_1fr]">
      <Panel title="Gross to net">
        <form onSubmit={run} className="space-y-3">
          <Field label="Monthly gross, TND"><input name="gross" type="number" min={1} step="0.001" defaultValue={2500} required className="field tabular" /></Field>
          <label className="flex items-center gap-2"><input type="checkbox" name="head" className="accent-[var(--door)]" /> Head of family</label>
          <Field label="Children">
            <div className="flex items-center gap-2">
              <input type="range" min={0} max={4} value={children} onChange={(event) => setChildren(Number(event.target.value))} className="flex-1 accent-[var(--door)]" />
              <span className="tabular w-4 text-right">{children}</span>
            </div>
          </Field>
          <Button type="submit" className="w-full">Calculate</Button>
          <p className="text-[13px] text-ink-soft">Computed by code from the active rules, never by a model. Nothing is stored.</p>
        </form>
      </Panel>
      <div>
        <ErrorNote message={error} />
        {result ? (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
            <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line px-4 py-3">
              <p><span className="text-ink-soft">Net pay</span> <span className="tabular ml-1 text-[28px] font-[520] tracking-tight">{money(result.totals.net_pay)}</span> <span className="text-ink-soft">TND</span></p>
              <p className="tabular text-ink-soft">Employer cost {money(result.totals.employer_cost)}</p>
            </div>
            <ul>
              {result.lines.map((line) => (
                <li key={line.code} className="row-hover flex items-baseline justify-between gap-4 border-b border-line px-4 py-2 last:border-0">
                  <span>{line.label} {line.rate ? <span className="tabular text-[13px] text-ink-soft">{(Number(line.rate) * 100).toFixed(2)}%</span> : null}</span>
                  <span className="tabular font-[500]">{money(line.amount)}</span>
                </li>
              ))}
            </ul>
            {result.rule_set.is_demo ? <p className="flex gap-2 bg-ochre-wash px-4 py-2.5 text-ochre"><Icon name="alert" /> Demo rules, not verified against the official texts.</p> : null}
          </motion.div>
        ) : !error ? (
          <p className="rounded-xl border border-dashed border-line-strong p-10 text-center text-ink-soft">Enter a salary to see every line and the rule behind it.</p>
        ) : null}
      </div>
    </div>
  );
}

function RunDrawer({ run, onClose, onChanged }: { run: Run; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data: slips, error } = useLoad(() => get<Slip[]>(`/packs/finance/payroll-runs/${run.id}/payslips`), [run.id]);
  const [busy, setBusy] = useState(false);
  async function act(path: string, done: string) {
    setBusy(true);
    try {
      const result = await post<{ ok?: boolean; match?: boolean; matched?: boolean }>(`/packs/finance/payroll-runs/${run.id}/${path}`);
      toast(path === "verify" ? `Replay finished: ${result.ok ?? result.match ?? result.matched ? "every payslip matches" : "see the run for differences"}.` : done);
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }
  const position = STEPS.indexOf(run.status);
  return (
    <Drawer open onClose={onClose} label="Payroll run" width={720}>
      <div className="border-b border-line p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[19px] font-[560]">{dayLabel(run.period_start)} to {dayLabel(run.period_end)}</h2>
            <p className="text-ink-soft">Paid on {dayLabel(run.pay_date)}</p>
          </div>
          <Button variant="quiet" size="sm" aria-label="Close" onClick={onClose}><Icon name="close" size={14} /></Button>
        </div>
        <ol className="mt-4 flex gap-1">
          {STEPS.map((step, index) => (
            <li key={step} className="flex-1">
              <span className={`block h-1 rounded-full ${index <= position ? "bg-door" : "bg-sunken"}`} />
              <span className={`mt-1 block text-[13px] ${index === position ? "font-[560] text-ink" : "text-ink-soft"}`}>{titleCase(step)}</span>
            </li>
          ))}
        </ol>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {run.status === "draft" || run.calculation_state === "failed" ? <Button size="sm" disabled={busy} onClick={() => act("calculate", "The worker is calculating every payslip.")}>Calculate</Button> : null}
          {run.status === "calculated" ? <Button size="sm" disabled={busy} onClick={() => act("submit", "Submitted. A different person must approve it.")}>Submit for approval</Button> : null}
          {run.status === "submitted" ? <Button size="sm" variant="secondary" disabled={busy} onClick={() => act("recall", "Taken back.")}>Recall</Button> : null}
          {run.status !== "draft" ? <Button size="sm" variant="secondary" disabled={busy} onClick={() => act("verify", "")}><Icon name="shield" size={13} /> Replay and verify</Button> : null}
        </div>
      </div>
      <div className="p-5">
        <ErrorNote message={error} />
        {!slips && !error ? <Loading rows={5} /> : null}
        {slips?.length ? (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[560px] text-left">
              <thead className="text-[13px] text-ink-soft">
                <tr className="border-b border-line">
                  <th className="px-3 py-2 font-[500]">Employee</th>
                  <th className="px-3 py-2 text-right font-[500]">Gross</th>
                  <th className="px-3 py-2 text-right font-[500]">Tax</th>
                  <th className="px-3 py-2 text-right font-[500]">Deductions</th>
                  <th className="px-3 py-2 text-right font-[500]">Net</th>
                </tr>
              </thead>
              <tbody>
                {slips.map((slip) => (
                  <tr key={slip.id} className="row-hover tabular border-b border-line last:border-0">
                    <td className="px-3 py-2 font-[500]">{slip.employee}</td>
                    <td className="px-3 py-2 text-right">{money(slip.gross)}</td>
                    <td className="px-3 py-2 text-right text-ink-soft">{money(slip.income_tax)}</td>
                    <td className="px-3 py-2 text-right text-ink-soft">{money(slip.employee_deductions)}</td>
                    <td className="px-3 py-2 text-right font-[560]">{money(slip.net_pay)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : slips ? <p className="py-6 text-center text-ink-soft">Payslips appear once the run is calculated.</p> : null}
      </div>
    </Drawer>
  );
}

export default function PayrollPage() {
  const [tab, setTab] = useState<"runs" | "calculator" | "rules">("runs");
  const [openId, setOpenId] = useState<string | null>(null);
  const toast = useToast();
  const runs = useLoad(() => get<Run[]>("/packs/finance/payroll-runs"), []);
  const rules = useLoad(() => get<RuleSet[]>("/packs/finance/rule-sets"), []);
  const notices = useLoad(() => get<{ id: string; status: string; candidate_name?: string; person_name?: string }[]>("/packs/finance/hire-notices?status=open").catch(() => []), []);
  const open = runs.data?.find((run) => run.id === openId);
  const active = rules.data?.find((rule) => rule.status === "active");

  async function newRun() {
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    const iso = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    try {
      const run = await post<Run>("/packs/finance/payroll-runs", { period_start: iso(start), period_end: iso(end), pay_date: iso(end), external_request_id: `ui-${iso(start)}` });
      toast("Payroll run created.");
      await runs.reload();
      setOpenId(run.id);
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  return (
    <>
      <PageHeader
        title="Payroll"
        subtitle="Calculated by code, approved by two people, replayable to the last millime."
        action={<Button onClick={newRun} disabled={!active}><Icon name="plus" size={14} /> New payroll run</Button>}
      />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "runs", label: "Runs", count: runs.data?.length }, { id: "calculator", label: "Calculator" }, { id: "rules", label: "Rule sets", count: rules.data?.length }]} />
      <ErrorNote message={runs.error} />
      {notices.data?.length ? (
        <p className="mt-4 flex items-center gap-2 rounded-lg bg-door-wash px-3 py-2 text-door-deep"><Icon name="users" /> {notices.data.length} new hires need their contract terms.</p>
      ) : null}
      {tab === "runs" ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
          {!runs.data && !runs.error ? <div className="p-4"><Loading /></div> : null}
          {runs.data?.length === 0 ? (
            <div className="p-12 text-center">
              <p className="text-[15px] font-[560]">No payroll runs yet</p>
              <p className="mt-1 text-ink-soft">{active ? "Create the first run for this month." : "Activate a rule set first. It takes two people."}</p>
            </div>
          ) : null}
          {runs.data?.length ? (
            <table className="w-full min-w-[640px] text-left">
              <thead className="text-[13px] text-ink-soft">
                <tr className="border-b border-line">
                  <th className="px-4 py-2.5 font-[500]">Period</th>
                  <th className="px-4 py-2.5 font-[500]">Status</th>
                  <th className="px-4 py-2.5 text-right font-[500]">Payslips</th>
                  <th className="px-4 py-2.5 text-right font-[500]">Total net, TND</th>
                  <th className="px-4 py-2.5 text-right font-[500]">Open issues</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => {
                  const issues = Object.values(run.open_issues ?? {}).reduce((sum, value) => sum + value, 0);
                  return (
                    <tr key={run.id} onClick={() => setOpenId(run.id)} className="row-hover tabular cursor-pointer border-b border-line last:border-0">
                      <td className="px-4 py-3 font-[520]">{dayLabel(run.period_start)} to {dayLabel(run.period_end)}</td>
                      <td className="px-4 py-3"><Tag tone={STATUS_TONE[run.status] ?? "neutral"}>{titleCase(run.status)}</Tag></td>
                      <td className="px-4 py-3 text-right">{run.totals?.payslips ?? run.totals?.count ?? "n/a"}</td>
                      <td className="px-4 py-3 text-right font-[520]">{money(run.totals?.net_pay ?? run.totals?.net)}</td>
                      <td className="px-4 py-3 text-right">{issues ? <Tag tone="warn">{issues}</Tag> : "None"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </div>
      ) : null}
      {tab === "calculator" ? <Calculator /> : null}
      {tab === "rules" ? (
        <Panel className="mt-4" flush>
          <ul>
            {rules.data?.map((rule) => (
              <li key={rule.id} className="row-hover flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                <Icon name="file" className="text-ink-faint" />
                <span className="min-w-0 flex-1 font-[520]">{rule.rule_id} <span className="font-[400] text-ink-soft">version {rule.version}, from {dayLabel(rule.valid_from)}</span></span>
                {rule.is_demo ? <Tag tone="warn">Demo values</Tag> : null}
                <Tag tone={STATUS_TONE[rule.status] ?? "neutral"}>{titleCase(rule.status)}</Tag>
              </li>
            ))}
            {rules.data?.length === 0 ? <li className="p-10 text-center text-ink-soft">No rule sets yet.</li> : null}
          </ul>
        </Panel>
      ) : null}
      {open ? <RunDrawer run={open} onClose={() => setOpenId(null)} onChanged={() => void runs.reload()} /> : null}
    </>
  );
}
