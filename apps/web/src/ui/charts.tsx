"use client";

import { useState } from "react";

/** Quiet charts: thin marks, a 2px gap between fills, and a tooltip on every mark. */

export const STAGE_COLORS: Record<string, string> = {
  applied: "#9aa3ea",
  shortlisted: "#4254db",
  interview: "#1b8fa0",
  hired: "#1f7a55",
  rejected: "#c5c8d4",
};

export function Tip({ x, y, children }: { x: number; y: number; children: React.ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg bg-night px-2 py-1 text-xs whitespace-nowrap text-white shadow-lift"
      style={{ left: x, top: y - 6 }}
    >
      {children}
    </div>
  );
}

export function StackedBar({
  parts,
  height = 10,
}: {
  parts: { key: string; label: string; value: number; color: string }[];
  height?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  if (total === 0) return <div className="rounded-full bg-sunken" style={{ height }} />;
  return (
    <div role="img" aria-label={parts.map((part) => `${part.label}: ${part.value}`).join(", ")} className="flex gap-[2px]" style={{ height }}>
      {parts
        .filter((part) => part.value > 0)
        .map((part) => (
          <div
            key={part.key}
            onMouseEnter={() => setHover(part.key)}
            onMouseLeave={() => setHover(null)}
            className="relative rounded-[3px] transition-opacity duration-100"
            style={{
              flexGrow: part.value,
              flexBasis: 0,
              minWidth: 4,
              background: part.color,
              opacity: hover && hover !== part.key ? 0.45 : 1,
            }}
          >
            {hover === part.key ? (
              <Tip x={0} y={0}>
                <span className="relative left-6">
                  {part.label}: {part.value}
                </span>
              </Tip>
            ) : null}
          </div>
        ))}
    </div>
  );
}

export function HBars({
  rows,
  color = "var(--door)",
  format = (value: number) => String(value),
}: {
  rows: { label: string; value: number; tone?: string }[];
  color?: string;
  format?: (value: number) => string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <ul className="space-y-1">
      {rows.map((row) => (
        <li key={row.label} className="group row-hover -mx-1.5 flex items-center gap-2.5 rounded-md px-1.5 py-1">
          <span className="w-32 shrink-0 truncate text-ink-soft group-hover:text-ink" title={row.label}>
            {row.label}
          </span>
          <span className="relative h-2 flex-1 rounded-full bg-sunken">
            <span
              className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-500"
              style={{ width: `${Math.max(3, (row.value / max) * 100)}%`, background: row.tone ?? color }}
            />
          </span>
          <span className="tabular w-10 text-right font-[520]">{format(row.value)}</span>
        </li>
      ))}
    </ul>
  );
}

export function AreaLine({
  points,
  height = 120,
  unit = "",
}: {
  points: { label: string; value: number }[];
  height?: number;
  unit?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const pad = 6;
  const max = Math.max(1, ...points.map((point) => point.value));
  const x = (index: number) => pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2);
  const y = (value: number) => height - 18 - (value / max) * (height - 34);
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index)} ${y(point.value)}`).join(" ");
  const area = `${line} L${x(points.length - 1)} ${height - 18} L${x(0)} ${height - 18} Z`;
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={points.map((point) => `${point.label}: ${point.value}`).join(", ")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - box.left) / box.width;
          setHover(Math.round(ratio * (points.length - 1)));
        }}
      >
        <defs>
          <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--door)" stopOpacity="0.16" />
            <stop offset="1" stopColor="var(--door)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1={pad} x2={width - pad} y1={height - 18} y2={height - 18} stroke="var(--line)" />
        {points.length > 1 ? <path d={area} fill="url(#area-fill)" /> : null}
        <path d={line} fill="none" stroke="var(--door)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {points.map((point, index) =>
          index % Math.ceil(points.length / 6) === 0 ? (
            <text key={point.label} x={x(index)} y={height - 4} fontSize="11" fill="var(--ink-faint)" textAnchor={index === 0 ? "start" : "middle"}>
              {point.label}
            </text>
          ) : null,
        )}
        {hover !== null && points[hover] ? (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={8} y2={height - 18} stroke="var(--line-strong)" />
            <circle cx={x(hover)} cy={y(points[hover].value)} r="4" fill="var(--door)" stroke="var(--surface)" strokeWidth="2" />
          </g>
        ) : null}
      </svg>
      {hover !== null && points[hover] ? (
        <Tip x={(x(hover) / width) * 100 + 0} y={0}>
          <span>{points[hover].label}: {points[hover].value}{unit}</span>
        </Tip>
      ) : null}
    </div>
  );
}

export function Ring({ value, size = 44, label }: { value: number; size?: number; label?: string }) {
  const radius = size / 2 - 3;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg width={size} height={size} role="img" aria-label={label ?? `${Math.round(value * 100)} percent`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--sunken)" strokeWidth="4" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--door)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - value)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 500ms" }}
      />
      <text x="50%" y="50%" dy=".35em" textAnchor="middle" fontSize={size * 0.26} fontWeight="560" fill="var(--ink)">
        {Math.round(value * 100)}
      </text>
    </svg>
  );
}
