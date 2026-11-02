import type { RouteObject } from 'react-router-dom';
import { BiasTest } from '@/screens/wsk/BiasTest';
import { HeatMap } from '@/screens/wsk/HeatMap';
import { Insights } from '@/screens/wsk/Insights';
import { ClientCarried, FutranCarried } from '@/screens/wsk/Carried';
import { BiasData } from '@/screens/wsk/Links';

/** Wave 3 WS-K: bias test calculator (29), heat map and lineage (35), benchmarking (34), annual review carry-forward (F16). */
export const wskFutranRoutes: RouteObject[] = [
  { path: '/systems/:systemId/bias-test', element: <BiasTest /> },
  { path: '/clients/:clientId/heatmap', element: <HeatMap /> },
  { path: '/insights', element: <Insights /> },
  { path: '/engagements/:engagementId/carried', element: <FutranCarried /> },
];
export const wskClientRoutes: RouteObject[] = [
  { path: '/carried', element: <ClientCarried /> },
  { path: '/bias-data', element: <BiasData /> },
];
