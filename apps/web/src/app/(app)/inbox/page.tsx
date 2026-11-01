"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useState } from "react";
import { type ApiError, type Digest, get, type InboxStats, post, put, type ThreadDetail, type ThreadPage } from "@/lib/api";
import { useLocal } from "@/lib/local";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { ago, Avatar, Button, EmptyState, ErrorNote, Field, Loading, Modal, PageHeader, Tabs, Tag, type Tone, titleCase, useLoad } from "@/ui/kit";
import { useToast } from "@/ui/Shell";

type View = "digest" | "human" | "open" | "handled";

const URGENCY_TONE: Record<string, Tone> = { high: "bad", critical: "bad", medium: "warn", low: "neutral" };
const NO_DRAFTS: Record<string, string> = {};

function Correct({ stats, messageId, sorting, onDone, onClose }: { stats: InboxStats | null; messageId: string; sorting: NonNullable<ThreadDetail["messages"][number]["sorting"]>; onDone: () => void; onClose: () => void }) {
  const toast = useToast();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await put(`/comms/messages/${messageId}/sorting`, {
        type: form.get("type"),
        urgency: form.get("urgency"),
        needs_human: form.get("needs_human") === "on",
        reason: form.get("reason") || null,
      });
      toast("Correction saved. Salem's first answer is kept, so accuracy stays measurable.");
      onDone();
      onClose();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <Modal open onClose={onClose} label="Correct the sorting" width={420}>
      <form onSubmit={save} className="space-y-3 p-5">
        <h2 className="text-[17px] font-[560]">Correct the sorting</h2>
        <Field label="Type">
          <select name="type" defaultValue={sorting.type} className="field">
            {(stats?.types ?? [sorting.type]).map((type) => <option key={type} value={type}>{titleCase(type)}</option>)}
          </select>
        </Field>
        <Field label="Urgency">
          <select name="urgency" defaultValue={sorting.urgency} className="field">
            {(stats?.urgencies ?? [sorting.urgency]).map((urgency) => <option key={urgency} value={urgency}>{titleCase(urgency)}</option>)}
          </select>
        </Field>
        <label className="flex items-center gap-2">
          <input type="checkbox" name="needs_human" defaultChecked={sorting.needs_human} className="accent-[var(--door)]" /> Needs a person
        </label>
        <Field label="Reason">
          <input name="reason" defaultValue={sorting.human_reason ?? ""} className="field" />
        </Field>
        <div className="flex gap-2">
          <Button type="submit">Save correction</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

function ThreadPane({ id, stats, onChanged }: { id: string; stats: InboxStats | null; onChanged: () => void }) {
  const toast = useToast();
  const { data: thread, error, reload } = useLoad(() => get<ThreadDetail>(`/comms/threads/${id}`), [id]);
  const [correcting, setCorrecting] = useState<string | null>(null);
  const [drafts, setDrafts] = useLocal<Record<string, string>>("inbox.drafts", NO_DRAFTS);

  async function setHandled(handled: boolean) {
    try {
      if (handled) await post(`/comms/threads/${id}/handled`, { note: "Dealt with" });
      else await post(`/comms/threads/${id}/reopen`);
      toast(handled ? "Marked as handled." : "Reopened.");
      reload();
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  if (error) return <div className="p-5"><ErrorNote message={error} /></div>;
  if (!thread) return <div className="p-5"><Loading rows={6} /></div>;
  const correctingMessage = thread.messages.find((message) => message.id === correcting);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[16px] font-[560]" dir="auto">{thread.subject}</h2>
          <p className="truncate text-[13px] text-ink-soft">{thread.party_email}</p>
        </div>
        {thread.status === "open" ? (
          <Button variant="secondary" size="sm" onClick={() => setHandled(true)}><Icon name="check" size={13} /> Mark handled</Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setHandled(false)}>Reopen</Button>
        )}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto bg-plaster p-5">
        {thread.messages.map((message) => (
          <motion.article key={message.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className={`rounded-xl border border-line bg-surface p-3.5 ${message.direction === "out" ? "ml-8" : "mr-8"}`}>
            <div className="flex items-center gap-2">
              <Avatar name={message.sender} size={24} />
              <p className="min-w-0 flex-1 truncate font-[520]">{message.sender}</p>
              <span className="text-[13px] text-ink-soft">{ago(message.sent_at)}</span>
            </div>
            <p className="mt-2 whitespace-pre-wrap leading-relaxed" dir="auto">{message.body}</p>
            {message.attachments.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {message.attachments.map((file) => (
                  <li key={file.id} className="flex items-center gap-1.5 text-[13px] text-ink-soft">
                    <Icon name="file" size={13} /> {file.filename} <Tag tone={file.status === "rejected" ? "bad" : "neutral"}>{titleCase(file.status)}</Tag>
                  </li>
                ))}
              </ul>
            ) : null}
            {message.sorting ? (
              <div className="mt-3 rounded-lg bg-plaster p-2.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Face agent={agentById("inbox_triage")} size={20} />
                  <Tag>{titleCase(message.sorting.type)}</Tag>
                  <Tag tone={URGENCY_TONE[message.sorting.urgency] ?? "neutral"}>{titleCase(message.sorting.urgency)}</Tag>
                  {message.sorting.needs_human ? <Tag tone="bloom">Needs a person</Tag> : null}
                  {message.sorting.flagged ? <Tag tone="bad">Injection attempt flagged</Tag> : null}
                  {message.sorting.corrected ? <Tag tone="info">Corrected by a person</Tag> : null}
                  <button type="button" onClick={() => setCorrecting(message.id)} className="ml-auto text-[13px] font-[520] text-door hover:underline">Correct</button>
                </div>
                <p className="mt-1.5 text-ink-soft" dir="auto">{message.sorting.summary}</p>
                {message.sorting.human_reason ? <p className="mt-0.5 text-bloom">{message.sorting.human_reason}</p> : null}
              </div>
            ) : null}
          </motion.article>
        ))}
      </div>
      <div className="border-t border-line bg-surface p-3">
        {thread.pending_reply_ids.length > 0 ? (
          <div className="flex items-center gap-2.5 rounded-lg bg-door-wash p-2.5">
            <Face agent={agentById("reply_drafter")} mood="waiting" size={28} />
            <p className="min-w-0 flex-1">Yara drafted a reply from this candidate&rsquo;s file. It waits for you.</p>
            <Link href={`/approvals?id=${thread.pending_reply_ids[0]}`} className="flex h-7 items-center rounded-lg bg-door px-2.5 text-[13px] font-[520] whitespace-nowrap text-white hover:bg-door-deep">Review draft</Link>
          </div>
        ) : (
          <div>
            <textarea
              aria-label="Your own note or draft"
              placeholder="Write a private draft. It stays on this device until you send it through approvals."
              value={drafts[id] ?? ""}
              onChange={(event) => setDrafts((all) => ({ ...all, [id]: event.target.value }))}
              rows={2}
              className="field"
            />
          </div>
        )}
      </div>
      {correctingMessage?.sorting ? (
        <Correct stats={stats} messageId={correctingMessage.id} sorting={correctingMessage.sorting} onDone={() => { reload(); onChanged(); }} onClose={() => setCorrecting(null)} />
      ) : null}
    </div>
  );
}

function InboxInner() {
  const params = useSearchParams();
  const toast = useToast();
  const [view, setView] = useState<View>(params.get("view") === "human" ? "human" : "digest");
  const [type, setType] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(query), 220);
    return () => clearTimeout(timer);
  }, [query]);

  const stats = useLoad(() => get<InboxStats>("/comms/stats"), []);
  const digest = useLoad(() => get<Digest>("/comms/digest"), []);
  const threads = useLoad(() => {
    const filter = new URLSearchParams({ limit: "50", status: view === "handled" ? "handled" : "open" });
    if (view === "human") filter.set("needs_human", "true");
    if (type) filter.set("type", type);
    if (search) filter.set("q", search);
    return get<ThreadPage>(`/comms/threads?${filter}`);
  }, [view, type, search]);

  function refresh() {
    stats.reload();
    threads.reload();
    digest.reload();
  }

  async function rebuild() {
    setRebuilding(true);
    try {
      await post("/comms/digest");
      await digest.reload();
      toast("Digest rebuilt with the latest messages.");
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setRebuilding(false);
    }
  }

  const items = threads.data?.items ?? [];
  const current = selected ?? (view !== "digest" ? items[0]?.id : null);
  const groups = Object.entries(digest.data?.groups ?? {});

  return (
    <>
      <PageHeader
        title="Inbox"
        subtitle="Salem reads everything that arrives at HR and flags what needs a person."
        action={<Button variant="secondary" onClick={rebuild} disabled={rebuilding}><Icon name="sparkle" size={14} /> {rebuilding ? "Rebuilding…" : "Rebuild digest"}</Button>}
      />
      <Tabs
        value={view}
        onChange={(next) => { setView(next); setSelected(null); }}
        tabs={[
          { id: "digest", label: "Today's digest", count: digest.data?.totals.messages },
          { id: "human", label: "Needs a person", count: stats.data?.open_needing_a_person },
          { id: "open", label: "All open", count: stats.data?.threads.open },
          { id: "handled", label: "Handled", count: stats.data?.threads.handled },
        ]}
      />
      <ErrorNote message={threads.error ?? digest.error} />
      {view === "digest" ? (
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[1fr_minmax(0,1fr)]">
          <div className="space-y-5">
            {!digest.data ? <Loading rows={6} /> : null}
            {digest.data && groups.length === 0 ? (
              <div className="rounded-xl border border-line bg-surface">
                <EmptyState title="No digest yet today" art={<Face agent={agentById("inbox_triage")} size={56} mood="asleep" />}>Salem builds it at 07:00. You can rebuild it any time.</EmptyState>
              </div>
            ) : null}
            {digest.data && groups.length > 0 ? (
              <div className="grid grid-cols-3 divide-x divide-line rounded-xl border border-line bg-surface shadow-soft">
                {[["Messages", digest.data.totals.messages], ["Need a person", digest.data.totals.needs_human], ["Urgent", digest.data.totals.high_urgency]].map(([label, value]) => (
                  <div key={label} className="px-4 py-3">
                    <p className="text-ink-soft">{label}</p>
                    <p className="tabular text-[24px] leading-tight font-[520]">{value}</p>
                  </div>
                ))}
              </div>
            ) : null}
            {groups.map(([group, rows]) => (
              <section key={group} className="overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
                <h2 className="flex items-center justify-between border-b border-line px-4 py-2.5 font-[560]">
                  {titleCase(group)} <span className="tabular font-[400] text-ink-soft">{rows.length}</span>
                </h2>
                <ul>
                  {rows.map((row) => (
                    <li key={row.message_id}>
                      <button
                        type="button"
                        onClick={() => setSelected(row.thread_id)}
                        className={`flex w-full gap-2.5 border-b border-line px-4 py-2.5 text-left transition-colors last:border-0 ${current === row.thread_id ? "bg-door-wash" : "hover:bg-plaster"}`}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-[500]" dir="auto">{row.subject}</span>
                          <span className="line-clamp-2 text-ink-soft" dir="auto">{row.summary}</span>
                        </span>
                        <span className="flex shrink-0 flex-col items-end gap-1">
                          <Tag tone={URGENCY_TONE[row.urgency] ?? "neutral"}>{titleCase(row.urgency)}</Tag>
                          {row.needs_human ? <Tag tone="bloom">Person</Tag> : null}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
          <div className="sticky top-16 h-[calc(100vh-96px)] overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
            {current ? (
              <ThreadPane key={current} id={current} stats={stats.data} onChanged={refresh} />
            ) : (
              <EmptyState title="Pick a message" art={<Face agent={agentById("inbox_triage")} size={56} track />}>Its full conversation and Salem&rsquo;s reasoning open here.</EmptyState>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)] overflow-hidden rounded-xl border border-line bg-surface shadow-soft lg:h-[calc(100vh-232px)] lg:min-h-[520px] lg:grid-cols-[370px_1fr]">
          <div className="flex min-h-0 flex-col border-b border-line lg:border-r lg:border-b-0">
            <div className="space-y-2 border-b border-line p-2">
              <div className="relative">
                <Icon name="search" size={14} className="absolute top-2.5 left-2.5 text-ink-faint" />
                <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search conversations" placeholder="Search by subject or sender" className="field !pl-8" />
              </div>
              <div className="flex gap-1 overflow-x-auto pb-0.5">
                {[null, ...(stats.data?.types ?? [])].map((name) => (
                  <button
                    key={name ?? "all"}
                    type="button"
                    onClick={() => setType(name)}
                    className={`h-6 shrink-0 rounded-md px-1.5 text-xs font-[520] transition-colors ${type === name ? "bg-door-wash text-door-deep" : "text-ink-soft hover:bg-sunken"}`}
                  >
                    {name ? titleCase(name) : "All"}
                  </button>
                ))}
              </div>
            </div>
            <ul className="max-h-80 flex-1 overflow-y-auto lg:max-h-none">
              {!threads.data ? <li className="p-4"><Loading /></li> : null}
              {threads.data && items.length === 0 ? <li className="p-8 text-center text-ink-soft">No conversations match.</li> : null}
              {items.map((thread) => {
                const sorting = thread.latest_inbound?.sorting;
                return (
                  <li key={thread.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(thread.id)}
                      className={`flex w-full gap-2.5 border-b border-line px-3 py-2.5 text-left transition-colors ${current === thread.id ? "bg-door-wash" : "hover:bg-plaster"}`}
                    >
                      <Avatar name={thread.party_email} size={28} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-[520]" dir="auto">{thread.subject}</span>
                          <span className="shrink-0 text-[12px] text-ink-soft">{ago(thread.last_message_at)}</span>
                        </span>
                        <span className="line-clamp-1 text-ink-soft" dir="auto">{sorting?.summary ?? thread.party_email}</span>
                        <span className="mt-1 flex flex-wrap gap-1">
                          {sorting ? <Tag>{titleCase(sorting.type)}</Tag> : null}
                          {sorting?.needs_human ? <Tag tone="bloom">Person</Tag> : null}
                          {sorting?.flagged ? <Tag tone="bad">Flagged</Tag> : null}
                          {thread.pending_reply_ids.length ? <Tag tone="info">Draft ready</Tag> : null}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="min-h-0 min-w-0">
            {current ? <ThreadPane key={current} id={current} stats={stats.data} onChanged={refresh} /> : <EmptyState title="Nothing selected" art={<Face agent={agentById("inbox_triage")} size={56} mood="happy" />}>Nothing is waiting in this view.</EmptyState>}
          </div>
        </div>
      )}
    </>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<Loading />}>
      <InboxInner />
    </Suspense>
  );
}
