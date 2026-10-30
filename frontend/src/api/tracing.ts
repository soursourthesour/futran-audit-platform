import { useQuery } from '@tanstack/react-query';
import { api } from './client';

export type AddonState = 'locked' | 'requested' | 'active';

export type AddonRequest = {
  id: string; addon: string; plan: string; plan_label: string; systems: string[]; system_ids: string[]; trial: boolean; trial_ends_on: string | null;
  status: 'requested' | 'approved' | 'active' | 'declined' | 'cancelled'; status_label: string; note: string | null;
  requested_by: string | null; requested_by_id: string | null; requested_at: string; approver: string | null; approver_id: string | null;
  approved_by: string | null; decided_at: string | null; decision_comment: string | null; cancelled_at: string | null; cancel_reason: string | null;
};

export type AddonSystem = {
  id: string; reference: string; name: string; department: string | null; tier: number | null; tier_label: string | null; type: string; type_label: string;
  stage: string; stage_label: string; recommended: boolean; reasons: string[]; status: AddonState;
};

export type AddonsPage = {
  systems: AddonSystem[];
  plans: { value: string; label: string; hint: string; count: number | null }[];
  sponsors: { id: string; name: string; job_title: string | null }[];
  requests: AddonRequest[];
  trial_days: number; can_request: boolean; can_approve: boolean;
};

export type Deadline = {
  id: string; rule_code: string; recipient: string; law: string; citation: string; quote: string; source_url: string; period_text: string; statutory: boolean;
  binding: boolean; binding_note: string | null; clock_start_at: string; due_at: string; status: 'open' | 'done' | 'not_applicable' | 'withdrawn'; status_label: string;
  done_at: string | null; reference: string | null; na_reason: string | null; overdue: boolean;
};

export type Incident = {
  id: string; code: string; register_system_id: string; found_at: string; description: string; severity: string; severity_label: string; serious_kind: string; serious_label: string;
  risk_to_rights: boolean; cyber_incident: boolean; ag_notice_received_on: string | null; people_affected: number | null; cause: string | null; containment: string | null; fix: string | null;
  status: 'open' | 'contained' | 'closed'; status_label: string; contained_on: string | null; closed_on: string | null; owner_id: string | null; owner: string | null;
  history_entry_id: string | null; trace_ids: string[]; reportable: boolean; law: string | null; deadline_at: string | null; reported_at: string | null; provider_notified_at: string | null;
  deadlines: Deadline[]; created_at: string;
};

export type Trace = {
  id: string; at: string; session_id: string | null; action: string; tool: string | null; data_touched: string | null; decision: 'allowed' | 'blocked' | 'escalated'; decision_label: string;
  policy_ref: string | null; approver: string | null; agent_identity: string | null; source: string; external_id: string | null;
};

export type TracingPage = {
  system: { id: string; reference: string; name: string; type: string; stage: string; risk_tier: number | null; guardrail_policy_ref: string | null };
  state: AddonState; recommended: boolean; reasons: string[]; subscription: AddonRequest | null;
  law_families: ('eu_ai_act' | 'colorado' | 'india')[]; family_labels: Record<string, string>;
  can_record_traces: boolean; can_manage_incidents: boolean; can_request: boolean;
  incidents: Incident[]; traces: Trace[];
  kpis: { actions_24h: number; blocked_24h: number; escalated_24h: number; total: number; open_incidents: number; deadlines_missed: number } | null;
  people: { id: string; name: string; job_title: string | null }[];
  history_incidents: { id: string; occurred_on: string; summary: string }[];
  kept: { incidents: number; traces: number };
  guardrail_connected?: boolean;
  guardrail_needs_token?: boolean; can_set_guardrail_token?: boolean;
};

export const useAddons = () => useQuery({ queryKey: ['addons'], queryFn: () => api.get<AddonsPage>('/addons/tracing') });
export const useTracing = (systemId: string) => useQuery({ queryKey: ['tracing', systemId], queryFn: () => api.get<TracingPage>(`/register/${systemId}/tracing`), retry: false });

export const SEVERITIES = [{ value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' }, { value: 'high', label: 'High' }, { value: 'serious', label: 'Serious' }];
export const SERIOUS_KINDS = [
  { value: 'none', label: 'No, not a serious incident' },
  { value: 'death', label: 'Yes: death of a person (10 days)' },
  { value: 'health', label: "Yes: serious harm to a person's health (15 days)" },
  { value: 'critical_infrastructure', label: 'Yes: serious, irreversible disruption of critical infrastructure (2 days)' },
  { value: 'fundamental_rights', label: 'Yes: breach of EU law protecting fundamental rights (15 days)' },
  { value: 'property_environment', label: 'Yes: serious harm to property or the environment (15 days)' },
  { value: 'widespread_infringement', label: 'Yes: widespread infringement (2 days)' },
];
export const DECISIONS = [{ value: 'allowed', label: 'Allowed' }, { value: 'blocked', label: 'Blocked' }, { value: 'escalated', label: 'Escalated' }];
export const PERIODS = [{ value: '24h', label: 'Last 24 hours' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' }, { value: 'all', label: 'All' }];
