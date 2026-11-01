"use client";

import { useEffect, useId, useRef } from "react";

/**
 * The crew. Each agent has its own head shape and colour, and its mood is its real state:
 * working when a run is in progress, waiting when a person owes it a decision, asleep when idle.
 */

export type Mood = "idle" | "working" | "waiting" | "asleep" | "alert" | "happy";

export interface Agent {
  id: string;
  name: string;
  role: string;
  does: string;
  pack: "talent" | "kernel" | "journey";
  shape: "round" | "squircle" | "hex" | "bean" | "tall" | "wide";
  hue: number;
  feature?: "antenna" | "ears" | "bow" | "tuft" | "visor" | "bolts";
}

export const AGENTS: Agent[] = [
  { id: "rubric_builder", name: "Mira", role: "Drafts job criteria", does: "Reads a job description and proposes what should count. A person activates it.", pack: "talent", shape: "squircle", hue: 275, feature: "tuft" },
  { id: "cv_reader", name: "Idris", role: "Reads CVs", does: "Reads each CV without the name or photo, and checks every quote word for word.", pack: "talent", shape: "round", hue: 232, feature: "visor" },
  { id: "ranking", name: "Nour", role: "Ranks candidates", does: "Scores by formula, never by opinion, and explains every point with evidence.", pack: "talent", shape: "hex", hue: 196, feature: "antenna" },
  { id: "inbox_triage", name: "Salem", role: "Sorts the inbox", does: "Sorts every email by type and urgency and flags those that need a person.", pack: "kernel", shape: "wide", hue: 160, feature: "ears" },
  { id: "reply_drafter", name: "Yara", role: "Drafts replies", does: "Drafts from that candidate's file only. Nothing is sent until someone approves.", pack: "talent", shape: "bean", hue: 340, feature: "bow" },
  { id: "followup", name: "Tarek", role: "Prepares follow-ups", does: "Notices who went quiet and prepares a reminder, up to two per candidate.", pack: "talent", shape: "tall", hue: 40, feature: "antenna" },
  { id: "scheduler", name: "Dali", role: "Finds interview times", does: "Holds three real free times from the calendars and prepares the invitation.", pack: "talent", shape: "squircle", hue: 18, feature: "bolts" },
  { id: "policy_answers", name: "Hela", role: "Answers policy questions", does: "Answers only from company policy, with citations, or passes it to HR.", pack: "kernel", shape: "round", hue: 300, feature: "tuft" },
  { id: "onboarding_planner", name: "Aziz", role: "Plans onboarding", does: "Prepares a 30/60/90 plan when someone joins. HR activates it.", pack: "journey", shape: "wide", hue: 130, feature: "bolts" },
  { id: "skill_gap_analyst", name: "Rym", role: "Spots skill gaps", does: "Compares evidence against role needs and explains each gap it proposes.", pack: "journey", shape: "bean", hue: 212, feature: "ears" },
  { id: "training_planner", name: "Malek", role: "Plans training", does: "Proposes training tied to a KPI, with its cost and expected effect.", pack: "journey", shape: "hex", hue: 80, feature: "visor" },
];

const FALLBACK: Agent = { id: "agent", name: "Agent", role: "Background agent", does: "", pack: "kernel", shape: "round", hue: 240 };

export function agentById(id: string): Agent {
  return AGENTS.find((agent) => agent.id === id) ?? { ...FALLBACK, id, role: id.replace(/_/g, " ") };
}

const HEADS: Record<Agent["shape"], string> = {
  round: "M32 10c13 0 23 9.5 23 22.5S45 56 32 56 9 45.500 9 32.500 19 10 32 10z",
  squircle: "M24 11h16c10 0 15 5 15 15v14c0 10-5 15-15 15H24c-10 0-15-5-15-15V26c0-10 5-15 15-15z",
  hex: "M26 9.500c3.700-2 8.300-2 12 0l13 7.200c3.700 2.100 6 6 6 10.300v12c0 4.300-2.300 8.200-6 10.300l-13 7.200c-3.700 2-8.300 2-12 0l-13-7.200c-3.700-2.100-6-6-6-10.300V27c0-4.300 2.300-8.200 6-10.300z",
  bean: "M34 10c12 0 21 8 21 21 0 14-10 25-24 25C18 56 9 47 9 35c0-9 4-13 7-17 4-5 9-8 18-8z",
  tall: "M32 7c11 0 18 7 18 18v18c0 9-7 14-18 14s-18-5-18-14V25C14 14 21 7 32 7z",
  wide: "M20 15h24c10 0 17 7 17 17s-7 22-17 22H20C10 54 3 42 3 32s7-17 17-17z",
};

