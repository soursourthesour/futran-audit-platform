import { useQuery } from '@tanstack/react-query';
import { api } from './client';

export type Opt = { value: string; label: string };
export type PersonRef = { id: string; name: string; job_title?: string | null } | null;

export type RoleSummary = { required: number; filled: number; recommended: number; no_such_person: number; pending_committee: number; not_answered: number; not_yet_due: number; blocking: string[] };
export type Gate = { state: 'retired' | 'live_finding' | 'live_clear' | 'not_due' | 'blocked' | 'awaiting_approval' | 'ready'; label: string; roles: string[]; requirements: string[] };
export type LawLink = { id: string; regulation_id: string; short_name: string; source: string; status: 'active' | 'removal_pending'; removal_reason: string | null; removal_requested_by: string | null };
export type SystemData = { data_categories: string[]; data_subjects: string[]; consent_basis: string | null; consent_ref: string | null; consent_evidence_id: string | null; retention_period: string | null; cross_border: string | null };
export type Bias = { last_tested_on: string | null; next_due: string | null; overdue: boolean; result: string | null; label: string; null_compliance: boolean };
export type Tracing = { locked: boolean; recommended: boolean; reasons: string[] };
export type Statement = { id: string; statement: string; period_from: string | null; signed_by: string | null; signed_at: string | null; owner: string | null; owner_id: string | null } | null;

export type RegSystem = {
  id: string; reference: string; name: string; type: string; type_label: string; sourcing: string; sourcing_label: string; stage: string; stage_label: string;
  department: { id: string; name: string } | null; company_wide: boolean; purpose: string | null; users_scope: string | null; users_description: string | null; user_count: number | null;
  owner: PersonRef; vendor: { id: string; name: string } | null; ai_provider: string | null; ai_provider_label: string | null; model_name: string | null; model_version: string | null;
  algorithm_type: string | null; algorithm_label: string | null; hosting: string | null; vendor_trains_on_data: string | null; vendor_documents: string[]; autonomy: string | null;
  guardrail_policy_ref: string | null; agentassure_status: string | null; decision_impact: string | null; risk_tier: number | null; risk_tier_reason: string | null;
  bias_next_due: string | null; origin: string; live_since: string | null; data: SystemData; actions: { action_code: string; label: string; description: string | null }[];
  laws: LawLink[]; bias: Bias; consent: { label: string; missing: boolean }; roles: RoleSummary; gate: Gate;
  go_live: { requested_by: PersonRef; requested_at: string | null; approved_by: PersonRef; approved_at: string | null };
  updated_at: string | null; updated_by: PersonRef; retired_reason: string | null;
  can_edit?: boolean; can_add_law?: boolean; can_remove_law?: boolean; can_fill_roles?: boolean; can_record_history?: boolean; can_submit_go_live?: boolean; can_approve_go_live?: boolean;
  history?: { answers: Record<string, string>; statement: Statement; tracing: Tracing };
  suggested_laws?: { regulation_id: string; short_name: string; reason: string | null }[];
};

export type RegisterCan = { edit: boolean; org_wide: boolean; import_inventory: boolean; add_law: boolean; remove_law: boolean; fill_roles: boolean; company_roles: boolean; approve_go_live: boolean; submit_go_live: boolean; record_history: boolean; committee_members: boolean; record_committee: boolean };
export type Register = {
  systems: RegSystem[];
  kpis: { systems: number; agents: number; go_live_blocked: number; roles_no_person: number; bias_overdue: number; consent_missing: number };
  can: RegisterCan;
  departments: { id: string; name: string; can_edit: boolean }[];
  people: { id: string; name: string; job_title: string | null; department_id: string | null }[];
  vendors: { id: string; name: string }[];
};

export type RoleRow = {
  role_id: string; code: string; number: number; name: string; description: string | null; level: 'company' | 'system' | 'agent'; extra_checks: string | null;
  requirement: 'required' | 'recommended'; needed_by: string; needed_by_label: string; required_by: string[]; basis: string | null; status: string | null; status_label: string;
  filled: boolean; due_for_gate: boolean; inherited: boolean; assignment: Assignment | null;
};
export type Assignment = {
  id: string; status: string; user: PersonRef; extra_users: { id: string; name: string }[]; external_party: string | null; external_contact: string | null; backup_user: PersonRef;
  target_date: string | null; reason: string | null; effective_from: string | null; training_completed: boolean | null; has_authority_to_override: boolean | null; override: boolean;
  override_reason: string | null; evidence_ids: string[]; notes: string | null;
};
export type RolePerson = { id: string; name: string; job_title: string | null; committee_role: string | null };
export type RolesPage = { system: RegSystem; rows: RoleRow[]; summary: RoleSummary; gate: Gate; people: RolePerson[]; can: { fill: boolean; company: boolean; mark_na: boolean; submit: boolean; approve: boolean } };

