/* Types for the policy builder (27), AI literacy training (33) and the Trust Center (32). */

export type Block = { type: 'heading'; level: 1 | 2 | 3; text: string } | { type: 'paragraph'; text: string } | { type: 'list'; ordered: boolean; items: string[] };
export type Question = { key: string; label: string; type: 'text' | 'textarea' | 'list' | 'choice' | 'multi' | 'yesno'; help: string; required?: boolean; options?: { value: string; label: string }[] };
export type TemplateCard = { code: string; version: string; title: string; name: string; summary: string; catalog_codes: string[] };
export type AckStats = { sent: number; acknowledged: number; outstanding: number };
export type PolicyDoc = {
  id: string; title: string; status: 'draft' | 'awaiting_approval' | 'published' | 'retired'; status_label: string; version_no: number;
  template: { code: string; version: string; name: string; current_version: string | null };
  commitment: { id: string; description: string; target_date: string; status: string } | null;
  submitted_by: string | null; submitted_at: string | null; return_note: string | null; approved_by: string | null; approved_at: string | null;
  published_at: string | null; review_due: string | null; review_overdue: boolean; published_file: { id: string; filename: string } | null; edited: boolean;
  futran_review_requested_at: string | null; futran_team: { id: string; name: string }[]; acknowledgments?: AckStats; updated_at: string | null;
  answers?: Record<string, unknown>; blocks?: Block[]; questions?: Question[];
  can?: { edit: boolean; approve: boolean; request_review: boolean };
};
export type OpenCommitment = { id: string; description: string; target_date: string; owner: string; status: string; catalog_code: string | null; suggested_template: string | null };
export type PolicyList = { templates: TemplateCard[]; policies: PolicyDoc[]; commitments: OpenCommitment[]; can: { edit: boolean; approve: boolean } };

export type ModuleCard = { code: string; version: string; title: string; minutes: number; audience: string; summary: string; pass_mark: number; questions: number };
export type ModulePage = { title: string; paragraphs?: string[]; points?: string[] };
export type LearnerModule = ModuleCard & { pages: ModulePage[]; quiz: { id: string; question: string; options: { id: string; text: string }[] }[] };
export type Answered = { option_id: string; correct: boolean; explanation: string; correct_option: string };
export type Assignment = { id: string; module: ModuleCard; status: 'assigned' | 'in_progress' | 'completed'; due_date: string | null; started_at: string | null; completed_at: string | null; score: number | null; attempts: number; overdue: boolean };
export type PlayerState = Omit<Assignment, 'module'> & { name: string | null; module: LearnerModule; answered: Record<string, Answered> };
export type FinishResult = { passed: boolean; score: number; attempts: number; status: string; pass_mark?: number; certificate_no: string | null };
export type DeptRow = { id: string | null; name: string; assigned: number; completed: number; pct: number | null; below_target: boolean };
export type TrainingOverview = {
  modules: (ModuleCard & { assigned: number; completed: number; pct: number | null })[]; departments: DeptRow[];
  overall: { assigned: number; completed: number; pct: number | null; overdue: number };
  program: { target_pct: number; target_date: string | null; evidence: { id: string }[] };
  can: { manage: boolean }; is_literacy_owner: boolean;
  options: { groups: { id: string; name: string }[]; departments: { id: string; name: string }[]; roles: { value: string; label: string }[] };
};

export type TrustItem = {
  id: string; kind: 'commitment' | 'policy' | 'bias_summary' | 'badge' | 'governance' | 'rights_contact'; kind_label: string; title: string; body: string | null;
  link_label: string | null; link_url: string | null; source_id: string | null; options: { show_rating?: boolean };
  status: 'draft' | 'awaiting_confirmation' | 'returned' | 'published' | 'withdrawn'; live: boolean; content: Record<string, unknown> | null; problem: string | null;
  published_content: Record<string, unknown> | null; client_approved_by: string | null; client_approved_at: string | null; confirmed_by: string | null; confirmed_at: string | null;
  confirm_note: string | null; return_note: string | null; published_at: string | null;
  update_to: { policy_id: string; version_no: number } | null;
};
export type TrustPage = { id: string; slug: string; title: string; intro: string | null; contact_email: string | null; live: boolean; access: 'public' | 'nda'; nda_text: string | null; indexable: boolean; url_path: string };
export type TrustEditorData = {
  page: TrustPage | null; items: TrustItem[]; views: { day: string; views: number }[]; kinds: { value: string; label: string }[]; has_signed_report: boolean;
  sources: { engagements: { id: string; name: string; audit_ref: string | null; report_ref: string; signed_on: string }[]; bias_summaries: { id: string; tool_name: string | null; audit_date: string | null }[]; policies: { id: string; title: string; version_no: number }[] };
  can: { edit: boolean };
};
export type PublicItem = { id: string; kind: TrustItem['kind']; title: string; body: string; content: Record<string, any>; gated: boolean };
export type PublicTrust = { slug: string; organization: string; title: string; intro: string | null; contact_email: string | null; access: 'public' | 'nda'; nda_text: string | null; noindex: boolean; items: PublicItem[]; updated_at: string | null };
