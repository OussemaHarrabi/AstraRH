/** Typed client for the AstraRH API. Same origin, cookie session, double-submit CSRF. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )astra_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    headers.set("x-csrf-token", csrfToken());
    if (typeof init.body === "string") headers.set("content-type", "application/json");
  }
  const response = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? "Please check the values you entered." : body.detail;
    throw new ApiError(
      response.status,
      body.error ?? "error",
      body.message ?? detail ?? "The server could not complete this request.",
    );
  }
  if (response.status === 204) return null as T;
  return response.json();
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body: unknown = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const upload = <T,>(path: string, form: FormData) =>
  request<T>(path, { method: "POST", body: form });

export interface Me {
  user_id: string;
  display_name: string;
  email: string;
  roles: string[];
  step_up_fresh: boolean;
}

export interface Pack {
  id: string;
  name: string;
  status: string;
  description: string;
  route: string | null;
  nav_label: string | null;
  roles: string[];
  actions: { id: string; risk: string; description: string }[];
  agents: { id: string; title: string; description: string }[];
}

export interface Job {
  id: string;
  external_id?: string | null;
  title: string;
  description: string;
  org_unit: string | null;
  active_rubric_id: string | null;
  cv_counts: Record<string, number>;
}

export interface Criterion {
  id: string;
  label: string;
  weight: string;
  must_have?: boolean;
  required_years?: number;
  description?: string;
  keywords?: string[];
}

export interface Rubric {
  id: string;
  version: number;
  status: string;
  source: string;
  criteria: Criterion[];
}

export interface JobDetail extends Job {
  rubrics: Rubric[];
}

export interface Factor {
  key: string;
  label: string;
  weight: string;
  value: string;
  contribution: string;
}

export interface RankedCandidate {
  application_id: string;
  name: string | null;
  rank: number;
  score: string | null;
  meets_must_haves: boolean;
  missing_must_haves: string[];
  stage: string;
  decision_record_id: string | null;
  narrative: string | null;
  flagged: boolean;
  flags: string[];
  parse_method: string | null;
  factors: Factor[];
}

export interface Shortlist {
  ranking: {
    id: string;
    status: string;
    finished_at: string | null;
    order_hash: string | null;
    embedding_model: string | null;
  } | null;
  candidates: RankedCandidate[];
  unranked: { filename: string; status: string; reason: string | null }[];
}

export interface CvStatus {
  id: string;
  filename: string;
  status: string;
  status_reason: string | null;
  flagged: boolean;
}

export interface Proposal {
  id: string;
  action_type: string;
  status: string;
  risk: string;
  summary: string;
  payload: Record<string, unknown>;
  target: Record<string, unknown>;
  decision_record_id: string;
  revision: number;
  payload_hash?: string;
  agent_run_id?: string | null;
  expires_at: string;
  created_at: string;
}

export interface Why {
  id: string;
  kind: string;
  question: string;
  outcome: Record<string, unknown>;
  score: string | null;
  rationale: string | null;
  narrative: string | null;
  factors: Factor[];
  evidence: {
    ref: string;
    factor_key: string | null;
    source_type: string;
    quote: string;
    locator: { kind?: string; years?: string | null };
  }[];
  counterfactuals: {
    description: string;
    outcome: { rank?: number; score?: string };
  }[];
  not_considered: string[];
  limits: string[];
  versions: Record<string, unknown>;
  scorer: string | null;
  trace_id: string | null;
  human_decisions: { decision: string; status: string; reason: string | null; at: string }[];
}

export interface AuditRow {
  seq: number;
  at: string;
  actor_type: string;
  actor_id: string;
  action: string;
  result: string;
  reason: string | null;
  proposal_id: string | null;
  hash: string;
}

export interface DigestItem {
  message_id: string;
  thread_id: string;
  sender: string;
  subject: string;
  summary: string;
  urgency: string;
  needs_human: boolean;
  human_reason: string | null;
  flagged: boolean;
  sent_at: string;
}

export interface Digest {
  day: string;
  totals: { messages: number; needs_human: number; high_urgency: number; flagged: number };
  groups: Record<string, DigestItem[]>;
}

export interface ThreadView {
  id: string;
  subject: string;
  party_email: string;
  pending_reply_ids: string[];
  messages: {
    id: string;
    direction: string;
    sender: string;
    body: string;
    sent_at: string;
    needs_human: boolean | null;
    human_reason: string | null;
    flagged: boolean;
  }[];
}

export interface AskedQuestion {
  id: string;
  text: string;
  status: string;
  answer: string | null;
  refusal_reason: string | null;
  citations: { ref: string; document: string; section: string; quote: string }[];
}

export interface HrTicket {
  id: string;
  reason: string;
  question: string;
  asked_at: string;
}

export interface Interview {
  id: string;
  application_id: string;
  status: string;
  slots: { starts_at: string; ends_at: string }[];
  starts_at: string | null;
  ends_at?: string | null;
  candidate?: string | null;
  created_at?: string;
}

export interface Sorting {
  type: string;
  urgency: string;
  needs_human: boolean;
  human_reason: string | null;
  summary: string;
  quote: string | null;
  flagged: boolean;
  flags: string[];
  corrected: boolean;
  model_values: Record<string, unknown> | null;
}

export interface ThreadRow {
  id: string;
  subject: string;
  party_email: string;
  status: string;
  last_message_at: string;
  handled_at: string | null;
  handled_note: string | null;
  messages: number;
  latest_inbound: { message_id: string; sender: string; sent_at: string; sorting: Sorting | null } | null;
  pending_reply_ids: string[];
}

export interface ThreadPage {
  items: ThreadRow[];
  next_before: string | null;
}

export interface ThreadDetail {
  id: string;
  subject: string;
  party_email: string;
  status: string;
  last_message_at: string;
  handled_note: string | null;
  pending_reply_ids: string[];
  messages: {
    id: string;
    direction: string;
    sender: string;
    recipient: string;
    subject: string;
    body: string;
    sent_at: string;
    sorting: Sorting | null;
    attachments: { id: string; filename: string; status: string; reason?: string | null }[];
  }[];
}

export interface InboxStats {
  threads: { open: number; handled: number };
  open_needing_a_person: number;
  open_messages_by_type: Record<string, number>;
  flagged_messages: number;
  classified_messages: number;
  corrected_by_a_person: number;
  types: string[];
  urgencies: string[];
}

export interface AgentRun {
  id: string;
  agent: string;
  pack: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  error: string | null;
  trace_id: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentRunDetail extends AgentRun {
  steps: {
    name: string;
    tier: string | null;
    provider: string | null;
    model: string | null;
    input_tokens: number;
    output_tokens: number;
    cost_usd: string;
    latency_ms: number;
    cached: boolean;
    fallback: boolean;
  }[];
}

export interface GraphData {
  nodes: { id: string; label: string; props: Record<string, string> }[];
  edges: { from: string; to: string; type: string }[];
  rows: Record<string, unknown>[];
}

export interface Employee {
  id: string;
  external_id: string | null;
  display_name: string;
  email: string;
  org_unit_id: string;
  position_id: string;
  manager_id: string | null;
  start_date: string;
  status: string;
}

export interface OrgReference {
  org_units: { id: string; external_id: string; name: string }[];
  positions: { id: string; external_id: string; title: string }[];
  skills: { id: string; external_id: string; name: string }[];
  kpis: { id: string; external_id: string; name: string; unit: string }[];
}

export interface Plan {
  id: string;
  employee_id: string;
  start_date: string;
  target_ramp_date: string;
  status: string;
  phase: string;
}

export interface PlanDetail extends Plan {
  tasks: {
    id: string;
    phase: string;
    position: number;
    title: string;
    owner_role: string;
    due_at: string;
    status: string;
    mandatory: boolean;
    evidence_required: string | null;
  }[];
  checkins?: { id: string; status: string; due_at?: string; day?: number; kind?: string }[];
  flags?: { id?: string; kind?: string; message?: string; reason?: string; severity?: string }[];
}

export interface SkillGap {
  id: string;
  employee_id: string;
  skill_id: string;
  current_level: number;
  required_level: number;
  severity: string;
  message: string;
  status: string;
}

export interface PolicyDocument {
  id: string;
  external_id: string;
  title: string;
  version: string;
  audience_roles: string[];
  status: string;
  sections: number;
  published_at: string;
}

export interface Ticket {
  id: string;
  status: string;
  reason: string;
  question: string;
  asked_at: string;
  assignee?: string | null;
  answer?: string | null;
}

export interface Booking {
  id: string;
  title?: string;
  starts_at: string;
  ends_at: string;
  status: string;
  participants?: string[];
}

export interface BusyItem {
  id?: string;
  kind?: string;
  source?: string;
  label?: string | null;
  starts_at: string;
  ends_at: string;
}

export interface PayrollRun {
  id: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: string;
  totals?: Record<string, string>;
}

export const put = <T,>(path: string, body: unknown = {}) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });
