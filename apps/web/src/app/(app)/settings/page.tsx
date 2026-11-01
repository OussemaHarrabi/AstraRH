"use client";

import { type FormEvent, useState } from "react";
import { get, type Pack } from "@/lib/api";
import { EMPTY_MAP, newId, useLocal } from "@/lib/local";
import { Icon } from "@/ui/Icon";
import { Avatar, Button, Field, Loading, Modal, PageHeader, Panel, RiskTag, Tabs, Tag, titleCase, useLoad } from "@/ui/kit";
import { useMe, useToast } from "@/ui/Shell";

type Tab = "account" | "team" | "rules" | "templates" | "privacy";

const TEAM = [
  ["Nadia Ben Salah", "nadia@cds.example.test", "Recruiter"],
  ["Leila Haddad", "leila@cds.example.test", "HR"],
  ["Karim Jaziri", "karim@cds.example.test", "Manager"],
  ["Sami Trabelsi", "sami@cds.example.test", "Finance"],
  ["Audit Office", "audit@cds.example.test", "Auditor"],
  ["Platform Admin", "admin@cds.example.test", "Admin"],
];

interface Template { id: string; name: string; body: string }
interface Erasure { id: string; email: string; at: string; status: string }

const DEFAULT_TEMPLATES: Template[] = [
  { id: "t1", name: "Application received", body: "Hello {first_name}, we received your application for {job_title}. We will get back to you within a week." },
  { id: "t2", name: "Interview invitation", body: "Hello {first_name}, we would like to meet you for {job_title}. Here are three times that work for us." },
];
const NO_ERASURES: Erasure[] = [];
const NO_INVITES: { id: string; email: string; role: string }[] = [];
const DEFAULT_NOTIFY = { approvals: true, digest: true, mentions: true, failures: false };

function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="row-hover -mx-2 flex items-center justify-between gap-4 rounded-lg px-2 py-2">
      <span>{label}</span>
      <input type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[var(--door)]" />
    </label>
  );
}

function Account() {
  const me = useMe();
  const [notify, setNotify] = useLocal("settings.notify", DEFAULT_NOTIFY);
  const [theme, setTheme] = useLocal<"system" | "light" | "dark">("theme", "system");
  if (!me) return null;
  return (
    <div className="mt-4 grid items-start gap-5 lg:grid-cols-2">
      <Panel title="Your profile">
        <div className="flex items-center gap-3">
          <Avatar name={me.display_name} size={48} />
          <div>
            <p className="text-[15px] font-[560]">{me.display_name}</p>
            <p className="text-ink-soft">{me.email}</p>
            <div className="mt-1 flex gap-1">{me.roles.map((role) => <Tag key={role} tone="info">{titleCase(role)}</Tag>)}</div>
          </div>
        </div>
      </Panel>
      <Panel title="Appearance">
        <div className="flex gap-1.5">
          {(["system", "light", "dark"] as const).map((value) => (
            <button key={value} type="button" aria-pressed={theme === value} onClick={() => setTheme(value)} className={`h-8.5 flex-1 rounded-lg border font-[500] transition-colors ${theme === value ? "border-door bg-door-wash text-door-deep" : "border-line-strong hover:bg-plaster"}`}>{titleCase(value)}</button>
          ))}
        </div>
      </Panel>
      <Panel title="Notifications" className="lg:col-span-2">
        <Switch label="A proposal is waiting for my decision" checked={notify.approvals} onChange={(value) => setNotify({ ...notify, approvals: value })} />
        <Switch label="The daily inbox digest is ready" checked={notify.digest} onChange={(value) => setNotify({ ...notify, digest: value })} />
        <Switch label="Someone mentions me in a note" checked={notify.mentions} onChange={(value) => setNotify({ ...notify, mentions: value })} />
        <Switch label="An agent run fails" checked={notify.failures} onChange={(value) => setNotify({ ...notify, failures: value })} />
      </Panel>
    </div>
  );
}

function Team() {
  const toast = useToast();
  const [invites, setInvites] = useLocal("settings.invites", NO_INVITES);
  const [inviting, setInviting] = useState(false);
  function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setInvites((list) => [{ id: newId(), email: String(form.get("email")), role: String(form.get("role")) }, ...list]);
    setInviting(false);
    toast("Invitation saved on this device. Sending invitations isn't connected yet.");
  }
  return (
    <Panel className="mt-4" flush title="People with access" action={<Button size="sm" onClick={() => setInviting(true)}><Icon name="plus" size={13} /> Invite</Button>}>
      <ul>
        {invites.map((item) => (
          <li key={item.id} className="row-hover flex items-center gap-3 border-b border-line px-4 py-2.5">
            <Avatar name={item.email} size={28} />
            <span className="min-w-0 flex-1 truncate">{item.email}</span>
            <Tag>{item.role}</Tag>
            <Tag tone="warn">Not sent</Tag>
            <Button size="sm" variant="quiet" onClick={() => setInvites((list) => list.filter((entry) => entry.id !== item.id))}>Remove</Button>
          </li>
        ))}
        {TEAM.map(([name, email, role]) => (
          <li key={email} className="row-hover flex items-center gap-3 border-b border-line px-4 py-2.5 last:border-0">
            <Avatar name={name} size={28} />
            <span className="min-w-0 flex-1"><span className="block font-[520]">{name}</span><span className="block truncate text-ink-soft">{email}</span></span>
            <Tag tone="info">{role}</Tag>
          </li>
        ))}
      </ul>
      <Modal open={inviting} onClose={() => setInviting(false)} label="Invite someone" width={400}>
        <form onSubmit={invite} className="space-y-3 p-5">
          <h2 className="text-[17px] font-[560]">Invite someone</h2>
          <Field label="Work email"><input name="email" type="email" required autoFocus className="field" /></Field>
          <Field label="Role">
            <select name="role" className="field">{["Recruiter", "HR", "Manager", "Finance", "Employee", "Auditor"].map((role) => <option key={role}>{role}</option>)}</select>
          </Field>
          <div className="flex gap-2"><Button type="submit">Save invitation</Button><Button variant="secondary" onClick={() => setInviting(false)}>Cancel</Button></div>
        </form>
      </Modal>
    </Panel>
  );
}

