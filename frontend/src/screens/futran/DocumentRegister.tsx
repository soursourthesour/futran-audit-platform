import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, FieldHelp, Loading, PageHeader, SelectField, TextField, fileUrl, fmtDate } from '@/components/ui';
import { documentHelp } from '@/help/client';

export type DocRequest = {
  id: string; code: string; title: string; description: string | null; category: number; category_title: string; system_id: string | null; system: string | null; system_ref: string | null;
  status: 'pending' | 'received' | 'not_available'; due_at: string | null; received_at: string | null; files: { id: string; filename: string }[]; not_available_note: string | null;
  chases?: number; last_chased_at?: string | null; escalate?: boolean; finding?: { id: string; ref: string } | null;
};
type Register = {
  client: { id: string; name: string }; audit_ref: string; fieldwork_start: string | null; due: string | null; requested_at: string | null; not_yet_requested: number;
  kpis: { requested: number; received: number; pending: number; past_escalation: number; not_available: number; findings: number };
  requests: DocRequest[]; systems: { id: string; reference_id: string; name: string }[];
};

export const STATUS: Record<string, { label: string; tone: 'success' | 'warn' | 'danger' | 'muted' }> = {
  pending: { label: 'Pending', tone: 'warn' }, received: { label: 'Received', tone: 'success' }, not_available: { label: 'Not available', tone: 'danger' },
};

