import type { RouteObject } from 'react-router-dom';
import { DiscoveryImport } from '@/screens/discovery/DiscoveryImport';

/** Release 2 R6a: G-05 discovery import, G-06 service templates, G-09 agent assurance. */
export const r6aFutranRoutes: RouteObject[] = [
  { path: '/e/:engagementId/discovery/import', element: <DiscoveryImport /> },
];
export const r6aClientRoutes: RouteObject[] = [
  { path: '/integrations/import', element: <DiscoveryImport /> },
];
