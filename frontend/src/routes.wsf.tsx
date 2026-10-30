import type { RouteObject } from 'react-router-dom';
import { AdminHome, MyWork, QAQueue } from '@/screens/homes/FutranHomes';
import { ClientAdminHome, DPOHome, DepartmentHome, MyTasks, SponsorHome } from '@/screens/homes/ClientHomes';

/** v0.6.1 WS-F role homes (spec §13.1). The Chief Auditor's Dashboard (/audits) and the CAICO's Getting started (/start)
 *  are unchanged and registered in routes.tsx. */
export const futranHomeRoutes: RouteObject[] = [
  { path: '/staff/admin', element: <AdminHome /> },
  { path: '/my-work', element: <MyWork /> },
  { path: '/qa', element: <QAQueue /> },
];
export const clientHomeRoutes: RouteObject[] = [
  { path: '/admin/home', element: <ClientAdminHome /> },
  { path: '/summary', element: <SponsorHome /> },
  { path: '/data-review', element: <DPOHome /> },
  { path: '/my-department', element: <DepartmentHome /> },
  { path: '/my-tasks', element: <MyTasks /> },
];
