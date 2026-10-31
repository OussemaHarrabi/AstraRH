"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, get, post, type Proposal, type Shortlist } from "@/lib/api";
import { WhyPanel } from "@/ui/WhyPanel";
import {
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  RiskTag,
  humanDate,
} from "@/ui/kit";

function useCandidateNames(proposal: Proposal): string[] | null {
  const [names, setNames] = useState<string[] | null>(null);
  const jobId = proposal.payload.job_id as string | undefined;
  const ids = proposal.payload.application_ids as string[] | undefined;
  useEffect(() => {
    if (!jobId || !ids) return;
    get<Shortlist>(`/packs/talent/jobs/${jobId}/shortlist`)
      .then((list) => {
        const byId = new Map(list.candidates.map((c) => [c.application_id, c.name ?? "Unnamed"]));
        setNames(ids.map((id) => byId.get(id) ?? "Earlier ranking"));
      })
      .catch(() => setNames(null));
  }, [jobId, ids]);
  return names;
}

function ProposalItem({ proposal, onChanged }: { proposal: Proposal; onChanged: () => void }) {
  const names = useCandidateNames(proposal);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [stepUp, setStepUp] = useState(false);

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await post(`/trust/proposals/${proposal.id}/approve`);
      onChanged();
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
    setError(null);
    try {
      await post(`/trust/proposals/${proposal.id}/reject`, { reason });
      onChanged();
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <li className="py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className="text-lg font-semibold">{proposal.summary}</h2>
          <p className="text-sm text-ink-soft">Proposed {humanDate(proposal.created_at)}</p>
        </div>
        <RiskTag risk={proposal.risk} />
      </div>

      {names ? (
        <ol className="mt-3 list-decimal pl-5">
          {names.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ol>
      ) : typeof proposal.payload.reason === "string" ? (
        <p className="mt-3">Reason given: {proposal.payload.reason}</p>
      ) : null}

      <div className="mt-3">
        <ErrorNote message={error} />
      </div>

      {stepUp ? (
        <form onSubmit={confirmPassword} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="font-medium">
            Confirm your password to approve this
            <input
              name="password"
              type="password"
              required
              autoFocus
              autoComplete="current-password"
              className="mt-1 block rounded-md border border-line bg-surface px-3 py-2"
            />
          </label>
          <Button type="submit" disabled={busy}>
            Confirm and approve
          </Button>
          <Button variant="secondary" onClick={() => setStepUp(false)}>
            Cancel
          </Button>
        </form>
      ) : rejecting ? (
        <form onSubmit={reject} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="min-w-64 flex-1 font-medium">
            Why are you rejecting this?
            <input
              name="reason"
              required
              autoFocus
              className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2"
            />
          </label>
          <Button type="submit" variant="danger" disabled={busy}>
            Reject
          </Button>
          <Button variant="secondary" onClick={() => setRejecting(false)}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={approve} disabled={busy}>
            Approve
          </Button>
          <Button variant="secondary" onClick={() => setRejecting(true)} disabled={busy}>
            Reject
          </Button>
          <Button variant="quiet" onClick={() => setWhy(true)}>
            Why this suggestion?
          </Button>
        </div>
      )}

      {why ? (
        <WhyPanel
          decisionId={proposal.decision_record_id}
          title={proposal.summary}
          onClose={() => setWhy(false)}
        />
      ) : null}
    </li>
  );
}

export default function ApprovalsPage() {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    get<Proposal[]>("/trust/proposals?status=pending_approval")
      .then(setProposals)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Agents can only suggest. Nothing here happens until you approve it."
      />
      <ErrorNote message={error} />
      {!proposals && !error ? <Loading /> : null}
      {proposals?.length === 0 ? (
        <EmptyState title="Nothing is waiting">New suggestions from the agents appear here.</EmptyState>
      ) : null}
      {proposals && proposals.length > 0 ? (
        <ul className="divide-y divide-line border-y border-line">
          {proposals.map((proposal) => (
            <ProposalItem key={proposal.id} proposal={proposal} onChanged={load} />
          ))}
        </ul>
      ) : null}
    </>
  );
}
