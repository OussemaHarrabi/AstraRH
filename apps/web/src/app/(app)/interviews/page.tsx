"use client";

import { motion } from "motion/react";
import { type ChangeEvent, type FormEvent, useMemo, useRef, useState } from "react";
import { type ApiError, type Booking, del, get, type Interview, post, upload } from "@/lib/api";
import { loadCandidates } from "@/lib/hiring";
import { agentById, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Button, dayLabel, ErrorNote, Field, Loading, Modal, PageHeader, Panel, Tag, timeLabel, titleCase, useLoad } from "@/ui/kit";
import { useMe, useToast } from "@/ui/Shell";

const START_HOUR = 8;
const END_HOUR = 18;
const HOUR_PX = 46;

interface Block {
  id?: string;
  source?: string;
  kind?: string;
  label?: string | null;
  starts_at: string;
  ends_at: string;
}

function mondayOf(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
  // On a weekend the useful week is the one coming up.
  if (date.getDay() === 0 || date.getDay() === 6) copy.setDate(copy.getDate() + 7);
  return copy;
}

function placed(block: { starts_at: string; ends_at: string }) {
  const start = new Date(block.starts_at);
  const end = new Date(block.ends_at);
  const from = start.getHours() + start.getMinutes() / 60;
  const to = end.getHours() + end.getMinutes() / 60;
  return { top: (Math.max(from, START_HOUR) - START_HOUR) * HOUR_PX, height: Math.max(18, (Math.min(to, END_HOUR) - Math.max(from, START_HOUR)) * HOUR_PX - 2) };
}

