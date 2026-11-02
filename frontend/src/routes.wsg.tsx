import type { RouteObject } from 'react-router-dom';
import { AILog } from '@/screens/ai/AILog';
import { ObligationQueue } from '@/screens/ai/Obligations';
import { QuestionnaireDetail, Questionnaires } from '@/screens/ai/Questionnaires';

/** Wave 3 WS-G: AI copilot log (screen 25), obligation review (F5), customer questionnaires (F10). */
export const wsgFutranRoutes: RouteObject[] = [
  { path: '/engagements/:engagementId/ai-log', element: <AILog /> },
  { path: '/reg/obligations', element: <ObligationQueue /> },
];
export const wsgClientRoutes: RouteObject[] = [
  { path: '/questionnaires', element: <Questionnaires /> },
  { path: '/questionnaires/:questionnaireId', element: <QuestionnaireDetail /> },
];
