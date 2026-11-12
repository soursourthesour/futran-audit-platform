import type { RouteObject } from 'react-router-dom';
import { DiscoveryImport } from '@/screens/discovery/DiscoveryImport';
import { FutranAssurancePage } from '@/screens/assurance/Assurance';
import { RegisterSystemPage } from '@/screens/register/RegisterSystem';
import { ServiceTemplates } from '@/screens/admin/ServiceTemplates';

/** Release 2 R6a: G-05 discovery import, G-06 service templates, G-09 agent assurance. */
export const r6aFutranRoutes: RouteObject[] = [
  { path: '/e/:engagementId/discovery/import', element: <DiscoveryImport /> },
  { path: '/clients/:clientId/register/:systemId/assurance', element: <FutranAssurancePage /> },
  { path: '/staff/admin/service-templates', element: <ServiceTemplates /> },
];
export const r6aClientRoutes: RouteObject[] = [
  { path: '/integrations/import', element: <DiscoveryImport /> },
  { path: '/register/:systemId/assurance', element: <RegisterSystemPage tab="assurance" /> },
];
