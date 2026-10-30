import type { SignOffView } from '@/components/SignPanel';

/** Role home data (spec §13.1); one endpoint per home, each behind its own permission. */
export type EngagementRef = { id: string; audit_ref: string; name: string; type_label: string; stage: number; stage_name: string; stage_label: string; status: string; status_label: string };

export type AdminHomeData = {
  users: { total: number; active: number; invited: number; mfa: number; by_role: Record<string, number> };
  clients: { total: number; drafts: number; in_progress: number; completed: number };
  law_matrix: { label: string | null; status_date: string | null; published_at: string | null; laws: number; jurisdictions: number };
  templates: number;
  pending_proposals: number;
};

export type WorkEngagement = EngagementRef & { client: string; client_id: string; my_role: string | null; systems: number; systems_assessed: number; link: string };
export type WorkTask = { kind: string; client: string; client_id: string; title: string; detail: string; link: string; overdue: boolean; due: string | null };
export type MyWorkData = { engagements: WorkEngagement[]; tasks: WorkTask[] };

export type QaFinding = { id: string; ref: string; title: string; severity: string; description: string | null; control_refs: string[]; client: string; client_id: string; audit_ref: string; author: string | null; submitted_at: string | null; waiting_days: number | null; can_review: boolean; link: string };
export type QaOverride = { system_id: string; reference_id: string; system: string; client: string; client_id: string; audit_ref: string; rating: string; computed_rating: string | null; rationale: string | null; by: string | null; at: string | null; waiting_days: number | null; can_review: boolean; link: string };
export type QaData = { findings: QaFinding[]; overrides: QaOverride[]; reviewed: { kind: 'finding' | 'override'; decision: 'approved' | 'returned'; summary: string | null; at: string }[] };

export type ClientAdminData = {
  organization: string;
  engagement: EngagementRef | null;
  users: { total: number; active: number; invited: number; disabled: number };
  invitations: { pending: number; expiring: { user: string; roles: string[]; expires_at: string }[] };
  departments: { total: number; items: { id: string; name: string; has_lead: boolean; in_scope: boolean }[]; without_lead: { id: string; name: string }[]; blocks_stage: number | null };
  email: { status: string; done: boolean; link: string };
  sso: { available: boolean };
  role_changes: { summary: string | null; by: string | null; at: string; sign_off_role: boolean }[];
  todos: { kind: string; text: string; link: string }[];
};

export type SignOffBlock = { sign_off: SignOffView | null; link: string; unmet?: string[] };
export type SponsorData = {
  organization: string; engagement: EngagementRef | null; signoffs: Record<string, SignOffBlock>; waiting: number[];
  findings: { total: number; by_severity: Record<string, number> } | null;
  rating: { overall: string | null; maturity: number | null; narrative: string | null } | null;
  systems: number; use_cases: number; final_report_released?: boolean;
};

export type DpoUseCase = { id: string; name: string; department: string | null; tier: number | null; data: string[]; data_labels: string[]; accounts: string[]; personal_account: boolean; status: string; status_label: string; link: string };
export type DpoData = {
  organization: string; engagement: EngagementRef | null; signoff3: SignOffBlock | null; use_cases: DpoUseCase[];
  privacy: { min_group: number; individuals_visible_to: string[]; notice_acknowledged?: boolean };
  campaign: { status: string; closes_at: string; responses: number } | null;
};

export type DeptSection = {
  id: string; name: string;
  use_cases: { id: string; name: string; status: string; status_label: string; tier: number | null; by: string | null; link: string }[];
  tiers: Record<string, number>; awaiting_approval: number; signoff2: SignOffBlock;
  attestation: { responses: number | string | null; headcount: number | null; status: string | null; min_group: number };
  findings: { id: string; ref: string; title: string; severity: string; response_status: string; due_date: string | null; link: string }[] | null;
  register: { total: number; live: number; items: { id: string; reference: string; name: string; stage: string; link: string }[] };
};
export type DepartmentData = { organization: string; engagement: EngagementRef | null; departments: DeptSection[]; findings_shared: boolean };

export type TaskUseCase = { id: string; name: string; status: string; status_label: string; tier: number | null; department: string | null; comment: string | null; from_attestation: boolean; link: string };
export type MyTasksData = {
  organization: string; engagement: EngagementRef | null; returned: TaskUseCase[]; drafts: TaskUseCase[];
  evidence: { id: string; ref: string; description: string; due_date: string; use_case: string | null; overdue: boolean }[];
  documents: { id: string; title: string; system: string | null; due_at: string | null }[];
  entries: TaskUseCase[];
  /** False once sign-off 4 or the end of fieldwork has locked the inventory. */
  inventory_open?: boolean;
};
