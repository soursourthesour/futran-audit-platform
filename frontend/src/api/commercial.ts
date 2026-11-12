import { useQuery } from '@tanstack/react-query';
import { api } from './client';

/** Release 2 R5: SM-13 handoff, G-01 plan and usage, G-02 engagement commercials, G-03 time and hours. */

export type HandoffItem = { kind: string; label: string; details: string; status: string; next_owner: string | null; link: string | null; ref_id: string | null };
export type Handoff = {
  id: string; opportunity_id: string; client_id: string; client_name: string; client_status: string | null; order_id: string | null; items: HandoffItem[];
  accepted_by: { name: string | null; title: string | null; po_number: string | null; at: string; version: number } | null; year1_value: number;
  needs_separate_team: string[]; status: 'awaiting' | 'confirmed';
  team: { account_owner_id: string | null; account_owner_name: string | null; separate_team: { id: string; name: string | null }[]; independence_note: string | null };
  independence_confirmed_by: string | null; independence_confirmed_at: string | null; confirmed_by: string | null; confirmed_at: string | null;
  can_confirm: boolean; can_confirm_independence: boolean; can_view_plan: boolean; staff: { id: string; name: string }[];
};
export const useHandoff = (oppId: string) => useQuery({ queryKey: ['handoff', oppId], queryFn: () => api.get<Handoff>(`/sales/opportunities/${oppId}/handoff`), retry: false });

export type EntitlementRow = { key: string; label: string; unit: string | null; limit: number; used: number | null; pct: number | null; hard: boolean; enabled: boolean | null;
  over_plan: boolean; near_limit: boolean; measured_on: string | null };
export type PlanOrderLine = { id: string; order_ref: string; code: string; description: string | null; qty: number; unit_price: number; billing: string; start_on: string | null;
  end_on: string | null; entitlement: string | null; line_value: number; engagement_id: string | null; change_order_id: string | null };
export type PlanPage = {
  client: { id: string; name: string; client_ref: string | null; status: string };
  plan: { plan: string; plan_label: string; tier: string | null; start_on: string | null; term_end_on: string | null; renewal_alert_on: string | null; auto_renew: boolean | null;
    data_region: string | null; support_level: string | null; onboarding_fee_waived: boolean | null; order_ref: string | null; from_order: boolean };
  entitlements: EntitlementRow[]; over_plan: string[]; order_lines: PlanOrderLine[];
  exports: { id: string; period: string; rows: number; run_at: string; all_clients: boolean }[]; can_edit: boolean; can_export: boolean;
};
export const usePlan = (clientId: string) => useQuery({ queryKey: ['plan', clientId], queryFn: () => api.get<PlanPage>(`/staff/clients/${clientId}/plan`) });

export type ChangeOrderLine = { code: string; description: string | null; qty: number; unit_price?: number; list_price?: number; value?: number };
export type ChangeOrder = {
  id: string; ref: string; engagement_id: string; kind: string | null; kind_label: string | null; reason: string; lines: ChangeOrderLine[]; status: string; status_label: string;
  raised_by: string | null; raised_at: string; em_approved_by: string | null; needs_price_approval: boolean; futran_approved_by: string | null; client_approved_by: string | null;
  approved_at: string | null; decided_note: string | null; scope_change_ref: string | null; applied: boolean; value?: number; engagement_name?: string; audit_ref?: string | null;
};
export type Milestone = { label: string; trigger: string; trigger_label: string; pct: number; amount: number; reached_on: string | null; status: string };
export type CommercialPage = {
  engagement: { id: string; name: string; audit_ref: string | null; client_id: string; client_name: string; status: string };
  order: { id: string; ref: string; po_number: string | null } | null; fee_total: number | null; has_commercials: boolean;
  order_lines: { id: string; code: string; description: string | null; qty: number; unit_price: number; value: number; change_order_id: string | null }[];
  milestones: Milestone[]; deliverables: { code: string; text: string }[]; change_orders: ChangeOrder[]; kinds: { code: string; label: string }[];
  can_edit: boolean; can_raise: boolean; can_approve_price: boolean; can_manager_approve: boolean; me: string;
};
export const useCommercial = (engagementId: string) => useQuery({ queryKey: ['commercial', engagementId], queryFn: () => api.get<CommercialPage>(`/e/${engagementId}/commercial`) });

export type TimeTarget = { key: string; label: string; kind: 'engagement' | 'bank' | 'retainer' | 'internal'; billable_default: boolean; status?: string };
export type TimeRow = { target: string; label: string; activity: string; activity_label?: string; billable: boolean; billable_label?: string; note: string | null;
  hours: Record<string, number>; total?: number };
export type Week = {
  week_start: string; days: string[]; rows: TimeRow[]; total: number; billable_total: number; status: 'draft' | 'submitted' | 'approved' | 'returned';
  targets: TimeTarget[]; activities: { code: string; label: string }[]; can_approve: boolean; can_view_margins: boolean; can_manage_costs: boolean; can_manage_retainers: boolean;
};
export type Banks = {
  banks: { id: string; client_id: string; client_name: string; code: string; label: string; purchased: number; used: number; remaining: number; pct: number | null; over: number;
    expires_on: string | null }[];
  retainers: { id: string; client_id: string; client_name: string; code: string; type: string; status: string; monthly_fee: number; hourly_rate: number | null;
    monthly_hours: number | null; hours_this_month: number; hours_billed: number; activated_at: string | null; incident_engagement_id: string | null }[];
};
export type Margins = {
  engagements: { engagement_id: string; label: string; fee: number; hours: number; cost: number | null; margin: number | null; margin_pct: number | null }[];
  missing_costs: string[]; costs: { role: string; cost_per_hour: number; effective_from: string }[];
};

export const money = (v: number | null | undefined, cents = false) =>
  v == null ? '—' : `$${v.toLocaleString('en-US', { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 })}`;
export const hrs = (v: number | null | undefined) => (v == null ? '—' : `${Number(v.toFixed(2)).toString()}`);
