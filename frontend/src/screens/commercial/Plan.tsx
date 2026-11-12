import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { money, usePlan, type PlanPage } from '@/api/commercial';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextField, fmtDate } from '@/components/ui';
import './commercial.css';

const REGIONS = [{ value: 'us', label: 'US' }, { value: 'eu', label: 'EU' }, { value: 'in', label: 'India' }];

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
const monthName = (p: string) => new Date(`${p}-01T00:00:00`).toLocaleString('en-US', { month: 'long' });

/** G-01 Plans, entitlements and usage (`/staff/clients/:clientId/plan`): a tab of the client page. */
export function Plan() {
  const { clientId = '' } = useParams();
  const q = usePlan(clientId);
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const p = d.plan;
  const period = lastMonth();
  const exportNow = async (all: boolean) => {
    setMsg(null);
    try {
      const r = await api.post<{ id: string; rows: number }>('/staff/billing-export', { period, client_id: all ? null : clientId });
      window.location.assign(`/api/v1/staff/billing-export/${r.id}.csv`);
      setMsg({ tone: 'success', text: `Billing export for ${monthName(period)}: ${r.rows} rows.` });
      await qc.invalidateQueries({ queryKey: ['plan', clientId] });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  };
  return (
    <div className="page commercial">
      <PageHeader crumbs={[{ to: '/clients', label: 'Clients' }, { to: `/clients/${clientId}`, label: d.client.name }, { label: 'Plan' }]}
        title="Plan, entitlements and usage" subtitle={d.client.name}
        actions={<>
          {d.can_edit && <Button onClick={() => setEditing(true)}>Edit plan settings</Button>}
          {d.can_export && <Button variant="primary" onClick={() => exportNow(false)}>Billing export ({monthName(period)})</Button>}
        </>} />
      <ClientTabs clientId={clientId} active="plan" />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="plan-tiles">
        <div className="tile"><div className="tile-label">Plan</div><div className="tile-value">{p.plan_label}</div><div className="small muted">{p.tier ? `Tier ${p.tier}` : 'No tier'}</div></div>
        <div className="tile"><div className="tile-label">Term</div><div className="tile-value">{p.start_on ? `${fmtDate(p.start_on)} – ${fmtDate(p.term_end_on)}` : '—'}</div>
          <div className="small muted">{p.renewal_alert_on ? `Renewal opportunity from ${fmtDate(p.renewal_alert_on)}` : 'No order term'}{p.auto_renew ? ' · auto-renews' : ''}</div></div>
        <div className="tile"><div className="tile-label">Data region</div><div className="tile-value">{(p.data_region ?? '—').toUpperCase()}</div><div className="small muted">Change needs a migration ticket</div></div>
        <div className="tile"><div className="tile-label">Support</div><div className="tile-value">{p.support_level ?? '—'}</div>
          <div className="small muted">{p.onboarding_fee_waived ? 'Onboarding fee waived' : p.onboarding_fee_waived === false ? 'Onboarding fee charged' : ' '}</div></div>
      </div>
      <Card title="Entitlements · used vs limit">
        {d.entitlements.length === 0 ? <EmptyState>{p.from_order ? 'This order has no metered entitlements.' : 'No order yet: this client is on a plan set before orders, with no limits.'}</EmptyState> : (
          <div className="ent-grid">
            {d.entitlements.map((e) => (
              <div key={e.key} className={`ent ${e.over_plan ? 'over' : e.near_limit ? 'near' : ''}`}>
                <div className="ent-head"><span>{e.label}</span>
                  <strong>{e.hard ? (e.enabled ? 'On' : 'Off') : `${e.used ?? '—'} / ${e.limit}${e.unit ? ` ${e.unit}` : ''}`}{e.pct != null && !e.over_plan ? ` · ${e.pct}%` : ''}</strong>
                  {e.over_plan && <Badge tone="danger">Over plan</Badge>}</div>
                {!e.hard && <div className="bar" role="progressbar" aria-label={e.label} aria-valuenow={e.pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
                  <span style={{ width: `${Math.min(100, e.pct ?? 0)}%` }} /></div>}
              </div>
            ))}
          </div>
        )}
        {d.entitlements.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>Soft limits: the client keeps working. Overages go on the billing export, and the account owner gets an opportunity at 90%.
          API access and Trust Center are switched on or off by the plan.</p>}
      </Card>
      <Card title={`Order lines${p.order_ref ? ` (${p.order_ref})` : ''}`}>
        {(p.discount_one_time_pct || p.discount_recurring_pct) ? <p className="small muted" style={{ marginTop: 0 }}>Prices are list prices frozen from the proposal;
          {p.discount_one_time_pct ? ` ${p.discount_one_time_pct}% off one-time lines` : ''}{p.discount_one_time_pct && p.discount_recurring_pct ? ' and' : ''}
          {p.discount_recurring_pct ? ` ${p.discount_recurring_pct}% off recurring lines` : ''} on the billing export.</p> : null}
        {d.order_lines.length === 0 ? <EmptyState>No order lines.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Code</th><th>Line</th><th>Qty</th><th>Billing</th><th className="num">Unit price</th><th>Start</th><th>End</th><th>Entitlement</th></tr></thead>
            <tbody>{d.order_lines.map((l) => (
              <tr key={l.id}><td>{l.code}</td><td>{l.description}</td><td>{l.qty}</td><td>{l.billing}</td><td className="num">{money(l.unit_price)}</td>
                <td>{fmtDate(l.start_on)}</td><td>{l.end_on ? fmtDate(l.end_on) : '—'}</td><td className="small">{l.entitlement ?? '—'}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      {d.can_export && (
        <Card title="Billing exports" actions={<Button size="sm" onClick={() => exportNow(true)}>Export all clients ({monthName(period)})</Button>}>
          {d.exports.length === 0 ? <EmptyState>None yet. The all-clients export for the month before is written on the 1st.</EmptyState> : (
            <ul className="plain small">{d.exports.map((x) => (
              <li key={x.id}><a href={`/api/v1/staff/billing-export/${x.id}.csv`}>{x.period} · {x.all_clients ? 'all clients' : d.client.name}</a> <span className="muted">· {x.rows} rows · {fmtDate(x.run_at)}</span></li>
            ))}</ul>
          )}
        </Card>
      )}
      {editing && <PlanSettings d={d} onClose={() => setEditing(false)} onSaved={(v) => { qc.setQueryData(['plan', clientId], v); setEditing(false); setMsg({ tone: 'success', text: 'Plan settings saved.' }); }} />}
    </div>
  );
}

function PlanSettings({ d, onClose, onSaved }: { d: PlanPage; onClose: () => void; onSaved: (v: PlanPage) => void }) {
  const p = d.plan;
  const [f, setF] = useState({ tier: p.tier ?? '', support_level: p.support_level ?? '', term_end_on: p.term_end_on ?? '', data_region: p.data_region ?? 'us', migration_ticket: '',
    auto_renew: !!p.auto_renew, onboarding_fee_waived: !!p.onboarding_fee_waived });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const moving = !!p.data_region && f.data_region !== p.data_region;
  const save = async () => {
    setErr(null); setErrs({});
    try {
      onSaved(await api.patch<PlanPage>(`/staff/clients/${d.client.id}/plan`, { ...f, term_end_on: f.term_end_on || null, migration_ticket: moving ? f.migration_ticket : null }));
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); }
  };
  return (
    <Dialog title="Plan settings" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Tier" value={f.tier} onChange={(e) => setF({ ...f, tier: e.target.value })} error={errs.tier} />
        <TextField label="Term ends" type="date" value={f.term_end_on} onChange={(e) => setF({ ...f, term_end_on: e.target.value })} error={errs.term_end_on} />
        <TextField label="Support level" value={f.support_level} onChange={(e) => setF({ ...f, support_level: e.target.value })} error={errs.support_level} />
        <SelectField label="Data region" value={f.data_region} options={REGIONS} onChange={(e) => setF({ ...f, data_region: e.target.value })} error={errs.data_region}
          help="Set when the client is created. Moving it needs a migration ticket." />
        {moving && <TextField label="Migration ticket" value={f.migration_ticket} onChange={(e) => setF({ ...f, migration_ticket: e.target.value })} error={errs.migration_ticket} />}
        <Checkbox label="Renews automatically" checked={f.auto_renew} onChange={(e) => setF({ ...f, auto_renew: e.target.checked })} />
        <Checkbox label="Onboarding fee waived" checked={f.onboarding_fee_waived} onChange={(e) => setF({ ...f, onboarding_fee_waived: e.target.checked })} />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** The client page's tabs that are their own screens (plan); the rest are on the client page itself. */
export function ClientTabs({ clientId, active }: { clientId: string; active: string }) {
  return (
    <div className="tabs" role="tablist" aria-label="Client sections">
      <Link role="tab" aria-selected={false} to={`/clients/${clientId}`}>Overview</Link>
      <Link role="tab" aria-selected={active === 'plan'} className={active === 'plan' ? 'active' : ''} to={`/staff/clients/${clientId}/plan`}>Plan and usage</Link>
    </div>
  );
}
