"use client";

import type { Factor } from "@/lib/api";

/**
 * The formula, drawn. Each segment is one job criterion: its width is the weight the recruiter
 * approved, and its fill is how much the CV proved. The filled area is the score.
 */
export function EvidenceStrip({ factors, large = false }: { factors: Factor[]; large?: boolean }) {
  const description = factors
    .map((f) => `${f.label}: ${Math.round(Number(f.value) * 100)} percent proven`)
    .join(", ");
  return (
    <div
      role="img"
      aria-label={description}
      className={`flex w-full gap-[3px] ${large ? "h-5" : "h-3"}`}
    >
      {factors.map((factor) => (
        <div
          key={factor.key}
          title={`${factor.label}: ${Math.round(Number(factor.value) * 100)}% proven, weight ${Math.round(Number(factor.weight) * 100)}%`}
          className="relative overflow-hidden rounded-[3px] bg-line"
          style={{ flexGrow: Number(factor.weight), flexBasis: 0 }}
        >
          <div
            className="absolute inset-y-0 left-0 bg-door"
            style={{ width: `${Number(factor.value) * 100}%` }}
          />
        </div>
      ))}
    </div>
  );
}
