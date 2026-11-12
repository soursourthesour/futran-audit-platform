import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hrs, money, type Banks, type Margins, type TimeRow, type Week } from '@/api/commercial';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import './commercial.css';

function monday(d: Date): string {
  const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  x.setUTCDate(x.getUTCDate() - ((x.getUTCDay() + 6) % 7));
  return x.toISOString().slice(0, 10);
}
function shift(iso: string, days: number): string {
  const x = new Date(`${iso}T00:00:00Z`);
  x.setUTCDate(x.getUTCDate() + days);
  return x.toISOString().slice(0, 10);
}
const DAY = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' });
const STATUS: Record<string, 'muted' | 'navy' | 'success' | 'warn'> = { draft: 'muted', submitted: 'navy', approved: 'success', returned: 'warn' };
const ROLE_LABEL: Record<string, string> = { chief_auditor: 'Chief Auditor', engagement_manager: 'Engagement Manager', auditor: 'Auditor', qa_reviewer: 'QA Reviewer',
  legal_reviewer: 'Legal/Compliance Reviewer', admin: 'Admin', sales_team: 'Sales Officer', sales_manager: 'Sales Manager', pricing_approver: 'Pricing Approver', price_list_owner: 'Price List Owner' };

/** G-03 Time and hours (`/staff/time`): every Futran person's weekly timesheet, hours banks and retainers with their
 *  balance, approvals, and the margin view for the Chief Auditor and Sales Manager. */
