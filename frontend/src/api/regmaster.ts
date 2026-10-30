/* Regulatory master API types (spec §25.6: M1, M1a, M1b, M2, M4, M5). */
export type LawRow = {
  id: string; geography: string; jurisdiction_code: string | null; short_name: string; label: string; citation: string | null; type: string; binding: boolean | null;
  status: string | null; status_label: string; effective: string; effective_on: string | null; scope: string; applies_to: string[]; topics: string[];
  requirement_count: number; role_count: number; committee: string; penalty: string; last_change: string; pending_count: number; verify: boolean; version_no: number | null;
  region: string; review_due_on: string | null; reviewer_id: string | null; refresh_every_days: number | null; watch: boolean;
};
export type Option = { value: string; label: string };
export type Library = {
  kpis: { geographies: number; laws: number; requirements: number; pending: number; upcoming: number; shown: number; library: number; all: number };
  groups: { region: string; label: string; laws: LawRow[] }[]; regions: Option[]; topics: Option[]; claude_available: boolean; can_approve: boolean; can_edit: boolean;
  last_refresh: { id: string; status: string; started_at: string; finished_at: string | null; open: number; total: number } | null;
};
export type Requirement = {
  id: string; code: string; text: string; applies_to: string[]; needed_by_stage: string | null; evidence_text: string | null; role: string | null; role_name: string | null;
  ai_types: string[]; citation: string | null; source_quote: string | null; source_url: string | null; verify_flag: boolean;
};
export type Change = {
  id: string; field_path: string; change_type: string; summary: string; old_value: unknown; new_value: unknown; status: string; origin: string; confidence: string;
  source_url: string | null; source_quote: string | null; proposed_by: string | null; created_at: string | null; batch_id: string | null;
};
export type LawRecord = {
  id: string; short_name: string; label: string; citation: string | null; type: string; binding: boolean | null; topics: string[]; region: string; geography: string; jurisdiction_code: string | null; parent_geography: string | null;
  version: {
    id: string; version_no: number; status: string; status_label: string; signed_on: string | null; effective_on: string | null; compliance_on: string | null; effective_text: string | null;
    scope_text: string | null; applies_to: string[]; enforcer: string | null; private_right_of_action: boolean | null; penalty_text: string | null; cure_period: string | null;
    exemptions_text: string | null; removed_text: string | null; litigation_text: string | null; main_duty: string | null; verify: boolean; approved_at: string | null; approved_by: string | null;
  };
  scope_tests: { order: number; question_text: string; answer_type: string; in_scope_rule: Record<string, unknown> | null; decisive: boolean; prefill_from: string | null; note: string | null }[];
  requirements: Requirement[];
  role_maps: { role: string; name: string; level: string; needed_by_stage: string | null; basis: string | null; applies_to: string[]; requirements: string[]; verify: boolean }[];
  committees: { committee_type: string; title: string | null; level: string; basis: string | null; condition: string | null; items: string[] }[];
  history: { id: string; version_no: number; change: string; by: string; date: string | null }[];
  pending: Change[]; sources: { id: string; name: string; url: string; kind: string; last_read_at: string | null }[];
  used_by_clients: number; used_by_systems: number; can_edit: boolean; can_suggest: boolean; can_approve: boolean; roles: { code: string; name: string }[];
};
export type RoleRow = { code: string; number: number; name: string; description: string | null; level: string; default_stage: string; main_sources: string | null; extra_checks: string | null };
export type Cell = { level: string; needed_by_stage: string | null; basis: string | null; requirements: string[] };
export type Committee = { committee_type: string; title: string; level: string; items: string[]; sources: { law: string; level: string; basis: string | null; condition?: string | null }[] };
export type RoleCatalogue = { roles: RoleRow[]; laws: { id: string; label: string; short_name: string }[]; cells: Record<string, Record<string, Cell>>; committees: Committee[]; stages: string[]; can_edit: boolean; can_approve: boolean };
export type ClientLaw = {
  regulation_id: string; label: string; short_name: string; geography: string; binding: boolean; kind: string; status: string; reason: string | null; override: boolean;
  version_no: number | null; main_duty: string | null; questions: { order: number; question_text: string; answer: string | null; manual: boolean; decisive: boolean }[];
};
export type ClientRole = { code: string; name: string; number: number; level: string; level_kind: string; needed_by: string; description: string | null; sources: { law: string; level: string; needed_by: string; basis: string | null }[] };
export type ClientCommittee = { committee_type: string; title: string | null; level: string; items: string[]; condition_text: string | null; sources: { law: string; level: string; basis: string | null }[] };
export type Letter = {
  id: string; version_no: number; status: 'draft' | 'approved' | 'sent'; file_id: string | null; approved_by: string | null; approved_at: string | null; sent_at: string | null; created_at: string | null;
  edited_text: { opening?: string; closing?: string }; changes: { text: string }[]; versions: string[]; html: string | null;
};
export type Applicability = {
  client: { id: string; name: string; client_ref: string | null; engagement_status: string | null }; caico: { name: string; email: string } | null;
  geographies: { id: string; jurisdiction_code: string; name: string; parent: string | null; level: string; basis: string; source: string }[];
  laws_in: ClientLaw[]; laws_out: ClientLaw[]; roles: ClientRole[]; committees: ClientCommittee[];
  changes_since_letter: { letter_id: string; version_no: number; sent_at: string | null; approved_count: number; items: { text: string; pending: boolean }[] } | null;
  letter: Letter | null; letters: Letter[]; bases: string[]; can_edit: boolean; can_approve: boolean;
};

