import type { RouteObject } from 'react-router-dom';
import { CatalogSlotTab } from '@/screens/catalog/CatalogShell';
import { PriceList } from '@/screens/catalog/PriceList';
import { Packages } from '@/screens/catalog/Packages';
import { Estimator } from '@/screens/catalog/Estimator';

/** Release 2 R1: master price list (SM-14) with its tabs, and the Estimator (SM-15). The mapping rules, question bank
 *  and proposal templates tabs are filled by R3 and R4 through `catalog-tab-*.tsx` files (see CatalogShell.tsx). */
export const r1FutranRoutes: RouteObject[] = [
  { path: '/staff/admin/catalog', element: <PriceList /> },
  { path: '/staff/admin/catalog/packages', element: <Packages /> },
  { path: '/staff/admin/catalog/rules', element: <CatalogSlotTab tab="rules" /> },
  { path: '/staff/admin/catalog/questions', element: <CatalogSlotTab tab="questions" /> },
  { path: '/staff/admin/catalog/proposal-templates', element: <CatalogSlotTab tab="proposal-templates" /> },
  { path: '/sales/estimate', element: <Estimator /> },
];
