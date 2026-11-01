"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type ApiError, get, post, type AskedQuestion, type HrTicket } from "@/lib/api";
import { useMe } from "@/ui/Shell";
import { Button, ErrorNote, PageHeader, Tag, humanDate } from "@/ui/kit";

const POLL_MS = 1500;

function withoutSources(text: string): string {
  return text.replace(/\s*\[C\d+\]/g, "");
}

export default function AskPage() {
  const me = useMe();
  const [questions, setQuestions] = useState<AskedQuestion[]>([]);
  const [tickets, setTickets] = useState<HrTicket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isHr = me?.roles.some((role) => ["hr", "admin"].includes(role));

  const load = useCallback(() => {
    get<AskedQuestion[]>("/knowledge/questions")
      .then(setQuestions)
      .catch((e: ApiError) => setError(e.message));
    if (isHr) {
      get<HrTicket[]>("/knowledge/tickets")
        .then(setTickets)
        .catch(() => setTickets([]));
    }
  }, [isHr]);

  useEffect(load, [load]);

  const waiting = questions.some((question) => question.status === "pending");
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, load]);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const question = new FormData(form).get("question");
    setBusy(true);
    setError(null);
    try {
      await post("/knowledge/questions", { question });
      form.reset();
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Ask HR"
        subtitle="Answers come only from company documents, with their sources. If they don't cover your question, it goes to a person."
      />
      <form onSubmit={ask} className="mb-8 flex flex-wrap gap-2">
        <label className="min-w-64 flex-1">
          <span className="sr-only">Your question</span>
          <input
            name="question"
            required
            minLength={3}
            maxLength={1000}
            placeholder="How many leave days do I get after two years?"
            className="w-full rounded-md border border-line bg-surface px-3 py-2"
          />
        </label>
        <Button type="submit" disabled={busy}>
          Ask
        </Button>
      </form>
      <ErrorNote message={error} />

      <ul className="space-y-6">
        {questions.map((question) => (
          <li key={question.id}>
            <p className="font-semibold">{question.text}</p>
            {question.status === "pending" ? (
              <p role="status" className="mt-1 text-ink-soft">
                Reading the company documents…
              </p>
            ) : null}
            {question.status === "answered" ? (
              <>
                <p className="mt-1 max-w-3xl">{withoutSources(question.answer ?? "")}</p>
                <ul className="mt-2 space-y-2">
                  {question.citations.map((citation) => (
                    <li key={citation.ref} className="border-l-3 border-door pl-3">
                      <p className="text-sm font-medium">
                        {citation.document}, {citation.section}
                      </p>
                      {citation.quote ? (
                        <blockquote className="text-sm text-ink-soft">{citation.quote}</blockquote>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {question.status === "escalated" ? (
              <p className="mt-1 max-w-3xl">
                <Tag tone="info">Passed to HR</Tag> {question.refusal_reason} A person will follow up.
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      {isHr && tickets.length > 0 ? (
        <section className="mt-10" aria-labelledby="tickets">
          <h2 id="tickets" className="text-xl font-semibold">
            Questions passed to you
          </h2>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {tickets.map((ticket) => (
              <li key={ticket.id} className="py-3">
                <p className="font-medium">{ticket.question}</p>
                <p className="text-sm text-ink-soft">
                  {ticket.reason} {humanDate(ticket.asked_at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
