"use client";

import { useCallback, useEffect, useState } from "react";
import { type ApiError, get, post, type Digest, type DigestItem, type ThreadView } from "@/lib/api";
import { Button, EmptyState, ErrorNote, Loading, PageHeader, Tag, humanDate } from "@/ui/kit";

const TYPE_LABELS: Record<string, string> = {
  legal_or_complaint: "Legal and complaints",
  offer_or_salary: "Offers and pay",
  visa_or_permit: "Visas and permits",
  reschedule: "Rescheduling",
  availability: "Availability",
  question: "Questions",
  application: "New applications",
  policy_question: "Employee questions",
  internal: "Internal",
  other: "Other",
  spam: "Spam",
};
const TYPE_ORDER = Object.keys(TYPE_LABELS);

function Conversation({ threadId, onClose }: { threadId: string; onClose: () => void }) {
  const [thread, setThread] = useState<ThreadView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<ThreadView>(`/comms/threads/${threadId}`)
      .then(setThread)
      .catch((e: ApiError) => setError(e.message));
  }, [threadId]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Conversation"
        className="drawer-enter h-full w-full max-w-2xl overflow-y-auto bg-surface p-6 shadow-2xl md:p-8"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-ink-soft">{thread?.party_email}</p>
            <h2 className="mt-1 text-2xl font-bold">{thread?.subject ?? "Conversation"}</h2>
          </div>
          <Button variant="secondary" onClick={onClose} autoFocus>
            Close
          </Button>
        </div>
        <ErrorNote message={error} />
        {!thread && !error ? <Loading /> : null}
        {thread?.pending_reply_ids.length ? (
          <p className="mt-4 rounded-md bg-door-wash px-3 py-2 text-door-deep">
            A drafted reply is waiting in{" "}
            <a className="font-semibold underline" href="/approvals">
              Approvals
            </a>
            .
          </p>
        ) : null}
        <ol className="mt-6 space-y-6">
          {thread?.messages.map((message) => (
            <li key={message.id}>
              <p className="text-sm text-ink-soft">
                {message.direction === "in" ? message.sender : "Sent by the team"},{" "}
                {humanDate(message.sent_at)}
              </p>
              <p dir="auto" className="mt-1 whitespace-pre-wrap">
                {message.body}
              </p>
              {message.needs_human ? (
                <p className="mt-2 font-medium text-ochre">
                  A person should answer this: {message.human_reason}
                </p>
              ) : null}
              {message.flagged ? (
                <p className="mt-1 font-medium text-brick">
                  This message tries to instruct the AI. Its instructions were not followed.
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

function Item({ item, onOpen }: { item: DigestItem; onOpen: (threadId: string) => void }) {
  return (
    <li className="py-3">
      <button type="button" onClick={() => onOpen(item.thread_id)} className="w-full text-left">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-door hover:underline">{item.subject}</span>
          {item.urgency === "high" ? <Tag tone="warn">Urgent</Tag> : null}
          {item.needs_human ? <Tag tone="info">Needs a person</Tag> : null}
          {item.flagged ? <Tag tone="bad">Tries to instruct the AI</Tag> : null}
        </span>
        <span className="mt-0.5 block">{item.summary}</span>
        <span className="block text-sm text-ink-soft">
          {item.sender}
          {item.human_reason ? `. ${item.human_reason}` : ""}
        </span>
      </button>
    </li>
  );
}

export default function InboxPage() {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    get<Digest>("/comms/digest")
      .then(setDigest)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function refresh() {
    setBusy(true);
    try {
      setDigest(await post<Digest>("/comms/digest"));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const types = digest ? TYPE_ORDER.filter((type) => digest.groups[type]?.length) : [];
  return (
    <>
      <PageHeader
        title="Inbox"
        subtitle="Today's digest, grouped by type. Messages that need a person come first."
        action={
          <Button variant="secondary" onClick={refresh} disabled={busy}>
            {busy ? "Updating…" : "Update digest"}
          </Button>
        }
      />
      <ErrorNote message={error} />
      {!digest && !error ? <Loading /> : null}
      {digest ? (
        <p className="tabular mb-6 text-lg">
          <strong>{digest.totals.messages}</strong> messages,{" "}
          <strong>{digest.totals.needs_human}</strong> need a person,{" "}
          <strong>{digest.totals.high_urgency}</strong> urgent
          {digest.totals.flagged ? (
            <>
              , <strong>{digest.totals.flagged}</strong> tried to instruct the AI
            </>
          ) : null}
          .
        </p>
      ) : null}
      {digest && types.length === 0 ? (
        <EmptyState title="Nothing sorted yet">
          New messages appear here once the agent has read them. Use Update digest to refresh.
        </EmptyState>
      ) : null}
      {types.map((type) => (
        <section key={type} className="mb-8" aria-labelledby={`group-${type}`}>
          <h2 id={`group-${type}`} className="text-xl font-semibold">
            {TYPE_LABELS[type]}
          </h2>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {digest?.groups[type].map((item) => (
              <Item key={item.message_id} item={item} onOpen={setOpen} />
            ))}
          </ul>
        </section>
      ))}
      {open ? <Conversation threadId={open} onClose={() => setOpen(null)} /> : null}
    </>
  );
}
