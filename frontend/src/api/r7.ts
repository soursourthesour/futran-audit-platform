/** Release 2 R7: client hierarchy (G-04), evidence vault and retention (G-10), partners and referrals (G-11). */
import { api } from '@/api/client';

export type Rollup = { systems_total: number; by_stage: Record<string, number>; high_risk: number; bias_audit_due: number; audit: { status: string; stage: string } | null };
export type Ll144Scope = { in_scope: boolean; aedts: { id: string; name: string }[]; roles_note: string | null; own_public_summary: boolean; vendor_allows_summary: boolean };
export type EntityNode = {
  id: string; name: string; client_ref: string | null; status: string; parent_id: string | null; depth: number;
  relationship: string | null; relationship_label: string | null; consent: { given_by: string | null; given_at: string } | null; consented: boolean;
  rollup: Rollup | null; ll144: Ll144Scope | null; children: number;
};
export type EntityTree = {
  root: { id: string; name: string }; nodes: EntityNode[]; ll144: { end_clients: number; in_scope: number; aedts: number };
  parent_systems: { id: string; name: string }[]; can_manage: boolean;
};
export type ImportResult = { rows: { row: number; name: string; relationship: string; ll144_in_scope: boolean; roles_note: string | null; status: string }[];
  errors: { row: number; field: string; message: string }[]; applied: boolean; created: number };

export type GroupChild = { id: string; name: string; relationship: string | null; relationship_label: string | null; consent: boolean | null; rollup: Rollup | null;
  ll144: { in_scope: boolean; roles_note: string | null; own_public_summary: boolean } | null };
export type MyGroup = {
  organization: { id: string; name: string; relationship: string | null; relationship_label: string | null };
  parent: { id: string; name: string } | null; can_consent: boolean; can_give_consent: boolean;
  consent: { given_by: string | null; given_at: string } | null; children: GroupChild[];
};

export const RELATIONSHIPS = [
  { value: 'subsidiary', label: 'Subsidiary' },
  { value: 'end_client', label: 'End-client (staffing)' },
  { value: 'customer_of_vendor', label: 'Customer of vendor (L-10)' },
];

export const hierarchyApi = {
  tree: (clientId: string) => api.get<EntityTree>(`/staff/clients/${clientId}/entities`),
  add: (clientId: string, body: { name: string; relationship: string; parent_id?: string | null }) => api.post<{ id: string; tree: EntityTree }>(`/staff/clients/${clientId}/entities`, body),
  link: (clientId: string, body: { child_id: string; relationship: string }) => api.post<EntityTree>(`/staff/clients/${clientId}/entities/link`, body),
  relationship: (entityId: string, relationship: string) => api.patch<EntityTree>(`/staff/entities/${entityId}`, { relationship }),
  unlink: (entityId: string) => api.post<EntityTree>(`/staff/entities/${entityId}/unlink`),
  scope: (entityId: string, body: { ll144_in_scope: boolean; aedt_system_ids: string[]; roles_note: string | null; own_public_summary: boolean; vendor_allows_summary: boolean }) =>
    api.put<EntityTree>(`/staff/entities/${entityId}/ll144`, body),
  importCsv: (clientId: string, file: File, apply: boolean) => {
    const f = new FormData();
    f.append('file', file);
    return api.upload<ImportResult>(`/staff/clients/${clientId}/entities/import${apply ? '?apply=true' : ''}`, f);
  },
  myGroup: () => api.get<MyGroup>('/group'),
  consent: () => api.post<MyGroup>('/group/consent'),
  revoke: () => api.post<MyGroup>('/group/consent/revoke'),
};

export type Hold = { id: string; ref: string; name: string; matter_ref: string | null; reason: string; scope: Record<string, unknown>; scope_label: string; set_by: string | null;
  set_at: string; active: boolean; released_at: string | null; released_by: string | null; release_reason: string | null };
export type CountdownItem = { item_type: string; id: string; filename: string; kind: string; engagement_id: string; engagement: string; due_on: string; delete_on: string;
  notified_on: string | null; hold: string | null; size: number | null };
