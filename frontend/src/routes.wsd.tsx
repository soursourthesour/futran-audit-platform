import type { RouteObject } from 'react-router-dom';
import { RefreshReview } from '@/screens/reg/RefreshReview';
import { RefreshAlerts } from '@/screens/staff/RefreshAlerts';
import { Litigation } from '@/screens/litigation/Litigation';
import { CaseRecord } from '@/screens/litigation/CaseRecord';
import { Opportunities } from '@/screens/sales/Opportunities';
import { ClientAlerts } from '@/screens/alerts/ClientAlerts';

/** v0.6 WS-D screens (Futran shell): M3, M6, L1, L2, S1, A1. */
export const wsdRoutes: RouteObject[] = [
  { path: '/reg/refresh', element: <RefreshReview /> },
  { path: '/staff/alerts', element: <RefreshAlerts /> },
  { path: '/litigation', element: <Litigation /> },
  { path: '/litigation/:caseId', element: <CaseRecord /> },
  { path: '/opportunities', element: <Opportunities /> },
  { path: '/alerts', element: <ClientAlerts /> },
];
