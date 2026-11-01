"use client";

import { useMotionValue } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ApiError, post } from "@/lib/api";
import { Button, ErrorNote, Field } from "@/ui/kit";
import { Logo } from "@/ui/Logo";
import { Scene } from "@/ui/landing/Scene";

const DEMO_USERS = [
  { email: "nadia@cds.example.test", who: "Nadia", role: "Recruiter" },
  { email: "leila@cds.example.test", who: "Leila", role: "HR" },
  { email: "sami@cds.example.test", who: "Sami", role: "Finance" },
  { email: "karim@cds.example.test", who: "Karim", role: "Manager" },
  { email: "mehdi@cds.example.test", who: "Mehdi", role: "Employee" },
  { email: "audit@cds.example.test", who: "Audit", role: "Auditor" },
];

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const still = useMotionValue(0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", {
        tenant: form.get("tenant"),
        email: form.get("email"),
        password: form.get("password"),
      });
      router.replace("/overview");
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.25fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden p-10 text-white lg:flex">
        <Scene progress={still} />
        <Link href="/" className="relative flex items-center gap-2 text-[17px] font-[600] tracking-tight">
          <Logo size={24} /> AstraRH
        </Link>
        <p className="relative max-w-md text-[34px] leading-[1.08] font-[480] tracking-[-0.018em]">Your crew has been busy. Let&rsquo;s see what needs you.</p>
      </section>
      <section className="flex items-center justify-center bg-surface p-6 sm:p-10">
        {/* method=post: if scripts ever fail to load, credentials must not end up in the URL. */}
        <form method="post" onSubmit={submit} className="w-full max-w-sm space-y-4">
          <Link href="/" className="flex items-center gap-2 text-[17px] font-[600] tracking-tight lg:hidden">
            <Logo size={24} /> AstraRH
          </Link>
          <div>
            <h1 className="text-[26px] font-[520]">Log in</h1>
            <p className="mt-1 text-ink-soft">
              New here? <Link href="/signup" className="font-[520] text-door hover:underline">Request access</Link>
            </p>
          </div>
          <ErrorNote message={error} />
          <Field label="Company">
            <input name="tenant" required defaultValue="cds" autoComplete="organization" className="field" />
          </Field>
          <Field label="Work email">
            <input
              name="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="field"
            />
          </Field>
          <Field label="Password">
            <input name="password" type="password" required autoComplete="current-password" className="field" />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Logging in…" : "Log in"}
          </Button>
          <div className="border-t border-line pt-4">
            <p className="text-[13px] text-ink-soft">Demo company accounts</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {DEMO_USERS.map((user) => (
                <button
                  key={user.email}
                  type="button"
                  onClick={() => setEmail(user.email)}
                  className={`rounded-lg border px-2 py-1 text-[13px] transition-colors ${
                    email === user.email ? "border-door bg-door-wash text-door-deep" : "border-line text-ink-soft hover:border-line-strong hover:text-ink"
                  }`}
                >
                  {user.who}, {user.role.toLowerCase()}
                </button>
              ))}
            </div>
          </div>
        </form>
      </section>
    </main>
  );
}
