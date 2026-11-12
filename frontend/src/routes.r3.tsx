import type { RouteObject } from 'react-router-dom';
import { ScopingCall } from '@/screens/scoping/ScopingCall';
import { ReviewAnswers } from '@/screens/scoping/ReviewAnswers';
import { ClientQuestionnaire } from '@/screens/scoping/ClientQuestionnaire';

/** Release 2 R3: SM-05 and SM-08 (Futran shell) and SM-07 (public, no login). The SM-14 Mapping rules and Question bank
 *  tabs are screens/scoping/catalog-tab-rules.tsx and catalog-tab-questions.tsx, which R1's CatalogShell mounts. */
export const r3FutranRoutes: RouteObject[] = [
  { path: '/sales/opportunities/:id/scoping', element: <ScopingCall /> },
  { path: '/sales/opportunities/:id/scoping/review', element: <ReviewAnswers /> },
];

export const r3PublicRoutes: RouteObject[] = [{ path: '/q/:token', element: <ClientQuestionnaire /> }];
