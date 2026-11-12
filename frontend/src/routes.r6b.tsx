import type { RouteObject } from 'react-router-dom';
import { ClientCopilotScreen, CopilotReadinessScreen } from '@/screens/r6b/CopilotReadiness';
import { EuAiActClientScreen, EuAiActEngagementScreen } from '@/screens/r6b/EuAiAct';

/** Release 2 R6b: G-07 Copilot readiness (spec screen `/e/:id/copilot`, client view `/copilot`) and G-08 EU AI Act
 *  conformity (`/e/:id/eu-ai-act`, and `/clients/:id/eu-ai-act` for systems with EU geography outside such an engagement). */
export const r6bFutranRoutes: RouteObject[] = [
  { path: '/e/:engagementId/copilot', element: <CopilotReadinessScreen /> },
  { path: '/e/:engagementId/eu-ai-act', element: <EuAiActEngagementScreen /> },
  { path: '/clients/:clientId/eu-ai-act', element: <EuAiActClientScreen /> },
];
export const r6bClientRoutes: RouteObject[] = [
  { path: '/copilot', element: <ClientCopilotScreen /> },
];
