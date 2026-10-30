import { Navigate, type RouteObject } from 'react-router-dom';
import { UsersAdmin } from '@/screens/admin/Users';
import { AuditLogScreen } from '@/screens/admin/AuditLog';
import { OutboxScreen } from '@/screens/admin/Outbox';
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
import { FutranInventory, Inventory } from '@/screens/client/Inventory';
import { UseCaseForm } from '@/screens/client/UseCaseForm';
import { NamedUserConfirm } from '@/screens/phone/NamedUserConfirm';
import { SystemsRegister } from '@/screens/futran/SystemsRegister';
import { SystemAssessment } from '@/screens/futran/SystemAssessment';
import { SystemPrefill, SystemsPrefillList } from '@/screens/client/SystemPrefill';
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
import { RegisterGrid } from '@/screens/register/RegisterGrid';
import { RegisterNew, RegisterSystemPage } from '@/screens/register/RegisterSystem';
import { CompanyRoles } from '@/screens/register/CompanyRoles';
import { LawLibrary } from '@/screens/futran/reg/LawLibrary';
import { LawRecord } from '@/screens/futran/reg/LawRecord';
import { LawEdit } from '@/screens/futran/reg/LawEdit';
import { RoleCatalogue } from '@/screens/futran/reg/RoleCatalogue';
import { Applicability } from '@/screens/futran/reg/Applicability';
import { wsdRoutes } from '@/routes.wsd';
import { FutranEmail } from '@/screens/email/FutranEmail';
import { ClientEmailSetup } from '@/screens/email/ClientEmailSetup';
import { ClientGroupsForFutran, GroupsScreen } from '@/screens/email/Groups';
import { SendToGroups } from '@/screens/email/SendToGroups';
import { EmailLog } from '@/screens/email/EmailLog';
import { LinkLanding } from '@/screens/email/LinkLanding';
import { ConsentResult, TestConsent } from '@/screens/email/Consent';
import { MailboxPrompt } from '@/screens/email/MailboxPrompt';

/** Screens added by later tasks register here, so routes.tsx stays stable. */
export const futranRoutes: RouteObject[] = [
  ...wsdRoutes,
  { path: '/admin/users', element: <UsersAdmin /> },
  { path: '/staff/admin/email', element: <FutranEmail /> },
  { path: '/clients/:clientId/groups', element: <ClientGroupsForFutran /> },
  { path: '/admin/audit-log', element: <AuditLogScreen /> },
  { path: '/admin/outbox', element: <OutboxScreen /> },
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
export const clientRoutes: RouteObject[] = [{ path: '/admin/email', element: <ClientEmailSetup /> }, { path: '/admin/groups', element: <GroupsScreen /> }, { path: '/people', element: <Navigate to="/people/departments" replace /> }, { path: '/people/departments', element: <UsersDepartments tab="departments" /> }, { path: '/people/users', element: <UsersDepartments tab="users" /> }, { path: '/users', element: <Navigate to="/people/users" replace /> }, { path: '/governance', element: <Governance /> }, { path: '/attestation', element: <AttestationTracker /> }, { path: '/my-attestation', element: <MyAttestation /> }, { path: '/inventory', element: <Inventory /> }, { path: '/inventory/new', element: <UseCaseForm /> }, { path: '/inventory/:useCaseId', element: <UseCaseForm /> }, { path: '/systems', element: <SystemsPrefillList /> }, { path: '/systems/:systemId', element: <SystemPrefill /> }, { path: '/documents', element: <DocumentUploads /> }, { path: '/review', element: <InventoryReview /> }, { path: '/report', element: <ClientReport /> }, { path: '/responses', element: <ManagementResponse /> }, { path: '/remediation', element: <Remediation /> },
  // AI system register (spec §24, §27.2)
  { path: '/register', element: <RegisterGrid /> }, { path: '/register/new', element: <RegisterNew /> },
  { path: '/register/:systemId', element: <RegisterSystemPage tab="details" /> }, { path: '/register/:systemId/roles', element: <RegisterSystemPage tab="roles" /> },
  { path: '/register/:systemId/history', element: <RegisterSystemPage tab="history" /> }, { path: '/register/:systemId/tracing', element: <RegisterSystemPage tab="tracing" /> },
  { path: '/register/:systemId/evidence', element: <RegisterSystemPage tab="evidence" /> }, { path: '/register/:systemId/changes', element: <RegisterSystemPage tab="changes" /> },
  { path: '/governance/roles', element: <CompanyRoles /> }];
export const publicRoutes: RouteObject[] = [{ path: '/m/s/:token', element: <LinkLanding shared /> }, { path: '/m/:token', element: <LinkLanding /> }, { path: '/mail/test-consent', element: <TestConsent /> }, { path: '/mail/consent-result', element: <ConsentResult /> }, { path: '/welcome/mailbox', element: <MailboxPrompt /> }, { path: '/attest/:token', element: <PhoneAttestation /> }, { path: '/confirm/:token', element: <NamedUserConfirm /> }];
/** Screens in both portals (spec §26.10: E4 and E5 are in the client and the Futran shell). */
export const sharedRoutes: RouteObject[] = [{ path: '/send', element: <SendToGroups /> }, { path: '/admin/log', element: <EmailLog /> }];
