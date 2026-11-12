/** Release 2 R3: scoping questionnaire (SM-05 to SM-08) and the SM-14 question bank and mapping rules tabs. */

export type Option = { value: string; label: string };
export type Question = {
  code: string; section: string; section_label: string; label: string; client_label: string | null; help: string | null; type: 'count' | 'total' | 'single' | 'multi' | 'yes_no' | 'text';
  options: Option[]; sum_of: string[]; client_visible: boolean; internal_only: boolean; unknown_assumption: string | null; order: number; active: boolean;
};
export type AnswerOut = { value: unknown; confidence: 'confirmed' | 'estimate' | 'unknown'; source: string; display: string; note?: string | null; by?: string | null; at?: string | null };
export type Section = { key: string; label: string; intro: string | null; internal: boolean; answered: number; total: number; questions: Question[] };
export type Line = { code: string; qty: number; reason: string; rule_code: string; removed_reason: string | null; name?: string | null; sellable_status?: string | null; in_catalog?: boolean | null };
export type Estimate = { available: boolean; one_time: number | null; recurring_y1: number | null; missing: string[]; percent: string[]; note: string | null };
export type SendRow = {
  id: string; contact_name: string; contact_email: string; question_count: number; answered: number; status: string; due_on: string | null; sent_at: string;
  opened_at: string | null; submitted_at: string | null; reminder_days: number[]; reminders_sent: number[]; forwarded: boolean; closed: boolean;
};
export type QOut = { id: string; version: number; mode: string; status: string; bank_version: number; locked: boolean; locked_by_name: string | null; locked_at: string | null; updated_at: string | null; removed_lines: { code: string; reason: string }[]; proposal_id: string | null };
export type ScopingView = {
  opportunity: { id: string; name: string; company: string; stage: string; prospect: boolean }; can_work: boolean;
  questionnaire: QOut | null; bank?: { version: number; starter: boolean }; sections?: Section[];
  answers?: Record<string, AnswerOut & { client: AnswerOut | null }>; suggested?: Line[]; not_answered_sections?: string[]; estimate?: Estimate;
  assumptions?: { code: string; text: string }[]; conflict_count?: number; rule_errors?: RuleError[]; sends?: SendRow[]; versions?: { id: string; version: number; status: string }[];
};
export type RuleError = { rule_code: string; line_code: string; message: string };
export type Draft = { value: unknown; confidence: 'confirmed' | 'estimate' | 'unknown'; note: string };

export const SOURCE_LABELS: Record<string, string> = { rep: 'Rep', client: 'Client', rep_confirmed_client: 'Client, confirmed by rep', derived: 'Sum of counts' };
export const STATUS_LABELS: Record<string, string> = {
  draft: 'Recording', sent: 'Sent to client', client_in_progress: 'Client answering', client_submitted: 'Client submitted', locked: 'Locked',
  opened: 'Opened', in_progress: 'In progress', submitted: 'Submitted', revoked: 'Closed', expired: 'Expired',
};

export function usd(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `$${Math.round(v).toLocaleString('en-US')}`;
}
