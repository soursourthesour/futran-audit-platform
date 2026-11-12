import type { RouteObject } from 'react-router-dom';
import { Handoff } from '@/screens/commercial/Handoff';
import { Plan } from '@/screens/commercial/Plan';
import { EngagementCommercial } from '@/screens/commercial/EngagementCommercial';
import { TimeAndHours } from '@/screens/commercial/Time';
import { BillingExports } from '@/screens/commercial/BillingExports';
import { ClientChangeOrders } from '@/screens/commercial/ClientChangeOrders';

/** Release 2 R5: SM-13 handoff, G-01 plan and usage, G-02 engagement commercials, G-03 time and hours. */
export const r5FutranRoutes: RouteObject[] = [
  { path: '/sales/opportunities/:oppId/handoff', element: <Handoff /> },
  { path: '/staff/clients/:clientId/plan', element: <Plan /> },
  { path: '/e/:engagementId/commercial', element: <EngagementCommercial /> },
  { path: '/staff/time', element: <TimeAndHours /> },
  { path: '/staff/billing', element: <BillingExports /> },
];
export const r5ClientRoutes: RouteObject[] = [{ path: '/change-orders', element: <ClientChangeOrders /> }];
