/** Types for the email screens (spec §26, §27.1): E1–E5, the mailbox prompt and the no-login links. */
export type Credentials = {
  test_mode: boolean;
  microsoft365: { configured: boolean; missing: string[]; redirect_uri: string; available: boolean };
  google: { configured: boolean; missing: string[]; redirect_uri: string; available: boolean };
};
export type Connection = {
  id?: string; status: 'not_connected' | 'consent_requested' | 'connected' | 'error' | 'disconnected'; provider: 'microsoft365' | 'google' | null; provider_label?: string | null;
  mailbox_address: string | null; send_as_name?: string | null; reply_to?: string | null; reply_to_mode?: string; sender_mode?: 'own' | 'futran_on_behalf'; scopes?: string[];
  consent_by?: string | null; consent_at?: string | null; last_sync_at?: string | null; spf_ok?: boolean | null; dkim_ok?: boolean | null; dmarc_ok?: boolean | null;
  sync_interval_min?: number; options?: Record<string, unknown>; domain?: string | null; it_request_email?: string | null; it_request_sent_at?: string | null;
  test_sent_at?: string | null; test_sent_to?: string | null; last_error?: string | null; onboarding_step?: number; completed_at?: string | null;
};
export type DirectoryStatus = {
  schedule: string; include_guests: boolean; use_directory_groups: boolean; department_field: string; scope_group: string | null; scope_group_name: string | null;
  last_run_at: string | null; people: number; joined: number; left: number; changed: number; status: string; report: { unmatched_departments?: string[]; groups?: number; departments?: number; error?: string };
  groups: { id: string; name: string; member_count: number }[];
};
export type FutranMail = { connection: Connection; credentials: Credentials; can_manage: boolean; per_user_sync: string; email_mode: string };
export type ClientMail = {
  connection: Connection; directory: DirectoryStatus | null; step: number; credentials: Credentials; can_manage: boolean; futran_sender: string | null; organization: string;
  per_user_sync: string; can_set_user_sync: boolean;
};
export type Group = {
  id: string; name: string; purpose: string | null; source: 'manual' | 'rule' | 'directory'; source_label: string; rule: Record<string, string> | null; rule_text: string;
  directory_group_id: string | null; member_count: number; last_synced_at: string | null; used_by: string | null; is_default: boolean; system_key: string | null;
  owner_role: string | null; department_id: string | null; department: string | null; exclude_on_leave: boolean; can_edit: boolean;
};
export type Person = { id: string; name: string; email: string; department: string | null; department_id: string | null; job_title: string | null; office: string | null; status: string; source: string; has_login: boolean };
export type GroupMember = (Person & { member_id: string | null; kind: 'person' }) | { member_id: string; kind: 'group'; id: string; name: string; member_count: number };
export type GroupDetail = Group & { members: GroupMember[]; exclusions: Person[] };
export type GroupsList = {
  organization: { id: string; name: string; type: 'futran' | 'client' }; groups: Group[]; can_create: boolean; my_departments: string[] | null;
  departments: { id: string; name: string }[]; directory_connected: boolean; directory_groups: { id: string; directory_id: string; name: string; member_count: number }[];
};
export type Template = { id: string; key: string; name: string; purpose: string; default_mode: 'personal' | 'bcc'; subject: string; body: string; button_label: string | null; version: number; owner: 'futran' | 'client'; can_edit?: boolean };
export type Step = { label: string; count: number; kind: 'group' | 'add' | 'remove' | 'total' };
export type SendOptions = {
  organization: { id: string; name: string }; engagement: { id: string; audit_ref: string; name: string } | null; templates: Template[];
  groups: { id: string; name: string; source: string; member_count: number; system_key: string | null }[]; senders: { key: string; label: string }[];
  departments: { id: string; name: string }[]; offices: string[]; defaults: { link_days: number; batch_size: number; reminder_days: number[] }; pace_per_minute: number;
};
export type Preview = { steps: Step[]; total: number; people: Person[]; message: { from: string; to: string; subject: string; html: string; text: string }; campaign: string | null };
export type SendRow = {
  id: string; kind: string; sent_at: string; scheduled_at: string | null; template: string; template_key: string | null; groups: string[]; mode: string; mode_label: string; sent_by: string;
  status: string; channel: string | null; sender: string | null; subject: string | null; recipients: number; delivered: number; bounced: number; opened: number; completed: number;
  queued: number; replies: number; reminder_plan: number[] | null; parent_send_id: string | null; steps: Step[] | null;
};
export type SendDetail = SendRow & {
  subject_ref: string | null; message: { subject: string; html: string; to: string[]; bcc_count: number };
  recipients: { id: string; name: string | null; email: string; status: string; reminders_sent: number; opened_at: string | null; completed_at: string | null; error: string | null; out_of_office: boolean }[];
  replies: { id: string; from: string; received_at: string; subject: string; snippet: string; kind: string }[]; can_remind: boolean;
};
export type AdminEntry = { id: string; at: string; who: string; category: string; label: string; action: string; summary: string; retain_until: string };
export type MyMailbox = {
  policy: 'required' | 'optional' | 'off'; prompt: boolean; required: boolean; suggested_provider: string | null; credentials: Credentials;
  connection: { status: string; mailbox: string | null; provider: string; provider_label: string; consented_at: string | null } | null;
};

export const PROVIDER_LABEL: Record<string, string> = { microsoft365: 'Microsoft 365', google: 'Google Workspace' };

export function statusLabel(s: Connection['status']): { text: string; tone: 'success' | 'warn' | 'danger' | 'muted' } {
  if (s === 'connected') return { text: 'Connected', tone: 'success' };
  if (s === 'consent_requested') return { text: 'Waiting for approval', tone: 'warn' };
  if (s === 'error') return { text: 'Needs attention', tone: 'danger' };
  if (s === 'disconnected') return { text: 'Disconnected', tone: 'muted' };
  return { text: 'Not connected', tone: 'muted' };
}

/** Follow a consent URL. In test mode it is the platform's own consent page, so stay in the app. */
export function goToConsent(url: string) {
  window.location.assign(url);
}

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
