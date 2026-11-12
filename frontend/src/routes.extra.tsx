import { Navigate, type RouteObject } from 'react-router-dom';
import { UsersAdmin } from '@/screens/admin/Users';
import { ClientUsers } from '@/screens/admin/ClientUsers';
import { AuditLogScreen } from '@/screens/admin/AuditLog';
import { SettingsScreen } from '@/screens/admin/Settings';
import { ReferenceData } from '@/screens/admin/ReferenceData';
import { TemplatesAdmin } from '@/screens/admin/Templates';
import { NewClientStart, NewClientWizard } from '@/screens/futran/newclient/Wizard';
import { ClientPage } from '@/screens/futran/ClientPage';
import { UsersDepartments } from '@/screens/client/UsersDepartments';
import { Governance } from '@/screens/client/Governance';
import { GovernanceRequestSetup } from '@/screens/futran/GovernanceRequestSetup';
import { AttestationTracker, FutranAttestation } from '@/screens/client/AttestationTracker';
import { PhoneAttestation } from '@/screens/phone/Attestation';
import { MyAttestation } from '@/screens/client/MyAttestation';
import { FutranInventory } from '@/screens/client/Inventory';
import { UseCaseForm } from '@/screens/client/UseCaseForm';
import { NamedUserConfirm } from '@/screens/phone/NamedUserConfirm';
import { SystemsRegister } from '@/screens/futran/SystemsRegister';
import { SystemAssessment } from '@/screens/futran/SystemAssessment';
import { SystemPrefill } from '@/screens/client/SystemPrefill';
import { DocumentRegister } from '@/screens/futran/DocumentRegister';
import { SystemScore } from '@/screens/futran/SystemScore';
import { FieldworkUseCase } from '@/screens/futran/FieldworkUseCase';
import { FindingsQA } from '@/screens/futran/FindingsQA';
import { FinalReport } from '@/screens/futran/FinalReport';
import { ClientReport } from '@/screens/client/Report';
import { ManagementResponse } from '@/screens/client/ManagementResponse';
import { Remediation } from '@/screens/shared/Remediation';
import { DocumentUploads } from '@/screens/client/DocumentUploads';
import { InventoryReview } from '@/screens/client/InventoryReview';
import { ListPreset, RegisterGrid } from '@/screens/register/RegisterGrid';
import { RegisterNew, RegisterSystemPage } from '@/screens/register/RegisterSystem';
import { CompanyRoles } from '@/screens/register/CompanyRoles';
import { AddonsPage } from '@/screens/tracing/Addons';
import { LawLibrary } from '@/screens/futran/reg/LawLibrary';
import { LawRecord } from '@/screens/futran/reg/LawRecord';
import { LawEdit } from '@/screens/futran/reg/LawEdit';
import { RoleCatalogue } from '@/screens/futran/reg/RoleCatalogue';
import { Applicability } from '@/screens/futran/reg/Applicability';
import { wsdRoutes } from '@/routes.wsd';
import { r3FutranRoutes, r3PublicRoutes } from '@/routes.r3'; // Release 2 R3: scoping questionnaire
import { r4FutranRoutes, r4PublicRoutes } from '@/routes.r4'; // Release 2 R4: proposals, approvals, acceptance
import { wskClientRoutes, wskFutranRoutes } from '@/routes.wsk';
import { wsgClientRoutes, wsgFutranRoutes } from '@/routes.wsg';
import { clientHomeRoutes, futranHomeRoutes } from '@/routes.wsf';
import { wslClientRoutes, wslFutranRoutes } from '@/routes.wsl';
import { wsjClientRoutes, wsjFutranRoutes, wsjPublicRoutes } from '@/routes.wsj';
import { wshClientRoutes, wshFutranRoutes } from '@/routes.wsh';
import { FutranEmail } from '@/screens/email/FutranEmail';
import { ClientEmailSetup } from '@/screens/email/ClientEmailSetup';
import { ClientGroupsForFutran, GroupsScreen } from '@/screens/email/Groups';
import { SendToGroups } from '@/screens/email/SendToGroups';
import { EmailLog } from '@/screens/email/EmailLog';
import { LinkLanding } from '@/screens/email/LinkLanding';
import { ConsentResult, TestConsent } from '@/screens/email/Consent';
import { MailboxPrompt } from '@/screens/email/MailboxPrompt';
import { wsiClientRoutes, wsiFutranRoutes, wsiPublicRoutes } from '@/routes.wsi';
import { r6aClientRoutes, r6aFutranRoutes } from '@/routes.r6a';
import { r5ClientRoutes, r5FutranRoutes } from '@/routes.r5';  // Release 2 R5
import { r1FutranRoutes } from '@/routes.r1';  // Release 2 R1: price list and Estimator
import { r6bClientRoutes, r6bFutranRoutes } from '@/routes.r6b';  // Release 2 R6b: Copilot readiness, EU AI Act conformity
import { r7ClientRoutes, r7FutranRoutes } from '@/routes.r7';  // Release 2 R7: hierarchy, vault, partners

