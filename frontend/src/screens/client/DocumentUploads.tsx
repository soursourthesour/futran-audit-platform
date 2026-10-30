import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, FieldHelp, Loading, PageHeader, TextArea, fileUrl, fmtDate } from '@/components/ui';
import { documentHelp as H } from '@/help/client';
import { DocumentUploadsList, type DocRequest } from '@/screens/futran/DocumentRegister';

type EvidenceReq = { id: string; ref: string; description: string; status: string; due_date: string; answer: string | null; use_case: string | null; files: { id: string; filename: string }[]; overdue: boolean };

/** The client's requested documents (template §2) and the auditor's fieldwork evidence requests. */
export function DocumentUploads() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['me-documents'], queryFn: () => api.get<{ requests: DocRequest[]; due: string | null }>('/me/document-requests') });
  const ev = useQuery({ queryKey: ['me-evidence'], queryFn: () => api.get<{ requests: EvidenceReq[] }>('/me/evidence-requests') });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const open = d.requests.filter((r) => r.status === 'pending').length;
  const evidence = ev.data?.requests ?? [];
  return (
    <div className="page">
      <PageHeader title="Documents" subtitle={d.due ? `Please provide these by ${fmtDate(d.due)}. ${open} still to do.` : 'Documents and evidence the auditor has asked for.'} />
      <div className="stack">
        {evidence.length > 0 && <Card title={`Evidence requests from the auditor · ${evidence.filter((r) => r.status === 'outstanding').length} outstanding`}>{evidence.map((r) => <EvidenceItem key={r.id} r={r} onDone={() => qc.invalidateQueries({ queryKey: ['me-evidence'] })} />)}</Card>}
        {d.requests.length === 0 ? <EmptyState>Futran has not requested any documents from you yet.</EmptyState> : <DocumentUploadsList rows={d.requests} onDone={() => qc.invalidateQueries({ queryKey: ['me-documents'] })} />}
      </div>
    </div>
  );
}

function EvidenceItem({ r, onDone }: { r: EvidenceReq; onDone: () => void }) {
  const [text, setText] = useState(r.answer ?? '');
  const [err, setErr] = useState<string | null>(null);
  const done = r.status !== 'outstanding';
  async function answer() { setErr(null); try { await api.post(`/evidence-requests/${r.id}/answer`, { answer: text }); onDone(); } catch (e) { setErr(errorMessage(e)); } }
  async function upload(file: File) { setErr(null); const form = new FormData(); form.append('file', file); try { await api.upload(`/evidence-requests/${r.id}/files`, form); onDone(); } catch (e) { setErr(errorMessage(e)); } }
  return (
    <div className="stack-sm" style={{ padding: '12px 0', borderTop: '1px solid var(--line-soft)' }}>
      <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
        <div><span className="small muted">{r.ref}{r.use_case ? ` · ${r.use_case}` : ''}</span><div><strong>{r.description}</strong></div></div>
        <Badge tone={done ? 'success' : r.overdue ? 'danger' : 'warn'}>{done ? (r.status === 'waived' ? 'No longer needed' : 'Sent') : `Due ${fmtDate(r.due_date)}`}</Badge>
      </div>
      {err && <Alert tone="danger">{err}</Alert>}
      {r.files.length > 0 && <div className="small">{r.files.map((f) => <a key={f.id} className="file-link" href={fileUrl(f.id)} style={{ marginRight: 8 }}>{f.filename}</a>)}</div>}
      {r.status !== 'waived' && (
        <>
          <TextArea label="Answer (if there is no document)" help={H.evidenceAnswer} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ gap: 8 }}><Button size="sm" onClick={answer}>Send answer</Button><label className="btn btn-sm">Upload a file<input type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label><FieldHelp label={`uploading evidence for ${r.ref}`}>{H.upload}</FieldHelp></div>
        </>
      )}
    </div>
  );
}
