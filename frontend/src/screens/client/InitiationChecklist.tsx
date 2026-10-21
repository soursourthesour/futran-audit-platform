import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, Progress, WithHelp, fileUrl, fmtDate } from '@/components/ui';
import { checklistHelp } from '@/help/client';
import { SignPanel } from '@/components/SignPanel';
import { DocPreview } from '@/components/DocPreview';

type Item = { key: string; title: string; description: string; done: boolean; self_complete: boolean; document: { id: string; pdf_file_id: string | null; docx_file_id: string | null; csv_file_id: string | null } | null };
type Checklist = { engagement: { id: string; audit_ref: string; name: string }; items: Item[]; done: number; total: number; requested_by: string | null; sign_off_1_id: string | null; chief_auditor: string | null };

const LATER: Record<string, string> = {};
const PEOPLE: Record<string, string> = { nominate: 'Nominate', departments: 'Confirm', users: 'Add users' };

export function InitiationChecklist() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['my-initiation'], queryFn: () => api.get<Checklist>('/me/initiation'), retry: false });
  const [signing, setSigning] = useState(false);
  const [preview, setPreview] = useState<{ id: string; title: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <div className="page"><PageHeader title="Getting started" /><Card><EmptyState>Your initiation package will appear here once Futran sends it.</EmptyState></Card></div>;
  }
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const c = q.data;
  const isCaico = !!me?.roles.some((r) => r.role === 'caico');
  const canManage = !!me?.roles.some((r) => r.role === 'caico' || r.role === 'client_admin');

  async function markDone(key: string) {
    setErr(null);
    try {
      await api.post(`/me/initiation/items/${key}/done`);
      await qc.invalidateQueries({ queryKey: ['my-initiation'] });
    } catch (ex) { setErr(errorMessage(ex)); }
  }

  return (
    <div className="page page-narrow">
      <PageHeader title="Welcome to your AI governance assessment" subtitle={`Complete these seven items to start. Futran's team is notified as each one is done.${c.requested_by ? ` Requested by ${fmtDate(c.requested_by)}.` : ''}`} />
      {err && <Alert tone="danger">{err}</Alert>}
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
                  {it.document && (
                    <div className="row small" style={{ gap: 12, marginTop: 4 }}>
                      {it.key !== 'users' && it.key !== 'departments' && <button type="button" className="link-btn" onClick={() => setPreview({ id: it.document!.id, title: it.title })}>Read</button>}
                      {it.document.pdf_file_id && <a href={fileUrl(it.document.pdf_file_id)}>PDF</a>}
                      {it.document.docx_file_id && <a href={fileUrl(it.document.docx_file_id)}>Word</a>}
                      {it.document.csv_file_id && <a href={fileUrl(it.document.csv_file_id)}>Download template</a>}
                    </div>
                  )}
                </div>
                <div>
                  {it.done ? <Badge tone="success">Done</Badge>
                    : it.key === 'sign' && c.sign_off_1_id && isCaico ? <Button variant="primary" onClick={() => setSigning(true)}>Review and sign</Button>
                    : it.key === 'guide' ? <Button onClick={() => markDone('guide')}>Mark as read</Button>
                    : it.key === 'notice' && isCaico ? <Button onClick={() => markDone('notice')}>Acknowledge</Button>
                    : it.key === 'governance' && isCaico ? <Link className="btn" to="/governance">Start</Link>
                    : PEOPLE[it.key] && canManage ? <Link className="btn" to="/users">{PEOPLE[it.key]}</Link>
                    : LATER[it.key] ? <span className="small muted">{LATER[it.key]}: opens with the next step</span> : <span className="small muted">Open</span>}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Card>
      {c.chief_auditor && <p className="small muted" style={{ marginTop: 16 }}>Questions? Contact your Futran team: {c.chief_auditor}, Chief Auditor.</p>}
      {signing && c.sign_off_1_id && <Dialog title="Sign the engagement letter" onClose={() => setSigning(false)} wide><SignPanel signOffId={c.sign_off_1_id} onSigned={() => setSigning(false)} /></Dialog>}
      {preview && <DocPreview docId={preview.id} title={preview.title} onClose={() => setPreview(null)} />}
    </div>
  );
}
