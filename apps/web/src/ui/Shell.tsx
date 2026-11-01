"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  get,
  type Job,
  type Me,
  post,
  type Proposal,
  type ThreadPage,
} from "@/lib/api";
import { useLocal } from "@/lib/local";
import { AGENTS } from "./Face";
import { Icon } from "./Icon";
import { ago, Avatar, Loading, Modal, titleCase } from "./kit";
import { Logo } from "./Logo";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

interface Toast {
  id: number;
  text: string;
  tone: "ok" | "bad";
}
const ToastContext = createContext<(text: string, tone?: Toast["tone"]) => void>(() => undefined);
export const useToast = () => useContext(ToastContext);

const ALL = ["admin", "hr", "recruiter", "manager", "finance", "employee", "auditor"];

const NAV: { group: string | null; items: { href: string; label: string; icon: string; roles: string[]; badge?: "approvals" | "inbox" }[] }[] = [
  {
    group: null,
    items: [
      { href: "/overview", label: "Overview", icon: "home", roles: ALL },
      { href: "/approvals", label: "Approvals", icon: "stamp", roles: ALL, badge: "approvals" },
      { href: "/inbox", label: "Inbox", icon: "inbox", roles: ["admin", "hr", "recruiter", "auditor"], badge: "inbox" },
    ],
  },
  {
    group: "Hiring",
    items: [
      { href: "/jobs", label: "Jobs", icon: "brief", roles: ["admin", "hr", "recruiter", "auditor"] },
      { href: "/candidates", label: "Candidates", icon: "users", roles: ["admin", "hr", "recruiter", "auditor"] },
      { href: "/interviews", label: "Interviews", icon: "calendar", roles: ["admin", "hr", "recruiter", "manager"] },
    ],
  },
  {
    group: "People",
    items: [
      { href: "/onboarding", label: "Onboarding", icon: "sprout", roles: ["admin", "hr", "manager", "employee"] },
      { href: "/payroll", label: "Payroll", icon: "coin", roles: ["admin", "hr", "finance", "auditor"] },
      { href: "/ask", label: "Ask HR", icon: "chat", roles: ALL },
    ],
  },
  {
    group: "Trust",
    items: [
      { href: "/agents", label: "Agents", icon: "bot", roles: ["admin", "hr", "recruiter", "auditor"] },
      { href: "/graph", label: "Graph", icon: "graph", roles: ["admin", "hr", "recruiter", "auditor", "manager"] },
      { href: "/audit", label: "Audit log", icon: "shield", roles: ["admin", "hr", "auditor"] },
      { href: "/reports", label: "Reports", icon: "chart", roles: ["admin", "hr", "recruiter", "auditor"] },
    ],
  },
];

function NavLink({
  href,
  label,
  icon,
  badge,
  active,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: string;
  badge?: number;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`group relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 font-[500] transition-colors duration-100 ${
        active ? "text-ink" : "text-ink-soft hover:bg-sunken hover:text-ink"
      }`}
    >
      {active ? (
        <motion.span
          layoutId="nav-active"
          transition={{ type: "spring", stiffness: 520, damping: 42 }}
          className="absolute inset-0 rounded-lg border border-line bg-surface shadow-soft"
        />
      ) : null}
      <Icon name={icon} className={`relative ${active ? "text-door" : ""}`} />
      <span className="relative flex-1 truncate">{label}</span>
      {badge ? (
        <span className="tabular relative min-w-5 rounded-md bg-door-wash px-1 text-center text-xs font-[600] text-door-deep">
          {badge}
        </span>
      ) : null}
    </Link>
  );
}

interface PaletteItem {
  id: string;
  label: string;
  hint: string;
  icon: string;
  run: () => void;
}

function Palette({ open, onClose, items }: { open: boolean; onClose: () => void; items: PaletteItem[] }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (q ? items.filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(q)) : items).slice(0, 9);
  }, [items, query]);

  function close() {
    setQuery("");
    setCursor(0);
    onClose();
  }

  return (
    <Modal open={open} onClose={close} label="Search and actions" width={560}>
      <div className="flex items-center gap-2.5 border-b border-line px-4">
        <Icon name="search" className="text-ink-faint" />
        <input
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setCursor((value) => Math.min(value + 1, results.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setCursor((value) => Math.max(value - 1, 0));
            } else if (event.key === "Enter" && results[cursor]) {
              results[cursor].run();
              close();
            }
          }}
          aria-label="Search pages, jobs and actions"
          placeholder="Search pages, jobs and actions"
          className="h-12 w-full bg-transparent text-[15px] outline-none placeholder:text-ink-faint"
        />
      </div>
      <ul className="p-1.5">
        {results.map((item, index) => (
          <li key={item.id}>
            <button
              type="button"
              onMouseEnter={() => setCursor(index)}
              onClick={() => {
                item.run();
                close();
              }}
              className={`flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left ${
                cursor === index ? "bg-door-wash text-door-deep" : "text-ink"
              }`}
            >
              <Icon name={item.icon} />
              <span className="flex-1 truncate font-[500]">{item.label}</span>
              <span className="text-[13px] text-ink-soft">{item.hint}</span>
            </button>
          </li>
        ))}
        {results.length === 0 ? <li className="px-3 py-6 text-center text-ink-soft">Nothing matches that.</li> : null}
      </ul>
    </Modal>
  );
}