function Feature({ kind, hue }: { kind: Agent["feature"]; hue: number }) {
  const dark = `oklch(0.5 0.13 ${hue})`;
  const light = `oklch(0.85 0.1 ${hue})`;
  switch (kind) {
    case "antenna":
      return (
        <g>
          <path d="M32 11V3" stroke={dark} strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="32" cy="3" r="2.6" fill={light} stroke={dark} strokeWidth="1.5" />
        </g>
      );
    case "ears":
      return (
        <g fill={dark}>
          <rect x="1" y="26" width="6" height="13" rx="3" />
          <rect x="57" y="26" width="6" height="13" rx="3" />
        </g>
      );
    case "bow":
      return (
        <path d="M44 9l-7 4 7 5 2-4zM52 9l7 4-7 5-2-4z" transform="translate(-4 -3)" fill={dark} />
      );
    case "tuft":
      return (
        <path
          d="M26 13c-1-5 2-8 5-10 0 3 1 4 3 6 1-2 3-3 5-3-1 3-1 5-3 8z"
          fill={dark}
        />
      );
    case "bolts":
      return (
        <g fill={dark}>
          <circle cx="6.500" cy="33" r="3.500" />
          <circle cx="57.500" cy="33" r="3.500" />
        </g>
      );
    default:
      return null;
  }
}

export function Face({
  agent,
  mood = "idle",
  size = 40,
  track = false,
}: {
  agent: Agent;
  mood?: Mood;
  size?: number;
  track?: boolean;
}) {
  const id = useId();
  const eyes = useRef<SVGGElement>(null);
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!track) return;
    function onMove(event: PointerEvent) {
      const box = svg.current?.getBoundingClientRect();
      if (!box || !eyes.current) return;
      const dx = event.clientX - (box.left + box.width / 2);
      const dy = event.clientY - (box.top + box.height / 2);
      const distance = Math.hypot(dx, dy) || 1;
      const reach = Math.min(2.4, distance / 60);
      eyes.current.style.transform = `translate(${(dx / distance) * reach}px, ${(dy / distance) * reach}px)`;
    }
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [track]);

  const top = `oklch(0.8 0.11 ${agent.hue})`;
  const bottom = `oklch(0.64 0.14 ${agent.hue})`;
  const asleep = mood === "asleep";
  const eye = mood === "alert" ? "#ffd27a" : "#ffffff";

  return (
    <svg
      ref={svg}
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={`${agent.name}, ${mood}`}
      className={`shrink-0 overflow-visible ${mood === "working" ? "face-working" : ""}`}
    >
      <defs>
        <linearGradient id={`${id}-h`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={top} />
          <stop offset="1" stopColor={bottom} />
        </linearGradient>
      </defs>
      <g className={asleep ? "" : "face-bob"}>
        <Feature kind={agent.feature} hue={agent.hue} />
        <path d={HEADS[agent.shape]} fill={`url(#${id}-h)`} />
        <rect x="14" y="22" width="36" height="24" rx="11" fill="#191c33" />
        {asleep ? (
          <g stroke="#9aa0bd" strokeWidth="2.200" strokeLinecap="round" fill="none">
            <path d="M21 34c1.500 1.500 4 1.500 5.500 0" />
            <path d="M37.500 34c1.500 1.500 4 1.500 5.500 0" />
          </g>
        ) : (
          <g ref={eyes} style={{ transition: "transform 90ms ease-out" }}>
            <g className="face-eyes">
              {mood === "happy" ? (
                <g stroke={eye} strokeWidth="2.600" strokeLinecap="round" fill="none">
                  <path d="M20.500 35c1.200-3.500 5-3.500 6.200 0" />
                  <path d="M37.300 35c1.200-3.500 5-3.500 6.200 0" />
                </g>
              ) : (
                <g className="face-blink" fill={eye}>
                  <ellipse cx="24" cy="33.500" rx={mood === "waiting" ? 3.700 : 3.300} ry={mood === "waiting" ? 4.300 : 3.900} />
                  <ellipse cx="40" cy="33.500" rx={mood === "waiting" ? 3.700 : 3.300} ry={mood === "waiting" ? 4.300 : 3.900} />
                </g>
              )}
            </g>
          </g>
        )}
        {mood === "alert" ? (
          <path d="M28 41.500c2.500-1.500 5.500-1.500 8 0" stroke={eye} strokeWidth="1.800" strokeLinecap="round" fill="none" />
        ) : mood === "happy" || mood === "waiting" ? (
          <path d="M28 40.500c2.200 2 5.800 2 8 0" stroke="#fff" strokeOpacity="0.85" strokeWidth="1.800" strokeLinecap="round" fill="none" />
        ) : null}
      </g>
    </svg>
  );
}

/** A row of overlapping faces, the crew at a glance. */
export function Crew({
  moods,
  size = 34,
  onPick,
}: {
  moods: Record<string, Mood>;
  size?: number;
  onPick?: (agent: Agent) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {AGENTS.map((agent) => {
        const mood = moods[agent.id] ?? "idle";
        return (
          <button
            key={agent.id}
            type="button"
            onClick={() => onPick?.(agent)}
            title={`${agent.name}: ${agent.role}`}
            className="rounded-full transition-transform duration-150 hover:-translate-y-0.5"
          >
            <Face agent={agent} mood={mood} size={size} track />
          </button>
        );
      })}
    </div>
  );
}
