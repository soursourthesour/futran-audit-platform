import type { RouteObject } from 'react-router-dom';
import { ScopingCall } from '@/screens/scoping/ScopingCall';
import { ReviewAnswers } from '@/screens/scoping/ReviewAnswers';
import { ClientQuestionnaire } from '@/screens/scoping/ClientQuestionnaire';
import { QuestionBankPage } from '@/screens/scoping/QuestionBankTab';
import { MappingRulesPage } from '@/screens/scoping/MappingRulesTab';

/** Release 2 R3: SM-05 and SM-08 (Futran shell), the SM-14 question bank and mapping rules tabs (R1 owns the tab shell
 *  at /staff/admin/catalog and can render QuestionBankTab and MappingRulesTab inside it), and SM-07 (public, no login). */
export const r3FutranRoutes: RouteObject[] = [
  { path: '/sales/opportunities/:id/scoping', element: <ScopingCall /> },
  { path: '/sales/opportunities/:id/scoping/review', element: <ReviewAnswers /> },
  { path: '/staff/admin/catalog/questions', element: <QuestionBankPage /> },
  { path: '/staff/admin/catalog/rules', element: <MappingRulesPage /> },
];

export const r3PublicRoutes: RouteObject[] = [{ path: '/q/:token', element: <ClientQuestionnaire /> }];