function Bell({ proposals }: { proposals: Proposal[] }) {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useLocal<string>("bell.seen", "");
  const root = useRef<HTMLDivElement>(null);
  const unread = proposals.filter((proposal) => proposal.created_at > seen).length;

  useEffect(() => {
    if (!open) return;
    function away(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    window.addEventListener("mousedown", away);
    return () => window.removeEventListener("mousedown", away);
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label={`Notifications, ${unread} new`}
        onClick={() => {
          setOpen((value) => !value);
          if (proposals[0]) setSeen(proposals[0].created_at);
        }}
        className="relative flex size-8 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
      >
        <Icon name="bell" />
        {unread ? <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-bloom ring-2 ring-plaster" /> : null}
      </button>
      <AnimatePresence>
        {open ? (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute top-10 right-0 z-30 w-84 origin-top-right overflow-hidden rounded-xl border border-line bg-surface shadow-float"
          >
            <p className="border-b border-line px-3.5 py-2.5 font-[560]">From your agents</p>
            <ul className="max-h-80 overflow-y-auto">
              {proposals.slice(0, 8).map((proposal) => (
                <li key={proposal.id}>
                  <Link
                    href="/approvals"
                    onClick={() => setOpen(false)}
                    className="row-hover block border-b border-line px-3.5 py-2.5 last:border-0"
                  >
                    <p className="line-clamp-2">{proposal.summary}</p>
                    <p className="mt-0.5 text-[13px] text-ink-soft">{ago(proposal.created_at)}</p>
                  </Link>
                </li>
              ))}
              {proposals.length === 0 ? (
                <li className="px-3.5 py-6 text-center text-ink-soft">Your agents have nothing waiting.</li>
              ) : null}
            </ul>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [openThreads, setOpenThreads] = useState(0);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [palette, setPalette] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setTheme] = useLocal<"system" | "light" | "dark">("theme", "system");

  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    get<Me>("/auth/me")
      .then(setMe)
      .catch((error: ApiError) => {
        if (error.status === 401) router.replace("/login");
      });
  }, [router]);

  useEffect(() => {
    if (!me) return;
    const load = () => {
      get<Proposal[]>("/trust/proposals?status=pending_approval")
        .then(setProposals)
        .catch(() => undefined);
      get<ThreadPage>("/comms/threads?status=open&needs_human=true&limit=50")
        .then((page) => setOpenThreads(page.items.length))
        .catch(() => undefined);
    };
    load();
    get<Job[]>("/packs/talent/jobs")
      .then(setJobs)
      .catch(() => undefined);
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [me, pathname]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((value) => !value);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toast = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list, { id, text, tone }]);
    setTimeout(() => setToasts((list) => list.filter((item) => item.id !== id)), 3600);
  }, []);

  const items = useMemo<PaletteItem[]>(() => {
    if (!me) return [];
    const pages = NAV.flatMap((section) => section.items)
      .filter((item) => item.roles.some((role) => me.roles.includes(role)))
      .map((item) => ({
        id: item.href,
        label: item.label,
        hint: "Go to page",
        icon: item.icon,
        run: () => router.push(item.href),
      }));
    const jobItems = jobs.map((job) => ({
      id: job.id,
      label: job.title,
      hint: "Job",
      icon: "brief",
      run: () => router.push(`/jobs/${job.id}`),
    }));
    const agents = AGENTS.map((agent) => ({
      id: agent.id,
      label: `${agent.name}, ${agent.role.toLowerCase()}`,
      hint: "Agent",
      icon: "bot",
      run: () => router.push(`/agents?agent=${agent.id}`),
    }));
    return [
      { id: "new-job", label: "Create a job", hint: "Action", icon: "plus", run: () => router.push("/jobs?new=1") },
      { id: "ask", label: "Ask a policy question", hint: "Action", icon: "chat", run: () => router.push("/ask") },
      { id: "settings", label: "Settings", hint: "Go to page", icon: "gear", run: () => router.push("/settings") },
      ...pages,
      ...jobItems,
      ...agents,
    ];
  }, [me, jobs, router]);

  if (!me) {
    return (
      <main className="mx-auto max-w-lg p-16">
        <Loading />
      </main>
    );
  }

  async function signOut() {
    await post("/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  const dark =
    theme === "dark" ||
    (theme === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  const sidebar = (
    <>
      <Link href="/overview" className="flex h-9 items-center gap-2 px-2.5" onClick={() => setMobileNav(false)}>
        <Logo />
        <span className="text-[15px] font-[600] tracking-tight">AstraRH</span>
      </Link>
      <nav aria-label="Main" className="mt-3 flex-1 space-y-4 overflow-y-auto">
        {NAV.map((section) => {
          const visible = section.items.filter((item) => item.roles.some((role) => me.roles.includes(role)));
          if (!visible.length) return null;
          return (
            <div key={section.group ?? "home"} className="space-y-0.5">
              {section.group ? <p className="px-2.5 pb-1 text-[13px] text-ink-faint">{section.group}</p> : null}
              {visible.map((item) => (
                <NavLink
                  key={item.href}
                  href={item.href}
                  label={item.label}
                  icon={item.icon}
                  active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
                  onNavigate={() => setMobileNav(false)}
                  badge={item.badge === "approvals" ? proposals.length : item.badge === "inbox" ? openThreads : undefined}
                />
              ))}
            </div>
          );
        })}
      </nav>
      <div className="mt-3 space-y-0.5 border-t border-line pt-3">
        <NavLink
          href="/settings"
          label="Settings"
          icon="gear"
          active={pathname.startsWith("/settings")}
          onNavigate={() => setMobileNav(false)}
        />
        <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5">
          <Avatar name={me.display_name} size={24} />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-[500]">{me.display_name}</span>
            <span className="block truncate text-[12px] text-ink-soft">{me.roles.map((role) => (role === "hr" ? "HR" : titleCase(role))).join(", ")}</span>
          </span>
          <button
            type="button"
            aria-label="Sign out"
            title="Sign out"
            onClick={signOut}
            className="rounded-md p-1 text-ink-faint transition-colors hover:bg-sunken hover:text-ink"
          >
            <Icon name="out" />
          </button>
        </div>
      </div>
    </>
  );

  return (
    <MeContext.Provider value={me}>
      <ToastContext.Provider value={toast}>
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-plaster p-2.5 md:flex">
            {sidebar}
          </aside>
          <AnimatePresence>
            {mobileNav ? (
              <div className="fixed inset-0 z-40 md:hidden">
                <motion.div
                  className="absolute inset-0 bg-night/30"
                  onClick={() => setMobileNav(false)}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                />
                <motion.aside
                  className="absolute inset-y-0 left-0 flex w-64 flex-col bg-plaster p-2.5 shadow-float"
                  initial={{ x: -280 }}
                  animate={{ x: 0 }}
                  exit={{ x: -280 }}
                  transition={{ type: "spring", stiffness: 420, damping: 42 }}
                >
                  {sidebar}
                </motion.aside>
              </div>
            ) : null}
          </AnimatePresence>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-line bg-plaster/85 px-3 backdrop-blur-md md:px-6">
              <button
                type="button"
                aria-label="Open menu"
                onClick={() => setMobileNav(true)}
                className="flex size-8 items-center justify-center rounded-lg text-ink-soft hover:bg-sunken md:hidden"
              >
                <Icon name="sliders" />
              </button>
              <button
                type="button"
                onClick={() => setPalette(true)}
                className="flex h-8 w-full max-w-sm items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-ink-faint shadow-soft transition-colors hover:border-line-strong"
              >
                <Icon name="search" />
                <span className="flex-1 truncate text-left">Search or jump to</span>
                <kbd className="hidden rounded border border-line px-1 text-[11px] sm:block">Ctrl K</kbd>
              </button>
              <div className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  aria-label={dark ? "Use light theme" : "Use dark theme"}
                  onClick={() => setTheme(dark ? "light" : "dark")}
                  className="flex size-8 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
                >
                  <Icon name={dark ? "sun" : "moon"} />
                </button>
                <Bell proposals={proposals} />
              </div>
            </header>
            <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-7">
              <motion.div
                key={pathname}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="mx-auto max-w-[1180px]"
              >
                {children}
              </motion.div>
            </main>
          </div>
        </div>
        <Palette open={palette} onClose={() => setPalette(false)} items={items} />
        <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2">
          <AnimatePresence>
            {toasts.map((item) => (
              <motion.div
                key={item.id}
                layout
                initial={{ opacity: 0, y: 12, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 12 }}
                transition={{ type: "spring", stiffness: 520, damping: 36 }}
                className="flex items-center gap-2 rounded-xl bg-night px-3.5 py-2.5 text-white shadow-float"
              >
                <Icon name={item.tone === "ok" ? "check" : "alert"} className={item.tone === "ok" ? "text-[#7fe0b3]" : "text-[#ffb4a8]"} />
                {item.text}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </ToastContext.Provider>
    </MeContext.Provider>
  );
}
