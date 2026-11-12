import type { RouteObject } from 'react-router-dom';
import { AdminHome, ChiefHome, MyWork, QAQueue } from '@/screens/homes/FutranHomes';
import { ClientAdminHome, DPOHome, DepartmentHome, MyTasks, SponsorHome } from '@/screens/homes/ClientHomes';

/** v0.6.1 WS-F role homes (spec §13.1). The CAICO's Getting started (/start) is registered in routes.tsx. Since the 10 Nov
 *  feedback (F2) every Futran home shows the Dashboard and /audits redirects to the person's home. */
export const futranHomeRoutes: RouteObject[] = [
  { path: '/staff/chief', element: <ChiefHome /> },
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