function AddBusy({ day, hour, onClose, onDone }: { day: Date; hour: number; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const date = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await post("/calendar/busy", {
        starts_at: new Date(`${form.get("date")}T${form.get("from")}`).toISOString(),
        ends_at: new Date(`${form.get("date")}T${form.get("to")}`).toISOString(),
        label: form.get("label"),
      });
      toast("Added. Dali won't offer this time.");
      onDone();
      onClose();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <Modal open onClose={onClose} label="Block out time" width={380}>
      <form onSubmit={save} className="space-y-3 p-5">
        <h2 className="text-[17px] font-[560]">Block out time</h2>
        <Field label="What is it?"><input name="label" autoFocus placeholder="Team meeting" className="field" /></Field>
        <Field label="Day"><input name="date" type="date" defaultValue={date} required className="field" /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="From"><input name="from" type="time" required defaultValue={`${String(hour).padStart(2, "0")}:00`} className="field" /></Field>
          <Field label="To"><input name="to" type="time" required defaultValue={`${String(hour + 1).padStart(2, "0")}:00`} className="field" /></Field>
        </div>
        <div className="flex gap-2">
          <Button type="submit">Block out time</Button>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

export default function InterviewsPage() {
  const me = useMe();
  const toast = useToast();
  const [weekOffset, setWeekOffset] = useState(0);
  const [adding, setAdding] = useState<{ day: Date; hour: number } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const monday = useMemo(() => {
    const base = mondayOf(new Date());
    base.setDate(base.getDate() + weekOffset * 7);
    return base;
  }, [weekOffset]);
  const days = useMemo(() => Array.from({ length: 5 }, (_, index) => {
    const day = new Date(monday);
    day.setDate(day.getDate() + index);
    return day;
  }), [monday]);

  const week = useLoad(async () => {
    const from = monday.toISOString();
    const end = new Date(monday);
    end.setDate(end.getDate() + 7);
    const range = `from=${encodeURIComponent(from)}&to=${encodeURIComponent(end.toISOString())}`;
    const [busy, bookings] = await Promise.all([
      get<{ items: Block[] }>(`/calendar/busy?${range}`),
      get<{ items: Booking[] }>(`/calendar/bookings?${range}`),
    ]);
    return { busy: busy.items, bookings: bookings.items };
  }, [monday]);
  const hiring = useLoad(loadCandidates, []);

  const nameOf = (interview: Interview) => hiring.data?.candidates.find((candidate) => candidate.application_id === interview.application_id)?.name ?? "Candidate";
  const open = (hiring.data?.interviews ?? []).filter((interview) => interview.status !== "cancelled");

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await upload<{ imported?: number; blocks?: number }>("/calendar/import", form);
      toast(`Calendar imported: ${result.imported ?? result.blocks ?? 0} busy times. Titles and guests were dropped on purpose.`);
      void week.reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  async function remove(id: string) {
    try {
      await del(`/calendar/busy/${id}`);
      toast("Removed.");
      void week.reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  const now = new Date();
  const nowTop = (now.getHours() + now.getMinutes() / 60 - START_HOUR) * HOUR_PX;

  return (
    <>
      <PageHeader
        title="Interviews"
        subtitle={`${me?.display_name}'s calendar. Dali only offers times that are actually free.`}
        action={
          <>
            <input ref={fileInput} type="file" accept=".ics" className="sr-only" aria-label="Choose a calendar file" onChange={importFile} />
            <Button variant="secondary" onClick={() => fileInput.current?.click()}><Icon name="upload" size={14} /> Import .ics</Button>
            <Button onClick={() => setAdding({ day: days[0], hour: 9 })}><Icon name="plus" size={14} /> Block out time</Button>
          </>
        }
      />
      <ErrorNote message={week.error} />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[1fr_300px]">
        <section className="overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
          <div className="flex items-center gap-1 border-b border-line px-3 py-2">
            <Button variant="quiet" size="sm" aria-label="Previous week" onClick={() => setWeekOffset((value) => value - 1)}><Icon name="chevron" size={14} className="rotate-180" /></Button>
            <Button variant="quiet" size="sm" aria-label="Next week" onClick={() => setWeekOffset((value) => value + 1)}><Icon name="chevron" size={14} /></Button>
            <Button variant="secondary" size="sm" onClick={() => setWeekOffset(0)}>Today</Button>
            <p className="ml-2 font-[560]">Week of {monday.toLocaleDateString("en-GB", { day: "numeric", month: "long" })}</p>
            <ul className="ml-auto hidden gap-3 text-[13px] text-ink-soft sm:flex">
              <li className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-door" /> Booked</li>
              <li className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm border border-dashed border-door bg-door-wash" /> Held</li>
              <li className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-sunken" /> Busy</li>
            </ul>
          </div>
          <div className="overflow-x-auto">
            <div className="grid min-w-[640px] grid-cols-[44px_repeat(5,1fr)]">
              <div />
              {days.map((day) => {
                const today = day.toDateString() === now.toDateString();
                return (
                  <p key={day.toISOString()} className={`border-b border-l border-line py-1.5 text-center ${today ? "font-[600] text-door" : "text-ink-soft"}`}>{dayLabel(day.toISOString())}</p>
                );
              })}
              <div className="relative" style={{ height: (END_HOUR - START_HOUR) * HOUR_PX }}>
                {Array.from({ length: END_HOUR - START_HOUR }, (_, index) => (
                  <span key={index} className="tabular absolute right-1.5 text-xs text-ink-faint" style={{ top: index * HOUR_PX - 1 }}>{START_HOUR + index}:00</span>
                ))}
              </div>
              {days.map((day) => {
                const same = (value: string) => new Date(value).toDateString() === day.toDateString();
                const today = day.toDateString() === now.toDateString();
                return (
                  <div key={day.toISOString()} className="relative border-l border-line" style={{ height: (END_HOUR - START_HOUR) * HOUR_PX }}>
                    {Array.from({ length: END_HOUR - START_HOUR }, (_, index) => (
                      <button
                        key={index}
                        type="button"
                        aria-label={`Block out ${START_HOUR + index}:00 on ${dayLabel(day.toISOString())}`}
                        onClick={() => setAdding({ day, hour: START_HOUR + index })}
                        className="absolute inset-x-0 border-b border-line transition-colors hover:bg-door-wash/50"
                        style={{ top: index * HOUR_PX, height: HOUR_PX }}
                      />
                    ))}
                    {week.data?.busy.filter((block) => same(block.starts_at) && block.kind !== "booking").map((block, index) => {
                      const held = block.kind === "hold";
                      return (
                        <motion.div
                          key={block.id ?? `${block.starts_at}-${index}`}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className={`group/block absolute inset-x-1 overflow-hidden rounded-md px-1.5 py-0.5 text-xs ${held ? "border border-dashed border-door bg-door-wash text-door-deep" : "bg-sunken text-ink-soft"}`}
                          style={placed(block)}
                        >
                          {held ? "Held offer" : (block.label ?? "Busy")}
                          {block.id && block.source === "manual" ? (
                            <button type="button" aria-label="Remove" onClick={() => remove(block.id as string)} className="absolute top-0.5 right-0.5 hidden rounded p-0.5 hover:bg-line group-hover/block:block"><Icon name="close" size={10} /></button>
                          ) : null}
                        </motion.div>
                      );
                    })}
                    {week.data?.bookings.filter((booking) => same(booking.starts_at)).map((booking) => (
                      <motion.div key={booking.id} initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} className="absolute inset-x-1 overflow-hidden rounded-md bg-door px-1.5 py-0.5 text-xs font-[520] text-white shadow-soft" style={placed(booking)}>
                        {booking.title ?? "Interview"}
                      </motion.div>
                    ))}
                    {today && nowTop > 0 && nowTop < (END_HOUR - START_HOUR) * HOUR_PX ? (
                      <div className="pointer-events-none absolute inset-x-0 z-10 flex items-center" style={{ top: nowTop }}>
                        <span className="size-2 -translate-x-1 rounded-full bg-bloom" />
                        <span className="h-px flex-1 bg-bloom" />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
        <Panel title="In progress" flush>
          {!hiring.data ? <div className="p-4"><Loading /></div> : null}
          {hiring.data && open.length === 0 ? (
            <div className="p-6 text-center">
              <Face agent={agentById("scheduler")} size={48} track />
              <p className="mt-2 text-ink-soft">Propose interview times from a candidate&rsquo;s page and they appear here.</p>
            </div>
          ) : null}
          <ul>
            {open.map((interview) => (
              <li key={interview.id} className="border-b border-line px-4 py-2.5 last:border-0">
                <p className="flex items-center justify-between gap-2 font-[520]">{nameOf(interview)} <Tag tone={interview.status === "booked" ? "good" : "info"}>{titleCase(interview.status)}</Tag></p>
                <p className="text-ink-soft">
                  {interview.starts_at ? `${dayLabel(interview.starts_at)}, ${timeLabel(interview.starts_at)}` : interview.slots?.length ? `${interview.slots.length} times held` : "Finding times"}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      {adding ? <AddBusy day={adding.day} hour={adding.hour} onClose={() => setAdding(null)} onDone={() => void week.reload()} /> : null}
    </>
  );
}
