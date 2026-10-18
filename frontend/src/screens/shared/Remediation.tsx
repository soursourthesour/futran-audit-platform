import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, TextArea, fmtDate, fmtDateTime } from '@/components/ui';
import { SEV_TONE } from '@/screens/futran/FieldworkUseCase';

type Item = {
  id: string; source: 'finding' | 'commitment'; action: string; status: string; status_label: string; finding_ref: string | null; finding_title: string | null; severity: string | null;
  owner: string | null; due_date: string | null; overdue: boolean; done_note: string | null; marked_done_by: string | null; marked_done_at: string | null;
  verified_by: string | null; verified_at: string | null; verification_note: string | null; closed_by: string | null; closed_at: string | null; reopen_note: string | null;
  can_act: boolean; can_verify: boolean; can_close: boolean; can_reopen: boolean;
};
type Data = { audit_ref: string; client: string; stage: number; status: string; items: Item[]; counts: Record<string, number> };

const TONE: Record<string, 'muted' | 'navy' | 'warn' | 'success' | 'danger'> = { open: 'muted', in_progress: 'navy', awaiting_verification: 'warn', closed: 'success', reopened: 'danger' };
const TILES = [['open', 'Open'], ['in_progress', 'In progress'], ['awaiting_verification', 'Awaiting verification'], ['closed', 'Closed']] as const;

/** Screen 20: remediation tracker. Client owners mark items done; Futran verifies; the Chief Auditor closes. */
export function Remediation() {
  const params = useParams();
  const { data: me } = useMe();
  const futran = !!params.clientId;
  const clientId = params.clientId ?? me?.organization.id ?? '';
  const key = ['remediation', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/clients/${clientId}/remediation`), enabled: !!clientId });
  const [sel, setSel] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading || !clientId) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const it = d.items.find((x) => x.id === sel) ?? d.items.find((x) => x.can_verify || x.can_close || x.can_act && x.status !== 'closed') ?? d.items[0];
  const run = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); setNote(''); await qc.invalidateQueries({ queryKey: key }); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } };
  const ref = (x: Item) => x.finding_ref ? <><span>{x.finding_ref}</span> {x.severity && <Badge tone={SEV_TONE[x.severity]}>{x.severity[0].toUpperCase() + x.severity.slice(1)}</Badge>}</> : <span className="muted">Governance commitment</span>;
  return (
    <div className="page">
      <PageHeader title="Remediation" crumbs={futran ? [{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client} · ${d.audit_ref}` }, { label: 'Remediation' }] : undefined}
        subtitle={d.status === 'completed' ? 'Every item is closed. The engagement is complete.' : `Stage ${d.stage} · Client owners mark items done; Futran verifies; the Chief Auditor closes.`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid-tiles" style={{ marginTop: 16 }}>{TILES.map(([k, label]) => <div key={k} className="tile"><div className="label">{label}</div><div className="value">{(d.counts[k] ?? 0) + (k === 'open' ? d.counts.reopened ?? 0 : 0)}</div></div>)}</div>
      <div className="split" style={{ marginTop: 16 }}>
        <div className="main">
          <Card>
            {d.items.length === 0 ? <EmptyState>No remediation items yet. They come from the management responses and the governance commitments.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Action</th><th>Finding</th><th>Owner</th><th>Due</th><th>Status</th></tr></thead>
                <tbody>{d.items.map((x) => (
                  <tr key={x.id} className={`clickable${x.id === it?.id ? ' selected' : ''}`} onClick={() => { setSel(x.id); setNote(''); }}>
                    <td><strong>{x.action}</strong></td><td>{ref(x)}</td><td>{x.owner ?? '—'}</td>
                    <td>{fmtDate(x.due_date)}{x.overdue && <> <Badge tone="danger">Overdue</Badge></>}</td>
                    <td><Badge tone={TONE[x.status]}>{x.status === 'awaiting_verification' && x.verified_by ? 'Verified · with Chief Auditor' : x.status_label}</Badge></td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
        </div>
        <div className="side">
          {it && (
            <div className="card selected-panel stack">
              <div className="small muted">{it.finding_ref ? `${it.finding_ref} · ${it.finding_title}` : 'Governance commitment'}</div>
              <h3 style={{ margin: 0 }}>{it.action}</h3>
              <dl className="kv-stacked">
                <dt>Owner</dt><dd>{it.owner ?? '—'}</dd>
                <dt>Due</dt><dd>{fmtDate(it.due_date)}</dd>
                {it.marked_done_at && <><dt>Marked done</dt><dd>{it.marked_done_by}, {fmtDateTime(it.marked_done_at)}{it.done_note && <div className="small">{it.done_note}</div>}</dd></>}
                {it.verified_at && <><dt>Verified</dt><dd>{it.verified_by}, {fmtDateTime(it.verified_at)}{it.verification_note && <div className="small">{it.verification_note}</div>}</dd></>}
                {it.closed_at && <><dt>Closed</dt><dd>{it.closed_by}, {fmtDateTime(it.closed_at)}</dd></>}
                {it.reopen_note && it.status === 'reopened' && <><dt>Reopened</dt><dd>{it.reopen_note}</dd></>}
              </dl>
              {it.can_act && ['open', 'in_progress', 'reopened'].includes(it.status) && (
                <div className="stack-sm">
                  <TextArea label="What was done" help="Upload supporting files under Documents and mention them here." value={note} onChange={(e) => setNote(e.target.value)} />
                  <div className="row" style={{ gap: 8 }}>
                    <Button variant="primary" onClick={() => run(() => api.post(`/remediation/${it.id}/done`, { note }), 'Marked done. Futran has been told.')}>Mark done</Button>
                    {it.status !== 'in_progress' && <Button onClick={() => run(() => api.post(`/remediation/${it.id}/start`), 'Marked in progress.')}>Mark in progress</Button>}
                  </div>
                </div>
              )}
              {(it.can_verify || it.can_reopen) && (
                <div className="stack-sm">
                  <TextArea label={it.can_verify ? 'Verification note' : 'Reason to reopen'} value={note} onChange={(e) => setNote(e.target.value)} />
                  <div className="row" style={{ gap: 8 }}>
                    {it.can_verify && <Button variant="primary" onClick={() => run(() => api.post(`/remediation/${it.id}/verify`, { note }), 'Verified and sent to the Chief Auditor.')}>Verify, send to Chief Auditor</Button>}
                    {it.can_reopen && <Button onClick={() => run(() => api.post(`/remediation/${it.id}/reopen`, { note }), 'Reopened. The owner can mark it done again.')}>Reopen</Button>}
                  </div>
                </div>
              )}
              {it.can_close && <div><Button variant="primary" onClick={() => run(() => api.post(`/remediation/${it.id}/close`), 'Item closed.')}>Close item</Button></div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