export const STATUS_OPTIONS: Option[] = [
  { value: 'in_force', label: 'In force' }, { value: 'in_force_phased', label: 'In force, phased' }, { value: 'enacted_not_in_force', label: 'Enacted, not yet in force' },
  { value: 'delayed', label: 'Delayed or under amendment' }, { value: 'guidance', label: 'Guidance (not binding)' }, { value: 'repealed', label: 'Repealed or lapsed' }, { value: 'pending', label: 'Pending bill' },
];
export const APPLIES_OPTIONS: Option[] = [
  { value: 'deployer', label: 'Deployer (uses AI)' }, { value: 'developer', label: 'Developer' }, { value: 'provider', label: 'Provider' }, { value: 'employer', label: 'Employer' }, { value: 'data_fiduciary', label: 'Data fiduciary or controller' },
];
export const STAGE_OPTIONS: Option[] = [
  { value: 'program_setup', label: 'Program set-up' }, { value: 'procurement', label: 'Procurement' }, { value: 'development', label: 'Development' },
  { value: 'go_live', label: 'Go-live' }, { value: 'ongoing', label: 'Ongoing' }, { value: 'yearly', label: 'Yearly' },
];
export const AI_TYPE_OPTIONS: Option[] = [
  { value: 'decision', label: 'AI or ML software deciding about people' }, { value: 'agent', label: 'AI agents' }, { value: 'embedded', label: 'Embedded AI features' },
  { value: 'genai', label: 'Generative AI tools and chatbots' }, { value: 'all', label: 'All AI systems' },
];
export const BASIS_OPTIONS: Option[] = [
  { value: 'office', label: 'Office' }, { value: 'employees', label: 'Employees' }, { value: 'candidates', label: 'Candidates' }, { value: 'customers', label: 'Customers' }, { value: 'data', label: 'Data' },
];
export const TYPE_OPTIONS: Option[] = [
  { value: 'statute', label: 'Statute' }, { value: 'regulation', label: 'Regulation' }, { value: 'executive', label: 'Executive order' }, { value: 'guidance', label: 'Guidance' },
  { value: 'framework', label: 'Framework' }, { value: 'pending', label: 'Pending bill' },
];
export const label = (opts: Option[], v: string | null | undefined) => opts.find((o) => o.value === v)?.label ?? (v ?? '—');
export const stageLabel = (v: string | null | undefined) => label(STAGE_OPTIONS, v);
export const appliesLabel = (vs: string[]) => vs.map((v) => label(APPLIES_OPTIONS, v).replace(' (uses AI)', '').replace(' or controller', '')).join(', ') || '—';
export const statusTone = (s: string | null): 'success' | 'warn' | 'muted' | 'danger' | 'navy' =>
  s === 'in_force' || s === 'in_force_phased' ? 'success' : s === 'enacted_not_in_force' || s === 'delayed' ? 'warn' : s === 'repealed' ? 'danger' : s === 'guidance' ? 'muted' : 'navy';
