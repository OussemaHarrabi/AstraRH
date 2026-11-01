"use client";

import { useState } from "react";
import type { Factor } from "@/lib/api";
import { Tip } from "./charts";

/**
 * The formula, drawn. Each segment is one job criterion: its width is the weight the recruiter
 * approved, and its fill is how much the CV proved. The filled area is the score.
 */
export function EvidenceStrip({ factors, large = false }: { factors: Factor[]; large?: boolean }) {
  const [hover, setHover] = useState<string | null>(null);
  const description = factors.map((f) => `${f.label}: ${Math.round(Number(f.value) * 100)} percent proven`).join(", ");
  return (
    <div role="img" aria-label={description} className={`flex w-full gap-[2px] ${large ? "h-3.5" : "h-2"}`}>
      {factors.map((factor) => (
        <div
          key={factor.key}
          onMouseEnter={() => setHover(factor.key)}
          onMouseLeave={() => setHover(null)}
          className="relative rounded-[3px] bg-sunken"
          style={{ flexGrow: Number(factor.weight), flexBasis: 0 }}
        >
          <div
            className={`absolute inset-y-0 left-0 rounded-[3px] transition-colors duration-100 ${hover === factor.key ? "bg-door-deep" : "bg-door"}`}
            style={{ width: `${Number(factor.value) * 100}%` }}
          />
          {hover === factor.key ? (
            <Tip x={20} y={0}>
              {factor.label}: {Math.round(Number(factor.value) * 100)}% proven
            </Tip>
          ) : null}
        </div>
      ))}
    </div>
  );
}
