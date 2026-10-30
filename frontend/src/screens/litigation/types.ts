export type Match = { organization_id: string; organization_name: string; match_reason: string; systems: { id: string; name: string; type: string; type_label: string; stage: string }[] };
export type CaseRow = {
  id: string; name: string; geography: string | null; jurisdiction_id: string | null; area: string; court: string | null; docket_ref: string | null; description: string | null;
  stage: string; stage_label: string; stage_note: string | null; last_update_on: string | null; version: number; regulation_ids: string[]; clients_count: number;
  systems_count: number; following: boolean; origin: string; match_summary?: string;
};
export type CaseDetail = CaseRow & {
  why_matters: string | null; talking_points_futran: string | null; talking_points_client: string | null; sources: { title: string; url: string }[];
  timeline: { on: string; stage: string; label: string }[]; match_rule: { types?: string[]; sourcing?: string[]; vendors?: string[]; uses?: string[]; decision_impact?: string[] };
  matches: Match[]; can_edit: boolean;
};
export type CaseList = {
  items: CaseRow[]; can_edit: boolean;
  filters: { areas: string[]; geographies: string[]; stages: { value: string; label: string }[]; clients: { id: string; name: string }[] };
  last_refresh: { id: string; status: string; started_at: string; open: number; total: number; alert_status: string | null } | null;
};
export const STAGE_TONE: Record<string, 'navy' | 'warn' | 'success' | 'muted' | 'danger'> = {
  filed: 'navy', pleadings: 'navy', discovery: 'navy', stayed: 'warn', trial: 'warn', appeal: 'warn', decided: 'success', settled: 'muted', dismissed: 'muted',
};
export const lines = (t: string | null | undefined) => (t ?? '').split('\n').map((x) => x.trim()).filter(Boolean);
export const TYPE_LABELS: Record<string, string> = {
  agent: 'AI agents', vendor_app: 'vendor AI apps', embedded_feature: 'embedded AI features', foundation_model_api: 'foundation model APIs',
  in_house_model: 'in-house models', genai_chat_tool: 'generative AI tools and chatbots',
};
