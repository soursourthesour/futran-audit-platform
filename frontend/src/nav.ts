import { can, type Me } from '@/api/auth';

/** One navigation entry. It shows when the signed-in person holds any action in `requires` (from /auth/me, built from
 *  the permission matrix in backend app/policy), so a person with several roles sees the union of their modules.
 *  Only list screens that exist. `badge` names a count from /nav/badges shown beside the label. */
export type NavEntry = { to: string; label: string; requires: string[]; end?: boolean; badge?: NavBadge };
export type NavBadge = 'obligations_to_review';
/** A menu of entries (11-03 F4, C1). A group with one entry the person can use renders as a plain link. */
export type NavGroup = { id: string; label: string; entries: NavEntry[] };

/** Futran shell (spec §13.1), grouped. Role homes first, in the order of authority used for the landing page. */
export const FUTRAN_GROUPS: NavGroup[] = [
  { id: 'work', label: 'Home and work', entries: [
    { to: '/staff/chief', label: 'Chief Auditor home', requires: ['view_chief_home'] },
    { to: '/staff/admin', label: 'Admin home', requires: ['view_admin_home'] },
    { to: '/qa', label: 'QA queue', requires: ['view_qa_queue'] },
    { to: '/my-work', label: 'My work', requires: ['view_my_work'] },
    { to: '/clients', label: 'Clients', requires: ['view_engagement'], end: true },
  ] },
  { id: 'law', label: 'Law library', entries: [
    { to: '/reg', label: 'Law library', requires: ['view_reg_master'] },
    // the second-review queue: the Legal/Compliance Reviewer holds no other law library permission
    { to: '/reg/refresh', label: 'Refresh and review', requires: ['view_reg_changes'] },
    { to: '/reg/roles', label: 'Roles and committees', requires: ['view_reg_master'] },
    { to: '/reg/obligations', label: 'Obligations to review', requires: ['approve_obligations'], badge: 'obligations_to_review' },
    { to: '/reg/updates', label: 'Regulatory updates', requires: ['view_reg_updates'] }, // WS-H screen 26
  ] },
  { id: 'business', label: 'Business', entries: [
    { to: '/litigation', label: 'Litigation', requires: ['view_litigation'] },
    { to: '/opportunities', label: 'Opportunities', requires: ['view_opportunities'] },
    { to: '/alerts', label: 'Client alerts', requires: ['manage_client_alerts'] },
    { to: '/insights', label: 'Insights', requires: ['view_benchmarks', 'view_practice_insights'] }, // WS-K screen 34
  ] },
  { id: 'assurance', label: 'Assurance', entries: [
    // wave 3 WS-I: Trust Center confirmations (32) and client policy reviews (27, independence rule)
    { to: '/trust-confirmations', label: 'Trust Center confirmations', requires: ['confirm_trust_items'] },
    { to: '/client-policies', label: 'Client policy reviews', requires: ['view_client_policies'] },
    { to: '/staff/admin/trust', label: 'Platform trust', requires: ['view_platform_trust'] },
  ] },
  { id: 'admin', label: 'Administration', entries: [
    { to: '/admin/users', label: 'Users', requires: ['view_platform_settings'] },
    { to: '/admin/client-users', label: 'Client users', requires: ['view_all_client_users'] },  // feedback 10 Nov F1 (FX)
    { to: '/admin/templates', label: 'Templates', requires: ['configure_templates', 'approve_templates'] },
    { to: '/admin/reference', label: 'Reference data', requires: ['manage_reference_data', 'run_law_refresh'] },
    { to: '/staff/admin/email', label: 'Email and groups', requires: ['manage_futran_mailbox'] },
    // the outbox (test mode) is a tab of the email log; /admin/outbox redirects there
    { to: '/admin/log', label: 'Email log', requires: ['view_mail_log'] },
    { to: '/admin/audit-log', label: 'Audit log', requires: ['view_audit_log'] },
    { to: '/admin/settings', label: 'Settings', requires: ['view_platform_settings'] },
  ] },
];