export function TimeAndHours() {
  const [params, setParams] = useSearchParams();
  const week = params.get('week') ?? monday(new Date());
  const qc = useQueryClient();
  const w = useQuery({ queryKey: ['week', week], queryFn: () => api.get<Week>(`/staff/time/${week}`) });
  const banks = useQuery({ queryKey: ['hours-banks'], queryFn: () => api.get<Banks>('/staff/hours-banks') });
  const [rows, setRows] = useState<TimeRow[]>([]);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  useEffect(() => { if (w.data) { setRows(w.data.rows); setDirty(false); } }, [w.data]);
  if (w.isLoading) return <div className="page"><Loading /></div>;
  if (!w.data) return <div className="page"><Alert tone="danger">{errorMessage(w.error)}</Alert></div>;
  const d = w.data;
  const days = d.days.slice(0, 5).concat(d.days.slice(5).filter((day) => rows.some((r) => r.hours[day])));
  const locked = d.status === 'submitted' || d.status === 'approved';
  const total = rows.reduce((s, r) => s + Object.values(r.hours).reduce((a, b) => a + (Number(b) || 0), 0), 0);
  const billable = rows.filter((r) => r.billable).reduce((s, r) => s + Object.values(r.hours).reduce((a, b) => a + (Number(b) || 0), 0), 0);
  const set = (i: number, patch: Partial<TimeRow>) => { setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))); setDirty(true); };
  const save = async () => {
    setMsg(null);
    try { qc.setQueryData(['week', week], await api.put<Week>(`/staff/time/${week}`, { rows })); setMsg({ tone: 'success', text: 'Week saved.' }); await banks.refetch(); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  };
  const submit = async () => {
    setMsg(null);
    try {
      if (dirty) await api.put<Week>(`/staff/time/${week}`, { rows });
      qc.setQueryData(['week', week], await api.post<Week>(`/staff/time/${week}/submit`));
      setMsg({ tone: 'success', text: 'Week submitted for approval.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  };
  const go = (iso: string) => setParams((p) => { p.set('week', iso); return p; });
  return (
    <div className="page commercial">
      <PageHeader title="Time and hours" subtitle={`Week of ${fmtDate(week)} · ${hrs(total)} h logged · ${hrs(billable)} billable`}
        actions={<>
          <Button size="sm" variant="ghost" onClick={() => go(shift(week, -7))}>Previous week</Button>
          <Button size="sm" variant="ghost" onClick={() => go(shift(week, 7))}>Next week</Button>
          {!locked && <Button variant="primary" onClick={submit} disabled={rows.length === 0}>Submit week</Button>}
        </>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card title="Timesheet" actions={<Badge tone={STATUS[d.status]}>{d.status === 'draft' ? 'Draft' : d.status === 'submitted' ? 'Submitted' : d.status === 'approved' ? 'Approved' : 'Returned'}</Badge>}>
        <div className="table-wrap"><table className="table timesheet">
          <thead><tr><th>Charged to</th><th>Activity</th><th>Billable</th>{days.map((day) => <th key={day} className="num">{DAY(day)}</th>)}<th className="num">Total</th>{!locked && <th />}</tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={days.length + 5} className="muted">No time this week yet.</td></tr>}
            {rows.map((r, i) => {
              const rowTotal = Object.values(r.hours).reduce((a, b) => a + (Number(b) || 0), 0);
              const target = d.targets.find((t) => t.key === r.target);
              return (
                <tr key={i}>
                  <td>{locked ? r.label : (
                    <select aria-label="Charged to" value={r.target} onChange={(e) => { const t = d.targets.find((x) => x.key === e.target.value); set(i, { target: e.target.value, label: t?.label ?? '', billable: t?.billable_default ?? false }); }}>
                      {d.targets.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>)}</td>
                  <td>{locked ? r.activity_label : (
                    <select aria-label="Activity" value={r.activity} onChange={(e) => set(i, { activity: e.target.value })}>
                      {d.activities.map((a) => <option key={a.code} value={a.code}>{a.label}</option>)}
                    </select>)}</td>
                  <td>{locked || target?.kind === 'internal' ? (r.billable_label ?? (r.billable ? 'Yes' : 'No')) : (
                    <label className="small"><input type="checkbox" checked={r.billable} onChange={(e) => set(i, { billable: e.target.checked })} /> {r.billable ? 'Yes' : 'No'}</label>)}</td>
                  {days.map((day) => (
                    <td key={day} className="num">{locked ? (r.hours[day] ? hrs(r.hours[day]) : '') : (
                      <input className="hours" aria-label={`${DAY(day)} hours`} type="number" min={0} max={24} step={0.25} value={r.hours[day] ?? ''}
                        onChange={(e) => set(i, { hours: { ...r.hours, [day]: e.target.value === '' ? 0 : Number(e.target.value) } })} />)}</td>
                  ))}
                  <td className="num"><strong>{hrs(rowTotal)}</strong></td>
                  {!locked && <td><Button size="sm" variant="ghost" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); }}>Remove</Button></td>}
                </tr>
              );
            })}
          </tbody>
        </table></div>
        {!locked && (
          <div className="row" style={{ marginTop: 12 }}>
            <Button size="sm" onClick={() => { const t = d.targets[0]; setRows([...rows, { target: t.key, label: t.label, activity: t.kind === 'internal' ? 'other' : 'fieldwork', billable: t.billable_default, note: null, hours: {} }]); setDirty(true); }}>Add row</Button>
            <Button onClick={save} disabled={!dirty}>Save</Button>
          </div>
        )}
      </Card>
      <BanksCard banks={banks.data} canActivate={d.can_manage_retainers} onChange={() => banks.refetch()} />
      {d.can_approve && <ApprovalsCard week={week} />}
      {d.can_view_margins && <MarginsCard />}
      {d.can_manage_costs && <CostsCard />}
    </div>
  );
}

function BanksCard({ banks, canActivate, onChange }: { banks?: Banks; canActivate: boolean; onChange: () => void }) {
  const [activating, setActivating] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  if (!banks) return <Card title="Hours banks and retainers"><Loading /></Card>;
  const empty = banks.banks.length === 0 && banks.retainers.length === 0;
  const TYPE: Record<string, string> = { incident_response: 'M-12 Incident retainer', fractional_officer: 'X-01 Fractional AI officer', compliance: 'Compliance retainer' };
  return (
    <Card title="Hours banks and retainers">
      {empty ? <EmptyState>No hours banks or retainers yet. They are created when a proposal that includes them is accepted.</EmptyState> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Client</th><th>Type</th><th>Balance</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {banks.banks.map((b) => (
              <tr key={b.id}><td><Link to={`/staff/clients/${b.client_id}/plan`}>{b.client_name}</Link></td><td>{b.code} {b.label} ({hrs(b.purchased)} h)</td>
                <td>{hrs(b.remaining)} h left · {b.pct ?? 0}% used{b.over > 0 && <> · <Badge tone="danger">{hrs(b.over)} h over</Badge></>}{(b.pct ?? 0) >= 80 && b.over === 0 && <> <Badge tone="warn">80%</Badge></>}</td>
                <td>{b.expires_on ? fmtDate(b.expires_on) : '—'}</td><td /></tr>
            ))}
            {banks.retainers.map((r) => (
              <tr key={r.id}><td><Link to={`/staff/clients/${r.client_id}/plan`}>{r.client_name}</Link></td><td>{TYPE[r.type] ?? r.type}</td>
                <td>{r.type === 'incident_response'
                  ? (r.status === 'activated' ? `Activated ${fmtDate(r.activated_at)} · ${hrs(r.hours_billed)} h billed${r.hourly_rate ? ` at ${money(r.hourly_rate)}/h` : ''}` : `Standing · ${money(r.monthly_fee)} a month`)
                  : `${hrs(r.hours_this_month)}${r.monthly_hours ? ` / ${hrs(r.monthly_hours)}` : ''} h this month`}</td>
                <td>Monthly</td>
                <td>{canActivate && r.type === 'incident_response' && r.status === 'standing' && <Button size="sm" onClick={() => { setActivating(r.id); setReason(''); setErr(null); }}>Activate</Button>}</td></tr>
            ))}
          </tbody>
        </table></div>
      )}
      {activating && (
        <Dialog title="Activate the incident retainer" onClose={() => setActivating(null)}>
          <div className="stack">
            {err && <Alert tone="danger">{err}</Alert>}
            <p className="small" style={{ margin: 0 }}>Opens an incident engagement for the client and starts billable time at the retainer's hourly rate.</p>
            <TextArea label="What is the incident?" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="row"><Button variant="primary" onClick={async () => {
              try { await api.post(`/staff/retainers/${activating}/activate`, { reason }); setActivating(null); onChange(); } catch (e) { setErr(errorMessage(e)); }
            }}>Activate</Button><Button variant="ghost" onClick={() => setActivating(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </Card>
  );
}

function ApprovalsCard({ week }: { week: string }) {
  const q = useQuery({ queryKey: ['time-approvals'], queryFn: () => api.get<{ user_id: string; user_name: string; week_start: string; hours: number; billable: number }[]>('/staff/time-approvals') });
  const [err, setErr] = useState<string | null>(null);
  const decide = async (user_id: string, ws: string, approve: boolean) => {
    setErr(null);
    const note = approve ? null : window.prompt('What needs changing?');
    if (!approve && !note) return;
    try { await api.post(`/staff/time/${ws}/decide`, { user_id, approve, note }); await q.refetch(); } catch (e) { setErr(errorMessage(e)); }
  };
  void week;
  return (
    <Card title="Timesheets to approve">
      {err && <Alert tone="danger">{err}</Alert>}
      {!q.data || q.data.length === 0 ? <EmptyState>Nothing waiting for you.</EmptyState> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Person</th><th>Week of</th><th className="num">Hours</th><th className="num">Billable</th><th /></tr></thead>
          <tbody>{q.data.map((r) => (
            <tr key={`${r.user_id}${r.week_start}`}><td>{r.user_name}</td><td>{fmtDate(r.week_start)}</td><td className="num">{hrs(r.hours)}</td><td className="num">{hrs(r.billable)}</td>
              <td><div className="row"><Button size="sm" variant="primary" onClick={() => decide(r.user_id, r.week_start, true)}>Approve</Button>
                <Button size="sm" onClick={() => decide(r.user_id, r.week_start, false)}>Return</Button></div></td></tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

function MarginsCard() {
  const q = useQuery({ queryKey: ['margins'], queryFn: () => api.get<Margins>('/staff/margins') });
  if (!q.data) return <Card title="Margin by engagement"><Loading /></Card>;
  const m = q.data;
  return (
    <Card title="Margin by engagement (Chief Auditor, Sales Manager)">
      {m.engagements.length === 0 ? <EmptyState>No engagements with a fee or time yet.</EmptyState> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Engagement</th><th className="num">Fee</th><th className="num">Hours</th><th className="num">Cost</th><th className="num">Margin</th></tr></thead>
          <tbody>{m.engagements.map((r) => (
            <tr key={r.engagement_id}><td><Link to={`/e/${r.engagement_id}/commercial`}>{r.label}</Link></td><td className="num">{money(r.fee)}</td><td className="num">{hrs(r.hours)}</td>
              <td className="num">{r.cost == null ? <span className="muted">No cost</span> : money(r.cost)}</td>
              <td className="num">{r.margin_pct == null ? '—' : <span className={r.margin_pct < 0 ? 'neg' : ''}>{r.margin_pct}%</span>}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>Cost = hours × standard cost per role, entered by the Futran Admin.
        {m.missing_costs.length > 0 && ` No standard cost yet for ${m.missing_costs.map((r) => ROLE_LABEL[r] ?? r).join(', ')}.`}</p>
    </Card>
  );
}

function CostsCard() {
  const q = useQuery({ queryKey: ['standard-costs'], queryFn: () => api.get<Margins['costs']>('/staff/standard-costs') });
  const [f, setF] = useState({ role: 'auditor', cost_per_hour: '', effective_from: new Date().toISOString().slice(0, 10) });
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();
  const save = async () => {
    setErr(null);
    try { qc.setQueryData(['standard-costs'], await api.post('/staff/standard-costs', { ...f, cost_per_hour: Number(f.cost_per_hour) })); setF({ ...f, cost_per_hour: '' }); await qc.invalidateQueries({ queryKey: ['margins'] }); }
    catch (e) { setErr(errorMessage(e)); }
  };
  return (
    <Card title="Standard cost per hour">
      {err && <Alert tone="danger">{err}</Alert>}
      {q.data && q.data.length > 0 && (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Role</th><th className="num">Cost per hour</th><th>From</th></tr></thead>
          <tbody>{q.data.map((c, i) => <tr key={i}><td>{ROLE_LABEL[c.role] ?? c.role}</td><td className="num">{money(c.cost_per_hour, true)}</td><td>{fmtDate(c.effective_from)}</td></tr>)}</tbody>
        </table></div>
      )}
      <div className="row cost-form">
        <SelectField label="Role" value={f.role} options={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))} onChange={(e) => setF({ ...f, role: e.target.value })} />
        <TextField label="Cost per hour (US$)" type="number" min={0} value={f.cost_per_hour} onChange={(e) => setF({ ...f, cost_per_hour: e.target.value })} />
        <TextField label="From" type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} />
        <Button onClick={save} disabled={!f.cost_per_hour}>Add</Button>
      </div>
    </Card>
  );
}
