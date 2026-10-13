import { createBrowserRouter, Navigate } from 'react-router-dom';
import { ClientShell, FutranShell, RequireAuth } from '@/shells/Shells';
import { Login } from '@/screens/auth/Login';
import { MfaSetup, MfaVerify } from '@/screens/auth/Mfa';
import { AcceptInvite } from '@/screens/auth/AcceptInvite';
import { Dashboard } from '@/screens/futran/Dashboard';
import { InitiationChecklist } from '@/screens/client/InitiationChecklist';
import { useMe } from '@/api/auth';
import { Loading } from '@/components/ui';
import { homeFor } from '@/screens/auth/Login';
import { futranRoutes, clientRoutes, publicRoutes } from '@/routes.extra';

function Home() {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <Loading />;
  return <Navigate to={homeFor(me)} replace />;
}

export const router = createBrowserRouter([
  { path: '/', element: <Home /> },
  { path: '/login', element: <Login /> },
  { path: '/mfa', element: <MfaVerify /> },
  { path: '/mfa/setup', element: <MfaSetup /> },
  { path: '/invite', element: <AcceptInvite /> },
  { path: '/invite/:token', element: <AcceptInvite /> },
  ...publicRoutes,
  {
    element: <RequireAuth side="futran"><FutranShell /></RequireAuth>,
    children: [{ path: '/audits', element: <Dashboard /> }, ...futranRoutes],
  },
  {
    element: <RequireAuth side="client"><ClientShell /></RequireAuth>,
    children: [{ path: '/start', element: <InitiationChecklist /> }, ...clientRoutes],
  },
  { path: '*', element: <Home /> },
]);
