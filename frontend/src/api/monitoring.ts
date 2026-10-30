import { api } from './client';

export type ChangeItem = {
  id: string; kind: 'law' | 'litigation'; origin: string; change_type: string; change_label: string; subject: string; regulation_id: string | null; case_id: string | null;
  jurisdiction: string | null; field_path: string; old_value: unknown; new_value: unknown; summary: string; source_url: string | null; source_host: string | null;
  source_quote: string | null; confidence: 'high' | 'medium' | 'low'; claude_confidence: string | null; off_allowlist: boolean; needs_second_review: boolean;
  second_review: { outcome: 'concur' | 'object' | null; note: string | null; by: string | null; at: string | null }; assigned_reviewer: string | null;
  status: string; review_note: string | null; reviewer: string | null; created_at: string; seen_count: number; run_ids: string[];
  impact: { clients: number; systems: number; roles: string[]; letters: number }; notify_clients: boolean; update_letters: boolean; pending_edit?: unknown;
  impacts?: { organization_id: string; organization_name: string; systems: string[]; roles: string[]; letter_update_needed: boolean }[]; base_version_no?: number | null;
};
export type Queue = { items: ChangeItem[]; counts: Record<string, number>; reviewers: { id: string; name: string }[]; change_types: { value: string; label: string }[] };

export type Run = {
  id: string; legacy: boolean; kind: string; trigger: string; status: string; started_at: string; finished_at: string | null; started_by_name: string | null;
  jurisdictions: string[]; checks?: string[]; sources_read?: number; records_compared?: number; model_id?: string | null; model?: string | null; prompt_version?: string | null;
  cost_usd?: number; cost_cap_usd?: number | null; searches?: number; proposals_created?: number; proposals_merged?: number; warnings: string[]; error: string | null;
  alert_status?: string | null; counts: Record<string, number>; count_labels?: Record<string, string>; open?: number; total?: number; clients_affected?: number;
  systems_affected?: number; low_confidence?: number; proposals?: { id: string; change_type: string; status: string; jurisdiction: string; proposed: Record<string, unknown>; rationale: string; sources: { title: string; url: string }[] }[];
};

export type RunSettings = {
  kind: string; schedule_enabled: boolean; every_days: number; scope_mode: string; jurisdiction_codes: string[]; checks: string[]; source_set: string; cost_cap_usd: number;
  last_scheduled_at: string | null; next_due: string | null; check_options: { value: string; label: string }[];
  counts: { all: number; client_geographies: number; official_sources: number; secondary_sources: number };
  alert: { recipients_rule: string; cc_roles: string[]; channels: string[] }; enabled: boolean; model: string;
};

export type StaffAlert = {
  id: string; kind: 'refresh_done' | 'review_reminder' | 'escalation'; scope: string; title: string; run_id: string | null; at: string; read: boolean; resolved: boolean;
  needs_action: boolean; waiting: number; is_copy: boolean; is_test: boolean; emailed: boolean; link: string;
  summary: { sources_read: number; total: number; open: number; counts: Record<string, number>; clients_affected: number; systems_affected: number; low_confidence: number; low_confidence_items: string[] };
};

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.map(fmtValue).join(', ');
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if (typeof o.text === 'string') return `${o.code ? `${o.code}: ` : ''}${o.text}`;
    if (typeof o.short_name === 'string') return o.short_name;
    if (typeof o.name === 'string') return o.name;
    if (typeof o.level === 'string') return `${o.level}${o.needed_by_stage ? `, needed by ${o.needed_by_stage}` : ''}`;
    return JSON.stringify(v);
  }
  return String(v);
}

export const staffAlerts = () => api.get<{ unread: number; needs_action: number; items: StaffAlert[] }>('/staff/alerts');
