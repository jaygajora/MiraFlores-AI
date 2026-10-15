// Shapes of the main API payloads. Report tables and a few one-off views are
// passed through as `Data` (their columns are described by the server).

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Data = Record<string, any>;

export type Role = "preparer" | "reviewer" | "partner" | "firm_administrator" | "quality_reviewer" | "client";
export type Severity = "error" | "warning" | "info";
export type VerifyStatus = "verified" | "recalculated" | "stale" | "unverified" | "";

export interface User {
  id: string;
  name: string;
  role: Role;
  role_title: string;
  credential: string | null;
  clearance: boolean;
  active_from: string;
  note: string | null;
}

export interface Area { id: string; title: string }

export interface Standards {
  variance_review: { flag_if_change_over_percent: number; and_over_amount: number };
  partner_signoff_over: number;
  retention_years?: number;
  verification_types: string[];
  rules: string[];
}

export interface TimelineEntry { at: string; event: string }

export interface Person { id: string; role: string; name: string; dob?: string; relationship?: string; full_time_student?: boolean; months_lived_with_you?: number }

export interface Boot {
  me: User;
  users: User[];
  perms: string[];
  clock: string;
  firm: string;
  packet: { name: string; client_id: string };
  household: { tax_year: number; filing_status: string; people: Person[] };
  areas: Area[];
  reports: { id: string; title: string }[];
  standards: Standards;
  effect_categories: Record<string, string>;
  timeline_next: TimelineEntry[];
  deadlines: { what: string; date: string }[];
  head: number;
}

export interface Effect { fed_tax?: number; ca_tax?: number; fed_payments?: number; ca_payments?: number }

export interface Suggestion { line: string; delta: number; category: string; note?: string }

export interface Disposition { id: string; disposition: string; by: string; at: string; reason?: string; authority?: string }

export interface Finding {
  id: string;
  code?: string;
  kind: string;
  severity: Severity;
  source: "engine" | "check";
  title: string;
  summary: string;
  status: string;
  needs?: string;
  effect: Effect;
  suggestions: Suggestion[];
  lines: string[];
  disposition?: Disposition | null;
  client_answer?: string;
}

export interface OpenItem {
  id: string;
  type: "finding" | "approval" | "note" | "client_answer" | "client_question" | "document" | "reopened";
  title: string;
  summary: string;
  severity: Severity;
  area: string;
  mine: boolean;
  source?: string;
  needs?: string;
  effect?: Effect;
  impact?: number;
  by?: string;
  lines?: string[];
  target?: string;
}

export interface Message { by: string; at: string; text: string }

export interface Note {
  id: string;
  target: string;
  by: string;
  at: string;
  status: "open" | "resolved" | "answered" | string;
  blocking?: boolean;
  assignee?: string;
  thread: Message[];
}

export interface Approval { level: string; by: string; at: string }

export interface Adjustment {
  id: string;
  line: string;
  delta: number;
  engine_value: number | null;
  reason: string;
  authority?: string;
  by: string;
  at: string;
  status: string;
  effect: Effect;
  approvals?: Approval[];
  revert_reason?: string;
}

export interface Step { step: string; why: string; done: boolean; auto?: boolean; evidence?: string[] }

export interface SignoffState { by: string; at: string; valid: boolean; note?: string }

export interface AreaStatus {
  area: string;
  title: string;
  open_findings: number;
  adjustments: number;
  open_notes: number;
  hours: number;
  budget: number | null;
  signoffs: Partial<Record<"preparer" | "reviewer" | "partner", SignoffState>>;
}

export interface ReturnSide { agi?: number; total_tax: number; balance_due: number }

export interface Summary {
  basis: string;
  engine: { federal: ReturnSide; california: ReturnSide };
  workpaper: { federal: ReturnSide; california: ReturnSide };
}

export interface Overview {
  clock: string;
  head: number;
  summary: Summary;
  steps: Step[];
  areas: AreaStatus[];
  changes: { count: number; since: number };
  notifications: { kind: string; text: string }[];
  presence: { name: string; where: string }[];
  timeline_next: TimelineEntry[];
  approvals: { line: string; adjustment: string; size: number; by: string; level: string }[];
  assignments: Record<string, string>;
  team: { id: string; name: string }[];
}

export interface LogEvent {
  id: string;
  seq: number;
  kind: string;
  actor: string;
  actor_name: string;
  sim_at: string;
  target?: string;
  batch?: string;
  text: string;
  undone?: boolean;
}

export interface PageValue {
  id: string;
  label: string;
  span: [number, number] | null;
  landing?: { status: string; lines?: string[]; reason?: string };
  confidence: number;
  text_as_read?: string;
}

export type Span = [number, number];

export type Block =
  | { type: "heading"; spans: Span[] }
  | { type: "text"; spans: Span[] }
  | { type: "fields"; items: { label: string; label_span: Span; value_span: Span; value: string }[] }
  | { type: "table"; kind: string; columns: { key: string; label: string; numeric: boolean }[]; rows: Record<string, Span | null>[] };

export interface Page { page: number; text: string; values: PageValue[]; layout?: Block[]; unread?: boolean }