function Rules() {
  const { data } = useLoad(() => get<Pack[]>("/registry/packs"), []);
  if (!data) return <Loading rows={8} />;
  return (
    <div className="mt-4 space-y-5">
      <p className="text-ink-soft">The rules agents work under, read directly from each module. An action that isn&rsquo;t declared here can&rsquo;t run.</p>
      {data.map((pack) => (
        <Panel key={pack.id} flush title={pack.name} action={<Tag tone={pack.status === "live" ? "good" : "neutral"}>{titleCase(pack.status)}</Tag>}>
          <ul>
            {pack.actions.map((action) => (
              <li key={action.id} className="row-hover flex items-center gap-3 border-b border-line px-4 py-2 last:border-0">
                <span className="min-w-0 flex-1">{action.description}</span>
                <RiskTag risk={action.risk} />
              </li>
            ))}
          </ul>
        </Panel>
      ))}
    </div>
  );
}

function Templates() {
  const toast = useToast();
  const [templates, setTemplates] = useLocal("settings.templates", DEFAULT_TEMPLATES);
  const [drafts, setDrafts] = useLocal<Record<string, string>>("settings.template.drafts", EMPTY_MAP);
  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-ink-soft">Wording your team prefers. Saved on this device for now.</p>
        <Button size="sm" onClick={() => setTemplates((list) => [...list, { id: newId(), name: "New template", body: "" }])}><Icon name="plus" size={13} /> New template</Button>
      </div>
      {templates.map((template) => (
        <Panel key={template.id}>
          <input aria-label="Template name" value={template.name} onChange={(event) => setTemplates((list) => list.map((item) => (item.id === template.id ? { ...item, name: event.target.value } : item)))} className="w-full bg-transparent font-[560] outline-none" />
          <textarea
            aria-label={`${template.name} wording`}
            rows={3}
            value={drafts[template.id] ?? template.body}
            onChange={(event) => setDrafts((all) => ({ ...all, [template.id]: event.target.value }))}
            className="field mt-2"
          />
          <div className="mt-2 flex gap-1.5">
            <Button size="sm" variant="secondary" onClick={() => { setTemplates((list) => list.map((item) => (item.id === template.id ? { ...item, body: drafts[template.id] ?? item.body } : item))); toast("Template saved."); }}>Save</Button>
            <Button size="sm" variant="quiet" onClick={() => setTemplates((list) => list.filter((item) => item.id !== template.id))}>Delete</Button>
          </div>
        </Panel>
      ))}
    </div>
  );
}

function Privacy() {
  const toast = useToast();
  const [requests, setRequests] = useLocal("settings.erasures", NO_ERASURES);
  const [retention, setRetention] = useLocal("settings.retention", 24);
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const email = String(new FormData(form).get("email"));
    setRequests((list) => [{ id: newId(), email, at: new Date().toISOString(), status: "Waiting for review" }, ...list]);
    form.reset();
    toast("Request recorded on this device. Deleting the data still needs the backend step.");
  }
  return (
    <div className="mt-4 grid items-start gap-5 lg:grid-cols-2">
      <Panel title="How long we keep candidate data">
        <label className="flex items-center gap-3">
          <input type="range" min={6} max={60} step={6} value={retention} onChange={(event) => setRetention(Number(event.target.value))} className="flex-1 accent-[var(--door)]" aria-label="Months to keep candidate data" />
          <span className="tabular w-24 text-right font-[520]">{retention} months</span>
        </label>
        <p className="mt-2 text-ink-soft">Automatic deletion isn&rsquo;t connected yet. This records the policy your team chooses.</p>
      </Panel>
      <Panel title="Requests to delete personal data">
        <form onSubmit={add} className="flex gap-2">
          <input name="email" type="email" required aria-label="Candidate email" placeholder="Candidate email" className="field flex-1" />
          <Button type="submit">Record request</Button>
        </form>
        <ul className="mt-2">
          {requests.map((request) => (
            <li key={request.id} className="flex items-center justify-between gap-3 border-t border-line py-2 first:border-0">
              <span className="truncate">{request.email}</span>
              <Tag tone="warn">{request.status}</Tag>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("account");
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "account", label: "Account" },
          { id: "team", label: "Team" },
          { id: "rules", label: "Approval rules" },
          { id: "templates", label: "Templates" },
          { id: "privacy", label: "Data and privacy" },
        ]}
      />
      {tab === "account" ? <Account /> : null}
      {tab === "team" ? <Team /> : null}
      {tab === "rules" ? <Rules /> : null}
      {tab === "templates" ? <Templates /> : null}
      {tab === "privacy" ? <Privacy /> : null}
    </>
  );
}
