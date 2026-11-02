/** Wave 3 WS-L: comments and mentions (F18), public API and webhooks (F17), agent oversight (F14), platform trust (F19). */
import { useQuery } from '@tanstack/react-query';
import { api } from './client';

// ---- comments (F18)
export type CommentObjectType = 'response' | 'evidence_request' | 'document_request' | 'finding' | 'remediation';
export type CommentItem = {
  id: string; parent_id: string | null; author: string | null; author_id: string; author_side: 'futran' | 'client'; visibility: 'internal' | 'shared';
  body: string | null; mentions: { id: string; name: string | null }[]; at: string; edited_at: string | null; withdrawn: boolean; withdrawn_at: string | null;
  can_edit: boolean; can_withdraw: boolean;
};
export type CommentThread = CommentItem & { replies: CommentItem[] };
export type CommentsPage = { threads: CommentThread[]; shared_allowed: boolean; visibility_options: ('internal' | 'shared')[]; default_visibility: 'internal' | 'shared'; label: string; can_post: boolean };
export type Mentionable = { id: string; name: string; job_title: string | null; side: 'futran' | 'client' };

export const commentsKey = (t: string, id: string) => ['comments', t, id];
export function useComments(objectType: CommentObjectType, objectId: string, enabled = true) {
  return useQuery({ queryKey: commentsKey(objectType, objectId), queryFn: () => api.get<CommentsPage>(`/comments?object_type=${objectType}&object_id=${encodeURIComponent(objectId)}`), enabled });
}
export function useCommentCounts(objectType: CommentObjectType, ids: string[]) {
  const key = ids.slice().sort().join(',');
  return useQuery({ queryKey: ['comment-counts', objectType, key], queryFn: () => api.get<{ counts: Record<string, number> }>(`/comments/counts?object_type=${objectType}&ids=${key}`), enabled: ids.length > 0 });
}

// ---- public API and webhooks (F17)
export type ApiClientRow = { id: string; name: string; client_id: string; secret_hint: string; scopes: string[]; rate_limit_per_minute: number; status: 'active' | 'revoked'; owner: string | null; created_at: string; last_used_at: string | null; revoked_at: string | null };
export type Delivery = { id: string; event: string; status: 'pending' | 'retrying' | 'delivered' | 'failed' | 'blocked'; attempts: number; created_at: string; last_attempt_at: string | null; next_attempt_at: string | null; last_status_code: number | null; last_error: string | null; delivered_at: string | null };
export type WebhookRow = { id: string; url: string; events: string[]; description: string | null; status: 'active' | 'paused'; created_at: string; last_delivery: Delivery | null };
export type ApiAdmin = { clients: ApiClientRow[]; webhooks: WebhookRow[]; scopes: { code: string; label: string }[]; events: { code: string; label: string }[]; can_manage: boolean; token_url: string; base_url: string };
export function useApiAdmin() {
  return useQuery({ queryKey: ['api-admin'], queryFn: () => api.get<ApiAdmin>('/admin/api') });
}

// ---- agent oversight (F14)
export type AgentTool = { name: string; description: string | null; access: 'read' | 'write' | 'act'; needs_approval: boolean };
export type AgentRegistration = { tools: AgentTool[]; permissions: string[]; approval_points: string[]; autonomy_level: string; autonomy_label: string | null; kill_switch: string | null; kill_switch_tested_on: string | null; rate_limits: string | null; version: number; updated_at: string | null };
export type TrendMonth = { month: string; label: string; total: number; escalated: number; blocked: number; override_rate: number | null };
export type AgentPanel = {
  system: { id: string; reference: string; name: string; type: string; autonomy: string | null }; is_agent: boolean; registration: AgentRegistration | null; can_edit: boolean;
  unregistered_tools: string[]; trend: TrendMonth[]; flags: string[]; reviews: { id: string; completed_at: string | null; size: number; summary: Record<string, number> }[];
  autonomy_options: { value: string; label: string }[];
};
export type SampleDecision = { id: string; at?: string; action?: string; tool?: string | null; decision?: string; decision_label?: string; approver?: string | null; policy_ref?: string | null; verdict: string | null; verdict_label: string | null; note: string | null; reviewer: string | null };
export type Sample = { id: string; system_id: string; engagement: string | null; seed: number; population: number; size: number; period_from: string; period_to: string; method: string; status: 'open' | 'complete'; drawn_by: string | null; drawn_at: string; completed_by: string | null; completed_at: string | null; conclusion: string | null; summary: Record<string, number>; decisions: SampleDecision[] };
export type AgentRow = { id: string; reference: string; name: string; stage: string; department: string | null; registration: AgentRegistration | null; unregistered_tools: string[]; decisions: number; trend: TrendMonth[]; flags: string[]; samples: Sample[] };
export type AgentsPage = { client: string; engagement: string | null; agents: AgentRow[]; verdicts: { value: string; label: string }[] };

// ---- platform trust (F19)
export type SocControlRow = { id: string; code: string; criterion: string; criterion_label: string | null; title: string; description: string | null; owner_id: string | null; owner: string | null; status: string; status_label: string | null; evidence_link: string | null; last_reviewed_on: string | null; review_months: number; next_review_on: string | null; review_overdue: boolean; notes: string | null };
export type TrustPage = {
  controls: SocControlRow[]; criteria: { value: string; label: string }[]; statuses: { value: string; label: string }[]; summary: Record<string, number>;
  ai_systems: { id: string; reference: string; name: string; stage: string; purpose: string | null; risk_tier: number | null; ai_provider: string | null; model_name: string | null }[];
  trust_center: { link: string } | null; can_edit: boolean; people: { id: string; name: string }[];
};