/** Screens added by later tasks register here, so routes.tsx stays stable. */
export const futranRoutes: RouteObject[] = [
  ...r5FutranRoutes,
  ...r6bFutranRoutes,
  ...wsdRoutes,
  ...r3FutranRoutes,
  ...r4FutranRoutes,
  ...wskFutranRoutes,
  ...wslFutranRoutes,
  ...wsgFutranRoutes,
  ...wsiFutranRoutes,
  ...wshFutranRoutes,
  ...futranHomeRoutes,
  ...wsjFutranRoutes,
  ...r1FutranRoutes,
  ...r6aFutranRoutes,
  ...r7FutranRoutes,
  { path: '/admin/users', element: <UsersAdmin /> },
  { path: '/admin/client-users', element: <ClientUsers /> },  // feedback 10 Nov F1
  { path: '/staff/admin/email', element: <FutranEmail /> },
  { path: '/clients/:clientId/groups', element: <ClientGroupsForFutran /> },
  { path: '/admin/audit-log', element: <AuditLogScreen /> },
  { path: '/admin/outbox', element: <Navigate to="/admin/log?tab=outbox" replace /> },  // 11-03 F14b: the outbox is a tab of the email log
  { path: '/admin/settings', element: <SettingsScreen /> },
  { path: '/admin/reference', element: <ReferenceData /> },
  { path: '/admin/templates', element: <TemplatesAdmin /> },
  { path: '/audits/new', element: <NewClientStart /> },
  { path: '/clients/:clientId/setup/:step', element: <NewClientWizard /> },
  { path: '/clients/:clientId', element: <ClientPage /> },
  { path: '/clients/:clientId/governance', element: <GovernanceRequestSetup /> },
  { path: '/clients/:clientId/attestation', element: <FutranAttestation /> },
  { path: '/clients/:clientId/inventory', element: <FutranInventory /> },
  { path: '/clients/:clientId/inventory/:useCaseId', element: <UseCaseForm /> },
  { path: '/clients/:clientId/systems', element: <SystemsRegister /> },
  { path: '/clients/:clientId/people', element: <Navigate to="departments" replace /> },
  { path: '/clients/:clientId/people/departments', element: <UsersDepartments tab="departments" /> },
  { path: '/clients/:clientId/people/users', element: <UsersDepartments tab="users" /> },
  { path: '/clients/:clientId/assessment', element: <SystemAssessment /> },
  { path: '/systems/:systemId/assess', element: <SystemAssessment /> },
  { path: '/clients/:clientId/documents', element: <DocumentRegister /> },
  { path: '/systems/:systemId/score', element: <SystemScore /> },
  { path: '/clients/:clientId/fieldwork/:useCaseId', element: <FieldworkUseCase /> },
  { path: '/clients/:clientId/findings', element: <FindingsQA /> },
  { path: '/clients/:clientId/report', element: <FinalReport /> },
  { path: '/clients/:clientId/responses', element: <ManagementResponse /> },
  { path: '/clients/:clientId/remediation', element: <Remediation /> },
  { path: '/reg', element: <LawLibrary /> },
  { path: '/reg/new', element: <LawEdit /> },
  { path: '/reg/roles', element: <RoleCatalogue /> },
  { path: '/reg/:lawId', element: <LawRecord /> },
  { path: '/reg/:lawId/edit', element: <LawEdit /> },
  { path: '/clients/:clientId/applicability', element: <Applicability /> },
];
export const clientRoutes: RouteObject[] = [...r6bClientRoutes, ...r6aClientRoutes, ...r5ClientRoutes, ...clientHomeRoutes, ...wskClientRoutes, ...wslClientRoutes, ...wsgClientRoutes, ...wsiClientRoutes, ...wsjClientRoutes, ...wshClientRoutes, { path: '/admin/email', element: <ClientEmailSetup /> }, { path: '/admin/groups', element: <GroupsScreen /> }, { path: '/people', element: <Navigate to="/people/departments" replace /> }, { path: '/people/departments', element: <UsersDepartments tab="departments" /> }, { path: '/people/users', element: <UsersDepartments tab="users" /> }, { path: '/users', element: <Navigate to="/people/users" replace /> }, { path: '/governance', element: <Governance /> }, { path: '/attestation', element: <AttestationTracker /> }, { path: '/my-attestation', element: <MyAttestation /> }, { path: '/inventory', element: <ListPreset preset={{ type: 'inventory', all: '1' }} /> }, { path: '/inventory/new', element: <UseCaseForm /> }, { path: '/inventory/:useCaseId', element: <UseCaseForm /> }, { path: '/systems', element: <ListPreset preset={{ audit: 'yes' }} /> }, { path: '/systems/:systemId', element: <SystemPrefill /> }, { path: '/documents', element: <DocumentUploads /> }, { path: '/review', element: <InventoryReview /> }, { path: '/report', element: <ClientReport /> }, { path: '/responses', element: <ManagementResponse /> }, { path: '/remediation', element: <Remediation /> },
export const clientRoutes: RouteObject[] = [...r5ClientRoutes, ...r7ClientRoutes, ...clientHomeRoutes, ...wskClientRoutes, ...wslClientRoutes, ...wsgClientRoutes, ...wsiClientRoutes, ...wsjClientRoutes, ...wshClientRoutes, { path: '/admin/email', element: <ClientEmailSetup /> }, { path: '/admin/groups', element: <GroupsScreen /> }, { path: '/people', element: <Navigate to="/people/departments" replace /> }, { path: '/people/departments', element: <UsersDepartments tab="departments" /> }, { path: '/people/users', element: <UsersDepartments tab="users" /> }, { path: '/users', element: <Navigate to="/people/users" replace /> }, { path: '/governance', element: <Governance /> }, { path: '/attestation', element: <AttestationTracker /> }, { path: '/my-attestation', element: <MyAttestation /> }, { path: '/inventory', element: <ListPreset preset={{ type: 'inventory', all: '1' }} /> }, { path: '/inventory/new', element: <UseCaseForm /> }, { path: '/inventory/:useCaseId', element: <UseCaseForm /> }, { path: '/systems', element: <ListPreset preset={{ audit: 'yes' }} /> }, { path: '/systems/:systemId', element: <SystemPrefill /> }, { path: '/documents', element: <DocumentUploads /> }, { path: '/review', element: <InventoryReview /> }, { path: '/report', element: <ClientReport /> }, { path: '/responses', element: <ManagementResponse /> }, { path: '/remediation', element: <Remediation /> },
  // AI system register (spec §24, §27.2)
  { path: '/register', element: <RegisterGrid /> }, { path: '/register/new', element: <RegisterNew /> },
  { path: '/register/:systemId', element: <RegisterSystemPage tab="details" /> }, { path: '/register/:systemId/roles', element: <RegisterSystemPage tab="roles" /> },
  { path: '/register/:systemId/history', element: <RegisterSystemPage tab="history" /> }, { path: '/register/:systemId/tracing', element: <RegisterSystemPage tab="tracing" /> },
  { path: '/register/:systemId/agent', element: <RegisterSystemPage tab="agent" /> },
  { path: '/register/:systemId/evidence', element: <RegisterSystemPage tab="evidence" /> }, { path: '/register/:systemId/changes', element: <RegisterSystemPage tab="changes" /> },
  // tracing add-on (spec §27.3): R8 requests and the Executive Sponsor's approval
  { path: '/addons', element: <AddonsPage /> },
  { path: '/governance/roles', element: <CompanyRoles /> }];
export const publicRoutes: RouteObject[] = [...r3PublicRoutes, ...r4PublicRoutes, ...wsiPublicRoutes, ...wsjPublicRoutes, { path: '/m/s/:token', element: <LinkLanding shared /> }, { path: '/m/:token', element: <LinkLanding /> }, { path: '/mail/test-consent', element: <TestConsent /> }, { path: '/mail/consent-result', element: <ConsentResult /> }, { path: '/welcome/mailbox', element: <MailboxPrompt /> }, { path: '/attest/:token', element: <PhoneAttestation /> }, { path: '/confirm/:token', element: <NamedUserConfirm /> }];
/** Screens in both portals (spec §26.10: E4 and E5 are in the client and the Futran shell). */
export const sharedRoutes: RouteObject[] = [{ path: '/send', element: <SendToGroups /> }, { path: '/admin/log', element: <EmailLog /> }];
