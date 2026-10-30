import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, setCsrf } from '@/api/client';
import type { Me } from '@/api/auth';
import { homePath } from '@/nav';
import { Alert, Button, TextField } from '@/components/ui';
import { AuthLayout } from './AuthLayout';

type LoginOut = { mfa_required: boolean; mfa_enrolled: boolean; csrf_token: string };

/** Where a person lands after sign-in: their role home (spec §13.1), or the terms first. */
export function homeFor(me: Me | null | undefined): string {
  if (!me) return '/login';
  if (me.terms_required) return '/welcome/terms';
  return homePath(me);
}

function SignInForm({ portal }: { portal: 'staff' | 'client' }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const [params] = useSearchParams();
  const qc = useQueryClient();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const out = await api.post<LoginOut>('/auth/login', { email, password, portal });
      setCsrf(out.csrf_token);
      await qc.invalidateQueries();
      if (out.mfa_required) {
        nav(out.mfa_enrolled ? '/mfa' : '/mfa/setup', { replace: true, state: { next: params.get('next') } });
        return;
      }
      const me = await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api.get<Me>('/auth/me') });
      nav(me.terms_required ? '/welcome/terms' : params.get('next') || homeFor(me), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      {error && <Alert tone="danger">{error}</Alert>}
      <TextField label="Work email" type="email" autoComplete="username" placeholder={portal === 'staff' ? 'name@futransolutions.com' : undefined} value={email} onChange={(e) => setEmail(e.target.value)} required />
      <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      <Button type="submit" variant="primary" block disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
    </form>
  );
}

/** Screen 1: Futran staff sign in, a separate entry point from clients. */
export function StaffLogin() {
  return (
    <AuthLayout>
      <div className="stack">
        <div>
          <h1>Futran staff sign in</h1>
          <p className="muted" style={{ marginTop: 8 }}>For Chief Auditors, Admins, Auditors, Engagement Managers and QA Reviewers.</p>
        </div>
        <SignInForm portal="staff" />
        <div className="row" style={{ justifyContent: 'space-between', fontSize: 14, gap: 12, flexWrap: 'wrap' }}>
          <span className="muted">Forgot your password? Ask a Futran administrator for a reset link.</span>
          <Link to="/login">Client? Sign in here</Link>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>Multi-factor authentication is required for all accounts. Sign-ins are recorded in the audit log.</p>
      </div>
    </AuthLayout>
  );
}

/** Screen 9b: client sign in. Employees answering the attestation use their link and need no account. */
export function Login() {
  return (
    <AuthLayout>
      <div className="stack">
        <div>
          <h1>Sign in</h1>
          <p className="muted" style={{ marginTop: 8 }}>For client users of the Futran Audit Platform.</p>
        </div>
        <SignInForm portal="client" />
        <div className="row" style={{ justifyContent: 'space-between', fontSize: 14, gap: 12, flexWrap: 'wrap' }}>
          <Link to="/invite">Have an invitation?</Link>
          <span className="muted">Forgot your password? Ask your Client Admin.</span>
        </div>
        <Alert tone="info">Answering the AI use attestation? Use the link your compliance team sent you. You do not need an account.</Alert>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>Multi-factor authentication is required for all accounts. Sign-ins are recorded in the audit log. <Link to="/staff/login">Futran staff portal</Link></p>
      </div>
    </AuthLayout>
  );
}
