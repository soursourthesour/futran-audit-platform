/** Release 2 R2 sales desk: opportunity shapes from /api/v1/opportunities and /api/v1/sales/* (backend app/sales). */
export type Opt = { value: string; label: string };
export type Company = { id: string | null; name: string; kind: 'client' | 'prospect'; website?: string | null; industry?: string | null; size_band?: string | null; hq?: string };
export type Bant = { budget?: string | null; authority?: string | null; need?: string | null; timeline?: string | null };

export type Opp = {
  id: string; organization_id: string; client_name: string; name: string; company: Company; trigger: string; trigger_label: string; is_automatic: boolean;
  service: string; service_kind: string; why_now: string | null; value: number | null; est_value: number | null;
  owner_id: string | null; owner_name: string | null; stage: string; stage_label: string; next_step: string | null; next_step_due: string | null;
  system_types: string[]; system_count: number; addon_status: string | null;
  needs_ca_approval: boolean; approval: string; ca_decision: string | null; ca_approved_by_name: string | null; ca_note: string | null; can_send_offer: boolean;
  approval_requested_at: string | null; created_at: string; closed_at: string | null;
  source: string | null; source_label: string | null; partner_id: string | null; segment: string | null; segment_label: string | null;
  trigger_event: string | null; trigger_event_label: string | null; products_of_interest: string[]; products_labels: string[]; close_date: string | null;
  lost_reason: string | null; lost_reason_label: string | null; lost_note: string | null; bant: Bant; competitors: string[];
  independence_flag: boolean; independence_reason: string | null; last_activity_at: string | null; stale: boolean;
};

export type Reply = { id: string; from: string | null; at: string; subject: string | null; snippet: string | null };
export type ActivityRow = {
  id: string; kind: string; summary: string; by: string | null; at: string; outcome: string | null; next_step: string | null; due_on: string | null; done_at: string | null;
  to: string[]; replies: Reply[];
};
export type Contact = { id: string; name: string; title: string | null; email: string | null; phone: string | null; contact_role: string | null; contact_role_label: string | null };
export type Linked = {
  questionnaire: { id: string; version: number; status: string; mode: string; link: string } | null;
  estimates: { id: string; name: string; version: number | null; link: string }[];
  proposals: { id: string; version: number; status: string; title: string; sent_at: string | null; link: string }[];
  order: { id: string; ref: string | null; status: string; link: string } | null;
};
export type OppDetail = Opp & {
  activities: ActivityRow[]; contacts: Contact[]; linked: Linked; can_work: boolean; can_reassign: boolean; can_approve: boolean; owners: { id: string; name: string }[];
};

export type OppList = {
  items: Opp[]; owners: { id: string; name: string }[]; clients: { id: string; name: string }[];
  kpis: { open: number; created_by_triggers_this_month: number; waiting_approval: number; pipeline_value: number; won_this_quarter: number };
  triggers: Opt[]; stages: Opt[]; sources: Opt[]; segments: Opt[]; trigger_events: Opt[]; products: Opt[]; lost_reasons: Opt[]; contact_roles: Opt[];
  industries: string[]; size_bands: string[]; can_approve: boolean; can_work: boolean; can_reassign: boolean;
};

export type Duplicate = { organization_id: string; name: string; kind: 'client' | 'prospect'; website: string | null; reason: string; open_opportunity_id: string | null };

export type Brief = { id: string; name: string; company: string; stage: string; stage_label: string; value: number | null; next_step: string | null; next_step_due: string | null };
export type SalesHome = {
  scope: 'mine' | 'team'; can_see_team: boolean;
  kpis: { open_pipeline: number; open_count: number; weighted: number; proposals_out: number; proposals_expiring: number; won_this_quarter: number; won_count: number };
  by_stage: { stage: string; label: string; count: number; value: number }[];
  next_steps: Brief[]; tasks: { id: string; opportunity_id: string; summary: string; due_on: string | null; company: string }[];
  stale: (Brief & { days: number })[];
  approvals: { kind: 'to_decide' | 'waiting'; opportunity_id: string; label: string; rule: string; approver: string; link: string }[];
  recent_wins: (Brief & { closed_at: string })[];
  new_automatic: (Brief & { trigger_label: string; why_now: string | null })[];
};

export const PIPELINE = ['new', 'qualified', 'scoping', 'proposal', 'negotiation'];
export const STAGE_TONE: Record<string, 'navy' | 'warn' | 'success' | 'muted' | 'default' | 'danger'> = {
  new: 'default', contacted: 'default', qualified: 'navy', scoping: 'navy', proposal: 'warn', negotiation: 'warn', won: 'success', lost: 'muted', on_hold: 'muted',
};
export const usd = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${v.toLocaleString('en-US')}`);
export const oppLink = (id: string) => `/sales/opportunities/${id}`;
