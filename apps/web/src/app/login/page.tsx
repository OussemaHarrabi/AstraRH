"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ApiError, post } from "@/lib/api";
import { Button, ErrorNote } from "@/ui/kit";

const FIELD = "mt-1 w-full rounded-md border border-line bg-surface px-3 py-2";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      router.replace("/");
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen md:grid-cols-[1.2fr_1fr]">
      <section
        className="flex flex-col justify-end p-8 text-white md:p-14"
        style={{ background: "linear-gradient(160deg, var(--door-deep), var(--door))" }}
      >
        <h1 className="max-w-lg text-4xl leading-tight font-bold md:text-6xl">
          AI does the HR work. People decide about people.
        </h1>
        <p className="mt-5 max-w-md text-lg text-white/80">
          Every suggestion comes with its evidence, and nothing leaves until someone approves it.
        </p>
      </section>
      <section className="flex items-center justify-center p-8">
        {/* method=post: if scripts ever fail to load, credentials must not end up in the URL. */}
        <form method="post" onSubmit={submit} className="w-full max-w-sm space-y-4">
          <h2 className="text-2xl font-bold">Sign in to AstraRH</h2>
          <ErrorNote message={error} />
          <label className="block font-medium">
            Company
            <input name="tenant" required defaultValue="cds" autoComplete="organization" className={FIELD} />
          </label>
          <label className="block font-medium">
            Work email
            <input name="email" type="email" required autoComplete="username" className={FIELD} />
          </label>
          <label className="block font-medium">
            Password
            <input
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className={FIELD}
            />
          </label>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  );
}
