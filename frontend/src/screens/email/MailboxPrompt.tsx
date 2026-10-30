import { useState } from 'react';
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { type MyMailbox, PROVIDER_LABEL, goToConsent } from '@/api/mail';
import { Alert, Button, Card, Loading } from '@/components/ui';
import './email.css';

export function useMyMailbox(enabled = true) {
  return useQuery({ queryKey: ['my-mailbox'], queryFn: () => api.get<MyMailbox>('/me/mailbox'), enabled, retry: false, staleTime: 60_000 });
}

async function connect(provider: string) {
  const r = await api.post<{ url: string }>('/me/mailbox/connect', { provider });
  goToConsent(r.url);
}

/** Inside both shells: sends people whose organisation requires it to connect their mailbox, and offers it once to
 *  everyone else (spec §27.1). */
export function MailboxGate() {
  const loc = useLocation();
  const qc = useQueryClient();
  const q = useMyMailbox();
  const [err, setErr] = useState<string | null>(null);
  const m = q.data;
  if (!m || !m.prompt) return null;
  if (m.required) return <Navigate to={`/welcome/mailbox?next=${encodeURIComponent(loc.pathname)}`} replace />;
  const providers = (['microsoft365', 'google'] as const).filter((p) => m.credentials[p].available);
  if (!providers.length) return null;
  const preferred = m.suggested_provider && providers.includes(m.suggested_provider as 'microsoft365') ? m.suggested_provider : providers[0];
  return (
    <div className="mailbox-banner" role="region" aria-label="Connect your mailbox">
      <span>Connect your mailbox so emails you send from the platform come from your own address. Only replies to those emails are read back.</span>
      <span className="row" style={{ gap: 8 }}>
        <Button size="sm" variant="primary" onClick={async () => { try { await connect(preferred!); } catch (e) { setErr(errorMessage(e)); } }}>Connect {PROVIDER_LABEL[preferred!]}</Button>
        <Button size="sm" onClick={async () => { try { await api.post('/me/mailbox/decline'); await qc.invalidateQueries({ queryKey: ['my-mailbox'] }); } catch (e) { setErr(errorMessage(e)); } }}>Not now</Button>
      </span>
      {err && <span className="small" role="alert">{err}</span>}
    </div>
  );
}

/** /welcome/mailbox: connect at first sign-in (required, or chosen from the banner). */
export function MailboxPrompt() {
  const { data: me, isLoading } = useMe();
  const [params] = useSearchParams();
  const q = useMyMailbox(!!me);
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  if (isLoading || (me && q.isLoading)) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  const m = q.data;
  const home = me.organization.type === 'futran' ? '/audits' : '/start';
  const next = params.get('next') || home;
  const connected = m?.connection?.status === 'connected';
  const providers = m ? (['microsoft365', 'google'] as const).filter((p) => m.credentials[p].available) : [];
  return (
    <div className="mail-welcome">
      <Card title="Connect your mailbox">
        <div className="stack">
          {connected ? (
            <>
              <Alert tone="success">Connected: {m!.connection!.mailbox} ({m!.connection!.provider_label}). Emails you send from the platform now come from this address.</Alert>
              <Link className="btn btn-primary" to={next}>Continue</Link>
            </>
          ) : (
            <>
              <p style={{ margin: 0 }}>{m?.policy === 'required' ? `${me.organization.name} asks everyone to connect their work mailbox before continuing.` : 'You can connect your work mailbox now or later.'} Emails you send from the platform then come from your own address, and replies come back into the platform.</p>
              <ul className="small" style={{ margin: 0 }}>
                <li>Only email threads the platform started are read. The rest of your mailbox is never read.</li>
                <li>You can disconnect at any time, and the connection ends automatically if you leave the organisation.</li>
              </ul>
              {err && <Alert tone="danger">{err}</Alert>}
              {providers.length === 0 && <Alert tone="warn">Mailbox connection is not set up on this platform yet. Your emails come from your organisation's mailbox meanwhile.</Alert>}
              <div className="row" style={{ flexWrap: 'wrap' }}>
                {providers.map((p) => <Button key={p} variant={p === (m?.suggested_provider ?? 'microsoft365') ? 'primary' : 'default'} onClick={async () => { try { await connect(p); } catch (e) { setErr(errorMessage(e)); } }}>Connect {PROVIDER_LABEL[p]}</Button>)}
                {m?.policy !== 'required' && <Button variant="ghost" onClick={async () => { await api.post('/me/mailbox/decline'); await qc.invalidateQueries({ queryKey: ['my-mailbox'] }); window.location.assign(next); }}>Not now</Button>}
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
