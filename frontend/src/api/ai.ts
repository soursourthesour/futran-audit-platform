import { useQuery } from '@tanstack/react-query';
import { api } from './client';

/** AI features (spec §21 F1, F5, F10). Every AI output is a suggestion until a named person accepts it. */
export type Citation = { file_id?: string; filename?: string; page?: number | null; quote: string | null; found: boolean; source_type?: string; source_id?: string | null; label?: string };
export type Interaction = {
  id: string; feature: string; call_id: string; target_type: string | null; target_id: string | null; target_code: string | null; output: Record<string, any>; citations: Citation[];
  confidence: 'high' | 'medium' | 'low' | null; status: 'suggested' | 'unsupported' | 'accepted' | 'edited' | 'rejected'; decided_by: string | null; decided_at: string | null;
  reason: string | null; result_refs: { type: string; id: string }[]; follow_up: string | null; follow_up_ref: string | null; model: string; provider: string; prompt_version: string;
  created_at: string | null; requested_by: string | null; ai_system_id: string | null; system?: string | null;
  /** Pre-fill only: the question's answer as it stands, so the card shows what accepting would replace. */
  current?: CurrentAnswer | null;
};
export type CurrentAnswer = { value: unknown; status: string; display: string | null; side: string | null; source: string | null; verified: boolean };
export type AISwitch = { enabled: boolean; consent_note?: string | null; enabled_by?: string | null; enabled_at?: string | null; can_manage?: boolean; can_use_copilot?: boolean; can_view_log?: boolean };
export type CopilotPanel = { enabled: boolean; documents: { id: string; filename: string; pages: number; chars: number; error: string | null; is_evidence: boolean }[]; suggestions: Interaction[]; interview_list: Interaction[]; can_view_log: boolean };
export type Completeness = {
  signoff: number; unanswered_required: { code: string; label: string; sub_section: string }[]; ticks_without_evidence: { code: string; text: string }[];
  missing_source_person: { code: string; label: string; sub_section: string }[]; contradictions: Interaction[]; contradictions_checked_at: string | null;
};
export type EvidenceRow = { code: string; text: string; confirmed: boolean; status: 'no_evidence' | 'checked'; suggestion: Interaction | null };

export function useAISwitch(engagementId: string | undefined) {
  return useQuery({ queryKey: ['ai-switch', engagementId], queryFn: () => api.get<AISwitch>(`/engagements/${engagementId}/ai`), enabled: !!engagementId });
}

export const CONFIDENCE_LABEL: Record<string, string> = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence' };
export const STATUS_LABEL: Record<string, string> = { suggested: 'Suggested', unsupported: 'Unsupported', accepted: 'Accepted', edited: 'Accepted with edits', rejected: 'Rejected' };
export const FEATURE_LABEL: Record<string, string> = {
  copilot_prefill: 'Document pre-fill', evidence_check: 'Evidence check', draft_finding: 'Draft finding text', review_check: 'Completeness review', summary: 'Summary',
  ask: 'Ask the copilot', explain: 'Explain this question', obligation_extract: 'Obligation extraction', questionnaire: 'Questionnaire answers',
};
export function statusTone(s: string): 'success' | 'warn' | 'danger' | 'muted' | 'navy' {
  return s === 'accepted' || s === 'edited' ? 'success' : s === 'unsupported' ? 'danger' : s === 'rejected' ? 'muted' : 'navy';
}
export function citeText(c: Citation): string {
  if (c.filename) return `${c.filename}${c.page ? ` · page ${c.page}` : ''}`;
  return c.label ?? '';
}

export type Obligation = {
  id: string; regulation_id: string; law: string | null; text: string; actor: string; action: string | null; condition: string | null; deadline: string | null; citation: string | null;
  quote: string | null; quote_found: boolean | null; effective_date: string | null; control_ids: string[]; question_ids: string[]; requirement_ids: string[]; requirements: string[];
  confidence: string | null; status: 'suggested' | 'unsupported' | 'approved' | 'rejected'; approved_by: string | null; approved_at: string | null; rejected_reason: string | null;
};

export type QItem = { id: string; order: number; locator: Record<string, any>; section: string | null; question: string; answer: string | null; status: string; citations: Citation[]; confidence: string | null; audited_by_futran: boolean; decided_at: string | null };
export type Questionnaire = {
  id: string; title: string; customer_name: string | null; format: 'xlsx' | 'docx' | 'pdf'; status: string; filename: string | null; due_date: string | null; created_at: string | null;
  counts: { questions: number; approved: number; to_review: number; open: number; audited: number }; items?: QItem[]; ai_enabled?: boolean;
};
export type LibraryItem = { id: string; question: string; answer: string; tags: string[]; source: string; audited_by_futran: boolean; approved_at: string | null };
