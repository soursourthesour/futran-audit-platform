/** Release 2 R1: master price list (SM-14) and Estimator (SM-15). */
export type Pending = { id: string; code: string; field: string; label: string; old_display: string; new_display: string; new_value: unknown; effective_from: string | null; status: string; by: string; reason: string };
export type Item = {
  id: string; code: string; product: string; name: string; deliverables: string | null; description: string | null; pricing_unit: string | null; billing: string;
  basis: '$' | '%'; periods_per_year: number; low: number | null; list_price: number | null; high: number | null; price_status: string; sellable_status: string;
  delivery_mode: string | null; platform_feature_ref: string | null; included_quantities: Record<string, number>; applies_to: string[]; remediation_of: string[];
  engagement_type: string | null; entitlement_key: string | null; notes: string | null; status: 'active' | 'retired'; is_starter: boolean; range: string;
  billing_label: string; included_text: string; version_no: number; last_changed_by: string | null; last_changed_at: string | null; pending: Pending[];
  can_add?: boolean; why_not?: string | null;
};
export type Enums = {
  products: string[]; billing: Record<string, string>; price_status: Record<string, string>; sellable_status: Record<string, string>; delivery_mode: Record<string, string>;
  fields: Record<string, string>; suggestion_fields: Record<string, string>;
};
export type Settings = { second_check: boolean; second_check_pct: number; manager_discount_limit_pct: number };
export type Grid = {
  items: Item[]; version: number; last_saved: { version: number; saved_by: string; saved_at: string; reason: string } | null;
  counts: { items: number; available: number; manual_delivery: number; roadmap: number; retired: number }; starter: boolean;
  can_edit: boolean; can_suggest: boolean; can_manage_packages: boolean; open_suggestions: number | null; awaiting_check: Pending[]; settings: Settings;
  rule_flags: { rule_code: string; line_code: string; problem: string }[]; enums: Enums; package_count: number;
};
export type Change = {
  id: string; code: string; field: string; label: string; old_value: unknown; new_value: unknown; old_display: string; new_display: string; reason: string; by: string;
  by_id: string | null; at: string; version: number; source: string; status: string; effective_from: string | null; confirmed_by: string | null;
};
export type PackageLine = { code: string; qty: number; name: string | null; list_price: number | null; billing: string | null; sellable_status: string | null; price_status: string | null; problem: string | null };
export type Package = { id: string; key: string; name: string; description: string | null; lines: PackageLine[]; is_starter: boolean; updated_by: string | null; updated_at: string | null };
export type Suggestion = { id: string; item_code: string | null; field: string; field_label: string; suggested_value: string; reason: string; status: string; by: string; at: string; decided_by: string | null; decision_note: string | null };
export type ImportPreview = {
  id: string; filename: string; rows: number; base_version: number; adds: { row: number; code: string; name: string }[];
  changes: { row: number; code: string; field: string; label: string; old_display: string; new_display: string }[];
  retirements: { code: string; name: string; missing?: boolean }[]; restores: { code: string; name: string }[];
  errors: { row?: number; code?: string; field?: string; message: string }[]; warnings: { code: string; message: string }[]; can_save: boolean;
};

export type EstLine = {
  code: string; name: string; product: string; description: string | null; description_override: string | null; deliverables: string | null; deliverables_override: string | null;
  catalog_deliverables: string | null; qty: number; list_price: number | null; low: number | null; high: number | null; edited_price: number | null; unit_price_used: number | null;
  edited: boolean; billing: string; billing_label: string; basis: '$' | '%'; periods_per_year: number; price_status: string; sellable_status: string; item_status: string;
  assumption: string | null; line_value: number; recurring: boolean; value_difference: number; unit_difference: number; fixed: boolean; edited_by?: string | null; percent_of?: number;
};
export type Approval = { rule: string; kind: 'approval' | 'blocked' | 'note'; approver_role: string | null; approver: string | null; codes: string[]; message: string };
export type Totals = { one_time: number; one_time_discount: number; one_time_net: number; recurring_y1: number; discount: number; y1_total: number; arr: number };
export type Evaluation = { lines: EstLine[]; totals: Totals; approvals: Approval[]; summary: string; catalog_version: number };
export type Terms = { payment_days?: number; custom_liability?: string; sla_credits?: boolean; discount_one_time_pct?: number };
export type Estimate = {
  id: string; thread_id: string; name: string; version: number; opportunity_id: string | null; opportunity: string | null; package: string | null; discount_recurring_pct: number;
  term: number; data_region: string | null; terms: Terms; totals: Totals; approvals: Approval[]; summary: string; catalog_version: number; saved_by: string; saved_at: string;
  converted_proposal_id: string | null; can_convert: boolean; convert_note: string | null; lines?: EstLine[];
  versions?: { id: string; version: number; saved_by: string; saved_at: string; y1_total: number }[]; price_changes?: { code: string; name: string; old: number; new: number }[];
  current_catalog_version?: number;
};
export type EstimatorRef = {
  items: Item[]; packages: Package[]; catalog_version: number; opportunities: { id: string; name: string }[]; regions: Record<string, string>; terms: number[];
  discount_limit_pct: number; can_convert: boolean; convert_note: string | null;
};

export const PRICE_TONE: Record<string, 'success' | 'warn' | 'muted' | 'navy'> = { approved: 'success', proposed: 'warn', existing: 'navy' };
export const SELL_TONE: Record<string, 'success' | 'warn' | 'muted' | 'navy' | 'danger'> = { available: 'success', manual_delivery: 'warn', roadmap: 'muted' };
export const PRICE_LABEL: Record<string, string> = { approved: 'Approved', proposed: 'Proposed', existing: 'Existing' };
export const SELL_LABEL: Record<string, string> = { available: 'Available', manual_delivery: 'Manual delivery', roadmap: 'Roadmap' };

export function money(v: number | null | undefined, basis: '$' | '%' = '$'): string {
  if (v === null || v === undefined) return '—';
  if (basis === '%') return `${v}%`;
  const neg = v < 0;
  const s = `$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  return neg ? `−${s}` : s;
}

export function signedMoney(v: number): string {
  if (v === 0) return '$0';
  return v > 0 ? `+${money(v)}` : money(v);
}

/** The first sentence or so of a deliverables text, for the grid. */
export function summary(text: string | null | undefined, max = 170): string {
  if (!text) return '';
  const flat = text.replace(/\s*\n\s*•?\s*/g, ' ').replace(/^•\s*/, '').trim();
  return flat.length > max ? `${flat.slice(0, max).replace(/\s+\S*$/, '')}…` : flat;
}
