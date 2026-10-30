import { can, type Me } from '@/api/auth';

/** One navigation entry. It shows when the signed-in person holds any action in `requires` (from /auth/me, built from
 *  the permission matrix in backend app/policy), so a person with several roles sees the union of their modules.
 *  Only list screens that exist. */
export type NavEntry = { to: string; label: string; requires: string[]; end?: boolean };

/** Futran shell (spec §13.1). Role homes first, in the order of authority used for the landing page. */
export const FUTRAN_NAV: NavEntry[] = [
  { to: '/staff/admin', label: 'Admin home', requires: ['view_admin_home'] },
  { to: '/qa', label: 'QA queue', requires: ['view_qa_queue'] },
  { to: '/my-work', label: 'My work', requires: ['view_my_work'] },
  { to: '/audits', label: 'Dashboard', requires: ['view_engagement'], end: true },
  { to: '/clients', label: 'Clients', requires: ['view_engagement'], end: true },
  { to: '/reg', label: 'Regulatory master', requires: ['view_reg_master'] },
  { to: '/litigation', label: 'Litigation', requires: ['view_litigation'] },
  { to: '/opportunities', label: 'Opportunities', requires: ['view_opportunities'] },
  { to: '/alerts', label: 'Client alerts', requires: ['manage_client_alerts'] },
  { to: '/admin/templates', label: 'Templates', requires: ['configure_templates', 'approve_templates'] },
  { to: '/admin/reference', label: 'Reference data', requires: ['manage_reference_data', 'run_law_refresh'] },
  { to: '/admin/users', label: 'Users', requires: ['view_platform_settings'] },
  { to: '/admin/audit-log', label: 'Audit log', requires: ['view_audit_log'] },
  { to: '/admin/outbox', label: 'Outbox', requires: ['view_platform_settings'] },
  { to: '/staff/admin/email', label: 'Email and groups', requires: ['manage_futran_mailbox'] },
  { to: '/admin/log', label: 'Email log', requires: ['view_mail_log'] },
  { to: '/admin/settings', label: 'Settings', requires: ['view_platform_settings'] },
  // Wave 3 (spec §21, mockups 25–35) adds one entry each when its screen exists, for example:
  // { to: '/copilot', label: 'Copilot', requires: ['use_copilot'] }, bias calculator 29, heat map 35, benchmarking 34.
];

/** Client shell (spec §13.1). */
export const CLIENT_NAV: NavEntry[] = [
  { to: '/start', label: 'Getting started', requires: ['view_initiation_checklist'] },
  { to: '/summary', label: 'Summary', requires: ['view_sponsor_home'] },
  { to: '/data-review', label: 'Data review', requires: ['view_dpo_home'] },
  { to: '/admin/home', label: 'Admin home', requires: ['view_client_admin_home'] },
  { to: '/my-department', label: 'My department', requires: ['view_department_home'] },
  { to: '/my-tasks', label: 'My tasks', requires: ['view_my_tasks'] },
  { to: '/people', label: 'People', requires: ['manage_client_users'] },
  { to: '/register', label: 'AI system register', requires: ['view_register'] },
  { to: '/governance/roles', label: 'Company roles', requires: ['set_company_roles', 'manage_committee_members'] },
  { to: '/addons', label: 'Add-ons', requires: ['view_addons'] },
  { to: '/governance', label: 'Governance', requires: ['view_governance'], end: true },
  { to: '/attestation', label: 'Attestation', requires: ['view_attestation_aggregates', 'send_attestation'] },
  { to: '/my-attestation', label: 'My AI attestation', requires: ['complete_own_attestation'] },
  { to: '/inventory', label: 'AI inventory', requires: ['view_inventory'] },
  { to: '/review', label: 'Review', requires: ['sign_client_signoff', 'submit_use_case'] },
  { to: '/systems', label: 'AI systems', requires: ['prefill_system'] },
  { to: '/documents', label: 'Documents', requires: ['upload_requested_document'] },
  // the client report screen shows the whole report, so it is for those who hold the report and scores organization-wide
  // (a Department Compliance Lead holds view_final_report for department sections only)
  { to: '/report', label: 'Report', requires: ['view_scores'] },
  { to: '/responses', label: 'Responses', requires: ['respond_findings', 'approve_responses'] },
  { to: '/remediation', label: 'Remediation', requires: ['view_findings_responses'] },
  { to: '/admin/email', label: 'Email connection', requires: ['view_client_mailbox'] },
  { to: '/admin/groups', label: 'Groups', requires: ['view_client_groups'] },
  { to: '/admin/log', label: 'Email log', requires: ['view_mail_log'] },
  // Wave 3 adds one entry each when its screen exists: policy builder 27, integrations 30, monitoring 31, training 33.
];

export function navFor(me: Me, entries: NavEntry[]): NavEntry[] {
  return entries.filter((n) => can(me, ...n.requires));
}

/** Where this person lands after sign-in (their highest-authority role home, decided by the backend). */
export function homePath(me: Me): string {
  return me.home ?? (me.organization.type === 'futran' ? '/audits' : '/start');
}
