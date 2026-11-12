import type { RouteObject } from 'react-router-dom';
import { SalesHome } from '@/screens/sales/SalesHome';
import { OpportunitiesRedirect, SalesOpportunities } from '@/screens/sales/SalesOpportunities';
import { OpportunityRecord } from '@/screens/sales/OpportunityRecord';

/** Release 2 R2 sales desk (Futran shell): SM-01 Sales home, SM-02 Opportunities (list and board; SM-03 Log opportunity
 *  opens over it with ?log=1), SM-04 Opportunity record. The v0.6 /opportunities address redirects here, keeping filters. */
export const r2FutranRoutes: RouteObject[] = [
  { path: '/sales', element: <SalesHome /> },
  { path: '/sales/opportunities', element: <SalesOpportunities /> },
  { path: '/sales/opportunities/:id', element: <OpportunityRecord /> },
  { path: '/opportunities', element: <OpportunitiesRedirect /> },
];
