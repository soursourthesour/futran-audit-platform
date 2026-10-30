import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import { primaryRole, useMe, useSignOut, type Me } from '@/api/auth';
import { CLIENT_NAV, FUTRAN_NAV, activeNav, homePath, navFor, type NavEntry } from '@/nav';
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
      <span>{me.user.name} · {primaryRole(me)}</span>
      <button type="button" onClick={() => signOut(me.organization.type === 'futran')}>Sign out</button>
    </div>
  );
}

/** The header of both shells. Under 600 px the navigation and the user menu fold behind a Menu button (44 px, with
 *  aria-expanded) that closes on navigation and on Escape; focus is never trapped. */
function ShellHeader({ me, entries, client }: { me: Me; entries: NavEntry[]; client?: boolean }) {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const btn = useRef<HTMLButtonElement>(null);
  const mine = navFor(me, entries);
  const current = activeNav(loc.pathname, mine);
  useEffect(() => setOpen(false), [loc.pathname, loc.search]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); btn.current?.focus(); } };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);
  return (
    <header className={`shell-header${client ? ' client-header' : ''}`}>
      <Link to={homePath(me)} className="brand">
        <img className="brand-logo" src={client ? logo : logoWhite} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span>
        {client && <span className="brand-org muted small">{me.organization.name}</span>}
      </Link>
      <div className="shell-bell"><NotificationBell /></div>
      <button ref={btn} type="button" className="shell-menu-btn" aria-expanded={open} aria-controls="shell-menu" aria-label="Menu" onClick={() => setOpen((o) => !o)}>
        <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d={open ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" /></svg>
      </button>
      <div id="shell-menu" className="shell-menu" data-open={open ? 'true' : 'false'}>
        {client && <div className="shell-menu-org small">{me.organization.name}</div>}
        <nav className="shell-nav" aria-label="Main" onClick={(e) => { if ((e.target as HTMLElement).closest('a')) setOpen(false); }}>
          {mine.map((n) => <Link key={n.to} to={n.to} className={n.to === current ? 'active' : undefined} aria-current={n.to === current ? 'page' : undefined}>{n.label}</Link>)}
        </nav>
        <UserMenu me={me} />
      </div>
    </header>
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
      <ShellHeader me={me} entries={FUTRAN_NAV} />
      <main><MailboxGate /><Outlet /></main>
    </>
  );
}

export function ClientShell() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <TestModeBar me={me} />
      <ShellHeader me={me} entries={CLIENT_NAV} client />
      <main><MailboxGate /><Outlet /></main>
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
