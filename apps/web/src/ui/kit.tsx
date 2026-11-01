"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  type ButtonHTMLAttributes,
  type DependencyList,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

/** The small shared kit: every page uses these, so the product reads as one. */

type Variant = "primary" | "secondary" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-door text-white hover:bg-door-deep shadow-soft dark:text-plaster",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-plaster shadow-soft",
  quiet: "text-ink-soft hover:bg-sunken hover:text-ink",
  danger: "bg-surface text-brick border border-line-strong hover:bg-brick-wash shadow-soft",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "h-7 px-2.5 text-[13px]" : "h-8.5 px-3.5";
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-[520] whitespace-nowrap transition-[background-color,color,transform] duration-100 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 ${sizing} ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-[26px] font-[520]">{title}</h1>
        {subtitle ? <p className="mt-1 text-[15px] text-ink-soft">{subtitle}</p> : null}
      </div>
      {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
    </header>
  );
}

export function Panel({
  title,
  action,
  children,
  className = "",
  flush = false,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface shadow-soft ${className}`}>
      {title || action ? (
        <div className="flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2">
          <h2 className="text-sm font-[560]">{title}</h2>
          {action}
        </div>
      ) : null}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export function ErrorNote({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p role="alert" className="mb-3 rounded-lg bg-brick-wash px-3 py-2 text-brick">
      {message}
    </p>
  );
}

export function Loading({ rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-3 py-3">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton h-4" style={{ width: `${92 - index * 11}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  art,
}: {
  title: string;
  children?: ReactNode;
  art?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {art}
      <p className="mt-2 text-[15px] font-[560]">{title}</p>
      {children ? <div className="mt-1 max-w-sm text-ink-soft">{children}</div> : null}
    </div>
  );
}

export type Tone = "neutral" | "warn" | "good" | "bad" | "info" | "bloom";

const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-soft",
  warn: "bg-ochre-wash text-ochre",
  good: "bg-olive-wash text-olive",
  bad: "bg-brick-wash text-brick",
  info: "bg-door-wash text-door-deep",
  bloom: "bg-bloom-wash text-bloom",
};

export function Tag({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-xs font-[520] whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

const RISK_LABELS: Record<string, { label: string; tone: Tone }> = {
  R0: { label: "Automatic", tone: "neutral" },
  R1: { label: "Logged", tone: "neutral" },
  R2: { label: "Your approval", tone: "info" },
  R3: { label: "Two people", tone: "bloom" },
};

export function RiskTag({ risk }: { risk: string }) {
  const entry = RISK_LABELS[risk] ?? RISK_LABELS.R2;
  return <Tag tone={entry.tone}>{entry.label}</Tag>;
}

const AVATAR_HUES = [228, 268, 320, 180, 28, 150, 200, 345];

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const hash = [...name].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const hue = AVATAR_HUES[hash % AVATAR_HUES.length];
  const initials = name
    .split(/[\s.@]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span
      aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full font-[560] text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: `oklch(0.58 0.11 ${hue})`,
      }}
    >
      {initials}
    </span>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  const group = useId();
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={`relative h-9 px-2.5 font-[520] whitespace-nowrap transition-colors ${
            value === tab.id ? "text-ink" : "text-ink-soft hover:text-ink"
          }`}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="tabular ml-1.5 text-ink-faint">{tab.count}</span>
          ) : null}
          {value === tab.id ? (
            <motion.span
              layoutId={group}
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
              className="absolute inset-x-1 -bottom-px h-0.5 rounded-full bg-door"
            />
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function Drawer({
  open,
  onClose,
  label,
  width = 620,
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  width?: number;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-40 flex justify-end">
          <motion.div
            className="absolute inset-0 bg-night/30"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label={label}
            className="relative h-full w-full overflow-y-auto border-l border-line bg-surface shadow-float"
            style={{ maxWidth: width }}
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 24, opacity: 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 40 }}
          >
            {children}
          </motion.aside>
        </div>
      ) : null}
    </AnimatePresence>
  );
}

export function Modal({
  open,
  onClose,
  label,
  children,
  width = 480,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
          <motion.div
            className="absolute inset-0 bg-night/35"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.14 }}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={label}
            className="relative max-h-[76vh] w-full overflow-y-auto rounded-2xl border border-line bg-surface shadow-float"
            style={{ maxWidth: width }}
            initial={{ y: 10, opacity: 0, scale: 0.985 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 6, opacity: 0, scale: 0.99 }}
            transition={{ type: "spring", stiffness: 520, damping: 38 }}
          >
            {children}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block font-[520]">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[13px] text-ink-soft">{hint}</span> : null}
    </label>
  );
}

/** Fetch on mount and on demand. Keeps the last data while reloading, so nothing flickers. */
export function useLoad<T>(load: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  });
  const key = JSON.stringify(deps);
  const reload = useCallback(
    () =>
      latest
        .current()
        .then((value) => {
          setData(value);
          setError(null);
          return value;
        })
        .catch((failure: Error) => {
          setError(failure.message);
          return null;
        }),
    [],
  );
  useEffect(() => {
    let live = true;
    latest
      .current()
      .then((value) => {
        if (!live) return;
        setData(value);
        setError(null);
      })
      .catch((failure: Error) => {
        if (live) setError(failure.message);
      });
    return () => {
      live = false;
    };
  }, [key]);
  return { data, error, reload, setData };
}

/** Citation markers are for the validator, not for the person reading. */
export function withoutCitations(text: string): string {
  return text.replace(/\s*\[[EC]\d+\]/g, "").replace(/\s+([.,])/g, "$1");
}

export function humanDate(value: string): string {
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dayLabel(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function timeLabel(value: string): string {
  return new Date(value).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function ago(value: string): string {
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 0) return dayLabel(value);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return dayLabel(value);
}

export function percent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(Number(value) * 100)}`;
}

export function titleCase(value: string): string {
  const text = value.replace(/[_.]/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
