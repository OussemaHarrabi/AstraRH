"use client";

import { AnimatePresence, motion } from "motion/react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { type ApiError, type AskedQuestion, get, type PolicyDocument, post, type Ticket } from "@/lib/api";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { ago, Button, ErrorNote, Field, Loading, Modal, PageHeader, Panel, Tabs, Tag, titleCase, useLoad, withoutCitations } from "@/ui/kit";
import { useMe, useToast } from "@/ui/Shell";

const HELA = agentById("policy_answers");
const STARTERS = ["How many days can I work from home?", "How do I claim travel expenses?", "How much annual leave do I get?", "What should I do about harassment at work?"];
const HR_ROLES = ["admin", "hr"];

interface Question extends AskedQuestion {
  created_at?: string;
  feedback?: { helpful: boolean } | null;
}

function Answer({ question, onChanged }: { question: Question; onChanged: () => void }) {
  const toast = useToast();
  const [rated, setRated] = useState<boolean | null>(question.feedback?.helpful ?? null);
  const [open, setOpen] = useState<string | null>(null);

  async function rate(helpful: boolean) {
    setRated(helpful);
    try {
      await post(`/knowledge/questions/${question.id}/feedback`, { helpful, comment: "" });
      toast(helpful ? "Thanks for telling us." : "Sent to HR, with the answer you were given.");
      onChanged();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  const waiting = question.status === "pending" || question.status === "asked" || question.status === "processing";
  return (
    <div className="flex gap-2.5">
      <Face agent={HELA} size={30} mood={waiting ? "working" : question.answer ? "happy" : "alert"} />
      <div className="min-w-0 flex-1">
        {waiting ? (
          <div className="flex gap-1 py-2.5">
            {[0, 1, 2].map((dot) => <motion.span key={dot} className="size-1.5 rounded-full bg-ink-faint" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1, delay: dot * 0.16 }} />)}
          </div>
        ) : question.answer ? (
          <div className="rounded-xl rounded-tl-sm border border-line bg-surface p-3.5 shadow-soft">
            <p className="leading-relaxed whitespace-pre-wrap" dir="auto">{withoutCitations(question.answer)}</p>
            {question.citations.length > 0 ? (
              <ul className="mt-2.5 space-y-1 border-t border-line pt-2.5">
                {question.citations.map((citation) => (
                  <li key={citation.ref}>
                    <button type="button" aria-expanded={open === citation.ref} onClick={() => setOpen(open === citation.ref ? null : citation.ref)} className="flex items-center gap-1.5 text-left font-[520] text-door hover:underline">
                      <Icon name="file" size={13} /> {citation.document}, {citation.section}
                    </button>
                    <AnimatePresence initial={false}>
                      {open === citation.ref ? (
                        <motion.blockquote initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                          <p className="mt-1 border-l-2 border-door pl-2.5 text-ink-soft" dir="auto">{citation.quote}</p>
                        </motion.blockquote>
                      ) : null}
                    </AnimatePresence>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="mt-2.5 flex items-center gap-1.5 text-[13px] text-ink-soft">
              {rated === null ? (
                <>
                  <span>Did this help?</span>
                  <button type="button" onClick={() => rate(true)} className="rounded-md px-1.5 py-0.5 font-[520] hover:bg-sunken hover:text-ink">Yes</button>
                  <button type="button" onClick={() => rate(false)} className="rounded-md px-1.5 py-0.5 font-[520] hover:bg-sunken hover:text-ink">No, ask HR</button>
                </>
              ) : (
                <span>{rated ? "Marked helpful." : "HR will follow up."}</span>
              )}
            </div>
          </div>
        ) : (
          <div className="flex gap-2 rounded-xl rounded-tl-sm bg-bloom-wash p-3.5 text-bloom">
            <Icon name="users" className="mt-0.5" />
            <p>I don&rsquo;t have a policy I can cite for this, so I&rsquo;ve passed it to HR instead of guessing.{question.refusal_reason ? ` ${question.refusal_reason}` : ""}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Chat() {
  const toast = useToast();
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const { data, reload } = useLoad(() => get<Question[]>("/knowledge/questions"), []);
  const end = useRef<HTMLDivElement>(null);
  const questions = [...(data ?? [])].reverse();
  const waiting = questions.some((question) => question.status === "pending" || question.status === "asked" || question.status === "processing");

  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void reload(), 1500);
    return () => clearInterval(timer);
  }, [waiting, reload]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [questions.length, waiting]);

  async function ask(text: string) {
    if (!text.trim()) return;
    setAsking(true);
    setDraft("");
    try {
      await post("/knowledge/questions", { question: text });
      await reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
      setDraft(text);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="mt-4 flex h-[calc(100vh-232px)] min-h-[480px] flex-col overflow-hidden rounded-xl border border-line bg-plaster shadow-soft">
      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {data && questions.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Face agent={HELA} size={72} track />
            <p className="mt-3 text-[17px] font-[560]">Ask Hela about company policy</p>
            <p className="mt-1 max-w-sm text-ink-soft">She answers only from policies you&rsquo;re allowed to read, and shows the exact sentence.</p>
            <div className="mt-4 flex max-w-lg flex-wrap justify-center gap-1.5">
              {STARTERS.map((starter) => (
                <button key={starter} type="button" onClick={() => void ask(starter)} className="rounded-full border border-line bg-surface px-3 py-1 transition-colors hover:border-door hover:text-door">{starter}</button>
              ))}
            </div>
          </div>
        ) : null}
        {questions.map((question) => (
          <motion.div key={question.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-2.5">
            <p className="ml-auto w-fit max-w-[75%] rounded-xl rounded-br-sm bg-door px-3.5 py-2 text-white" dir="auto">{question.text}</p>
            <Answer question={question} onChanged={() => void reload()} />
          </motion.div>
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); void ask(draft); }} className="flex gap-2 border-t border-line bg-surface p-3">
        <input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Your question" placeholder="Ask about leave, expenses, remote work…" className="field flex-1" dir="auto" />
        <Button type="submit" disabled={asking || !draft.trim()}><Icon name="send" size={14} /> Ask</Button>
      </form>
    </div>
  );
}

function Tickets() {
  const toast = useToast();
  const me = useMe();
  const { data, error, reload } = useLoad(() => get<(Ticket & { assignee_id?: string | null })[]>("/knowledge/tickets?status=active"), []);
  const [answering, setAnswering] = useState<Ticket | null>(null);

  async function act(id: string, action: string, body: unknown, done: string) {
    try {
      await post(`/knowledge/tickets/${id}/${action}`, body);
      toast(done);
      void reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  async function answer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!answering) return;
    const text = new FormData(event.currentTarget).get("answer");
    await act(answering.id, "answer", { answer: text }, "Answer sent back to the employee.");
    setAnswering(null);
  }

  return (
    <div className="mt-4">
      <ErrorNote message={error} />
      {!data && !error ? <Loading /> : null}
      {data ? (
        <Panel flush>
          <ul>
            {data.map((ticket) => (
              <li key={ticket.id} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                <span className="min-w-0 flex-1">
                  <span className="block font-[520]" dir="auto">{ticket.question}</span>
                  <span className="block text-ink-soft">{titleCase(ticket.reason)}, asked {ago(ticket.asked_at)}</span>
                </span>
                <Tag tone={ticket.status === "open" ? "bloom" : "info"}>{titleCase(ticket.status)}</Tag>
                {ticket.status === "open" ? <Button size="sm" variant="secondary" onClick={() => act(ticket.id, "claim", {}, "It's yours now.")}>Take it</Button> : null}
                {ticket.status === "claimed" && ticket.assignee_id === me?.user_id ? (
                  <>
                    <Button size="sm" onClick={() => setAnswering(ticket)}>Answer</Button>
                    <Button size="sm" variant="quiet" onClick={() => act(ticket.id, "release", {}, "Back in the queue.")}>Release</Button>
                  </>
                ) : null}
              </li>
            ))}
            {data.length === 0 ? <li className="p-10 text-center text-ink-soft">No questions are waiting for HR.</li> : null}
          </ul>
        </Panel>
      ) : null}
      <Modal open={Boolean(answering)} onClose={() => setAnswering(null)} label="Answer the employee">
        <form onSubmit={answer} className="space-y-3 p-5">
          <h2 className="text-[17px] font-[560]">Answer the employee</h2>
          <p className="rounded-lg bg-plaster p-2.5" dir="auto">{answering?.question}</p>
          <Field label="Your answer"><textarea name="answer" rows={5} required autoFocus className="field" /></Field>
          <div className="flex gap-2">
            <Button type="submit">Send answer</Button>
            <Button variant="secondary" onClick={() => setAnswering(null)}>Cancel</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function Policies() {
  const toast = useToast();
  const { data, error, reload } = useLoad(() => get<PolicyDocument[]>("/knowledge/documents"), []);
  const [publishing, setPublishing] = useState<PolicyDocument | "new" | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const detail = useLoad(() => (opened ? get<{ title: string; sections: { heading?: string; title?: string; text?: string; body?: string }[] }>(`/knowledge/documents/${opened}`) : Promise.resolve(null)), [opened]);

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const current = publishing === "new" ? null : publishing;
    try {
      await post("/knowledge/documents", {
        external_id: current?.external_id ?? form.get("external_id"),
        title: form.get("title"),
        version: form.get("version"),
        audience_roles: current?.audience_roles ?? [],
        markdown: form.get("markdown"),
      });
      toast("Published. Once indexed, the older version stops being cited.");
      setPublishing(null);
      void reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  const current = publishing === "new" ? null : publishing;

  return (
    <div className="mt-4 grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[1fr_1fr]">
      <Panel flush title="Policy documents" action={<Button size="sm" onClick={() => setPublishing("new")}><Icon name="plus" size={13} /> Publish</Button>}>
        <ErrorNote message={error} />
        <ul>
          {data?.map((doc) => (
            <li key={doc.id} className={`group flex items-center gap-2.5 border-b border-line px-4 py-2.5 last:border-0 ${opened === doc.id ? "bg-door-wash" : "row-hover"}`}>
              <button type="button" onClick={() => setOpened(doc.id)} className="flex min-w-0 flex-1 items-center gap-2.5 text-left">
                <Icon name="file" className="text-ink-faint" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-[520]">{doc.title}</span>
                  <span className="block text-[13px] text-ink-soft">Version {doc.version}, {doc.sections} sections</span>
                </span>
              </button>
              {doc.audience_roles.length ? <Tag tone="warn"><Icon name="lock" size={11} /> {doc.audience_roles.join(", ")}</Tag> : null}
              <Button size="sm" variant="quiet" onClick={() => setPublishing(doc)}>New version</Button>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title={detail.data?.title ?? "Read a policy"}>
        {!opened ? <p className="py-6 text-center text-ink-soft">Choose a document to read it, section by section.</p> : !detail.data ? <Loading /> : (
          <div className="max-h-[60vh] space-y-3 overflow-y-auto">
            {detail.data.sections.map((section, index) => (
              <section key={index}>
                <h3 className="font-[560]">{section.heading ?? section.title}</h3>
                <p className="mt-0.5 text-ink-soft whitespace-pre-wrap" dir="auto">{section.text ?? section.body}</p>
              </section>
            ))}
          </div>
        )}
      </Panel>
      <Modal open={Boolean(publishing)} onClose={() => setPublishing(null)} label="Publish a policy" width={560}>
        <form onSubmit={publish} className="space-y-3 p-5">
          <h2 className="text-[17px] font-[560]">{current ? `New version of ${current.title}` : "Publish a policy"}</h2>
          {current ? null : <Field label="Reference"><input name="external_id" required placeholder="POL-TRAVEL" className="field" /></Field>}
          <Field label="Title"><input name="title" required defaultValue={current?.title} className="field" /></Field>
          <Field label="Version"><input name="version" required defaultValue={current ? String(Number(current.version) + 1) : "1"} className="field" /></Field>
          <Field label="Content, in Markdown" hint="Each ## heading becomes a section Hela can cite."><textarea name="markdown" rows={8} required className="field" /></Field>
          <div className="flex gap-2">
            <Button type="submit">Publish</Button>
            <Button variant="secondary" onClick={() => setPublishing(null)}>Cancel</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

export default function AskPage() {
  const me = useMe();
  const isHr = me?.roles.some((role) => HR_ROLES.includes(role));
  const [tab, setTab] = useState<"ask" | "tickets" | "policies">("ask");
  return (
    <>
      <PageHeader title="Ask HR" subtitle="Answers from company policy, with the source. Anything else goes to a person." />
      {isHr ? <Tabs value={tab} onChange={setTab} tabs={[{ id: "ask", label: "Ask" }, { id: "tickets", label: "Passed to HR" }, { id: "policies", label: "Policies" }]} /> : null}
      {tab === "ask" ? <Chat /> : null}
      {tab === "tickets" ? <Tickets /> : null}
      {tab === "policies" ? <Policies /> : null}
    </>
  );
}
