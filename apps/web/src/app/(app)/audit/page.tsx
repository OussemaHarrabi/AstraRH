"use client";

import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { type ApiError, type AuditRow, get, post } from "@/lib/api";
import { downloadCsv } from "@/lib/hiring";
import { Icon } from "@/ui/Icon";
import { Button, ErrorNote, humanDate, Loading, PageHeader, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";

const RESULT_TONE: Record<string, Tone> = { success: "good", denied: "bad", failure: "bad", failed: "bad" };

function HashLink({ row, previous }: { row: AuditRow & { prev_hash?: string }; previous?: AuditRow }) {
  const linked = !previous || row.prev_hash === previous.hash;
  return (
    <span className="tabular flex items-center gap-1.5 text-[13px] text-ink-soft" title={row.hash}>
      <Icon name={linked ? "shield" : "alert"} size={13} className={linked ? "text-olive" : "text-brick"} />
      {row.hash.slice(0, 10)}
    </span>
  );
}

export default function AuditPage() {
  const { data, error } = useLoad(() => get<(AuditRow & { prev_hash?: string; trace_id?: string })[]>("/trust/audit?limit=300"), []);
  const [actor, setActor] = useState("all");
  const [query, setQuery] = useState("");
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const [result, setResult] = useState<{ ok: boolean; length: number; first_bad_seq?: number | null } | null>(null);
  const [checking, setChecking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const rows = useMemo(
    () => (data ?? []).filter((row) => (actor === "all" || row.actor_type === actor) && (!query || `${row.action} ${row.reason ?? ""}`.toLowerCase().includes(query.toLowerCase()))),
    [data, actor, query],
  );
  const actors = [...new Set((data ?? []).map((row) => row.actor_type))];

  async function verify() {
    setChecking(true);
    try {
      setResult(await post("/trust/audit/verify"));
    } catch (e) {
      setFailure((e as ApiError).message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Each entry includes the hash of the one before it, so nothing can be edited or removed unnoticed."
        action={
          <>
            <Button variant="secondary" onClick={() => downloadCsv("audit-log.csv", [["Entry", "When", "Who", "Action", "Result", "Reason", "Hash"], ...rows.map((row) => [row.seq, row.at, row.actor_type, row.action, row.result, row.reason, row.hash])])}><Icon name="download" size={14} /> Export</Button>
            <Button onClick={verify} disabled={checking}><Icon name="shield" size={14} /> {checking ? "Recomputing…" : "Verify the chain"}</Button>
          </>
        }
      />
      <ErrorNote message={error ?? failure} />
      <AnimatePresence>
        {result ? (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className={`mb-3 flex items-center gap-2.5 rounded-xl px-4 py-3 font-[520] ${result.ok ? "bg-olive-wash text-olive" : "bg-brick-wash text-brick"}`}>
            <Icon name={result.ok ? "shield" : "alert"} />
            {result.ok ? `Verified: all ${result.length} entries recomputed, every hash matches.` : `The chain breaks at entry ${result.first_bad_seq}.`}
          </motion.div>
        ) : null}
      </AnimatePresence>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-xs">
          <Icon name="search" size={14} className="absolute top-2.5 left-2.5 text-ink-faint" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search actions" placeholder="Search actions" className="field !pl-8" />
        </div>
        <div className="flex gap-1">
          {["all", ...actors].map((name) => (
            <button key={name} type="button" onClick={() => setActor(name)} className={`h-8 rounded-lg px-2.5 font-[500] transition-colors ${actor === name ? "bg-door-wash text-door-deep" : "text-ink-soft hover:bg-sunken"}`}>
              {name === "all" ? "Everyone" : titleCase(name)}
            </button>
          ))}
        </div>
        <span className="tabular ml-auto text-ink-soft">{rows.length} entries</span>
      </div>
      {!data && !error ? <Loading rows={8} /> : null}
      {data ? (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-soft">
          <div className="min-w-[720px]">
            <div className="grid grid-cols-[60px_130px_90px_1fr_90px_120px] border-b border-line px-4 py-2.5 text-[13px] text-ink-soft">
              <span>Entry</span><span>When</span><span>Who</span><span>Action</span><span>Result</span><span>Hash</span>
            </div>
            <ul>
              {rows.map((row, index) => (
                <li key={row.seq} className="border-b border-line last:border-0">
                  <button type="button" aria-expanded={openSeq === row.seq} onClick={() => setOpenSeq(openSeq === row.seq ? null : row.seq)} className="row-hover grid w-full grid-cols-[60px_130px_90px_1fr_90px_120px] items-center px-4 py-2 text-left">
                    <span className="tabular text-ink-soft">{row.seq}</span>
                    <span className="tabular text-ink-soft">{humanDate(row.at)}</span>
                    <span>{titleCase(row.actor_type)}</span>
                    <span className="truncate font-[500]">{row.action}</span>
                    <span><Tag tone={RESULT_TONE[row.result] ?? "neutral"}>{titleCase(row.result)}</Tag></span>
                    <HashLink row={row} previous={rows[index + 1]?.seq === row.seq - 1 ? rows[index + 1] : undefined} />
                  </button>
                  <AnimatePresence initial={false}>
                    {openSeq === row.seq ? (
                      <motion.dl initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden bg-plaster">
                        <div className="space-y-1 px-4 py-3">
                          {[["Hash", row.hash], ["Previous", row.prev_hash], ["Actor", row.actor_id], ["Proposal", row.proposal_id], ["Reason", row.reason], ["Trace", row.trace_id]].filter(([, value]) => value).map(([label, value]) => (
                            <div key={label} className="flex gap-3">
                              <dt className="w-20 shrink-0 text-ink-soft">{label}</dt>
                              <dd className="tabular min-w-0 break-all">{value}</dd>
                            </div>
                          ))}
                        </div>
                      </motion.dl>
                    ) : null}
                  </AnimatePresence>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </>
  );
}
