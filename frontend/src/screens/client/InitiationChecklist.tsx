import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, Progress, WithHelp, fmtDate } from '@/components/ui';
import { checklistHelp } from '@/help/client';
import { SignPanel } from '@/components/SignPanel';
import { DocReader } from '@/components/DocReader';
import { DownloadLinks } from '@/components/DownloadLinks';
import { NoticeDialog } from './NoticePanel';

type Doc = { id: string; pdf_file_id: string | null; docx_file_id: string | null; csv_file_id: string | null };
type Acks = { acknowledged: number; pending: number; version: number } | null;
type Item = { key: string; title: string; description: string; done: boolean; self_complete: boolean; document: Doc | null; acknowledgements?: Acks };
export type Checklist = { engagement: { id: string; audit_ref: string; name: string }; items: Item[]; done: number; total: number; requested_by: string | null; sign_off_1_id: string | null; chief_auditor: string | null };

/** Where each item is done, when it is done on another screen. */
const GO_TO: Record<string, { to: string; label: string }> = {
  nominate: { to: '/people/users', label: 'Nominate' },
  departments: { to: '/people/departments', label: 'Confirm departments' },
  users: { to: '/people/users', label: 'Add employees' },
};

export function InitiationChecklist() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['my-initiation'], queryFn: () => api.get<Checklist>('/me/initiation'), retry: false });
  const [signing, setSigning] = useState(false);
  const [reading, setReading] = useState<Item | null>(null);
  const [notice, setNotice] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <div className="page"><PageHeader title="Getting started" /><Card><EmptyState>Your initiation package will appear here once Futran sends it.</EmptyState></Card></div>;
  }
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const c = q.data;
  const isCaico = !!me?.roles.some((r) => r.role === 'caico');
  const canManage = !!me?.roles.some((r) => r.role === 'caico' || r.role === 'client_admin');
  const letter = c.items.find((i) => i.key === 'sign')?.document ?? null;

  async function confirmRead(key: string) {
    setMsg(null);
    try {
      await api.post(`/me/initiation/items/${key}/done`);
      await qc.invalidateQueries({ queryKey: ['my-initiation'] });
      setReading(null);
    } catch (ex) { setMsg({ tone: 'danger', text: errorMessage(ex) }); setReading(null); }
  }

  function action(it: Item) {
    if (it.key === 'notice') {
      const label = isCaico ? (it.done ? 'Review or resend' : 'Review and send') : 'Read the notice';
      return <>{it.done && <Badge tone="success">Done</Badge>}<Button variant={!it.done && isCaico ? 'primary' : 'default'} size={it.done ? 'sm' : undefined} onClick={() => setNotice(true)}>{label}</Button></>;
    }
    if (it.done) return <Badge tone="success">Done</Badge>;
    if (it.key === 'guide' && it.document) return <Button variant="primary" onClick={() => setReading(it)}>Read and confirm</Button>;
    if (it.key === 'sign' && c.sign_off_1_id && isCaico) return <Button variant="primary" onClick={() => setSigning(true)}>Review and sign</Button>;
    if (it.key === 'governance' && isCaico) return <Link className="btn" to="/governance">Start</Link>;
    if (GO_TO[it.key] && canManage) return <Link className="btn" to={GO_TO[it.key].to}>{GO_TO[it.key].label}</Link>;
    return <span className="small muted">Open</span>;
  }

  return (
    <div className="page page-narrow">
      <PageHeader title="Welcome to your AI governance assessment" subtitle={`Complete these seven items to start. Futran's team is notified as each one is done.${c.requested_by ? ` Requested by ${fmtDate(c.requested_by)}.` : ''}`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card>
        <div className="stack">
          <div className="row" style={{ justifyContent: 'space-between' }}><strong>{c.done} of {c.total} complete</strong><span className="small muted">{c.engagement.audit_ref}</span></div>
          <Progress value={(c.done / c.total) * 100} label="Initiation progress" />
          <ol className="checklist">
            {c.items.map((it, i) => (
              <li key={it.key}>
                <span className={`num ${it.done ? 'done' : ''}`} aria-hidden="true">{it.done ? '✓' : i + 1}</span>
                <div className="body">
                  <h3><WithHelp help={checklistHelp[it.key]}>{it.title}</WithHelp></h3>
                  <div className="small muted">{it.description}</div>
                  {it.document && it.key !== 'departments' && it.key !== 'users' && (
                    <div className="small meta"><DownloadLinks pdf={it.document.pdf_file_id} docx={it.document.docx_file_id} title={it.title} /></div>
                  )}
                  {it.key === 'notice' && it.acknowledgements && (
                    <div className="small meta">Version {it.acknowledgements.version} sent · {it.acknowledgements.acknowledged} acknowledged, {it.acknowledgements.pending} pending</div>
                  )}
                </div>
                <div className="actions">{action(it)}</div>
              </li>
            ))}
          </ol>
        </div>
      </Card>
      {c.chief_auditor && <p className="small muted" style={{ marginTop: 16 }}>Questions? Contact your Futran team: {c.chief_auditor}, Chief Auditor.</p>}
      {signing && c.sign_off_1_id && (
        <Dialog title="Review and sign the engagement letter" onClose={() => setSigning(false)} wide>
          <div className="stack">
            {letter && (
              <>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <span className="small muted">Read the letter below, then sign at the end.</span>
                  <DownloadLinks pdf={letter.pdf_file_id} docx={letter.docx_file_id} title="the engagement letter" />
                </div>
                <DocReader docId={letter.id} label="Engagement letter and scope" maxHeight="48vh" />
              </>
            )}
            <SignPanel signOffId={c.sign_off_1_id} onSigned={() => setSigning(false)} hideDocument={!!letter} />
          </div>
        </Dialog>
      )}
      {reading && reading.document && (
        <Dialog title={reading.title} onClose={() => setReading(null)} wide>
          <div className="stack">
            <DocReader docId={reading.document.id} label={reading.title} maxHeight="60vh" />
            <div className="reader-confirm">
              <DownloadLinks pdf={reading.document.pdf_file_id} docx={reading.document.docx_file_id} title={reading.title} />
              <Button variant="primary" onClick={() => confirmRead(reading.key)}>I have read this guide</Button>
            </div>
          </div>
        </Dialog>
      )}
      {notice && <NoticeDialog onClose={() => setNotice(false)} onSent={(text) => { setNotice(false); setMsg({ tone: 'success', text }); }} />}
    </div>
  );
}

