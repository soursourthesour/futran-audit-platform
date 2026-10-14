import type { RouteObject } from 'react-router-dom';
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
import { FutranInventory, Inventory } from '@/screens/client/Inventory';
import { UseCaseForm } from '@/screens/client/UseCaseForm';
import { NamedUserConfirm } from '@/screens/phone/NamedUserConfirm';
import { SystemsRegister } from '@/screens/futran/SystemsRegister';

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
];
export const clientRoutes: RouteObject[] = [{ path: '/users', element: <UsersDepartments /> }, { path: '/governance', element: <Governance /> }, { path: '/attestation', element: <AttestationTracker /> }, { path: '/inventory', element: <Inventory /> }, { path: '/inventory/new', element: <UseCaseForm /> }, { path: '/inventory/:useCaseId', element: <UseCaseForm /> }];
export const publicRoutes: RouteObject[] = [{ path: '/attest/:token', element: <PhoneAttestation /> }, { path: '/confirm/:token', element: <NamedUserConfirm /> }];
