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

/** Screens added by later tasks register here, so routes.tsx stays stable. */
export const futranRoutes: RouteObject[] = [
  { path: '/admin/users', element: <UsersAdmin /> },
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
];
export const clientRoutes: RouteObject[] = [{ path: '/people', element: <Navigate to="/people/departments" replace /> }, { path: '/people/departments', element: <UsersDepartments tab="departments" /> }, { path: '/people/users', element: <UsersDepartments tab="users" /> }, { path: '/users', element: <Navigate to="/people/users" replace /> }, { path: '/governance', element: <Governance /> }, { path: '/attestation', element: <AttestationTracker /> }, { path: '/my-attestation', element: <MyAttestation /> }, { path: '/inventory', element: <Inventory /> }, { path: '/inventory/new', element: <UseCaseForm /> }, { path: '/inventory/:useCaseId', element: <UseCaseForm /> }, { path: '/systems', element: <SystemsPrefillList /> }, { path: '/systems/:systemId', element: <SystemPrefill /> }, { path: '/documents', element: <DocumentUploads /> }, { path: '/review', element: <InventoryReview /> }, { path: '/report', element: <ClientReport /> }, { path: '/responses', element: <ManagementResponse /> }, { path: '/remediation', element: <Remediation /> }];
export const publicRoutes: RouteObject[] = [{ path: '/attest/:token', element: <PhoneAttestation /> }, { path: '/confirm/:token', element: <NamedUserConfirm /> }];