export function DocumentRegister() {
  const { clientId = '' } = useParams();
  const key = ['documents', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Register>(`/clients/${clientId}/document-requests`) });
  const [cat, setCat] = useState('');
  const [sys, setSys] = useState('');
  const [preview, setPreview] = useState<{ to: string | null; cc: string[]; markdown: string; new_items: number } | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const run = async (fn: () => Promise<string>) => { setMsg(null); try { const t = await fn(); await refresh(); setMsg({ tone: 'success', text: t }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } };
  async function openPreview() {
    setMsg(null);
    try { setPreview(await api.get(`/clients/${clientId}/document-requests/preview`)); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const issue = () => run(async () => { const r = await api.post<{ count: number }>(`/clients/${clientId}/document-requests/issue`); setPreview(null); return `Request sent. ${r.count} documents on the register.`; });
  const chaseAll = () => run(async () => { const r = await api.post<{ chased: number }>(`/clients/${clientId}/document-requests/chase`, { note: 'Reminder sent' }); return `Reminder sent for ${r.chased} documents.`; });
  const chaseOne = (r: DocRequest) => run(async () => { await api.post(`/document-requests/${r.id}/chase`, { note: 'Chased by phone or email' }); return `Chase recorded for ${r.title}.`; });
  const rows = d.requests.filter((r) => (!cat || String(r.category) === cat) && (!sys || r.system_id === sys));
  const cats = [...new Map(d.requests.map((r) => [r.category, r.category_title])).entries()].sort((a, b) => a[0] - b[0]);
  const perSystem = d.requests.filter((r) => r.system_id).length;
  return (
    <div className="page">
      <PageHeader title="Document request register" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client.name} · ${d.audit_ref}` }, { label: 'Documents' }]}
        subtitle={<>Template §2 and Appendix A{d.requested_at ? ` · requested ${fmtDate(d.requested_at)}` : ''}{d.due ? ` · due ${fmtDate(d.due)} (5 business days before fieldwork)` : ' · set the fieldwork start date to fix the due date'} · missing documents become findings</>}
        actions={<>
          <Button onClick={openPreview}>{d.kpis.requested ? 'Preview request email' : 'Preview and send request'}</Button>
          {d.kpis.pending > 0 && <Button variant="primary" onClick={chaseAll}>Chase {d.kpis.pending} pending</Button>}
        </>} />
      {msg && msg.text && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {d.not_yet_requested > 0 && d.kpis.requested > 0 && <Alert tone="info">{d.not_yet_requested} documents are not requested yet (for example for a system added since). Preview the request to send them.</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Requested</div><div className="value">{d.kpis.requested}</div><div className="hint">{perSystem ? `incl. per-system items × ${d.systems.length} systems` : ' '}</div></div>
        <div className="tile"><div className="label">Received</div><div className="value">{d.kpis.received}</div><div className="hint"> </div></div>
        <div className="tile"><div className="label">Pending</div><div className="value">{d.kpis.pending}</div><div className="hint">{d.kpis.past_escalation ? `${d.kpis.past_escalation} past escalation (3 business days)` : ' '}</div></div>
        <div className="tile"><div className="label">Not available</div><div className="value">{d.kpis.not_available}</div><div className="hint">{d.kpis.findings} draft finding{d.kpis.findings === 1 ? '' : 's'} created</div></div>
      </div>
      <Card>
        {d.requests.length === 0 ? <EmptyState>Nothing requested yet. Preview the request email, then send it to the client's Chief AI Compliance Officer.</EmptyState> : (
          <>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
              <div style={{ minWidth: 220 }}><SelectField label="Category" value={cat} placeholder="All categories" onChange={(e) => setCat(e.target.value)} options={cats.map(([n, t]) => ({ value: String(n), label: `${n} ${t}` }))} /></div>
              <div style={{ minWidth: 220 }}><SelectField label="System" value={sys} placeholder="All systems" onChange={(e) => setSys(e.target.value)} options={d.systems.map((s) => ({ value: s.id, label: `${s.reference_id} ${s.name}` }))} /></div>
            </div>
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Document</th><th>System</th><th>Received</th><th>Status</th><th>Chases</th><th>Finding</th><th /></tr></thead>
              <tbody>{cats.filter(([n]) => rows.some((r) => r.category === n)).map(([n, t]) => (
                <Category key={n} title={`Category ${n} · ${t}`} rows={rows.filter((r) => r.category === n)} onChase={chaseOne} />
              ))}</tbody>
            </table></div>
          </>
        )}
      </Card>
      {preview && (
        <Dialog title="Document request email" onClose={() => setPreview(null)} wide>
          <div className="stack">
            <div className="small"><strong>To:</strong> {preview.to ?? 'no Chief AI Compliance Officer email on file'}{preview.cc.length > 0 && <> · <strong>Cc:</strong> {preview.cc.join(', ')}</>}</div>
            <pre className="email-preview">{preview.markdown}</pre>
            <p className="small muted" style={{ margin: 0 }}>The wording comes from the "Pre-audit document request email" template (Admin → Templates).</p>
            <div className="row">{preview.new_items > 0 ? <Button variant="primary" onClick={issue}>Send request ({preview.new_items} documents)</Button> : <span className="small muted">Everything has been requested already.</span>}<Button onClick={() => setPreview(null)}>Close</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function Category({ title, rows, onChase }: { title: string; rows: DocRequest[]; onChase: (r: DocRequest) => void }) {
  return (
    <>
      <tr><th colSpan={7} style={{ background: 'var(--bg, #f5f7fa)' }}>{title}</th></tr>
      {rows.map((r) => (
        <tr key={r.id}>
          <td>{r.title}{r.files.length > 0 && <div className="small">{r.files.map((f) => <a key={f.id} href={fileUrl(f.id)} style={{ marginRight: 8 }}>{f.filename}</a>)}</div>}{r.not_available_note && <div className="small muted">Client: {r.not_available_note}</div>}</td>
          <td>{r.system_ref ?? '—'}</td>
          <td>{r.received_at ? fmtDate(r.received_at) : '—'}</td>
          <td><Badge tone={r.escalate ? 'danger' : STATUS[r.status].tone}>{STATUS[r.status].label}{r.escalate ? ' · escalate' : ''}</Badge></td>
          <td>{r.chases ? `${r.chases}${r.last_chased_at ? ` (last ${fmtDate(r.last_chased_at)})` : ''}` : 0}</td>
          <td>{r.finding?.ref ?? '—'}</td>
          <td>{r.status === 'pending' && <Button size="sm" variant="ghost" onClick={() => onChase(r)}>Record chase</Button>}</td>
        </tr>
      ))}
    </>
  );
}

/** Client view: upload each requested document, or say it does not exist. */
export function DocumentUploadsList({ rows, onDone }: { rows: DocRequest[]; onDone: () => void }) {
  const [na, setNa] = useState<DocRequest | null>(null);
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function uploadFile(r: DocRequest, file: File) {
    setErr(null);
    const form = new FormData(); form.append('file', file);
    try { await api.upload(`/document-requests/${r.id}/files`, form); onDone(); } catch (e) { setErr(`${r.title}: ${errorMessage(e)}`); }
  }
  async function markNa() {
    if (!na) return;
    try { await api.post(`/document-requests/${na.id}/not-available`, { note }); setNa(null); setNote(''); onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  const cats = [...new Map(rows.map((r) => [r.category, r.category_title])).entries()].sort((a, b) => a[0] - b[0]);
  return (
    <>
      {err && <Alert tone="danger">{err}</Alert>}
      {cats.map(([n, t]) => (
        <Card key={n} title={`${n}. ${t}`}>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {rows.filter((r) => r.category === n).map((r) => (
              <li key={r.id} style={{ padding: '10px 0', borderTop: '1px solid var(--line-soft)' }}>
                <div className="row" style={{ justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 240 }}>
                    <strong>{r.title}</strong>{r.system && <span className="small muted"> · {r.system}</span>}
                    {r.description && <div className="small muted">{r.description}</div>}
                    {r.files.length > 0 && <div className="small">{r.files.map((f) => <a key={f.id} href={fileUrl(f.id)} style={{ marginRight: 8 }}>{f.filename}</a>)}</div>}
                  </div>
                  <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                    <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                    <label className="btn btn-sm">Upload<input type="file" hidden onChange={(e) => e.target.files?.[0] && uploadFile(r, e.target.files[0])} /></label>
                    <FieldHelp label={`uploading ${r.title}`}>{documentHelp.upload}</FieldHelp>
                    {r.status === 'pending' && <Button size="sm" variant="ghost" onClick={() => setNa(r)}>We don't have this</Button>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
      {na && (
        <Dialog title={`We don't have: ${na.title}`} onClose={() => setNa(null)}>
          <div className="stack">
            <p className="small" style={{ margin: 0 }}>The auditor will record this as a finding. If you are preparing the document, say when it will be ready.</p>
            <TextField label="Note for the auditor" help={documentHelp.notAvailableNote} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row"><Button variant="primary" onClick={markNa}>Confirm</Button><Button onClick={() => setNa(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </>
  );
}
