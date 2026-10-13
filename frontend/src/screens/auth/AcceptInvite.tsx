import { useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors, setCsrf } from '@/api/client';
import type { Me } from '@/api/auth';
import { Alert, Button, Loading, TextField } from '@/components/ui';
import { AuthLayout } from './AuthLayout';
import { homeFor } from './Login';

type Info = { email: string; name: string; organization_name: string; expired: boolean; used: boolean };

export function AcceptInvite() {
  const { token } = useParams();
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const nav = useNavigate();
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ['invite', token], queryFn: () => api.get<Info>(`/invitations/accept/${token}`), retry: false, enabled: !!token });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFe({});
    if (pw !== pw2) { setFe({ password2: 'The two passwords do not match.' }); return; }
    try {
      const out = await api.post<{ csrf_token: string; mfa_required: boolean }>(`/invitations/accept/${token}`, { password: pw });
      setCsrf(out.csrf_token);
      await qc.invalidateQueries();
      if (out.mfa_required) { nav('/mfa/setup', { replace: true }); return; }
      const me = await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api.get<Me>('/auth/me') });
      nav(homeFor(me), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setFe(fieldErrors(err));
    }
  }

  if (!token) {
    return (
      <AuthLayout>
        <div className="panel"><h1>Use your invitation</h1><p className="muted">Open the link in your invitation email. It is for you only and expires 7 days after it was sent.</p></div>
      </AuthLayout>
    );
  }
  if (info.isLoading) return <AuthLayout><Loading /></AuthLayout>;
  if (info.isError || !info.data) return <AuthLayout><div className="panel"><h1>Invitation not found</h1><Alert tone="danger">{errorMessage(info.error)}</Alert></div></AuthLayout>;
  const d = info.data;
  if (d.expired || d.used) {
    return (
      <AuthLayout>
        <div className="panel">
          <h1>{d.expired ? 'This invitation has expired' : 'This invitation has been used'}</h1>
          <p className="muted">{d.expired ? 'Ask your contact at Futran to send a new invitation.' : 'If you have already set a password, sign in instead.'}</p>
          <Button variant="primary" onClick={() => nav('/login')}>Go to sign in</Button>
        </div>
      </AuthLayout>
    );
  }
  return (
    <AuthLayout>
      <form onSubmit={submit} noValidate>
        <div>
          <h1>Welcome, {d.name}</h1>
          <p className="muted" style={{ marginTop: 8 }}>Set a password for {d.email} to open the Futran Audit Platform for {d.organization_name}.</p>
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
        <TextField label="New password" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} help="At least 12 characters. Do not reuse your email address." error={fe.password} />
        <TextField label="Confirm password" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} error={fe.password2} />
        <Button type="submit" variant="primary" block>Set password and continue</Button>
      </form>
    </AuthLayout>
  );
}
