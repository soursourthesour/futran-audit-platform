import type { RouteObject } from 'react-router-dom';
import { ClientEntities } from '@/screens/r7/ClientEntities';
import { MyGroup } from '@/screens/r7/MyGroup';
import { Vault } from '@/screens/r7/Vault';
import { Partners } from '@/screens/r7/Partners';

/** Release 2 R7: G-04 client hierarchy, G-10 evidence vault and retention, G-11 partners and referrals. */
export const r7FutranRoutes: RouteObject[] = [
  { path: '/staff/clients/:clientId/entities', element: <ClientEntities /> },
  { path: '/staff/clients/:clientId/vault', element: <Vault /> },
  { path: '/staff/partners', element: <Partners /> },
];
export const r7ClientRoutes: RouteObject[] = [{ path: '/group', element: <MyGroup /> }];
