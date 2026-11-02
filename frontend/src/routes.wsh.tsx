import type { RouteObject } from 'react-router-dom';
import { RegUpdates } from '@/screens/regupdates/RegUpdates';
import { ClientUpdates } from '@/screens/regupdates/ClientUpdates';
import { ProjectNew, ProjectPage, ProjectsList } from '@/screens/projects/Projects';

/** Wave 3 WS-H: regulatory change alerts (screen 26, Futran and client) and new AI projects (screen 28, client). */
export const wshFutranRoutes: RouteObject[] = [{ path: '/reg/updates', element: <RegUpdates /> }];
export const wshClientRoutes: RouteObject[] = [
  { path: '/updates', element: <ClientUpdates /> },
  { path: '/projects', element: <ProjectsList /> },
  { path: '/projects/new', element: <ProjectNew /> },
  { path: '/projects/:projectId', element: <ProjectPage /> },
];
