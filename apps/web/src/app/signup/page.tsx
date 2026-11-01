"use client";

import { AnimatePresence, motion, useMotionValue } from "motion/react";
import Link from "next/link";
import { type FormEvent, useState } from "react";
import { newId, useLocal } from "@/lib/local";
import { AGENTS, Face } from "@/ui/Face";
import { Button, Field } from "@/ui/kit";
import { Logo } from "@/ui/Logo";
import { Scene } from "@/ui/landing/Scene";

interface AccessRequest {
  id: string;
  name: string;
  email: string;
  company: string;
  size: string;
}

const NO_REQUESTS: AccessRequest[] = [];

export default function SignupPage() {
  const [, setRequests] = useLocal<AccessRequest[]>("access.requests", NO_REQUESTS);
  const [done, setDone] = useState<string | null>(null);
  const still = useMotionValue(0);
  const prefill = typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("email") ?? "");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const request = {
      id: newId(),
      name: String(form.get("name")),
      email: String(form.get("email")),
      company: String(form.get("company")),
      size: String(form.get("size")),
    };
    setRequests((list) => [request, ...list]);
    setDone(request.name.split(" ")[0]);
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.25fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden p-10 text-white lg:flex">
        <Scene progress={still} />
        <Link href="/" className="relative flex items-center gap-2 text-[17px] font-[600] tracking-tight">
          <Logo size={24} /> AstraRH
        </Link>
        <div className="relative">
          <p className="max-w-md text-[34px] leading-[1.08] font-[480] tracking-[-0.018em]">Eleven agents. No way to act without you.</p>
          <div className="mt-5 flex gap-1">
            {AGENTS.slice(0, 7).map((agent) => (
              <Face key={agent.id} agent={agent} size={40} track />
            ))}
          </div>
        </div>
      </section>
      <section className="flex items-center justify-center bg-surface p-6 sm:p-10">
        <AnimatePresence mode="wait">
          {done ? (
            <motion.div key="done" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-sm">
              <Face agent={AGENTS[3]} mood="happy" size={64} />
              <h1 className="mt-4 text-[26px] font-[520]">Thanks, {done}.</h1>
              <p className="mt-2 text-[15px] text-ink-soft">
                We saved your request on this device. Accounts are set up by an administrator during the pilot, so you can try the demo company in the meantime.
              </p>
              <Link href="/login" className="mt-5 inline-flex h-8.5 items-center rounded-lg bg-door px-3.5 font-[520] text-white transition-colors hover:bg-door-deep">
                Log in to the demo company
              </Link>
            </motion.div>
          ) : (
            <motion.form key="form" exit={{ opacity: 0 }} method="post" onSubmit={submit} className="w-full max-w-sm space-y-4">
              <Link href="/" className="flex items-center gap-2 text-[17px] font-[600] tracking-tight lg:hidden">
                <Logo size={24} /> AstraRH
              </Link>
              <div>
                <h1 className="text-[26px] font-[520]">Request access</h1>
                <p className="mt-1 text-ink-soft">
                  Have an account? <Link href="/login" className="font-[520] text-door hover:underline">Log in</Link>
                </p>
              </div>
              <Field label="Your name">
                <input name="name" required autoComplete="name" className="field" />
              </Field>
              <Field label="Work email">
                <input name="email" type="email" required defaultValue={prefill} autoComplete="email" className="field" />
              </Field>
              <Field label="Company">
                <input name="company" required autoComplete="organization" className="field" />
              </Field>
              <Field label="Company size">
                <select name="size" className="field" defaultValue="50-200">
                  <option>Under 50</option>
                  <option>50-200</option>
                  <option>200-1000</option>
                  <option>Over 1000</option>
                </select>
              </Field>
              <Button type="submit" className="w-full">Request access</Button>
            </motion.form>
          )}
        </AnimatePresence>
      </section>
    </main>
  );
}