export type HistoryEntry = {
  id: string; type: string; type_label: string; occurred_on: string; summary: string; result: string | null; severity: string | null; severity_label: string | null;
  details: Record<string, string | number | boolean>; requirement_ids: string[]; evidence: { id: string; filename: string }[]; recorded_by: string | null; recorded_at: string;
};
export type HistoryPage = { entries: HistoryEntry[]; answers: Record<string, string>; statement: Statement; tracing: Tracing; can_record: boolean; is_owner: boolean };
export type RequirementRow = {
  id: string; code: string; text: string; law: string; regulation_id: string; citation: string | null; evidence_text: string | null; needed_by: string | null; needed_by_label: string;
  gate: boolean; status: string; status_label: string; note: string | null; history_entries: { id: string; type: string; occurred_on: string; summary: string }[];
  evidence: { id: string; filename: string }[]; checked_by: string | null; checked_at: string | null; carried_from_previous_version: boolean;
};
export type Requirements = { rows: RequirementRow[]; total: number; met: number; blocking: number; can_edit: boolean };
export type Change = { id: string; at: string; field: string; field_label: string; old_value: string | null; new_value: string | null; reason: string | null; user: string; batch_id: string | null; entity: string };
export type EvidenceFile = { id: string; filename: string; uploaded_at: string; size: number; uploaded_by?: string | null };

export const useRegister = () => useQuery({ queryKey: ['register'], queryFn: () => api.get<Register>('/register') });
export const useRegSystem = (id: string) => useQuery({ queryKey: ['register', id], queryFn: () => api.get<RegSystem>(`/register/${id}`), enabled: !!id });

