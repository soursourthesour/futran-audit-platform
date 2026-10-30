import type { ReactNode } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';
import { primaryRole, useMe, useSignOut, type Me } from '@/api/auth';
import { CLIENT_NAV, FUTRAN_NAV, homePath, navFor } from '@/nav';
import { Loading } from '@/components/ui';
import { NotificationBell } from '@/components/NotificationBell';
import logo from '@/assets/futran-logo.svg';
import logoWhite from '@/assets/futran-logo-white.svg';
import { MailboxGate } from '@/screens/email/MailboxPrompt';

export function TestModeBar({ me }: { me?: Pick<Me, 'test_mode' | 'mfa_required' | 'email_mode'> | null }) {
  if (!me?.test_mode) return null;
  const parts: string[] = [];
  if (!me.mfa_required) parts.push('sign-in codes are switched off');
  if (me.email_mode === 'outbox') parts.push('emails go to the outbox');
  const text = parts.length ? `Test mode — ${parts.join(' and ')}. Do not enter client data.` : 'Test mode. Do not enter client data.';
  return <div className="test-mode-bar" data-testid="test-mode-bar" role="note">{text}</div>;
}

function UserMenu({ me }: { me: Me }) {
  const signOut = useSignOut();
  return (
    <div className="shell-user">
      <NotificationBell />
      <span>{me.user.name} · {primaryRole(me)}</span>
      <button type="button" onClick={() => signOut(me.organization.type === 'futran')}>Sign out</button>
    </div>
  );
}

export function RequireAuth({ children, side }: { children: ReactNode; side?: 'futran' | 'client' }) {
  const { data: me, isLoading } = useMe();
  const loc = useLocation();
  if (isLoading) return <Loading />;
  if (!me) return <Navigate to={`${side === 'futran' ? '/staff/login' : '/login'}?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (side && me.organization.type !== side) return <Navigate to={homePath(me)} replace />;
  if (me.terms_required) return <Navigate to="/welcome/terms" replace />;
  if (me.notice_required) return <Navigate to="/welcome/notice" replace />;
  return <>{children}</>;
}

export function FutranShell() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <TestModeBar me={me} />
      <header className="shell-header">
        <Link to={homePath(me)} className="brand"><img className="brand-logo" src={logoWhite} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span></Link>
        <nav className="shell-nav" aria-label="Main">
          {navFor(me, FUTRAN_NAV).map((n) => <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>)}
        </nav>
        <UserMenu me={me} />
      </header>
      <MailboxGate />
      <main><Outlet /></main>
    </>
  );
}

export function ClientShell() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <TestModeBar me={me} />
      <header className="shell-header client-header">
        <Link to={homePath(me)} className="brand"><img className="brand-logo" src={logo} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span><span className="muted small">· {me.organization.name}</span></Link>
        <nav className="shell-nav" aria-label="Main">
          {navFor(me, CLIENT_NAV).map((n) => <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>)}
        </nav>
        <UserMenu me={me} />
      </header>
      <MailboxGate />
      <main><Outlet /></main>
    </>
  );
}

/** For screens in both portals: the shell of the signed-in person's own side. */
export function EitherShell() {
  const { data: me } = useMe();
  if (!me) return null;
  return me.organization.type === 'futran' ? <FutranShell /> : <ClientShell />;
}

export function PhoneShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <header className="shell-header" style={{ minHeight: 56 }}>
        <span className="brand"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">{title}</span></span>
      </header>
      <main className="phone-shell">{children}</main>
    </div>
  );
}
