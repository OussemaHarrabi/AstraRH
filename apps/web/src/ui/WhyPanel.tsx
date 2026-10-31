"use client";

import { useEffect, useState } from "react";
import { ApiError, get, post, type Why } from "@/lib/api";
import { EvidenceStrip } from "./EvidenceStrip";
import { Button, ErrorNote, Loading, Tag, humanDate, percent, withoutCitations } from "./kit";

interface VerifyResult {
  verifiable: boolean;
  match: boolean | null;
  inputs_intact: boolean;
  recorded_score?: string;
  recomputed_score?: string;
}

const EVIDENCE_KIND: Record<string, string> = {
  direct: "Proven in the CV",
  listed: "Only listed as a keyword",
  semantic: "Similar wording, not an exact match",
};

function evidenceLabel(kind?: string): string {
  if (!kind) return "From the CV";
  if (kind.startsWith("related:")) return `Related skill: ${kind.slice(8)}`;
  return EVIDENCE_KIND[kind] ?? "From the CV";
}

export function WhyPanel({
  decisionId,
  title,
  onClose,
}: {
  decisionId: string;
  title: string;
  onClose: () => void;
}) {
  const [why, setWhy] = useState<Why | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    get<Why>(`/explain/${decisionId}`)
      .then(setWhy)
      .catch((e: ApiError) => setError(e.message));
  }, [decisionId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function runVerify() {
    setVerifying(true);
    try {
      setVerify(await post<VerifyResult>(`/explain/${decisionId}/verify`));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setVerifying(false);
    }
  }

  const outcome = why?.outcome ?? {};
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Why: ${title}`}
        className="drawer-enter h-full w-full max-w-2xl overflow-y-auto bg-surface p-6 shadow-2xl md:p-8"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-ink-soft">{why?.question ?? "Explanation"}</p>
            <h2 className="mt-1 text-2xl font-bold">{title}</h2>
          </div>
          <Button variant="secondary" onClick={onClose} autoFocus>
            Close
          </Button>
        </div>

        <ErrorNote message={error} />
        {!why && !error ? <Loading /> : null}

        {why ? (
          <div className="mt-6 space-y-8">
            {why.score !== null ? (
              <section>
                <div className="flex items-baseline gap-5">
                  <p className="font-display text-5xl font-bold tabular">
                    {percent(why.score)}
                    <span className="text-2xl text-ink-soft"> / 100</span>
                  </p>
                  {outcome.rank ? (
                    <p className="text-lg">
                      Rank {String(outcome.rank)} of {String(outcome.candidates)}
                    </p>
                  ) : null}
                </div>
                <div className="mt-3">
                  <EvidenceStrip factors={why.factors} large />
                </div>
                {outcome.meets_must_haves === false ? (
                  <p className="mt-3 text-ochre">
                    Does not meet every must-have, so ranks below those who do.
                  </p>
                ) : null}
              </section>
            ) : null}

            {why.narrative || why.rationale ? (
              <section>
                <h3 className="text-lg font-semibold">In short</h3>
                <p className="mt-1">{withoutCitations(why.narrative ?? why.rationale ?? "")}</p>
                {why.narrative ? (
                  <p className="mt-1 text-sm text-ink-soft">
                    Written by AI from the numbers below. It did not decide the rank.
                  </p>
                ) : null}
              </section>
            ) : null}

            {why.factors.length > 0 ? (
              <section>
                <h3 className="text-lg font-semibold">How the score adds up</h3>
                <ul className="mt-3 divide-y divide-line border-y border-line">
                  {why.factors.map((factor) => {
                    const quotes = why.evidence.filter((e) => e.factor_key === factor.key);
                    return (
                      <li key={factor.key} className="py-3">
                        <div className="flex items-baseline justify-between gap-4">
                          <span className="font-semibold">{factor.label}</span>
                          <span className="tabular text-ink-soft">
                            {Number((Number(factor.weight) * 100).toFixed(1))} points ×{" "}
                            {Math.round(Number(factor.value) * 100)}% ={" "}
                            <strong className="text-ink">
                              {(Number(factor.contribution) * 100).toFixed(1)}
                            </strong>
                          </span>
                        </div>
                        {quotes.length === 0 ? (
                          <p className="mt-1 text-ink-soft">
                            {factor.key === "job_match"
                              ? "Combines similarity of meaning with matching exact terms, across the whole CV."
                              : "No evidence found in this CV."}
                          </p>
                        ) : (
                          quotes.map((quote) => (
                            <blockquote
                              key={quote.ref}
                              dir="auto"
                              className="mt-2 border-l-3 border-door pl-3"
                            >
                              <p>{quote.quote}</p>
                              <p className="text-sm text-ink-soft">
                                {evidenceLabel(quote.locator?.kind)}
                                {quote.locator?.years ? `, ${Number(quote.locator.years)} years` : ""}
                              </p>
                            </blockquote>
                          ))
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}

            {why.counterfactuals.length > 0 ? (
              <section>
                <h3 className="text-lg font-semibold">What would change this</h3>
                <ul className="mt-2 space-y-1">
                  {why.counterfactuals.map((item) => (
                    <li key={item.description}>
                      {item.description}: rank {item.outcome.rank}, score{" "}
                      {percent(item.outcome.score)}.
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {why.limits.length > 0 ? (
              <section>
                <h3 className="text-lg font-semibold">Limits of this result</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {why.limits.map((limit) => (
                    <li key={limit}>{limit}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            {why.not_considered.length > 0 ? (
              <section>
                <h3 className="text-lg font-semibold">Not considered</h3>
                <p className="mt-1">
                  {why.not_considered.join(", ")}. These are removed before any AI reads the CV.
                </p>
              </section>
            ) : null}

            {why.human_decisions.length > 0 ? (
              <section>
                <h3 className="text-lg font-semibold">Human decision</h3>
                <ul className="mt-2 space-y-1">
                  {why.human_decisions.map((decision) => (
                    <li key={decision.at}>
                      <Tag tone={decision.decision === "approved" ? "good" : "bad"}>
                        {decision.decision === "approved" ? "Approved" : "Rejected"}
                      </Tag>{" "}
                      {humanDate(decision.at)}
                      {decision.reason ? `: ${decision.reason}` : ""}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {why.scorer ? (
              <section className="rounded-[var(--radius)] bg-door-wash p-4">
                <h3 className="text-lg font-semibold">Check this result</h3>
                <p className="mt-1">
                  Recalculate the score from the stored facts and compare it with what was recorded.
                </p>
                <Button className="mt-3" onClick={runVerify} disabled={verifying}>
                  {verifying ? "Recalculating…" : "Recalculate score"}
                </Button>
                {verify ? (
                  <p
                    role="status"
                    className={`mt-3 font-semibold ${verify.match ? "text-olive" : "text-brick"}`}
                  >
                    {verify.match
                      ? `Exact match: ${percent(verify.recomputed_score)} / 100.`
                      : "Mismatch: this record no longer matches its stored facts."}
                  </p>
                ) : null}
                <p className="mt-3 text-sm text-ink-soft">
                  Formula {why.scorer}, criteria version {String(why.versions.rubric_version)},
                  similarity model {String(why.versions.embedding_model).split("/").pop()}.
                </p>
              </section>
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
}
