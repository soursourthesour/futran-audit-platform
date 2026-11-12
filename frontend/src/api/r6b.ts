/** Release 2 R6b: G-07 Copilot readiness and G-08 EU AI Act conformity (backend app/copilot_readiness, app/euaiact). */

export type Evidence = { id: string; filename: string; sha256: string; uploaded_at?: string };

export type CopilotSite = {
  id: string; name: string; url: string | null; site_owner: string | null; label_coverage: number | null; sharing: string; sharing_label: string;
  sensitive_items: number | null; last_activity: string | null; risk: 'high' | 'medium' | 'low'; risk_overridden: boolean; action: string | null;
  action_label: string | null; action_owner: string | null; status: 'open' | 'in_progress' | 'done'; status_label: string; note: string | null; sources: string[];
};
export type CopilotWave = {
  id: string; name: string; groups: string | null; user_count: number | null; planned_on: string | null; gate_site_ids: string[]; gate_control_keys: string[];
  hold_note: string | null; gate: 'go' | 'hold'; gate_text: string;
};
export type CopilotControl = { key: string; label: string; phase: string; status: 'open' | 'done' | 'not_applicable'; status_label: string; note: string | null; evidence: Evidence[] };
export type CopilotImport = {
  id: string; kind: string; kind_label: string; filename: string | null; file_id: string | null; sha256: string; rows_read: number; rows_used: number;
  imported_by: string | null; imported_at: string;
};
export type CopilotView = {
  engagement: { id: string; name: string; audit_ref: string | null }; client: { id: string; name: string }; client_view: boolean;
  phase: 'pilot' | 'deploy' | 'operate'; phase_label: string; usage_as_of: string | null; by_department: { department: string; licences: number; active: number }[];
  summary: { licences: number | null; active_users: number | null; high_risk_sites: number; controls_ready: number; controls_total: number };
  sites: CopilotSite[]; waves: CopilotWave[]; controls: CopilotControl[]; imports: CopilotImport[];
  register_entry: { id: string; reference: string; name: string } | null;
  register_candidates: { id: string; reference: string; name: string }[]; register_choices: { id: string; reference: string; name: string }[];
  report: { file_id: string; filename: string; created_at: string | null } | null;
  options: {
    phases: Record<string, string>; actions: Record<string, string>; statuses: Record<string, string>; risks: Record<string, string>; control_statuses: Record<string, string>;
    import_kinds: Record<string, { label: string; source: string }>;
  };
  started: true; can_manage: boolean; can_update_sites: boolean;
};
/** A Copilot readiness engagement whose workspace the audit team has not started yet (reading never creates it). */
export type CopilotNotStarted = {
  started: false; engagement: { id: string; name: string; audit_ref: string | null }; client: { id: string; name: string }; client_view: boolean;
  can_manage: boolean; can_update_sites: boolean;
};

export type Deadline = { date: string | null; label: string; in_force: boolean; source: string | null };
export type EuOptions = { roles: Record<string, string>; classifications: Record<string, string>; areas: Record<string, string> };
export type EuRow = {
  id: string; reference: string; name: string; eu_exposure: string | null; exposure_basis: string | null; role: string | null; role_label: string | null;
  classification: string | null; classification_label: string | null; deadline: Deadline; obligations_met: number; obligations_total: number;
  fria_required: boolean; fria_status: string | null; signoff_status: 'draft' | 'awaiting_signoff' | 'signed_off' | 'returned'; signoff_label: string;
};
export type EuListing = {
  engagement: { id: string; name: string; audit_ref: string | null } | null; client: { id: string; name: string }; banner: string; systems: EuRow[];
  deadline_sources: Record<string, string>; can_edit: boolean; can_sign: boolean; ready_for_report: boolean; signed_count: number; due_count: number; options: EuOptions;
};
export type EuObligation = {
  key: string; article: string; title: string; status: string; status_label: string; note: string | null; evidence: Evidence[]; checked_by: string | null;
  checked_at: string | null; progress: string | null; library: { code: string; text: string; citation: string | null; law_version_id: string } | null;
};
export type EuDetail = EuRow & {
  client_view: false; engagement_id: string | null; also_deployer: boolean; annex_iii_area: string | null; public_service: boolean; reasoning: string | null;
  legal_review_flag: boolean; classified_by: string | null; classified_at: string | null; sent_by: string | null; sent_at: string | null;
  signed_off_by: string | null; signed_off_at: string | null; signoff_note: string | null; obligations: EuObligation[];
  annex_iv: { key: string; label: string; status: string; note: string | null }[]; annex_iv_done: number;
  fria: { status: string; answers: Record<string, string | null>; questions: { key: string; label: string }[] } | null;
  can_edit: boolean; can_sign: boolean; options: EuOptions;
};
export type EuClientView = {
  client_view: true; id: string; name: string; eu_exposure: string | null; status_text: string; role_label: string | null; classification: string | null;
  classification_label: string | null; deadline: Deadline | null; signed_off_at: string | null;
};
export type Workspaces = { copilot: boolean; eu_ai_act: boolean; eu_systems: number };

export const RISK_TONE: Record<string, 'danger' | 'warn' | 'muted'> = { high: 'danger', medium: 'warn', low: 'muted' };
export const SIGNOFF_TONE: Record<string, 'warn' | 'success' | 'danger' | 'muted'> = { draft: 'muted', awaiting_signoff: 'warn', signed_off: 'success', returned: 'danger' };
