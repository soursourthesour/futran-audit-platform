import { useState } from 'react';
import { homePath } from '@/nav';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe, useSignOut } from '@/api/auth';
import { Alert, Button, Card, Checkbox, Loading, fmtDate } from '@/components/ui';
import { HtmlReader } from '@/components/DocReader';
import { TestModeBar } from '@/shells/Shells';
import { noticeHelp as H } from '@/help/client';
import logo from '@/assets/futran-logo.svg';

type Pending = { version: number; title: string; html: string; sent_at: string; sent_by: string | null; organization: string };

/** Blocking page: a client user reads and acknowledges the employee data notice their CAICO sent. */
export function NoticeAcknowledge() {
  const { data: me, isLoading } = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const signOut = useSignOut();
  const q = useQuery({ queryKey: ['notice-pending'], queryFn: () => api.get<Pending>('/me/notice/pending'), enabled: !!me?.notice_required, retry: false });
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (isLoading) return <Loading />;
  if (!me) { nav('/login', { replace: true }); return null; }
  if (!me.notice_required) { nav(homePath(me), { replace: true }); return null; }

  async function acknowledge() {
    if (!q.data) return;
    setErr(null); setBusy(true);
    try {
      await api.post('/me/notice/acknowledge', { version: q.data.version, accepted: ok });
      await qc.invalidateQueries({ queryKey: ['me'] });
      nav(homePath(me!), { replace: true });
    } catch (e) {
      setErr(errorMessage(e));
      await qc.invalidateQueries({ queryKey: ['notice-pending'] });
      setOk(false);
    } finally { setBusy(false); }
  }

  return (
    <>
      <TestModeBar me={me} />
      <header className="shell-header client-header">
        <span className="brand"><img className="brand-logo" src={logo} alt="Futran Solutions" /><span className="brand-name">Audit Platform</span><span className="muted small">· {me.organization.name}</span></span>
        <div className="shell-user"><span>{me.user.name}</span><button type="button" onClick={() => signOut(false)}>Sign out</button></div>
      </header>
      <main className="ack-page">
        <div>
          <h1>Read and acknowledge</h1>
          <p className="muted" style={{ marginTop: 6 }}>
            {q.data ? `${q.data.sent_by ?? 'Your Chief AI Compliance Officer'} sent this notice on ${fmtDate(q.data.sent_at)}${q.data.version > 1 ? ` (version ${q.data.version})` : ''}. ` : ''}
            Read it before you continue to the audit.
          </p>
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
        {q.isLoading || !q.data ? (q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />) : (
          <Card title={q.data.title}>
            <div className="stack">
              <HtmlReader html={q.data.html} label={q.data.title} maxHeight="56vh" />
              <Checkbox label="I have read and understand this notice." help={H.acknowledge} checked={ok} onChange={(e) => setOk(e.target.checked)} />
              <div><Button variant="primary" onClick={acknowledge} disabled={!ok || busy}>Acknowledge and continue</Button></div>
            </div>
          </Card>
        )}
      </main>
    </>
  );
}
