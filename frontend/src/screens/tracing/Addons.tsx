import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { useAddons, type AddonRequest } from '@/api/tracing';
import { Alert, Badge, Button, Dialog, Loading, PageHeader, TextArea, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { unlockHelp as H } from '@/help/tracing';
import { UnlockDialog } from './UnlockDialog';
import './tracing.css';

const STATUS_TONE: Record<string, 'navy' | 'success' | 'muted' | 'danger'> = { requested: 'navy', approved: 'success', active: 'success', declined: 'danger', cancelled: 'muted' };

/** Add-ons `/addons`: the Executive Sponsor approves R8 requests here; the CAICO and Client Admin ask and follow them. */
export function AddonsPage() {
  const q = useAddons();
  const { data: me } = useMe();
  const qc = useQueryClient();
  const [unlocking, setUnlocking] = useState(false);
  const [deciding, setDeciding] = useState<{ r: AddonRequest; approve: boolean } | null>(null);
  const [cancelling, setCancelling] = useState<AddonRequest | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const waiting = d.requests.filter((r) => r.status === 'requested');
  const active = d.systems.filter((s) => s.status === 'active').length;
  const done = async (m: string) => { setDeciding(null); setCancelling(null); setUnlocking(false); setFlash(m); await Promise.all([qc.invalidateQueries({ queryKey: ['addons'] }), qc.invalidateQueries({ queryKey: ['tracing'] }), qc.invalidateQueries({ queryKey: ['register'] })]); };
  return (
    <div className="page reg-page">
      <PageHeader title="Add-ons" subtitle="The tracing and incident module: action traces for agents, an incident register with regulator deadline timers, and exports for regulators and Futran."
        actions={d.can_request ? <Button variant="primary" onClick={() => setUnlocking(true)}>Unlock tracing</Button> : undefined} />
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="reg-kpis" role="list" aria-label="Add-on summary">
        <div className="tile reg-kpi" role="listitem"><div className="value">{active}</div><div className="label">Systems with tracing</div></div>
        {(() => { const n = d.systems.filter((s) => s.status === 'locked' && s.recommended).length; return <div className={`tile reg-kpi ${n ? 'reg-kpi-warn' : ''}`} role="listitem"><div className="value">{n}</div><div className="label">Recommended, not yet traced</div></div>; })()}
        <div className="tile reg-kpi" role="listitem"><div className="value">{waiting.length}</div><div className="label">Waiting for approval</div></div>
      </div>
      {d.can_approve && waiting.length > 0 && (
        <section className="card" aria-labelledby="addon-wait-h">
          <div className="card-header"><h2 id="addon-wait-h">Waiting for your approval</h2></div>
          <div className="card-body stack">
            {waiting.map((r) => (
              <article key={r.id} className="trc-request" aria-label={`Request from ${r.requested_by}`}>
                <div className="stack-sm">
                  <strong>Tracing module · {r.plan_label} · {r.trial ? '30-day free trial, then paid' : 'paid from today'}</strong>
                  <span className="small">Asked by {r.requested_by} on {fmtDateTime(r.requested_at)}{r.approver ? ` · sent to ${r.approver}` : ''}</span>
                  <span>{r.systems.length} system{r.systems.length === 1 ? '' : 's'}: {r.systems.join(', ')}</span>
                  {r.note && <span className="small">Note: {r.note}</span>}
                </div>
                {r.requested_by_id === me?.user.id
                  ? <p className="small muted" style={{ margin: 0 }}>You asked for this, so another Executive Sponsor approves it.</p>
                  : <div className="row"><Button variant="primary" onClick={() => setDeciding({ r, approve: true })}>Approve</Button><Button onClick={() => setDeciding({ r, approve: false })}>Decline</Button></div>}
              </article>
            ))}
            <p className="small muted" style={{ margin: 0 }}>{H.decision} Buying the module does not change audit results; Futran auditors keep reviewing these systems independently.</p>
          </div>
        </section>
      )}
      <section className="card" aria-labelledby="addon-req-h">
        <div className="card-header"><h2 id="addon-req-h">Requests and subscriptions</h2></div>
        <div className="card-body">
          <DataGrid label="Add-on requests" rows={d.requests} rowId={(r) => r.id} rowLabel={(r) => `${r.plan_label} of ${fmtDate(r.requested_at)}`} initialSort={{ key: 'asked', dir: 'desc' }}
            emptyText={d.can_request ? 'No requests yet. Unlock tracing to ask your Executive Sponsor.' : 'No requests yet.'}
            columns={[
              { key: 'asked', header: 'Asked', value: (r) => r.requested_at, render: (r) => fmtDate(r.requested_at) },
              { key: 'systems', header: 'Systems', value: (r) => r.systems.join(', '), render: (r) => <span className="small">{r.plan === 'per_system' ? r.systems.join(', ') : `${r.plan_label} (${r.systems.join(', ')} at the time)`}</span> },
              { key: 'plan', header: 'Plan', value: (r) => r.plan_label },
              { key: 'start', header: 'Start', value: (r) => (r.trial ? 1 : 0), render: (r) => <span className="small">{r.trial ? (r.trial_ends_on ? `Trial until ${fmtDate(r.trial_ends_on)}` : '30-day trial') : 'Paid'}</span> },
              { key: 'by', header: 'Asked by', value: (r) => r.requested_by ?? '' },
              { key: 'approver', header: 'Approver', value: (r) => r.approved_by ?? r.approver ?? '' },
              { key: 'status', header: 'Status', value: (r) => r.status_label, render: (r) => <><Badge tone={STATUS_TONE[r.status]}>{r.status_label}</Badge>{(r.decision_comment || r.cancel_reason) && <div className="small muted">{r.cancel_reason ?? r.decision_comment}</div>}</> },
            ]}
            rowActions={(r) => [
              { label: 'Approve', disabled: !d.can_approve || r.status !== 'requested' || r.requested_by_id === me?.user.id, onSelect: () => setDeciding({ r, approve: true }) },
              { label: 'Decline', disabled: !d.can_approve || r.status !== 'requested' || r.requested_by_id === me?.user.id, onSelect: () => setDeciding({ r, approve: false }) },
              { label: 'Cancel subscription', danger: true, disabled: !d.can_approve || !['requested', 'active'].includes(r.status), onSelect: () => setCancelling(r) },
            ]} />
        </div>
      </section>
      {unlocking && <UnlockDialog onClose={() => setUnlocking(false)} onSent={done} />}
      {deciding && <DecideDialog r={deciding.r} approve={deciding.approve} onClose={() => setDeciding(null)} onDone={done} />}
      {cancelling && <CancelDialog r={cancelling} onClose={() => setCancelling(null)} onDone={done} />}
    </div>
  );
}

function DecideDialog({ r, approve, onClose, onDone }: { r: AddonRequest; approve: boolean; onClose: () => void; onDone: (m: string) => void }) {
  const [comment, setComment] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function go() {
    setErr(null); setFe({});
    try {
      await api.post(`/addons/requests/${r.id}/decide`, { approve, comment });
      onDone(approve ? `Approved. Tracing is now open on ${r.plan === 'per_system' ? r.systems.join(', ') : `every system the ${r.plan_label.toLowerCase()} plan covers`}.` : 'Declined. The person who asked has been told.');
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={approve ? 'Approve the tracing module' : 'Decline the tracing module'} onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0 }}>{r.plan_label} · {r.trial ? '30-day free trial, then paid' : 'paid from today'} · {r.systems.join(', ')}</p>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label={approve ? 'Comment (optional)' : 'Reason *'} help={approve ? H.decision : H.declineReason} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} error={fe.comment} />
        <div className="row"><Button variant={approve ? 'primary' : 'danger'} onClick={go}>{approve ? 'Approve' : 'Decline'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function CancelDialog({ r, onClose, onDone }: { r: AddonRequest; onClose: () => void; onDone: (m: string) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function go() {
    setErr(null); setFe({});
    try { await api.post(`/addons/requests/${r.id}/cancel`, { reason }); onDone('Cancelled. The Tracing tab is locked again; records already made are kept.'); }
    catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title="Cancel the tracing module" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Reason *" help={H.cancelReason} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} error={fe.reason} />
        <div className="row"><Button variant="danger" onClick={go}>Cancel subscription</Button><Button onClick={onClose}>Keep it</Button></div>
      </div>
    </Dialog>
  );
}
