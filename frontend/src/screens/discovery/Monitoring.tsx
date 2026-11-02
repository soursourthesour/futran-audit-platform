import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMonitoring, type MonitorResultRow, type MonitoringPage, type MonitorStatus } from '@/api/discovery';
import { Alert, Badge, Button, Card, Loading, PageHeader, SelectField, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { monitoringHelp as H } from '@/help/discovery';
import './discovery.css';

const STATUS_LABEL: Record<MonitorStatus, string> = { healthy: 'Healthy', attention: 'Attention', failed: 'Failed', not_started: 'Not started' };
const STATUS_TONE: Record<MonitorStatus, 'success' | 'warn' | 'danger' | 'muted'> = { healthy: 'success', attention: 'warn', failed: 'danger', not_started: 'muted' };
// client paths a result links to, and where the same page is on Futran's client page
const FUTRAN_PATHS: Record<string, string> = { '/integrations': 'integrations', '/remediation': 'remediation', '/governance': 'governance', '/documents': 'documents' };

function linkFor(r: MonitorResultRow, clientId?: string): string | null {
  if (!r.action_link) return null;
  if (!clientId) return r.action_link;
  const [path, query] = r.action_link.split('?');
  const sub = FUTRAN_PATHS[path];
  return sub ? `/clients/${clientId}/${sub}${query ? `?${query}` : ''}` : null;
}

/** Screen 31, Continuous monitoring. `/monitoring` for the client's CAICO and Client Admin; `/clients/:clientId/monitoring`
 *  for the Futran team, where the Futran Admin also sets the client's plan. */
export function Monitoring() {
  const { clientId } = useParams();
  const q = useMonitoring(clientId);
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const running = useRef(false);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const monitored = d.plan !== 'audit_only';
  const refresh = () => qc.invalidateQueries({ queryKey: ['monitoring'] });
  const once = async (key: string, fn: () => Promise<void>) => {
    if (running.current) return;
    running.current = true; setBusy(key); setFlash(null);
    try { await fn(); } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); } finally { running.current = false; setBusy(null); }
  };
  const runNow = () => once('run', async () => {
    const r = await api.post<{ counts: Record<MonitorStatus, number> }>('/monitoring/run');
    setFlash({ tone: 'success', text: `Checks run: ${r.counts.failed} failed, ${r.counts.attention} need attention, ${r.counts.healthy} healthy.` });
    await refresh();
  });
  const act = (r: MonitorResultRow) => once(r.id, async () => {
    const out = await api.post<{ message: string }>(`/monitoring/results/${r.id}/act`);
    setFlash({ tone: 'success', text: out.message });
    await refresh();
  });
  const crumbs = clientId ? [{ to: `/clients/${clientId}`, label: d.organization.name }, { label: 'Monitoring' }] : undefined;
  const sub = monitored
    ? `${d.plan_label} plan · checks run monthly and after each connector sync · ${d.last_run ? `last run ${fmtDateTime(d.last_run.at)}` : 'not run yet'}`
    : 'Audit only plan. Monitoring runs for clients on a Monitor plan.';
  return (
    <div className="page dsc-page">
      <PageHeader title="Continuous monitoring" crumbs={crumbs} subtitle={sub}
        actions={monitored && d.can_act ? <Button variant="primary" disabled={busy !== null} onClick={runNow} title={H.runNow}>Run checks now</Button> : undefined} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <p className="dsc-review"><strong>Next Futran annual review:</strong> {d.next_review_on ? fmtDate(d.next_review_on) : 'not set'}</p>
      {d.can_set_plan && <PlanForm d={d} clientId={clientId!} onSaved={async (m) => { setFlash({ tone: 'success', text: m }); await refresh(); }} />}
      {!monitored ? (
        <Card title="What the Monitor plan adds">
          <ul className="dsc-offers">{d.offers.map((o) => <li key={o}>{o}</li>)}</ul>
          <p className="small muted" style={{ margin: 0 }}>{clientId ? 'The Futran Admin sets the plan above.' : 'Ask your Futran contact to move you to the Monitor plan.'}</p>
        </Card>
      ) : (
        <>
          <div className="reg-kpis dsc-kpis" role="list" aria-label="Check results">
            {(['healthy', 'attention', 'failed', 'not_started'] as MonitorStatus[]).map((s) => (
              <div key={s} role="listitem" className={`tile reg-kpi dsc-kpi-${s}`}><div className="value">{d.kpis?.[s] ?? 0}</div><div className="label">{STATUS_LABEL[s]}</div></div>
            ))}
          </div>
          <section className="card" aria-labelledby="dsc-need-h">
            <div className="card-header"><h2 id="dsc-need-h">Checks needing action</h2></div>
            <div className="card-body stack">
              {!d.last_run && <p className="small muted" style={{ margin: 0 }}>No run yet. {d.can_act ? 'Run the checks now, or wait for the monthly run.' : 'The first run happens at the start of next month or after the next connector sync.'}</p>}
              {d.last_run && d.needs_action.length === 0 && <p className="small" style={{ margin: 0 }}>Nothing needs action.</p>}
              <ul className="dsc-needs">
                {d.needs_action.map((r) => {
                  const link = linkFor(r, clientId);
                  return (
                    <li key={r.id} className={`dsc-need dsc-need-${r.status}`}>
                      <Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Badge>
                      <div className="dsc-need-text">
                        <strong>{r.check}</strong>
                        <span className="small">{r.object_label}{r.detail ? ` · ${r.detail}` : ''}</span>
                        {r.action_taken && <span className="small muted">{r.action_label} started {fmtDate(r.action_taken_at)}</span>}
                      </div>
                      <div className="dsc-need-act">
                        {r.action_kind === 'server' && d.can_act && !r.action_taken && <Button size="sm" disabled={busy !== null} onClick={() => act(r)}>{r.action_label}</Button>}
                        {r.action_kind === 'link' && link && <Link className="btn btn-sm" to={link}>{r.action_label}</Link>}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <p className="small muted" style={{ margin: 0 }}>{H.page}</p>
            </div>
          </section>
          {d.healthy.length > 0 && (
            <section className="card" aria-labelledby="dsc-ok-h">
              <div className="card-header"><h2 id="dsc-ok-h">Other checks</h2></div>
              <div className="card-body">
                <DataGrid<MonitorResultRow> label="Other checks" rows={d.healthy} rowId={(r) => r.id} initialSort={{ key: 'status', dir: 'desc' }}
                  columns={[
                    { key: 'check', header: 'Check', value: (r) => r.check },
                    { key: 'object', header: 'Item', value: (r) => r.object_label },
                    { key: 'detail', header: 'Result', value: (r) => r.detail, render: (r) => <span className="small">{r.detail}</span> },
                    { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Badge> },
                  ]} />
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function PlanForm({ d, clientId, onSaved }: { d: MonitoringPage; clientId: string; onSaved: (m: string) => void | Promise<void> }) {
  const [plan, setPlan] = useState<string>(d.plan);
  const [review, setReview] = useState(d.next_review_on ?? '');
  const [note, setNote] = useState(d.subscription?.note ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    try {
      await api.put(`/clients/${clientId}/subscription`, { plan, next_review_on: review || null, note: note || null });
      await onSaved(`Plan set to ${d.plans.find((p) => p.value === plan)?.label}.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="Plan">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="dsc-plan-fields">
          <SelectField label="Plan *" help={H.plan} options={d.plans} value={plan} onChange={(e) => setPlan(e.target.value)} error={fe.plan} />
          <TextField label="Next Futran annual review" help={H.nextReview} type="date" value={review} onChange={(e) => setReview(e.target.value)} error={fe.next_review_on} />
          <TextField label="Note" help={H.note} value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
        </div>
        <div className="row"><Button variant="primary" disabled={busy} onClick={save}>Save plan</Button></div>
      </div>
    </Card>
  );
}