/** Client shell (spec §13.1), grouped. */
export const CLIENT_GROUPS: NavGroup[] = [
  { id: 'home', label: 'Home', entries: [
    { to: '/start', label: 'Getting started', requires: ['view_initiation_checklist'] },
    { to: '/summary', label: 'Summary', requires: ['view_sponsor_home'] },
    { to: '/data-review', label: 'Data review', requires: ['view_dpo_home'] },
    { to: '/admin/home', label: 'Admin home', requires: ['view_client_admin_home'] },
    { to: '/my-department', label: 'My department', requires: ['view_department_home'] },
    { to: '/my-tasks', label: 'My tasks', requires: ['view_my_tasks'] },
  ] },
  { id: 'audit', label: 'Audit', entries: [
    { to: '/review', label: 'Review', requires: ['sign_client_signoff', 'submit_use_case'] },
    { to: '/documents', label: 'Documents', requires: ['upload_requested_document'] },
    // the client report screen shows the whole report, so it is for those who hold the report and scores organization-wide
    // (a Department Compliance Lead holds view_final_report for department sections only)
    { to: '/report', label: 'Report', requires: ['view_scores'] },
    { to: '/responses', label: 'Responses', requires: ['respond_findings', 'approve_responses'] },
    { to: '/remediation', label: 'Remediation', requires: ['view_findings_responses'] },
  ] },
  { id: 'governance', label: 'AI governance', entries: [
    // 11-10 U1: one list for the register, the AI inventory and the current audit's systems (/inventory and /systems redirect here)
    { to: '/register', label: 'AI systems', requires: ['view_register', 'view_inventory', 'prefill_system'] },
    { to: '/governance', label: 'Governance', requires: ['view_governance'], end: true },
    { to: '/governance/roles', label: 'Company roles', requires: ['set_company_roles', 'manage_committee_members'] },
    { to: '/policies', label: 'Policies', requires: ['view_policies'] },
    { to: '/projects', label: 'New AI projects', requires: ['view_projects'] }, // WS-H screen 28
    { to: '/updates', label: 'Regulatory updates', requires: ['view_client_updates'] }, // WS-H screen 26 (client)
    { to: '/addons', label: 'Add-ons', requires: ['view_addons'] },
  ] },
  { id: 'people', label: 'People and training', entries: [
    { to: '/people', label: 'People', requires: ['manage_client_users'] },
    { to: '/attestation', label: 'Attestation', requires: ['view_attestation_aggregates', 'send_attestation'] },
    { to: '/my-attestation', label: 'My AI attestation', requires: ['complete_own_attestation'] },
    { to: '/training', label: 'AI literacy training', requires: ['view_training'] },
    { to: '/my-training', label: 'My training', requires: ['complete_own_training'] },
  ] },
  { id: 'data', label: 'Data and integrations', entries: [
    { to: '/bias-data', label: 'Bias test data', requires: ['keep_bias_data'] }, // WS-K: keep or delete raw applicant data
    { to: '/integrations', label: 'Integrations', requires: ['view_integrations'] },
    { to: '/monitoring', label: 'Monitoring', requires: ['view_monitoring'] },
    { to: '/questionnaires', label: 'Customer questionnaires', requires: ['use_questionnaires'] },
    { to: '/admin/api', label: 'API and webhooks', requires: ['view_api_clients'] },
    { to: '/trust', label: 'Trust Center', requires: ['view_trust_center'], end: true },
  ] },
  { id: 'email', label: 'Email', entries: [
    { to: '/admin/email', label: 'Email connection', requires: ['view_client_mailbox'] },
    { to: '/admin/groups', label: 'Groups', requires: ['view_client_groups'] },
    { to: '/admin/log', label: 'Email log', requires: ['view_mail_log'] },
  ] },
];

/** Every entry in one flat list, in menu order. */
export const FUTRAN_NAV: NavEntry[] = FUTRAN_GROUPS.flatMap((g) => g.entries);
export const CLIENT_NAV: NavEntry[] = CLIENT_GROUPS.flatMap((g) => g.entries);

/** The groups this person can use, each holding only the entries they can use; empty groups are dropped. */
export function groupsFor(me: Me, groups: NavGroup[]): NavGroup[] {
  return groups.map((g) => ({ ...g, entries: navFor(me, g.entries) })).filter((g) => g.entries.length > 0);
}

export function navFor(me: Me, entries: NavEntry[]): NavEntry[] {
  return entries.filter((n) => can(me, ...n.requires));
}

/** The one entry to mark as current: the longest path that matches, so /reg/refresh lights up "Refresh and review"
 *  and not "Law library" as well. */
export function activeNav(pathname: string, entries: NavEntry[]): string | null {
  const hits = entries.filter((n) => pathname === n.to || (!n.end && pathname.startsWith(`${n.to}/`)));
  return hits.sort((a, b) => b.to.length - a.to.length)[0]?.to ?? null;
}

/** Where this person lands after sign-in (their highest-authority role home, decided by the backend). */
export function homePath(me: Me): string {
  return me.home ?? (me.organization.type === 'futran' ? '/audits' : '/start');
}
