/** Release 2 R4: proposals (SM-09, SM-10), approvals (SM-11), public acceptance (SM-12) and proposal templates. */
export type Totals = { one_time: number; one_time_discount?: number; one_time_net?: number; recurring_y1: number; discount: number; y1_total: number; arr: number };

export type Line = {
  id: string; code: string; name: string; description: string | null; deliverables: string | null; deliverables_edited: boolean;
  qty: number; list_price: number | null; low: number | null; high: number | null; override_price: number | null; unit_price_used: number | null;
  periods_per_year: number; line_value: number | null; percent_of: number | null; billing: string; billing_label: string; basis: '$' | '%';
  pricing_unit: string | null; price_status: string | null; sellable_status: string | null; on_catalog: boolean; source: 'rule' | 'package' | 'manual';
  rule_code: string | null; reason: string | null; removed_reason: string | null; edited_by: string | null; edited_at: string | null; badges: string[];
};

export type RuleState = {
  rule: string; kind: 'approval' | 'blocked' | 'note'; approver_role: string | null; approver: string | null; codes: string[]; message: string;
  state: 'missing' | 'pending' | 'approved' | 'returned' | 'outdated' | null; request_id: string | null; note: string | null; decided_at: string | null;
};

export type VersionRef = { id: string; version: number; status: string; status_label: string; sent_at: string | null; y1_total: number | null };

export type ProposalSummary = {
  id: string; thread_id: string; version: number; status: string; status_label: string; title: string; company: string | null; prospect: boolean;
  opportunity_id: string; opportunity: string | null; opportunity_stage: string | null; package: string | null; totals: Totals; valid_days: number;
  valid_until: string | null; sent_at: string | null; editable: boolean; updated_at: string | null;
};

export type Terms = {
  payment_days?: number; payment_terms?: string; term_years?: number; sla?: string; data_region?: string; custom_liability?: string; sla_credits?: string;
  discount_one_time_pct?: number; start_on?: string;
};

export type Section = { key: string; title: string; body: string; edited: boolean };

export type Proposal = ProposalSummary & {
  lines: Line[]; discount_recurring_pct: number; terms: Terms; sections: Section[]; independence: { flag?: boolean; reason?: string };
  catalog_version: number | null; questionnaire_version: number | null; estimate_id: string | null; created_by: string | null; updated_by: string | null;
  sent_by: string | null; rules: RuleState[]; approvals_needed: RuleState[]; can_request: boolean; send_blockers: { rule: string; message: string }[];
  versions: VersionRef[]; price_changes: { code: string; name: string; edited: boolean; changes: Record<string, { from: unknown; to: unknown }> }[]; packages: { key: string; name: string }[]; regions: Record<string, string>; discount_limit_pct: number; can_work: boolean;
};

export type Diff = {
  from: number; to: number;
  lines: { code: string; name: string; kind: 'added' | 'removed' | 'changed'; changes: { field: string; from: unknown; to: unknown }[]; value: number | null; reason?: string | null }[];
  terms: { field: string; from: unknown; to: unknown }[];
  totals: Record<string, { from: number; to: number }>;
};

export type DocSection = { key: string; number: number; title: string; html: string };
export type LogEntry = { kind: string; at: string; by: string | null; detail: string | null; version: number };
export type LinkRow = { id: string; name: string; email: string; sent_at: string; expires_at: string; opened_at: string | null; open_count: number; active: boolean };

export type SendPage = {
  proposal: ProposalSummary; sections: DocSection[]; log: LogEntry[]; links: LinkRow[]; send_blockers: { rule: string; message: string }[];
  approvals: RuleState[]; contacts: { name: string; email: string; title: string | null }[]; default_subject: string; default_message: string;
  sender: string; valid_until_if_sent: string; can_work: boolean;
};

export type ApprovalItem = {
  id: string; rule: string; message: string; codes: string[]; status: string; approver_role: string; approver_label: string; proposal_id: string; version: number;
  company: string; y1_total: number | null; requested_by: string | null; requested_at: string; decided_at: string | null; decided_by: string | null;
  note: string | null; kind: 'pricing' | 'independence';
};

export type ApprovalDetail = ApprovalItem & {
  lines: { code: string; name: string; qty: number; low: number | null; list: number | null; used: number | null; high: number | null; edited: boolean;
    price_status: string | null; value: number | null; focus: boolean }[];
  margin_note: string; totals: Totals; discount_recurring_pct: number; terms: Terms; independence: { flag: boolean; reason: string | null } | null;
  can_decide: boolean; why_not: string | null; note_required: boolean; history: { rule: string; status: string; note: string | null; decided_at: string | null }[];
};

export type PublicProposal = {
  company: string; title: string; version: number; status: string; valid_until: string | null; valid_until_label: string;
  rep: { name: string | null; email: string | null }; included: { name: string; summary: string }[]; optional: { name: string }[];
  pricing: { name: string; qty: number; billing: string; unit: string; value: number | null; recurring: boolean }[]; totals: Totals;
  discount_recurring_pct: number; discount_one_time_pct: number; terms: string[]; sections: DocSection[]; contact: { name: string; email: string };
  accepted: { name: string; title: string; at: string; po_number: string | null } | null; can_respond: boolean;
};

export type ProposalTemplate = {
  key: string; title: string; body: string; sort: number; active: boolean; is_starter: boolean; always: boolean; auto: string | null;
  updated_by: string | null; updated_at: string | null;
};

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  const neg = v < 0;
  const s = Math.abs(v).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
  return neg ? `−${s}` : s;
}
