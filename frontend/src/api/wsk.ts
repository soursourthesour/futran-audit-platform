/* Wave 3 WS-K: bias test calculator (screen 29), risk heat map and lineage (35), benchmarking (34), annual review carry-forward. */

export type Category = {
  key: string; label: string; applicants: number; selected: number; rate: number; share: number; impact_ratio: number | null; excluded: boolean; below_threshold: boolean;
  parity_difference: number | null; true_positive_rate: number | null; equal_opportunity_difference: number | null;
};
export type BiasTable = { dimension: string; label: string; categories: Category[]; unknown: number; unknown_selected: number; reference: string | null; excluded: string[]; note: string | null };
export type Below = { dimension: string; key: string; label: string; impact_ratio: number };
export type BiasRun = {
  id: string; method: 'selection_rate' | 'scoring_rate'; method_label: string; dataset_filename: string | null; dataset_file_id: string | null; data_source: string | null;
  results: { total: number; selected_total: number; unknown_count: number; median: number | null; has_labels: boolean; tables: Record<'sex' | 'race' | 'intersectional', BiasTable> };
  validation: { rows_read: number; rows_valid: number; warnings: string[]; columns: Record<string, string> };
  settings: { threshold: number; small_share: number; exclude_small: boolean }; unknown_count: number; unknown_pct: number | null; excluded_categories: string[];
  lowest: Below | null; run_by: string | null; run_at: string; library_version: string; keep_raw_data: boolean; raw_deleted_at: string | null; raw_delete_on: string | null;
  public_summary_at: string | null; bias_test_id: string | null; finding_ids: string[];
  feeds: { q_6_2_06: number | null; q_5_1a_03: number | null; q_5_1a_05: string | null; below_threshold: Below[]; draft_findings: number; public_summary_required: boolean };
};
export type BiasPage = {
  system: { id: string; reference_id: string; name: string; client_id: string; client_name: string | null; register_system_id: string | null; engagement_id: string; audit_ref: string | null };
  settings: BiasRun['settings']; public_summary_required: boolean; can_run: boolean; engagement_files: { id: string; filename: string; uploaded_at: string }[]; runs: BiasRun[];
};
export type GuardrailRun = {
  id: string; adapter: string; endpoint_label: string | null; prompt_set_version: string; passed_count: number; failed_count: number; status: string; run_by: string | null; run_at: string;
  decision_note: string | null; results: { id: string; category: string; title: string; passed: boolean; reason: string; excerpt: string }[];
  suggestion: { question: string; answer: string; checklist: string; text: string };
};

export type HeatSystem = {
  id: string; reference_id: string; name: string; built_by: string | null; built_by_label: string; department: string | null; inherent: number | null; maturity: number | null;
  residual: number | null; final_rating: string | null; final_label: string; residual_band: string | null; knockouts: string[]; provisional: boolean; raised_by_knockout: boolean;
  override: boolean; column: number | null; row: string | null;
};
export type HeatMap = {
  client: { id: string; name: string }; engagement: { id: string; audit_ref: string | null; name: string; stage: number; status: string }; methodology_version: string;
  columns: { label: string; min: number; max: number }[]; rows: string[];
  grid: Record<string, { band: string; systems: { id: string; reference_id: string; final_rating: string | null; provisional: boolean }[] }[]>;
  systems: HeatSystem[]; unplaced: string[]; knockout_note: string;
  findings_grid: { domains: { key: string; label: string }[]; rows: { severity: string; label: string; counts: number[]; unassigned: number }[]; total: number };
  filters: { departments: { id: string; name: string }[]; build_types: { key: string; label: string }[]; frameworks: string[] };
  findings: { id: string; ref: string; title: string; severity: string; status: string }[];
};
export type Lineage = {
  finding: { id: string; ref: string; title: string; severity: string; status: string; system: string | null; system_id: string | null; proposed_owner: string | null };
  responses: { code: string; label: string; answer: string | null; status: string; source: string | null; side: string | null }[];
  checklist: { code: string; text: string; confirmed: boolean }[]; controls: { ref: string; label: string }[];
  obligations: { regulation: string; regulation_id: string; citation: string | null; kind: 'obligation' | 'requirement'; items: { code?: string; text: string; citation: string | null }[] }[];
  evidence: { id: string; filename: string; via: string }[]; requests: { title: string; status: string; chases: number }[]; evidence_note: string | null;
  remediation: { id: string; action: string; owner: string | null; due_date: string | null; status: string }[];
};
export type ControlProof = {
  control: { code: string; text: string; section: string }; system: { id: string; reference_id: string; name: string }; confirmed: boolean; auditor_note: string | null;
  evidence: { id: string; filename: string; via: string }[]; answers: { code: string; label: string; answer: string | null; source: string | null }[];
  also_satisfies: { controls: { ref: string; label: string }[]; requirements: { code: string; text: string; regulation: string; in_scope: boolean }[]; checklist: { code: string; text: string }[] };
};

export type Comparison = {
  client: { id: string; name: string; industry: string | null; size_band: string; consent: boolean | null }; min_peers: number; group: { label: string; n: number } | null;
  groups_considered: { label: string; n: number; shown: boolean }[]; note: string | null;
  domains: { key: string; label: string; client: number | null; peer_median: number | null; below_peers: boolean }[]; overall: { client: number | null; peer_median: number | null };
};
export type Practice = { clients: number; min_clients: number; themes: { code: string; label: string; service: string; clients: number }[]; note: string | null };

export type CarriedItem = {
  response_id: string; system_id: string | null; system: string; code: string; label: string; status: 'pending' | 'confirmed' | 'changed';
  prior: { value: unknown; status: string; text: string }; current: { value: unknown; status: string | null; text: string }; decided_at: string | null;
};
export type Carried = { engagement: { id: string; audit_ref: string | null; status: string }; prior_ref: string | null; counts: { total: number; pending: number; confirmed: number; changed: number }; items: CarriedItem[] };
export type ClientBiasData = { runs: { id: string; system: string; dataset_filename: string | null; run_at: string; keep_raw_data: boolean; raw_deleted_at: string | null; raw_delete_on: string | null }[] };

export const pct = (x: number | null | undefined, dp = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(dp)}%`);
export const ratio = (x: number | null | undefined) => (x === null || x === undefined ? '—' : x.toFixed(2));
export const RATING: Record<string, string> = { critical: 'Critical (5)', high: 'High (4)', medium: 'Medium (3)', low: 'Low (2)', observation: 'Observation (1)' };
