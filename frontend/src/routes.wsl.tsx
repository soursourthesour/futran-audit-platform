import type { RouteObject } from 'react-router-dom';
import { ApiAdmin } from '@/screens/wsl/ApiAdmin';
import { ApiReference } from '@/screens/wsl/ApiReference';
import { AgentOversight } from '@/screens/wsl/AgentOversight';
import { PlatformTrust } from '@/screens/wsl/PlatformTrust';

/** Wave 3 WS-L: public API and webhooks (F17), agent oversight (F14), platform trust (F19). Comments (F18) sit inside
 *  existing screens; the register system's Agent tab is in routes.extra.tsx with the other register tabs. */
export const wslFutranRoutes: RouteObject[] = [
  { path: '/clients/:clientId/agents', element: <AgentOversight /> },
  { path: '/staff/admin/trust', element: <PlatformTrust /> },
];
export const wslClientRoutes: RouteObject[] = [
  { path: '/admin/api', element: <ApiAdmin /> },
  { path: '/admin/api/reference', element: <ApiReference /> },
];