export const TYPES: Opt[] = [
  { value: 'agent', label: 'AI agent' }, { value: 'vendor_app', label: 'Vendor app with AI' }, { value: 'embedded_feature', label: 'Embedded AI feature' },
  { value: 'foundation_model_api', label: 'Foundation model / API' }, { value: 'in_house_model', label: 'In-house model' }, { value: 'genai_chat_tool', label: 'Generative AI chat tool' },
];
export const SOURCING: Opt[] = [{ value: 'vendor', label: 'Bought from vendor' }, { value: 'in_house', label: 'Built in-house' }, { value: 'contractor', label: 'Built by contractor' }, { value: 'shadow', label: 'Free or personal tool (shadow AI)' }];
export const STAGES: Opt[] = [{ value: 'proposed', label: 'Proposed' }, { value: 'in_development', label: 'In development / procurement' }, { value: 'ready_for_go_live', label: 'Ready for go-live' }, { value: 'live', label: 'Live' }, { value: 'retired', label: 'Retired' }];
export const PROVIDERS: Opt[] = [
  { value: 'openai', label: 'OpenAI' }, { value: 'anthropic', label: 'Anthropic' }, { value: 'azure_openai', label: 'Microsoft Azure OpenAI' }, { value: 'google', label: 'Google' },
  { value: 'amazon_bedrock', label: 'Amazon Bedrock' }, { value: 'meta_open', label: 'Meta (open model)' }, { value: 'in_house', label: 'In-house model' }, { value: 'unknown', label: 'Unknown, vendor did not disclose' },
];
export const ALGORITHMS: Opt[] = [
  { value: 'llm_agent', label: 'Large language model (LLM) agent' }, { value: 'llm', label: 'Large language model (LLM)' }, { value: 'ranking', label: 'Ranking or scoring model' },
  { value: 'classifier', label: 'Classifier' }, { value: 'regression', label: 'Regression' }, { value: 'computer_vision', label: 'Computer vision' }, { value: 'speech', label: 'Speech analysis' },
  { value: 'rules_ml', label: 'Rules plus machine learning' }, { value: 'other', label: 'Other' },
];
export const HOSTING: Opt[] = [{ value: 'vendor_cloud_us', label: 'Vendor cloud (US)' }, { value: 'vendor_cloud_eu', label: 'Vendor cloud (EU)' }, { value: 'vendor_cloud_other', label: 'Vendor cloud (other region)' }, { value: 'our_cloud', label: 'Our cloud tenant' }, { value: 'on_premises', label: 'On premises' }];
export const TRAINS: Opt[] = [{ value: 'no', label: 'No, contractually excluded' }, { value: 'yes', label: 'Yes' }, { value: 'unknown', label: 'Unknown' }];
export const VENDOR_DOCS: Opt[] = [
  { value: 'contract_ai_terms', label: 'Contract with AI terms' }, { value: 'dpa', label: 'Data processing agreement' }, { value: 'model_card', label: 'Model card or system documentation' },
  { value: 'vendor_bias_audit', label: "Vendor's own bias audit" }, { value: 'security_report', label: 'Security report (SOC 2 or ISO 27001)' }, { value: 'incident_clause', label: 'Incident notice clause' },
];
export const ACTIONS: Opt[] = [
  { value: 'read_records', label: 'Read records' }, { value: 'send_email', label: 'Send email' }, { value: 'write_calendar', label: 'Write to calendars' }, { value: 'change_records', label: 'Change records in a system of record' },
  { value: 'decide_people', label: 'Reject or advance people' }, { value: 'make_payments', label: 'Make payments' }, { value: 'search_knowledge', label: 'Search internal knowledge' },
];
export const AUTONOMY: Opt[] = [{ value: 'suggest_only', label: 'Suggests only; a person acts' }, { value: 'acts_with_approval', label: 'Acts, but a person approves first-time or unusual actions' }, { value: 'autonomous', label: 'Acts on its own' }];
export const AGENTASSURE: Opt[] = [{ value: 'planned', label: 'Futran AgentAssure: planned' }, { value: 'passed', label: 'Futran AgentAssure: passed' }, { value: 'vendor_only', label: 'Vendor testing only' }, { value: 'none', label: 'None' }];
export const DATA_CATEGORIES: Opt[] = [
  { value: 'personal', label: 'Personal information' }, { value: 'health', label: 'Health information' }, { value: 'biometric', label: 'Biometric data (face, voice)' },
  { value: 'sensitive', label: 'Sensitive categories (race, sex, age)' }, { value: 'children', label: "Children's data" }, { value: 'confidential', label: 'Company confidential' },
];
export const DATA_SUBJECTS: Opt[] = [{ value: 'candidates', label: 'Job candidates' }, { value: 'employees', label: 'Employees' }, { value: 'customers', label: 'Customers' }, { value: 'public', label: 'Members of the public' }, { value: 'none', label: 'No personal data' }];
export const CONSENT: Opt[] = [{ value: 'consent', label: 'Yes, consent obtained' }, { value: 'notice_only', label: 'Notice given only' }, { value: 'other_lawful_basis', label: 'Other lawful basis (contract, legitimate interest)' }, { value: 'not_obtained', label: 'No, not obtained' }, { value: 'na', label: 'Not applicable' }];
export const CROSS_BORDER: Opt[] = [{ value: 'no', label: 'No' }, { value: 'eu', label: 'Yes, to the EU' }, { value: 'india', label: 'Yes, to India' }, { value: 'other', label: 'Yes, other' }];
export const IMPACT: Opt[] = [{ value: 'none', label: 'No effect on decisions about people' }, { value: 'informs', label: 'Supports a decision a person makes' }, { value: 'consequential', label: 'Makes or substantially makes the decision' }];
export const ROLE_STATUSES: Opt[] = [{ value: 'assigned', label: 'Assigned' }, { value: 'external', label: 'External party' }, { value: 'no_such_person', label: 'No such person' }, { value: 'pending_committee', label: 'Pending committee' }, { value: 'not_applicable', label: 'Not applicable' }];
export const HISTORY_TYPES: Opt[] = [
  { value: 'incident', label: 'Incident' }, { value: 'bias_test', label: 'Bias test' }, { value: 'deployment_test', label: 'Deployment test' }, { value: 'impact_assessment', label: 'Impact assessment' },
  { value: 'notice_consent', label: 'Notice or consent' }, { value: 'model_change', label: 'Model change' }, { value: 'approval', label: 'Approval' }, { value: 'training', label: 'Training' },
  { value: 'vendor_audit', label: 'Vendor audit' }, { value: 'monitoring_review', label: 'Monitoring review' },
];
export const labelOf = (opts: Opt[], v: string | null | undefined) => opts.find((o) => o.value === v)?.label ?? '';

export const TIER_LABEL: Record<number, string> = { 3: 'Tier 3 · High', 2: 'Tier 2 · Medium', 1: 'Tier 1 · Low' };
export const TIER_TONE: Record<number, 'danger' | 'warn' | 'muted'> = { 3: 'danger', 2: 'warn', 1: 'muted' };
export const STATUS_TONE: Record<string, 'success' | 'navy' | 'danger' | 'warn' | 'muted'> = { assigned: 'success', external: 'navy', no_such_person: 'danger', pending_committee: 'warn', not_applicable: 'muted' };
export const GATE_TONE: Record<string, 'success' | 'danger' | 'warn' | 'muted' | 'navy'> = { live_clear: 'success', live_finding: 'danger', blocked: 'danger', not_due: 'muted', awaiting_approval: 'navy', ready: 'success', retired: 'muted' };
