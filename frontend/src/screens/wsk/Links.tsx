import { useState } from 'react';
import './wsk.css';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import type { ClientBiasData } from '@/api/wsk';

/** On the Futran client page: heat map and lineage, the annual review, and changes since the prior audit. */
export function ClientInsightLinks({ clientId, engagement }: { clientId: string; engagement: { id: string; status: string; type_label: string } }) {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[] | null>(null);
  const live = !['draft', 'pending_approval'].includes(engagement.status);
  const canStart = engagement.status === 'completed' && can(me, 'start_annual_review');
  if (!live && !can(me, 'view_heatmap')) return null;
  async function start() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const out = await api.post<{ notices?: string[] }>(`/engagements/${engagement.id}/annual-review`);
      await qc.invalidateQueries({ queryKey: ['client-page', clientId] });
      if (out.notices && out.notices.length) setNotices(out.notices);
      else navigate(`/clients/${clientId}/setup/company`);
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
          {notices ? (
            <div className="stack">
              <p className="small" style={{ margin: 0 }}>The draft engagement has been created.</p>
              {notices.map((n) => <Alert key={n} tone="warn">{n}</Alert>)}
              <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button variant="primary" onClick={() => navigate(`/clients/${clientId}/setup/company`)}>Review the draft</Button></div>
            </div>
          ) : (
          <div className="stack">
            <p className="small" style={{ margin: 0 }}>A new draft engagement is created for the next twelve months with the same scope, laws, contacts and team. Systems, the client's own answers and evidence links are carried forward: the client confirms each answer or updates it, and you answer, verify and re-test again. A Lead Auditor who helped write the client's policies is not copied in. Review the draft and submit it for approval as usual.</p>
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button onClick={() => setAsk(false)}>Cancel</Button><Button variant="primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start annual review'}</Button></div>
          </div>
          )}
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
      <PageHeader title="Bias test data" subtitle="Applicant data your auditor used for bias tests. It stays in your organization’s storage and is deleted at the end of the engagement retention period unless you keep it, for example for a regulator’s request. The results are always kept." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card>
        {q.data.runs.length === 0 ? <EmptyState>No bias test data has been uploaded.</EmptyState> : (
          <ul className="data-list">{q.data.runs.map((r) => (
            <li key={r.id}>
              <div><strong>{r.system}</strong><div className="small muted">{r.dataset_filename} · tested {fmtDate(r.run_at)}</div>
                <div className="small">{r.raw_deleted_at ? `Raw data deleted ${fmtDate(r.raw_deleted_at)}` : r.keep_raw_data ? 'Kept after the retention period' : r.raw_delete_on ? `Deleted on ${fmtDate(r.raw_delete_on)} unless kept` : 'Kept until the engagement retention period ends, then deleted unless kept'}</div></div>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>{r.raw_deleted_at ? null : r.keep_raw_data
                ? <><Badge tone="navy">Kept</Badge><Button size="sm" disabled={busy} onClick={() => void keep(r.id, false)} aria-label={`Let ${r.dataset_filename ?? 'this file'} be deleted at the end of the retention period`}>Let it be deleted</Button></>
                : <Button size="sm" disabled={busy} onClick={() => void keep(r.id, true)} aria-label={`Keep ${r.dataset_filename ?? 'this file'} after the retention period`}>Keep</Button>}</div>
            </li>
          ))}</ul>
        )}
      </Card>
    </div>
  );
}
