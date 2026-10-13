import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, setCsrf } from '@/api/client';
import type { Me } from '@/api/auth';
import { Alert, Button, TextField } from '@/components/ui';
import { AuthLayout } from './AuthLayout';

type LoginOut = { mfa_required: boolean; mfa_enrolled: boolean; csrf_token: string };

export function homeFor(me: Me | null | undefined): string {
  if (!me) return '/login';
  return me.organization.type === 'futran' ? '/audits' : '/start';
}

export function Login() {
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
      const out = await api.post<LoginOut>('/auth/login', { email, password });
      setCsrf(out.csrf_token);
      await qc.invalidateQueries();
      if (out.mfa_required) {
        nav(out.mfa_enrolled ? '/mfa' : '/mfa/setup', { replace: true, state: { next: params.get('next') } });
        return;
      }
      const me = await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api.get<Me>('/auth/me') });
      nav(params.get('next') || homeFor(me), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <form onSubmit={submit} noValidate>
        <div>
          <h1>Sign in</h1>
          <p className="muted" style={{ marginTop: 8 }}>Futran staff and client users sign in here.</p>
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
        <TextField label="Work email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Button type="submit" variant="primary" block disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
        <div className="row" style={{ justifyContent: 'space-between', fontSize: 14 }}>
          <span className="muted">Forgot your password? Ask your administrator to reset it.</span>
        </div>
        <p className="muted" style={{ fontSize: 12.5 }}>Multi-factor authentication is required for all accounts. Sign-ins are recorded in the audit log. <Link to="/invite">Have an invitation link?</Link></p>
      </form>
    </AuthLayout>
  );
}
