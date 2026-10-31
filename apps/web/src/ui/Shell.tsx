"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, post, type Me, type Pack, type Proposal } from "@/lib/api";
import { Loading } from "./kit";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

function NavLink({
  href,
  label,
  badge,
  active,
}: {
  href: string;
  label: string;
  badge?: number;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`flex items-center justify-between rounded-md px-3 py-2 font-medium ${
        active ? "bg-white/15 text-white" : "text-[var(--rail-text)] hover:bg-white/10"
      }`}
    >
      {label}
      {badge ? (
        <span className="tabular rounded-full bg-white px-2 text-sm font-bold text-[#12233f]">
          {badge}
        </span>
      ) : null}
    </Link>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    get<Me>("/auth/me")
      .then(setMe)
      .catch((error: ApiError) => {
        if (error.status === 401) router.replace("/login");
      });
    get<Pack[]>("/registry/packs")
      .then(setPacks)
      .catch(() => setPacks([]));
  }, [router]);

  useEffect(() => {
    if (!me) return;
    const load = () =>
      get<Proposal[]>("/trust/proposals?status=pending_approval")
        .then((rows) => setPending(rows.length))
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [me, pathname]);

  if (!me) return <main className="p-10"><Loading label="Signing you in" /></main>;

  const canSeeAudit = me.roles.some((role) => ["admin", "auditor", "hr"].includes(role));
  const nav = packs.filter(
    (pack) =>
      pack.route && pack.status !== "off" && pack.roles.some((role) => me.roles.includes(role)),
  );

  async function signOut() {
    await post("/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  return (
    <MeContext.Provider value={me}>
      <div className="flex min-h-screen flex-col md:flex-row">
        <aside className="flex flex-col bg-[var(--rail)] p-4 md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0">
          <Link href="/" className="px-3 py-2 font-display text-2xl font-bold text-white">
            AstraRH
          </Link>
          <nav aria-label="Main" className="mt-4 flex flex-wrap gap-1 md:flex-col">
            <NavLink href="/" label="Today" active={pathname === "/"} />
            {nav.map((pack) => (
              <NavLink
                key={pack.id}
                href={pack.route as string}
                label={pack.nav_label ?? pack.name}
                active={pathname.startsWith(pack.route as string)}
              />
            ))}
            <NavLink
              href="/approvals"
              label="Approvals"
              badge={pending}
              active={pathname.startsWith("/approvals")}
            />
            <NavLink href="/ask" label="Ask HR" active={pathname.startsWith("/ask")} />
            {canSeeAudit ? (
              <NavLink href="/audit" label="History" active={pathname.startsWith("/audit")} />
            ) : null}
          </nav>
          <div className="mt-auto hidden px-3 pt-6 text-[var(--rail-text)] md:block">
            <p className="font-medium text-white">{me.display_name}</p>
            <button type="button" onClick={signOut} className="mt-1 hover:underline">
              Sign out
            </button>
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-9">
          <div className="mx-auto max-w-5xl">{children}</div>
        </main>
      </div>
    </MeContext.Provider>
  );
}
