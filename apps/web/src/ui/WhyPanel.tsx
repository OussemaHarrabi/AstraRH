"use client";

import { useState } from "react";
import { type ApiError, get, post, type Why } from "@/lib/api";
import { EvidenceStrip } from "./EvidenceStrip";
import { Icon } from "./Icon";
import { Button, Drawer, ErrorNote, humanDate, Loading, percent, Tag, useLoad, withoutCitations } from "./kit";

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

/** The explanation itself, usable in a drawer or inline in a review pane. */
export function WhyBody({ decisionId }: { decisionId: string }) {
  const { data: why, error } = useLoad(() => get<Why>(`/explain/${decisionId}`), [decisionId]);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function runVerify() {
    setVerifying(true);
    try {
      setVerify(await post<VerifyResult>(`/explain/${decisionId}/verify`));
    } catch (e) {
      setFailure((e as ApiError).message);
    } finally {
      setVerifying(false);
    }
  }

  if (error) return <ErrorNote message={error} />;
  if (!why) return <Loading rows={6} />;
  const outcome = why.outcome ?? {};

  return (
    <div className="space-y-6">
      <ErrorNote message={failure} />
      {why.score !== null ? (
        <section>
          <div className="flex items-baseline gap-3">
            <p className="tabular text-[40px] leading-none font-[520] tracking-tight">
              {percent(why.score)}
              <span className="text-lg text-ink-soft"> / 100</span>
            </p>
            {outcome.rank ? (
              <p className="text-ink-soft">
                Rank {String(outcome.rank)} of {String(outcome.candidates)}
              </p>
            ) : null}
          </div>
          <div className="mt-3">
            <EvidenceStrip factors={why.factors} large />
          </div>
          {outcome.meets_must_haves === false ? (
            <p className="mt-2 text-ochre">Does not meet every must-have, so ranks below those who do.</p>
          ) : null}
        </section>
      ) : null}

      {why.narrative || why.rationale ? (
        <section>
          <p className="text-[15px] leading-relaxed">{withoutCitations(why.narrative ?? why.rationale ?? "")}</p>
          {why.narrative ? <p className="mt-1 text-[13px] text-ink-soft">Written by AI from the numbers below. It did not decide the rank.</p> : null}
        </section>
      ) : null}

      {why.factors.length > 0 ? (
        <section>
          <h3 className="font-[560]">How the score adds up</h3>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {why.factors.map((factor) => {
              const quotes = why.evidence.filter((e) => e.factor_key === factor.key);
              return (
                <li key={factor.key} className="py-2.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="font-[520]">{factor.label}</span>
                    <span className="tabular text-[13px] text-ink-soft">
                      {Number((Number(factor.weight) * 100).toFixed(1))} pts × {Math.round(Number(factor.value) * 100)}% ={" "}
                      <strong className="font-[600] text-ink">{(Number(factor.contribution) * 100).toFixed(1)}</strong>
                    </span>
                  </div>
                  {quotes.length === 0 ? (
                    <p className="mt-0.5 text-[13px] text-ink-soft">
                      {factor.key === "job_match" ? "Meaning and exact terms across the whole CV." : "No evidence found in this CV."}
                    </p>
                  ) : (
                    quotes.map((quote) => (
                      <blockquote key={quote.ref} dir="auto" className="mt-1.5 border-l-2 border-door pl-2.5">
                        <p>{quote.quote}</p>
                        <p className="text-[13px] text-ink-soft">
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

      {why.evidence.some((item) => !item.factor_key) ? (
        <section>
          <h3 className="font-[560]">What this is based on</h3>
          <div className="mt-1.5 space-y-1.5">
            {why.evidence
              .filter((item) => !item.factor_key)
              .map((item) => (
                <blockquote key={item.ref} dir="auto" className="border-l-2 border-door pl-2.5">
                  <p>{item.quote}</p>
                  <p className="text-[13px] text-ink-soft">From {item.source_type === "email" ? "their email, checked word for word" : item.source_type === "calendar" ? "the calendars" : "the file"}</p>
                </blockquote>
              ))}
          </div>
        </section>
      ) : null}

      {why.counterfactuals.length > 0 ? (
        <section>
          <h3 className="font-[560]">What would change this</h3>
          <ul className="mt-1.5 space-y-1">
            {why.counterfactuals.map((item) => (
              <li key={item.description} className="text-ink-soft">
                {item.description}: rank {item.outcome.rank}, score {percent(item.outcome.score)}.
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {why.limits.length > 0 ? (
        <section>
          <h3 className="font-[560]">Limits of this result</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-ink-soft">
            {why.limits.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {why.not_considered.length > 0 ? (
        <section className="flex gap-2 rounded-lg bg-plaster p-3">
          <Icon name="lock" className="mt-0.5 text-ink-soft" />
          <p className="text-ink-soft">
            <span className="font-[520] text-ink">Not considered:</span> {why.not_considered.join(", ")}. Removed before any AI reads the CV.
          </p>
        </section>
      ) : null}

      {why.human_decisions.length > 0 ? (
        <section>
          <h3 className="font-[560]">Human decision</h3>
          <ul className="mt-1.5 space-y-1">
            {why.human_decisions.map((decision) => (
              <li key={decision.at}>
                <Tag tone={decision.decision === "approved" ? "good" : "bad"}>{decision.decision === "approved" ? "Approved" : "Rejected"}</Tag>{" "}
                {humanDate(decision.at)}
                {decision.reason ? `: ${decision.reason}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {why.scorer ? (
        <section className="rounded-xl bg-door-wash p-4">
          <h3 className="font-[560]">Check this result</h3>
          <p className="mt-0.5">Recalculate the score from the stored facts and compare it with what was recorded.</p>
          <Button className="mt-2.5" onClick={runVerify} disabled={verifying}>
            {verifying ? "Recalculating…" : "Recalculate score"}
          </Button>
          {verify ? (
            <p role="status" className={`mt-2.5 font-[560] ${verify.match ? "text-olive" : "text-brick"}`}>
              {verify.match ? `Exact match: ${percent(verify.recomputed_score)} / 100.` : "Mismatch: this record no longer matches its stored facts."}
            </p>
          ) : null}
          <p className="mt-2.5 text-[13px] text-ink-soft">
            Formula {why.scorer}, criteria version {String(why.versions.rubric_version)}, similarity model {String(why.versions.embedding_model).split("/").pop()}.
          </p>
        </section>
      ) : null}
    </div>
  );
}

export function WhyPanel({ decisionId, title, onClose }: { decisionId: string; title: string; onClose: () => void }) {
  return (
    <Drawer open onClose={onClose} label={`Why: ${title}`}>
      <div className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-line bg-surface px-5 py-3">
        <h2 className="truncate text-[16px] font-[560]">{title}</h2>
        <Button variant="quiet" size="sm" onClick={onClose} aria-label="Close">
          <Icon name="close" size={14} />
        </Button>
      </div>
      <div className="p-5">
        <WhyBody decisionId={decisionId} />
      </div>
    </Drawer>
  );
}
