"use client";

import { useEffect, useState } from "react";
import { type ApiError, type AuditRow, get, post } from "@/lib/api";
import { Button, ErrorNote, Loading, PageHeader, Tag, humanDate } from "@/ui/kit";

const ACTION_TEXT: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.step_up": "Confirmed their password",
  "proposal.created": "Suggested an action",
  "proposal.approved": "Approved",
  "proposal.rejected": "Rejected",
  "proposal.edited": "Edited a suggestion",
  "proposal.superseded": "Replaced an old suggestion",
  "proposal.approve": "Tried to approve",
  "proposal.reject": "Tried to reject",
  "proposal.edit": "Tried to edit",
  "execution.started": "Started the action",
  "execution.succeeded": "Completed the action",
  "execution.failed": "The action failed",
  "execution.unknown": "Outcome unknown, needs a person",
  "execution.denied": "Blocked the action",
  "talent.cv.read": "Read a CV",
  "talent.rubric.activated": "Approved job criteria",
  "talent.criterion.overridden": "Corrected a score",
  "agent.run.succeeded": "An agent finished",
  "agent.run.failed": "An agent failed",
};

interface Verified {
  ok: boolean;
  length: number;
  first_bad_seq: number | null;
}

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [verified, setVerified] = useState<Verified | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<AuditRow[]>("/trust/audit?limit=200")
      .then(setRows)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  async function verify() {
    setBusy(true);
    try {
      setVerified(await post<Verified>("/trust/audit/verify"));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="History"
        subtitle="Every action, by people and by agents. Records can only be added, and each one seals the one before it."
        action={
          <Button onClick={verify} disabled={busy}>
            {busy ? "Checking…" : "Check for tampering"}
          </Button>
        }
      />
      <ErrorNote message={error} />
      {verified ? (
        <p
          role="status"
          className={`mb-4 rounded-md px-3 py-2 font-semibold ${
            verified.ok ? "bg-olive-wash text-olive" : "bg-brick-wash text-brick"
          }`}
        >
          {verified.ok
            ? `All ${verified.length} records are intact.`
            : `Record ${verified.first_bad_seq} has been changed. The history after it can't be trusted.`}
        </p>
      ) : null}
      {!rows && !error ? <Loading /> : null}
      <ol className="divide-y divide-line border-y border-line">
        {rows?.map((row) => (
          <li key={row.seq} className="grid gap-x-4 py-2.5 md:grid-cols-[4rem_11rem_6rem_1fr]">
            <span className="tabular text-ink-soft">{row.seq}</span>
            <span className="text-ink-soft">{humanDate(row.at)}</span>
            <span>{row.actor_type === "human" ? "Person" : row.actor_type === "agent" ? "Agent" : "System"}</span>
            <span className="flex flex-wrap items-center gap-2">
              {ACTION_TEXT[row.action] ?? row.action}
              {row.result === "denied" ? <Tag tone="bad">Denied</Tag> : null}
              {row.result === "failure" ? <Tag tone="warn">Failed</Tag> : null}
              {row.reason ? <span className="text-ink-soft">{row.reason.replaceAll("_", " ")}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
