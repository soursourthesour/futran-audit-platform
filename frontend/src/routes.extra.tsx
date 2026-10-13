import type { RouteObject } from 'react-router-dom';
import { UsersAdmin } from '@/screens/admin/Users';
import { AuditLogScreen } from '@/screens/admin/AuditLog';
import { OutboxScreen } from '@/screens/admin/Outbox';
import { SettingsScreen } from '@/screens/admin/Settings';
import { ReferenceData } from '@/screens/admin/ReferenceData';

/** Screens added by later tasks register here, so routes.tsx stays stable. */
export const futranRoutes: RouteObject[] = [
  { path: '/admin/users', element: <UsersAdmin /> },
  { path: '/admin/audit-log', element: <AuditLogScreen /> },
  { path: '/admin/outbox', element: <OutboxScreen /> },
  { path: '/admin/settings', element: <SettingsScreen /> },
  { path: '/admin/reference', element: <ReferenceData /> },
];
export const clientRoutes: RouteObject[] = [];
export const publicRoutes: RouteObject[] = [];
