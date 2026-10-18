import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors, setCsrf } from '@/api/client';
import type { Me } from '@/api/auth';
import { Alert, Button, Loading, TextField } from '@/components/ui';
import { AuthLayout } from './AuthLayout';
import { homeFor } from './Login';

type Info = { email: string; name: string; job_title: string | null; organization_name: string; roles: string[]; expired: boolean; used: boolean };

/** Screen 9a: confirm details → password → sign-in codes → terms → checklist. */
export function AcceptInvite() {
  const { token } = useParams();
  const [step, setStep] = useState<'details' | 'password' | 'declined'>('details');
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
  async function decline() {
    setError(null);
    try { await api.post(`/invitations/decline/${token}`); setStep('declined'); } catch (err) { setError(errorMessage(err)); }
  }

  if (!token) {
    return (
      <AuthLayout>
        <div className="panel"><h1>Use your invitation</h1><p className="muted">Open the link in your invitation email. It is for you only and expires 7 days after it was sent.</p><Link to="/login">Back to sign in</Link></div>
      </AuthLayout>
    );
  }
  if (info.isLoading) return <AuthLayout><Loading /></AuthLayout>;
  if (info.isError || !info.data) return <AuthLayout><div className="panel"><h1>Invitation not found</h1><Alert tone="danger">{errorMessage(info.error)}</Alert></div></AuthLayout>;
  const d = info.data;
  if (step === 'declined') {
    return <AuthLayout><div className="panel"><h1>Invitation cancelled</h1><p className="muted">Thank you. We have told the person who sent it, so they can check the email address. You can close this page.</p></div></AuthLayout>;
  }
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
  if (step === 'details') {
    return (
      <AuthLayout>
        <div className="stack">
          <div><div className="small muted">Step 1 of 4</div><h1>Confirm your details</h1></div>
          {error && <Alert tone="danger">{error}</Alert>}
          <dl className="details">
            <dt>Name</dt><dd>{d.name}</dd>
            <dt>Work email</dt><dd>{d.email}</dd>
            {d.job_title && <><dt>Job title</dt><dd>{d.job_title}</dd></>}
            <dt>Organization</dt><dd>{d.organization_name}</dd>
            {d.roles.length > 0 && <><dt>Your role</dt><dd>{d.roles.join(', ')}</dd></>}
          </dl>
          <Button variant="primary" block onClick={() => setStep('password')}>These are my details</Button>
          <Button variant="ghost" block onClick={decline}>Not you? Cancel this invitation</Button>
        </div>
      </AuthLayout>
    );
  }
  return (
    <AuthLayout>
      <form onSubmit={submit} noValidate className="stack">
        <div>
          <div className="small muted">Step 2 of 4</div>
          <h1>Set a password</h1>
          <p className="muted" style={{ marginTop: 8 }}>For {d.email}. Next you will set up sign-in codes on your phone.</p>
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
        <TextField label="New password" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} help="At least 12 characters. Common or breached passwords are refused." error={fe.password} />
        <TextField label="Confirm password" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} error={fe.password2} />
        <Button type="submit" variant="primary" block>Set password and continue</Button>
        <Button variant="ghost" block onClick={() => setStep('details')}>Back</Button>
      </form>
    </AuthLayout>
  );
}
