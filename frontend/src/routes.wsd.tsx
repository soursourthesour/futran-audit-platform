import type { RouteObject } from 'react-router-dom';
import { RefreshReview } from '@/screens/reg/RefreshReview';
import { RefreshAlerts } from '@/screens/staff/RefreshAlerts';
import { Litigation } from '@/screens/litigation/Litigation';
import { CaseRecord } from '@/screens/litigation/CaseRecord';
import { ClientAlerts } from '@/screens/alerts/ClientAlerts';

/** v0.6 WS-D screens (Futran shell): M3, M6, L1, L2, A1. S1 opportunities moved to Release 2 R2 (routes.r2, /opportunities redirects). */
export const wsdRoutes: RouteObject[] = [
  { path: '/reg/refresh', element: <RefreshReview /> },
  { path: '/staff/alerts', element: <RefreshAlerts /> },
  { path: '/litigation', element: <Litigation /> },
  { path: '/litigation/:caseId', element: <CaseRecord /> },
  { path: '/alerts', element: <ClientAlerts /> },
];
