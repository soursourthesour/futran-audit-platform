import type { ReactNode } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';
import { hasRole, primaryRole, useMe, useSignOut, type Me } from '@/api/auth';
import { Loading } from '@/components/ui';
import { NotificationBell } from '@/components/NotificationBell';
import logo from '@/assets/futran-logo.svg';
import logoWhite from '@/assets/futran-logo-white.svg';

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
  if (side && me.organization.type !== side) return <Navigate to={me.organization.type === 'futran' ? '/audits' : '/start'} replace />;
  if (me.terms_required) return <Navigate to="/welcome/terms" replace />;
  if (me.notice_required) return <Navigate to="/welcome/notice" replace />;
  return <>{children}</>;
}

export function FutranShell() {
  const { data: me } = useMe();
  if (!me) return null;
  const nav: { to: string; label: string; show: boolean }[] = [
    { to: '/audits', label: 'Dashboard', show: true },
    { to: '/clients', label: 'Clients', show: true },
    { to: '/admin/templates', label: 'Templates', show: hasRole(me, 'admin', 'chief_auditor') },
    { to: '/admin/reference', label: 'Reference data', show: hasRole(me, 'admin', 'chief_auditor') },
    { to: '/admin/users', label: 'Users', show: hasRole(me, 'admin', 'chief_auditor') },
    { to: '/admin/audit-log', label: 'Audit log', show: hasRole(me, 'admin', 'chief_auditor') },
    { to: '/admin/outbox', label: 'Outbox', show: hasRole(me, 'admin', 'chief_auditor') },
    { to: '/admin/settings', label: 'Settings', show: hasRole(me, 'admin', 'chief_auditor') },
  ];
  return (
    <>
      <TestModeBar me={me} />
      <header className="shell-header">
        <Link to="/audits" className="brand"><img className="brand-logo" src={logoWhite} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span></Link>
        <nav className="shell-nav" aria-label="Main">
          {nav.filter((n) => n.show).map((n) => <NavLink key={n.to} to={n.to}>{n.label}</NavLink>)}
        </nav>
        <UserMenu me={me} />
      </header>
      <main><Outlet /></main>
    </>
  );
}

/** Client screens that exist so far; later phases add theirs here. */
const BUILT_CLIENT_ROUTES = new Set(['/start', '/people', '/register', '/governance/roles', '/governance', '/attestation', '/my-attestation', '/inventory', '/systems', '/documents', '/review', '/report', '/responses', '/remediation']);

export function ClientShell() {
  const { data: me } = useMe();
  if (!me) return null;
  const nav = [
    { to: '/start', label: 'Getting started' },
    { to: '/people', label: 'People', show: hasRole(me, 'client_admin', 'caico') },
    { to: '/register', label: 'AI system register', show: hasRole(me, 'caico', 'client_admin', 'dept_compliance_lead') },
    { to: '/governance/roles', label: 'Governance roles', show: hasRole(me, 'caico', 'client_admin') },
    { to: '/governance', label: 'Governance', show: hasRole(me, 'caico', 'dpo', 'exec_sponsor'), end: true },
    { to: '/attestation', label: 'Attestation', show: hasRole(me, 'caico', 'dpo', 'dept_compliance_lead', 'client_admin') },
    { to: '/my-attestation', label: 'My AI attestation' },
    { to: '/inventory', label: 'AI inventory' },
    { to: '/review', label: 'Review', show: hasRole(me, 'caico', 'dpo', 'exec_sponsor', 'dept_compliance_lead', 'contributor') },
    { to: '/systems', label: 'AI systems', show: hasRole(me, 'caico', 'dept_compliance_lead', 'contributor') },
    { to: '/documents', label: 'Documents', show: hasRole(me, 'caico', 'dpo', 'dept_compliance_lead', 'contributor') },
    { to: '/report', label: 'Report', show: hasRole(me, 'caico', 'dpo', 'exec_sponsor') },
    { to: '/responses', label: 'Responses', show: hasRole(me, 'caico', 'exec_sponsor', 'dept_compliance_lead') },
    { to: '/remediation', label: 'Remediation', show: hasRole(me, 'caico', 'dpo', 'exec_sponsor', 'dept_compliance_lead', 'contributor') },
  ].filter((n) => n.show !== false && BUILT_CLIENT_ROUTES.has(n.to));
  return (
    <>
      <TestModeBar me={me} />
      <header className="shell-header client-header">
        <Link to="/start" className="brand"><img className="brand-logo" src={logo} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span><span className="muted small">· {me.organization.name}</span></Link>
        <nav className="shell-nav" aria-label="Main">
          {nav.map((n) => <NavLink key={n.to} to={n.to} end={'end' in n ? n.end : undefined}>{n.label}</NavLink>)}
        </nav>
        <UserMenu me={me} />
      </header>
      <main><Outlet /></main>
    </>
  );
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