export type VaultView = {
  client: { id: string; name: string };
  storage: { used_gb: number; limit_gb: number | null; plan_code: string | null; measured_on: string | null; pct: number | null };
  retention: { years: number; is_default: boolean; tiers: number[]; effective_from: string | null; set_by: string | null; reason: string | null;
    history: { years: number; effective_from: string; set_by: string | null; reason: string | null }[] };
  holds: Hold[]; active_holds: number;
  countdown: { items: CountdownItem[]; total: number; held: number; will_delete: number };
  scope_options: { engagements: { id: string; name: string; audit_ref: string | null }[]; systems: { id: string; name: string; reference: string; engagement: string | null }[] };
  can: { set_tier: boolean; manage_holds: boolean };
};

export const vaultApi = {
  get: (clientId: string) => api.get<VaultView>(`/staff/clients/${clientId}/vault`),
  tier: (clientId: string, years: number, reason: string) => api.put<VaultView>(`/staff/clients/${clientId}/vault/retention`, { years, reason }),
  hold: (clientId: string, body: { name: string; matter_ref: string; reason: string; scope: Record<string, unknown> }) => api.post<VaultView>(`/staff/clients/${clientId}/vault/holds`, body),
  release: (clientId: string, holdId: string, reason: string) => api.post<VaultView>(`/staff/clients/${clientId}/vault/holds/${holdId}/release`, { reason }),
};

export type PartnerRow = {
  id: string; name: string; type: string; type_label: string; status: string; agreement_label: string | null; agreement_file_id: string | null;
  contact_name: string | null; contact_email: string | null; contact_phone: string | null; notes: string | null; is_law_firm: boolean;
  referred_in: number; referred_out: number; commission_label: string | null; commission_rule: { rate_pct: number } | null; won_value: number | null; commission_due: number | null;
};
export type CommissionRow = { id: string; partner: string | null; partner_id: string; client: string | null; opportunity: string | null; opportunity_id: string; order_ref: string | null;
  base_value: number; rate: number; amount: number; due_on: string; status: string; paid_on: string | null; void_reason: string | null };
export type ReferralRow = { id: string; partner: string | null; partner_id: string; direction: 'in' | 'out'; client: string | null; opportunity: string | null; opportunity_id: string | null;
  note: string | null; at: string; recorded_by: string | null };
export type PartnersView = { partners: PartnerRow[]; referrals: ReferralRow[]; commissions: CommissionRow[] | null; types: { value: string; label: string }[]; law_firm_note: string;
  can: { manage: boolean; settle: boolean; see_money: boolean } };
export type PartnerIn = { name: string; type: string; rate_pct: number | null; agreement_label: string | null; contact_name: string | null; contact_email: string | null;
  contact_phone: string | null; notes: string | null; status?: string };

export const partnersApi = {
  list: () => api.get<PartnersView>('/staff/partners'),
  options: () => api.get<{ clients: { id: string; name: string }[]; opportunities: { id: string; label: string }[] }>('/staff/partners/options'),
  add: (body: PartnerIn) => api.post<PartnersView>('/staff/partners', body),
  edit: (id: string, body: Partial<PartnerIn>) => api.patch<PartnersView>(`/staff/partners/${id}`, body),
  agreement: (id: string, file: File) => { const f = new FormData(); f.append('file', file); return api.upload<PartnersView>(`/staff/partners/${id}/agreement`, f); },
  referral: (id: string, body: { direction: string; organization_id?: string | null; opportunity_id?: string | null; note?: string | null }) =>
    api.post<PartnersView>(`/staff/partners/${id}/referrals`, body),
  paid: (id: string) => api.post<PartnersView>(`/staff/partners/commissions/${id}/paid`),
  void: (id: string, reason: string) => api.post<PartnersView>(`/staff/partners/commissions/${id}/void`, { reason }),
};

export function money(v: number | null | undefined): string {
  return v == null ? '—' : `$${v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}
