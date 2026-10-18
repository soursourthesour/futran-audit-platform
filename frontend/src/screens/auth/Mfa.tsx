import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useSessionState, type Me } from '@/api/auth';
import { Alert, Button, Loading, TextField } from '@/components/ui';
import { AuthLayout } from './AuthLayout';
import { homeFor } from './Login';

function useFinish() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { next?: string } };
  return async () => {
    await qc.invalidateQueries();
    const me = await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api.get<Me>('/auth/me') });
    nav(loc.state?.next || homeFor(me), { replace: true });
  };
}

function CodeForm({ intro, onCodes }: { intro: string; onCodes?: (codes: string[]) => void }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const finish = useFinish();
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const out = await api.post<{ ok: boolean; recovery_codes?: string[] }>('/auth/mfa/verify', { code });
      if (out.recovery_codes && onCodes) { onCodes(out.recovery_codes); return; }
      await finish();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <form onSubmit={submit} noValidate>
      <p className="muted">{intro}</p>
      {error && <Alert tone="danger">{error}</Alert>}
      <TextField label="Authenticator code" autoComplete="one-time-code" placeholder="6-digit code or a recovery code" value={code} onChange={(e) => setCode(e.target.value)} />
      <Button type="submit" variant="primary" block>Continue</Button>
    </form>
  );
}

export function MfaVerify() {
  return (
    <AuthLayout>
      <div className="panel">
        <h1>Enter your code</h1>
        <CodeForm intro="Open your authenticator app and enter the 6-digit code for Futran Audit." />
      </div>
    </AuthLayout>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  const finish = useFinish();
  const [saved, setSaved] = useState(false);
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>Keep these recovery codes somewhere safe, such as your password manager. Each one signs you in once if you lose your phone. They are shown only now.</p>
      <pre className="recovery-codes" aria-label="Recovery codes">{codes.join('\n')}</pre>
      <label className="row" style={{ gap: 8 }}><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />I have saved my recovery codes</label>
      <Button variant="primary" block disabled={!saved} onClick={() => finish()}>Continue</Button>
    </div>
  );
}

export function MfaSetup() {
  const { data: s } = useSessionState();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [enroll, setEnroll] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();
  useEffect(() => {
    if (!s) return;
    if (!s.authenticated && !codes) { nav('/login', { replace: true }); return; }
    if (s.mfa_enrolled || codes) { if (!codes) nav('/mfa', { replace: true }); return; }
    if (!enroll) api.post<{ secret: string; qr_svg: string }>('/auth/mfa/enroll').then(setEnroll).catch((e) => setError(errorMessage(e)));
  }, [s, enroll, nav, codes]);
  if (codes) return <AuthLayout><div className="panel"><div className="small muted">Step 3 of 4</div><h1>Save your recovery codes</h1><RecoveryCodes codes={codes} /></div></AuthLayout>;
  return (
    <AuthLayout>
      <div className="panel">
        <div className="small muted">Step 3 of 4</div>
        <h1>Set up sign-in codes</h1>
        <p className="muted">Scan this code with an authenticator app such as Microsoft Authenticator or Google Authenticator, then enter the 6-digit code it shows.</p>
        {error && <Alert tone="danger">{error}</Alert>}
        {!enroll && !error && <Loading />}
        {enroll && (
          <>
            <div style={{ alignSelf: 'center' }} dangerouslySetInnerHTML={{ __html: enroll.qr_svg }} aria-label="QR code for your authenticator app" role="img" />
            <p className="small muted">Can't scan it? Enter this key instead: <code style={{ userSelect: 'all' }}>{enroll.secret}</code></p>
            <CodeForm intro="" onCodes={setCodes} />
          </>
        )}
      </div>
    </AuthLayout>
  );
}
