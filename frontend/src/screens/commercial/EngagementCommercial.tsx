import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { money, useCommercial, type ChangeOrder, type CommercialPage } from '@/api/commercial';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import './commercial.css';

const STATUS_TONE: Record<string, 'success' | 'warn' | 'danger' | 'muted' | 'navy'> = {
  draft: 'muted', awaiting_futran_approval: 'warn', awaiting_client: 'navy', approved: 'success', rejected: 'danger',
};

/** G-02 Engagement commercials (`/e/:engagementId/commercial`), a tab of the engagement. Fees and prices come from the
 *  server only for the Chief Auditor, Engagement Manager, sales roles and Admin; Auditors get a 403 here. */
export function EngagementCommercial() {
  const { engagementId = '' } = useParams();
  const q = useCommercial(engagementId);
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><PageHeader title="Commercial" /><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const e = d.engagement;
  const refresh = () => qc.invalidateQueries({ queryKey: ['commercial', engagementId] });
  const co = d.change_orders.find((c) => c.id === selected) ?? null;
  const act = async (path: string, body: unknown, ok: string) => {
    setMsg(null);
    try { await api.post(path, body); setMsg({ tone: 'success', text: ok }); await refresh(); } catch (ex) { setMsg({ tone: 'danger', text: errorMessage(ex) }); }
  };
  return (
    <div className="page commercial">
      <PageHeader crumbs={[{ to: `/clients/${e.client_id}`, label: e.client_name }, { label: e.name }]} title="Commercial" subtitle={`${e.client_name} · ${e.name}${e.audit_ref ? ` · ${e.audit_ref}` : ''}`}
        actions={d.can_edit ? <Button onClick={() => setEditing(true)}>Edit fee and milestones</Button> : undefined} />
      <p className="small muted fee-note">Visible to Chief Auditor, Engagement Manager, Sales and Admin. Hidden from Auditors.</p>
      <div className="tabs" role="tablist" aria-label="Engagement sections">
        <Link role="tab" aria-selected={false} to={`/clients/${e.client_id}`}>Overview</Link>
        <Link role="tab" aria-selected={false} to={`/clients/${e.client_id}/systems`}>Scope and systems</Link>
        <Link role="tab" aria-selected className="active" to={`/e/${e.id}/commercial`}>Commercial</Link>
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <Card title="Order lines on this engagement" actions={d.order ? <span className="small muted">{d.order.ref}{d.order.po_number ? ` · PO ${d.order.po_number}` : ''}</span> : undefined}>
            {d.order_lines.length === 0 && d.change_orders.length === 0 ? <EmptyState>{d.has_commercials ? 'No order lines.' : 'This engagement did not come from an order. Set the fee to track it.'}</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Code</th><th>Line</th><th>Qty</th><th className="num">Value</th><th>Deliverable</th></tr></thead>
                <tbody>
                  {d.order_lines.filter((l) => !l.change_order_id).map((l) => (
                    <tr key={l.id}><td>{l.code}</td><td>{l.description}</td><td>{l.qty}</td><td className="num">{money(l.value)}</td>
                      <td className="small">{d.deliverables.find((x) => x.code === l.code)?.text.split('\n')[0] ?? '—'}</td></tr>
                  ))}
                  {d.change_orders.filter((c) => c.status !== 'rejected').map((c) => (
                    <tr key={c.id} className="co-row"><td><button type="button" className="linklike" onClick={() => setSelected(c.id)}>{c.ref}</button></td>
                      <td>Change order: {c.lines.map((l) => `${l.qty} × ${l.description ?? l.code} (${l.code})`).join(', ')}</td><td>{c.lines[0]?.qty}</td>
                      <td className="num">{money(c.value)}</td><td><Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge></td></tr>
                  ))}
                </tbody>
                {d.fee_total != null && <tfoot><tr><td colSpan={3}><strong>Fee</strong></td><td className="num"><strong>{money(d.fee_total)}</strong></td><td /></tr></tfoot>}
              </table></div>
            )}
          </Card>
          <Card title="Billing milestones">
            {d.milestones.length === 0 ? <EmptyState>No milestones.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Milestone</th><th>Trigger</th><th className="num">Amount</th><th>Status</th></tr></thead>
                <tbody>{d.milestones.map((m, i) => (
                  <tr key={i}><td>{m.label}</td><td>{m.trigger_label}</td><td className="num">{money(m.amount)}</td><td>{m.reached_on ? <Badge tone="success">{m.status}</Badge> : <span className="muted">{m.status}</span>}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
          {d.deliverables.length > 0 && (
            <Card title="Deliverables">
              <ul className="plain">{d.deliverables.map((x) => <li key={x.code}><strong>{x.code}</strong> <span className="pre-line small">{x.text}</span></li>)}</ul>
            </Card>
          )}
          <Card title="Change orders">
            {d.change_orders.length === 0 ? <EmptyState>None.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Ref</th><th>Change</th><th>Raised by</th><th className="num">Value</th><th>Status</th></tr></thead>
                <tbody>{d.change_orders.map((c) => (
                  <tr key={c.id} className={selected === c.id ? 'selected' : ''}><td><button type="button" className="linklike" onClick={() => setSelected(c.id)}>{c.ref}</button></td>
                    <td>{c.kind_label}</td><td>{c.raised_by}</td><td className="num">{money(c.value)}</td><td><Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge></td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
        </div>
        <div className="side stack">
          {co ? <ChangeOrderPanel d={d} co={co} onAct={act} onClose={() => setSelected(null)} />
            : d.can_raise ? <RaiseChangeOrder d={d} onRaised={async (c) => { setSelected(c.id); setMsg({ tone: 'success', text: `${c.ref} raised.` }); await refresh(); }} /> : null}
        </div>
      </div>
      {editing && <EditFee d={d} onClose={() => setEditing(false)} onSaved={(v) => { qc.setQueryData(['commercial', engagementId], v); setEditing(false); setMsg({ tone: 'success', text: 'Fee and milestones saved.' }); }} />}
    </div>
  );
}

function Step({ done, children }: { done: boolean; children: React.ReactNode }) {
  return <li className={done ? 'done' : ''}><span aria-hidden="true">{done ? '✓' : '○'}</span> {children}</li>;
}

function ChangeOrderPanel({ d, co, onAct, onClose }: { d: CommercialPage; co: ChangeOrder; onAct: (p: string, b: unknown, ok: string) => Promise<void>; onClose: () => void }) {
  const [note, setNote] = useState('');
  const line = co.lines[0];
  const canManager = co.status === 'draft' && d.can_manager_approve;
  const canPrice = co.status === 'awaiting_futran_approval' && d.can_approve_price;
  return (
    <Card title={`${co.ref} · ${co.kind_label ?? 'Change order'}`} actions={<Button size="sm" variant="ghost" onClick={onClose}>New change order</Button>}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>Raised by {co.raised_by}{co.scope_change_ref?.startsWith('system_addition:') ? ' from Scope when a system was found after initiation (template §1.3).' : '.'}</p>
        <div><div className="small muted">Reason</div><div>{co.reason}</div></div>
        {line && <div><div className="small muted">Line</div><div>{line.code} {line.description} · {line.qty} × {money(line.unit_price)} = <strong>{money(line.value)}</strong></div></div>}
        <ol className="co-steps">
          <Step done={!!co.em_approved_by}>Engagement Manager approved{co.em_approved_by ? ` (${co.em_approved_by})` : ''}</Step>
          <Step done={!co.needs_price_approval || !!co.futran_approved_by}>{co.needs_price_approval ? `Price approved by sales${co.futran_approved_by ? ` (${co.futran_approved_by})` : ''}` : `Price within guardrails (${money(line?.list_price)} list)`}</Step>
          <Step done={co.status === 'approved'}>CAICO approval in client app{co.status === 'awaiting_client' ? ' — sent' : co.client_approved_by ? ` — ${co.client_approved_by}` : ''}</Step>
          <Step done={co.applied}>Scope changes when approved</Step>
        </ol>
        {co.status === 'rejected' && <Alert tone="danger">Rejected{co.decided_note ? `: ${co.decided_note}` : '.'}</Alert>}
        {canManager && <Button variant="primary" onClick={() => onAct(`/change-orders/${co.id}/manager-approve`, {}, `${co.ref} approved.`)}>Approve as Engagement Manager</Button>}
        {canPrice && <>
          <TextArea label="Note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="row"><Button variant="primary" onClick={() => onAct(`/change-orders/${co.id}/price-decision`, { approve: true, note }, 'Price approved; sent to the client.')}>Approve price</Button>
            <Button onClick={() => onAct(`/change-orders/${co.id}/price-decision`, { approve: false, note }, 'Returned.')}>Return</Button></div>
        </>}
      </div>
    </Card>
  );
}

function RaiseChangeOrder({ d, onRaised }: { d: CommercialPage; onRaised: (c: ChangeOrder) => void }) {
  const [f, setF] = useState({ code: d.kinds[0]?.code ?? 'A-03', qty: '1', reason: '', unit_price: '' });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const raise = async () => {
    setErr(null); setErrs({});
    try {
      onRaised(await api.post<ChangeOrder>(`/e/${d.engagement.id}/change-orders`, { code: f.code, qty: Number(f.qty), reason: f.reason, unit_price: f.unit_price ? Number(f.unit_price) : null }));
      setF({ ...f, reason: '', unit_price: '' });
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); }
  };
  return (
    <Card title="Raise a change order">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Reason" rows={3} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} error={errs.reason} />
        <SelectField label="Line" value={f.code} options={d.kinds.map((k) => ({ value: k.code, label: k.label }))} onChange={(e) => setF({ ...f, code: e.target.value })} error={errs.code} />
        <TextField label="Qty" type="number" min={1} value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} error={errs.qty} />
        <TextField label="Unit price (leave empty for the price list)" type="number" min={0} value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value })}
          help="A price off the list needs a Sales Manager or Pricing Approver." />
        <p className="small muted" style={{ margin: 0 }}>Priced from the price list. The client's CAICO approves in the platform; the scope changes only then.</p>
        <div><Button variant="primary" onClick={raise}>Raise change order</Button></div>
      </div>
    </Card>
  );
}

function EditFee({ d, onClose, onSaved }: { d: CommercialPage; onClose: () => void; onSaved: (v: CommercialPage) => void }) {
  const [fee, setFee] = useState(String(d.fee_total ?? ''));
  const [ms, setMs] = useState(d.milestones.length ? d.milestones.map((m) => ({ label: m.label, trigger: m.trigger, pct: String(m.pct) }))
    : [{ label: '50% on start', trigger: 'sign_off_1', pct: '50' }, { label: '50% on report', trigger: 'sign_off_7', pct: '50' }]);
  const [err, setErr] = useState<string | null>(null);
  const triggers = [{ value: 'sign_off_1', label: 'Sign-off 1 approved' }, { value: 'sign_off_7', label: 'Sign-off 7 approved' }, { value: 'manual', label: 'Marked by hand' }];
  const save = async () => {
    setErr(null);
    try { onSaved(await api.put<CommercialPage>(`/e/${d.engagement.id}/commercial`, { fee_total: Number(fee), milestones: ms.map((m) => ({ ...m, pct: Number(m.pct) })) })); }
    catch (e) { setErr(errorMessage(e) + (Object.values(fieldErrors(e)).length ? ` ${Object.values(fieldErrors(e)).join(' ')}` : '')); }
  };
  return (
    <Dialog title="Fee and billing milestones" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Fee (US$)" type="number" min={0} value={fee} onChange={(e) => setFee(e.target.value)} />
        {ms.map((m, i) => (
          <div key={i} className="row ms-row">
            <TextField label="Milestone" value={m.label} onChange={(e) => setMs(ms.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <SelectField label="Trigger" value={m.trigger} options={triggers} onChange={(e) => setMs(ms.map((x, j) => (j === i ? { ...x, trigger: e.target.value } : x)))} />
            <TextField label="%" type="number" value={m.pct} onChange={(e) => setMs(ms.map((x, j) => (j === i ? { ...x, pct: e.target.value } : x)))} />
            <Button size="sm" variant="ghost" onClick={() => setMs(ms.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <div><Button size="sm" onClick={() => setMs([...ms, { label: '', trigger: 'manual', pct: '' }])}>Add milestone</Button></div>
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
