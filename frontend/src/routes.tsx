import { createBrowserRouter, Navigate } from 'react-router-dom';
import { ClientShell, EitherShell, FutranShell, RequireAuth } from '@/shells/Shells';
import { Login, StaffLogin } from '@/screens/auth/Login';
import { Terms } from '@/screens/auth/Terms';
import { NoticeAcknowledge } from '@/screens/auth/NoticeAcknowledge';
import { MfaSetup, MfaVerify } from '@/screens/auth/Mfa';
import { AcceptInvite } from '@/screens/auth/AcceptInvite';
import { Dashboard } from '@/screens/futran/Dashboard';
import { ClientsList } from '@/screens/futran/ClientsList';
import { InitiationChecklist } from '@/screens/client/InitiationChecklist';
import { useMe } from '@/api/auth';
import { Loading } from '@/components/ui';
import { homeFor } from '@/screens/auth/Login';
import { futranRoutes, clientRoutes, publicRoutes, sharedRoutes } from '@/routes.extra';

function Home() {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <Loading />;
  return <Navigate to={homeFor(me)} replace />;
}

export const router = createBrowserRouter([
  { path: '/', element: <Home /> },
  { path: '/login', element: <Login /> },
  { path: '/staff/login', element: <StaffLogin /> },
  { path: '/welcome/terms', element: <Terms /> },
  { path: '/welcome/notice', element: <NoticeAcknowledge /> },
  { path: '/mfa', element: <MfaVerify /> },
  { path: '/mfa/setup', element: <MfaSetup /> },
  { path: '/invite', element: <AcceptInvite /> },
  { path: '/invite/:token', element: <AcceptInvite /> },
  ...publicRoutes,
  {
    element: <RequireAuth side="futran"><FutranShell /></RequireAuth>,
    children: [{ path: '/audits', element: <Dashboard /> }, { path: '/clients', element: <ClientsList /> }, ...futranRoutes],
  },
  {
    element: <RequireAuth side="client"><ClientShell /></RequireAuth>,
    children: [{ path: '/start', element: <InitiationChecklist /> }, ...clientRoutes],
  },
  {
    element: <RequireAuth><EitherShell /></RequireAuth>,
    children: sharedRoutes,
  },
  { path: '*', element: <Home /> },
]);
