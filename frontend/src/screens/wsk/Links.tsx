import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, useMe } from '@/api/auth';
import { Alert, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import type { ClientBiasData } from '@/api/wsk';

/** On the Futran client page: heat map and lineage, the annual review, and changes since the prior audit. */
export function ClientInsightLinks({ clientId, engagement }: { clientId: string; engagement: { id: string; status: string; type_label: string } }) {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const live = !['draft', 'pending_approval'].includes(engagement.status);
  const canStart = engagement.status === 'completed' && can(me, 'start_annual_review');
  if (!live && !can(me, 'view_heatmap')) return null;
  async function start() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      await api.post(`/engagements/${engagement.id}/annual-review`);
      await qc.invalidateQueries({ queryKey: ['client-page', clientId] });
      navigate(`/clients/${clientId}/setup/company`);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="Risk insight and next year">
      {err && <Alert tone="danger">{err}</Alert>}
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {can(me, 'view_heatmap') && <li><Link to={`/clients/${clientId}/heatmap`}>Risk heat map and lineage</Link>: systems by inherent risk and maturity, findings by severity and domain, and why each finding was raised.</li>}
        {engagement.type_label.toLowerCase().includes('annual') && <li><Link to={`/engagements/${engagement.id}/carried`}>Changes since the prior audit</Link>: answers carried forward and what the client confirmed or changed.</li>}
      </ul>
      {canStart && <div className="row" style={{ gap: 8 }}><Button variant="primary" onClick={() => setAsk(true)}>Start annual review</Button><span className="small muted">Copies systems, answers and evidence links into a new draft engagement for next year.</span></div>}
      {ask && (
        <Dialog title="Start annual review" onClose={() => setAsk(false)}>
          <div className="stack">
            <p className="small" style={{ margin: 0 }}>A new draft engagement is created for the next twelve months with the same scope, laws, contacts and team. Systems, answers and evidence links are carried forward: the client confirms each answer or updates it, and you re-test the evidence. Review the draft and submit it for approval as usual.</p>
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button onClick={() => setAsk(false)}>Cancel</Button><Button variant="primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start annual review'}</Button></div>
          </div>
        </Dialog>
      )}
    </Card>
  );
}

/** Client screen: applicant data the auditor ran bias tests on, and the choice to keep it past the retention period. */
export function BiasData() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['bias-data'], queryFn: () => api.get<ClientBiasData>('/bias-data') });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  async function keep(id: string, on: boolean) {
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await api.put(`/bias-tests/${id}/keep-raw-data`, { keep: on }); setMsg({ tone: 'success', text: on ? 'The raw data will be kept after the retention period.' : 'The raw data will be deleted at the end of the retention period.' }); await qc.invalidateQueries({ queryKey: ['bias-data'] }); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  return (
    <div className="page">
      <PageHeader title="Bias test data" subtitle="Applicant data your auditor used for bias tests. It stays in your organization’s storage and is deleted at the end of the engagement retention period unless you keep it. The results are always kept." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card>
        {q.data.runs.length === 0 ? <EmptyState>No bias test data has been uploaded.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>System</th><th>File</th><th>Tested</th><th>Raw data</th><th>Keep after the retention period</th></tr></thead>
            <tbody>{q.data.runs.map((r) => (
              <tr key={r.id}>
                <td>{r.system}</td><td className="small">{r.dataset_filename}</td><td className="small">{fmtDate(r.run_at)}</td>
                <td className="small">{r.raw_deleted_at ? `Deleted ${fmtDate(r.raw_deleted_at)}` : r.raw_delete_on ? `Deleted on ${fmtDate(r.raw_delete_on)} unless kept` : 'Kept until the engagement retention period ends'}</td>
                <td>{r.raw_deleted_at ? '—' : <Checkbox label={`Keep ${r.dataset_filename ?? 'this file'}`} help="Keeps the raw rows after the retention period, for example for a regulator’s request. Untick to have them deleted on the date shown." checked={r.keep_raw_data} disabled={busy} onChange={(e) => void keep(r.id, e.target.checked)} />}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}
