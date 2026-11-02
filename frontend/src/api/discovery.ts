import { useQuery } from '@tanstack/react-query';
import { api } from './client';

/* Wave 3 WS-J: integrations and AI discovery (screen 30) and continuous monitoring (screen 31). */

export type ConnectorType = 'okta' | 'google_workspace' | 'microsoft_365' | 'entra_id' | 'expense_csv' | 'casb_csv';

export type ConnectorRow = {
  id?: string; type: ConnectorType; label: string; status: 'not_connected' | 'consent_requested' | 'connected' | 'error' | 'disconnected'; scopes: string[];
  tenant?: string | null; verified_domains?: string[]; authorized_by?: string | null; authorized_at?: string | null; last_sync_at?: string | null; error?: string | null;
  last_run: { kind: string; status: string; at: string; filename: string | null; rows_read: number; rows_matched: number; tools_found: number; error: string | null } | null;
};

export type DiscoveredTool = {
  id: string; vendor: string; product: string; category: string | null; signal: string; signal_label: string; source: ConnectorType; source_label: string;
  department_id: string | null; department: string; department_matched: boolean; user_count: number; detail: string | null; declared: boolean; attestation_exists: boolean;
  status: 'new' | 'confirmed' | 'mapped' | 'dismissed'; dismiss_reason: string | null; matched_tool: { id: string; label: string } | null; system_reference: string | null;
  first_seen: string; last_seen: string; decided_at: string | null;
};

export type ConnectorRunRow = {
  id: string; connector: string; kind: string; status: string; started_at: string; by: string; filename: string | null; rows_read: number; rows_matched: number;
  tools_found: number; error: string | null;
};

export type IntegrationsPage = {
  organization: { id: string; name: string };
  connectors: ConnectorRow[]; tools: DiscoveredTool[]; runs: ConnectorRunRow[]; ai_tools: { id: string; label: string }[];
  summary: { total: number; undeclared: number; new: number };
  credentials: { test_mode: boolean; microsoft: { available: boolean }; google: { available: boolean }; okta: { available: boolean } };
  can_manage: boolean; can_decide: boolean; can_view_people?: boolean;
};

export function useIntegrations(clientId?: string) {
  return useQuery({ queryKey: ['integrations', clientId ?? 'own'], queryFn: () => api.get<IntegrationsPage>(clientId ? `/clients/${clientId}/integrations` : '/integrations') });
}

export type MonitorStatus = 'healthy' | 'attention' | 'failed' | 'not_started';

export type MonitorResultRow = {
  id: string; check_code: string; check: string; severity: 'high' | 'medium' | 'low'; status: MonitorStatus; object_id: string | null; object_label: string; detail: string;
  action: string | null; action_label: string | null; action_link: string | null; action_kind: 'server' | 'link' | null; action_taken: string | null; action_taken_at: string | null; alert_sent: boolean; run_at: string;
};

export type MonitoringPage = {
  organization: { id: string; name: string };
  plan: 'audit_only' | 'monitor' | 'monitor_plus'; plan_label: string; plans: { value: string; label: string }[];
  subscription: { start_on: string | null; note: string | null } | null; next_review_on: string | null; offers: string[];
  kpis: Record<MonitorStatus, number> | null; needs_action: MonitorResultRow[]; healthy: MonitorResultRow[];
  last_run: { id: string; at: string; trigger: string } | null;
  runs: { id: string; at: string; trigger: string; status: string; counts: Record<MonitorStatus, number> }[];
  can_act: boolean; can_set_plan: boolean;
};

export function useMonitoring(clientId?: string) {
  return useQuery({ queryKey: ['monitoring', clientId ?? 'own'], queryFn: () => api.get<MonitoringPage>(clientId ? `/clients/${clientId}/monitoring` : '/monitoring') });
}
