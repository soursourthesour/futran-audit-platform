import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Card, Loading, TextField } from '@/components/ui';
import { PhoneShell } from '@/shells/Shells';
import { AttestationSteps, type AttestInfo, type Identity } from '@/screens/phone/AttestationForm';
import { emailHelp as H } from '@/help/email';
import type { Block, PlayerState } from '@/api/wsi';
import { BlockView } from '@/screens/wsi/Blocks';
import { TrainingPlayer } from '@/screens/wsi/TrainingPlayer';

type PolicyAck = { kind: 'policy_ack'; organization: string; title: string; version_no: number; status: string; approved_at: string | null; blocks: Block[]; already_acknowledged?: boolean };
type TrainingLink = { kind: 'training'; organization: string; module: { title: string }; status: string };
type LinkView = ({ kind: 'attestation' } & AttestInfo & { prefill?: Identity; already_answered?: boolean } | { kind: 'message'; title: string; organization: string; paragraphs: string[]; action: 'acknowledge' | 'sign_in'; completed: boolean } | PolicyAck | TrainingLink) & { mode: 'personal' | 'shared' };

function title(v?: LinkView) {
  if (!v) return 'Futran Audit Platform';
  if (v.kind === 'attestation') return `${v.client_name} · AI use check-in`;
  if (v.kind === 'training') return `${v.organization} · AI training`;
  return `${v.organization} · ${v.title}`;
}

/** The page behind a personal link in a group email (spec §26.5): no sign-in; the person's name and department come
 *  from the directory. Also the shared (BCC) link, which first confirms the work email with a one-time code. */
export function LinkLanding({ shared }: { shared?: boolean }) {
  const { token = '' } = useParams();
  const base = shared ? `/public/m/s/${token}` : `/public/m/${token}`;
  const q = useQuery({ queryKey: ['mail-link', base], queryFn: () => api.get<LinkView>(base), retry: false });
  const [proof, setProof] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  if (q.isLoading) return <PhoneShell title="Futran Audit Platform"><Loading /></PhoneShell>;
  if (q.error instanceof ApiError || !q.data) return <PhoneShell title="Futran Audit Platform"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const v = q.data;
  if (shared && !proof) return <PhoneShell title={title(v)}><ConfirmEmail base={base} onProof={setProof} /></PhoneShell>;
  if (done) {
    return (
      <PhoneShell title={title(v)}>
        <div className="stack">
          <h1 style={{ fontSize: 22 }}>Thank you</h1>
          <p>{v.kind === 'policy_ack' ? 'Your acknowledgment has been recorded. You can close this page.' : v.kind === 'attestation' ? 'Your answers have been recorded. If something changes, open the link in your latest email and answer again; your new answers replace the old ones.' : 'Your confirmation has been recorded. You can close this page.'}</p>
        </div>
      </PhoneShell>
    );
  }
  if (v.kind === 'training') return <PhoneShell title={title(v)}><TrainingLinkPlayer token={token} organization={v.organization} /></PhoneShell>;
  if (v.kind === 'policy_ack') {
    return (
      <PhoneShell title={title(v)}>
        <PolicyAckView v={v} onConfirm={async () => { await api.post(`${base}/attestation`, shared ? { confirm: true, proof } : { confirm: true }); setDone(true); }} />
      </PhoneShell>
    );
  }
  if (v.kind === 'attestation') {
    if (!v.open) return <PhoneShell title={title(v)}><Alert tone="info">This check-in has closed. Thank you; nothing more is needed.</Alert></PhoneShell>;
    return (
      <PhoneShell title={title(v)}>
        {v.already_answered && <div style={{ marginBottom: 12 }}><Alert tone="info">You have already answered. Answering again replaces your earlier answers.</Alert></div>}
        <AttestationSteps info={v} prefill={v.prefill} onSubmit={async (payload) => { await api.post(`${base}/attestation`, shared ? { ...payload, proof } : payload); setDone(true); }} />
      </PhoneShell>
    );
  }
  return (
    <PhoneShell title={title(v)}>
      <div className="stack">
        <h1 style={{ fontSize: 22, margin: 0 }}>{v.title}</h1>
        {v.paragraphs.map((p, i) => <p key={i} style={{ margin: 0, whiteSpace: 'pre-line' }}>{p}</p>)}
        {v.action === 'sign_in' ? <Link className="btn btn-primary btn-block" to="/login">Sign in to continue</Link>
          : v.completed ? <Alert tone="success">You have already confirmed this.</Alert>
          : <Button variant="primary" block onClick={async () => { await api.post(`${base}/done`, shared ? { proof } : {}); setDone(true); }}>I have read this</Button>}
      </div>
    </PhoneShell>
  );
}

function ConfirmEmail({ base, onProof }: { base: string; onProof: (p: string) => void }) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  async function go(fn: () => Promise<void>) {
    setErr(null); setFe({}); setBusy(true);
    try { await fn(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <div className="stack">
        <h1 style={{ fontSize: 22, margin: 0 }}>Confirm your work email</h1>
        <p className="small" style={{ margin: 0 }}>This link was sent to a group, so we check it is you before you answer. We send a 6-digit code to your work email.</p>
        {err && !Object.keys(fe).length && <Alert tone="danger">{err}</Alert>}
        <TextField label="Work email" help={H.linkEmail} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={fe.email} disabled={sent} />
        {!sent ? <Button variant="primary" block disabled={busy || !email.includes('@')} onClick={() => go(async () => { await api.post(`${base}/code`, { email }); setSent(true); })}>Send me a code</Button> : (
          <>
            <TextField label="Code" help={H.code} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} error={fe.code} />
            <Button variant="primary" block disabled={busy || code.length !== 6} onClick={() => go(async () => { const r = await api.post<{ proof: string }>(`${base}/verify`, { email, code }); onProof(r.proof); })}>Continue</Button>
            <Button variant="ghost" block disabled={busy} onClick={() => go(async () => { await api.post(`${base}/code`, { email }); setCode(''); })}>Send a new code</Button>
          </>
        )}
      </div>
    </Card>
  );
}

function TrainingLinkPlayer({ token, organization }: { token: string; organization: string }) {
  const q = useQuery({ queryKey: ['training-link', token], queryFn: () => api.get<PlayerState>(`/public/training/${token}`), retry: false });
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  return <TrainingPlayer state={q.data} base={`/public/training/${token}`} organization={organization} />;
}

function PolicyAckView({ v, onConfirm }: { v: PolicyAck; onConfirm: () => Promise<void> }) {
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (v.status !== 'published') return <Alert tone="info">This version of the policy has been replaced. Use the link in your most recent email.</Alert>;
  return (
    <div className="stack">
      <div>
        <h1 style={{ fontSize: 22, margin: 0 }}>{v.title}</h1>
        <p className="small muted" style={{ margin: '4px 0 0' }}>Version {v.version_no}{v.approved_at ? `, approved ${new Date(v.approved_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}` : ''}</p>
      </div>
      {v.already_acknowledged && <Alert tone="success">You have already acknowledged this policy.</Alert>}
      <div className="wsi-doc"><BlockView blocks={v.blocks} /></div>
      {!v.already_acknowledged && (
        <Card>
          <div className="stack">
            {err && <Alert tone="danger">{err}</Alert>}
            <label className="check"><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} /><span>I have read the {v.title} and will follow it.</span></label>
            <Button variant="primary" block disabled={!read || busy} onClick={async () => { setBusy(true); setErr(null); try { await onConfirm(); } catch (e) { setErr(errorMessage(e)); setBusy(false); } }}>Confirm</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
