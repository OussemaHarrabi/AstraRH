"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

/** The small shared kit: every module uses these, so the product reads as one. */

type Variant = "primary" | "secondary" | "soft" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-door text-white hover:bg-door-deep dark:text-plaster",
  secondary: "bg-surface text-ink border border-line hover:border-door",
  soft: "bg-door-wash text-door-deep hover:opacity-90",
  quiet: "text-door hover:underline",
  danger: "bg-surface text-brick border border-brick hover:bg-brick-wash",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`rounded-full px-4 py-2 text-[15px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-3xl font-bold md:text-4xl">{title}</h1>
        {subtitle ? <p className="mt-2 text-ink-soft">{subtitle}</p> : null}
      </div>
      {action}
    </header>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md bg-brick-wash px-3 py-2 text-brick">
      {message}
    </p>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p role="status" className="py-8 text-ink-soft">
      {label}…
    </p>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius)] border border-dashed border-line px-6 py-10 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      {children ? <div className="mt-2 text-ink-soft">{children}</div> : null}
    </div>
  );
}

export function Tag({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "warn" | "good" | "bad" | "info";
  children: ReactNode;
}) {
  const tones = {
    neutral: "bg-plaster text-ink-soft border border-line",
    warn: "bg-ochre-wash text-ochre",
    good: "bg-olive-wash text-olive",
    bad: "bg-brick-wash text-brick",
    info: "bg-door-wash text-door-deep",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-sm font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

const RISK_LABELS: Record<string, { label: string; tone: "info" | "warn" | "neutral" }> = {
  R0: { label: "Automatic", tone: "neutral" },
  R1: { label: "Draft only", tone: "neutral" },
  R2: { label: "Needs your approval", tone: "info" },
  R3: { label: "Needs a second person", tone: "warn" },
};

export function RiskTag({ risk }: { risk: string }) {
  const entry = RISK_LABELS[risk] ?? RISK_LABELS.R2;
  return <Tag tone={entry.tone}>{entry.label}</Tag>;
}

/** Citation markers are for the validator, not for the person reading. */
export function withoutCitations(text: string): string {
  return text.replace(/\s*\[E\d+\]/g, "").replace(/\s+([.,])/g, "$1");
}

export function humanDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function percent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(Number(value) * 100)}`;
}
