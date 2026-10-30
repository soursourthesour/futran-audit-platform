import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Button, Card, Loading, TextField } from '@/components/ui';
import { PhoneShell } from '@/shells/Shells';
import { emailHelp as H } from '@/help/email';
import './email.css';

type Info = { provider: string; provider_label: string; kind: 'admin' | 'user'; organization: string; mailbox: string | null; scopes: string[] };

/** Test mode only: stands in for the Microsoft or Google consent page, so the onboarding can be walked through
 *  without a real tenant. Nothing leaves the platform. */
export function TestConsent() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const state = params.get('state') ?? '';
  const provider = params.get('provider') ?? 'microsoft365';
  const q = useQuery({ queryKey: ['test-consent', state], queryFn: () => api.get<Info>(`/mail/test-consent-info?state=${encodeURIComponent(state)}`), retry: false });
  const [mailbox, setMailbox] = useState(params.get('login_hint') ?? '');
  const [err, setErr] = useState<string | null>(null);
  async function answer(approve: boolean) {
    setErr(null);
    try {
      const r = await api.post<{ redirect: string }>(`/mail/oauth/${provider}/test`, { state, mailbox: mailbox || q.data?.mailbox || null, approve });
      await qc.invalidateQueries();
      nav(r.redirect);
    } catch (e) { setErr(errorMessage(e)); }
  }
  if (q.isLoading) return <PhoneShell title="Sign in"><Loading /></PhoneShell>;
  if (!q.data) return <PhoneShell title="Sign in"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const i = q.data;
  return (
    <PhoneShell title={`${i.provider_label} (test mode)`}>
      <Card>
        <div className="stack">
          <Alert tone="info">Test mode. This page stands in for the {i.provider_label} consent screen; no real account is used and no email leaves the platform.</Alert>
          <h1 style={{ fontSize: 22, margin: 0 }}>{i.kind === 'admin' ? 'Approve access for your organisation' : 'Connect your mailbox'}</h1>
          <p style={{ margin: 0 }}>The Futran Audit Platform{i.kind === 'admin' ? ` asks to act for ${i.organization}` : ' asks to send mail as you'} with these permissions:</p>
          <ul className="small" style={{ margin: 0 }}>{i.scopes.map((s) => <li key={s}><span className="mail-code">{s}</span></li>)}</ul>
          <TextField label={i.kind === 'admin' ? 'Mailbox the emails come from' : 'Your mailbox'} help={H.mailbox} type="email" value={mailbox || i.mailbox || ''} onChange={(e) => setMailbox(e.target.value)} />
          {err && <Alert tone="danger">{err}</Alert>}
          <Button variant="primary" block onClick={() => answer(true)}>Accept</Button>
          <Button block onClick={() => answer(false)}>Cancel</Button>
        </div>
      </Card>
    </PhoneShell>
  );
}

/** Where a failed consent redirect lands (the callback needs no sign-in, so IT may land here). */
export function ConsentResult() {
  const [params] = useSearchParams();
  const error = params.get('error');
  return (
    <PhoneShell title="Futran Audit Platform">
      <div className="stack">
        {error ? <Alert tone="danger">{error}</Alert> : <Alert tone="success">Access approved. You can close this page.</Alert>}
        <p className="small">If you are the Client Admin, return to <Link to="/admin/email">Connect your email</Link> to finish the setup.</p>
      </div>
    </PhoneShell>
  );
}
