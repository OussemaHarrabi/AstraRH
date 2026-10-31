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
}
