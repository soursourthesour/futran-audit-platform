import type { RouteObject } from 'react-router-dom';
import { Integrations } from '@/screens/discovery/Integrations';
import { Monitoring } from '@/screens/discovery/Monitoring';
import { ConnectorTestConsent } from '@/screens/discovery/TestConsent';

/** Wave 3 WS-J: integrations and AI discovery (screen 30) and continuous monitoring (screen 31). */
export const wsjFutranRoutes: RouteObject[] = [
  { path: '/clients/:clientId/integrations', element: <Integrations /> },
  { path: '/clients/:clientId/monitoring', element: <Monitoring /> },
];
export const wsjClientRoutes: RouteObject[] = [
  { path: '/integrations', element: <Integrations /> },
  { path: '/monitoring', element: <Monitoring /> },
];
export const wsjPublicRoutes: RouteObject[] = [{ path: '/integrations/test-consent', element: <ConnectorTestConsent /> }];
