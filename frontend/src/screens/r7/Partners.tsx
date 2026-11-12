import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate } from '@/components/ui';
import { money, partnersApi, type PartnerIn, type PartnerRow, type PartnersView } from '@/api/r7';
import '@/styles/r7.css';

const STATUS: Record<string, ['warn' | 'success' | 'muted', string]> = { due: ['warn', 'Due'], paid: ['success', 'Paid'], void: ['muted', 'Void'] };

/** G-11 Partners and referrals. Commission values show only to those who may see them (never Auditors). */
export function Partners() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['partners'], queryFn: partnersApi.list });
  const [editing, setEditing] = useState<PartnerRow | 'new' | null>(null);
  const [referring, setReferring] = useState<PartnerRow | null>(null);
  const [voiding, setVoiding] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const v = q.data;
  const set = (nv: PartnersView, text: string) => { qc.setQueryData(['partners'], nv); setMsg({ tone: 'success', text }); };
  async function settle(id: string) {
    setMsg(null);
    try { set(await partnersApi.paid(id), 'Commission marked paid.'); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  return (
    <div className="page">
      <PageHeader title="Partners and referrals" actions={v.can.manage ? <Button variant="primary" onClick={() => setEditing('new')}>Add partner</Button> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card title="Partners">
        {v.partners.length === 0 ? <EmptyState>No partners yet.</EmptyState> : (
          <div className="table-wrap"><table className="table stack-table">
            <thead><tr><th>Partner</th><th>Type</th><th>Agreement</th>{v.can.see_money && <th>Commission rule</th>}<th>Referred in</th><th>Referred out</th>{v.can.see_money && <><th>Won value</th><th>Commission due</th></>}<th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{v.partners.map((p) => (
              <tr key={p.id}>
                <td><strong>{p.name}</strong>{p.status === 'inactive' && <> <Badge tone="muted">Inactive</Badge></>}{p.contact_name && <div className="small muted">{p.contact_name}{p.contact_email ? ` · ${p.contact_email}` : ''}</div>}</td>
                <td>{p.type_label}</td>
                <td>{p.agreement_label ?? '—'}{p.agreement_file_id && <div><a className="small" href={fileUrl(p.agreement_file_id)}>Download</a></div>}</td>
                {v.can.see_money && <td className="small">{p.commission_label}</td>}
                <td>{p.referred_in}</td>
                <td>{p.referred_out}</td>
                {v.can.see_money && <><td>{money(p.won_value)}</td><td>{p.commission_due ? money(p.commission_due) : '—'}</td></>}
                <td>{v.can.manage && <div className="row" style={{ gap: 6 }}><Button size="sm" onClick={() => setEditing(p)}>Edit</Button><Button size="sm" onClick={() => setReferring(p)}>Record referral</Button></div>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {!v.can.see_money && <p className="r7-note">Law firms: {v.law_firm_note.replace(/^None: /, '')}.</p>}
      </Card>
      {v.commissions && (
        <Card title="Commissions">
          {v.commissions.length === 0 ? <EmptyState>No commissions yet. They are created when a referred opportunity is won.</EmptyState> : (
            <div className="table-wrap"><table className="table stack-table">
              <thead><tr><th>Partner</th><th>Opportunity</th><th>Order</th><th>First-year value</th><th>Rate</th><th>Amount</th><th>Due</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{v.commissions.map((c) => (
                <tr key={c.id}>
                  <td>{c.partner}</td><td>{c.client}<div className="small muted">{c.opportunity}</div></td><td>{c.order_ref ?? '—'}</td><td>{money(c.base_value)}</td><td>{c.rate}%</td>
                  <td>{money(c.amount)}</td><td>{fmtDate(c.due_on)}</td>
                  <td><Badge tone={STATUS[c.status][0]}>{STATUS[c.status][1]}</Badge>{c.void_reason && <div className="small muted">{c.void_reason}</div>}</td>
                  <td>{c.status === 'due' && v.can.settle && <div className="row" style={{ gap: 6 }}><Button size="sm" onClick={() => settle(c.id)}>Mark paid</Button><Button size="sm" variant="ghost" onClick={() => setVoiding(c.id)}>Void</Button></div>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
          <p className="r7-note">Commissions are created on win from the accepted proposal and appear on the monthly billing export. Law firms never receive one: {v.law_firm_note.replace(/^None: /, '').toLowerCase()}.</p>
        </Card>
      )}
      <Card title="Referrals">
        {v.referrals.length === 0 ? <EmptyState>No referrals recorded yet.</EmptyState> : (
          <div className="table-wrap"><table className="table stack-table">
            <thead><tr><th>Date</th><th>Direction</th><th>Partner</th><th>Client or opportunity</th><th>Note</th></tr></thead>
            <tbody>{v.referrals.map((r) => (
              <tr key={r.id}>
                <td>{fmtDate(r.at)}</td><td>{r.direction === 'in' ? 'Referred to Futran' : 'Referred by Futran'}</td><td>{r.partner}</td>
                <td>{r.client ?? '—'}{r.opportunity && <div className="small muted">{r.opportunity}</div>}</td><td className="small">{r.note ?? ''}<div className="muted">{r.recorded_by}</div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      {editing && <PartnerDialog v={v} p={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onDone={(nv, t) => { setEditing(null); set(nv, t); }} />}
      {referring && <ReferralDialog p={referring} onClose={() => setReferring(null)} onDone={(nv) => { setReferring(null); set(nv, 'Referral recorded.'); }} />}
      {voiding && <VoidDialog id={voiding} onClose={() => setVoiding(null)} onDone={(nv) => { setVoiding(null); set(nv, 'Commission made void.'); }} />}
    </div>
  );
}

function PartnerDialog({ v, p, onClose, onDone }: { v: PartnersView; p: PartnerRow | null; onClose: () => void; onDone: (v: PartnersView, text: string) => void }) {
  const [f, setF] = useState<PartnerIn>({
    name: p?.name ?? '', type: p?.type ?? 'ats_vendor', rate_pct: p?.commission_rule?.rate_pct ?? null, agreement_label: p?.agreement_label ?? '', contact_name: p?.contact_name ?? '',
    contact_email: p?.contact_email ?? '', contact_phone: p?.contact_phone ?? '', notes: p?.notes ?? '', status: p?.status ?? 'active',
  });
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const law = f.type === 'law_firm';
  async function save() {
    setErr(null);
    const body = { ...f, rate_pct: law ? null : f.rate_pct };
    try {
      let out = p ? await partnersApi.edit(p.id, body) : await partnersApi.add(body);
      const id = p?.id ?? out.partners.find((x) => x.name === f.name.trim())?.id;
      if (file && id) out = await partnersApi.agreement(id, file);
      onDone(out, p ? 'Partner saved.' : 'Partner added.');
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={p ? `Edit ${p.name}` : 'Add partner'} onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="Name" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <SelectField label="Type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} options={v.types} />
          <TextField label="Agreement" placeholder="For example: Channel agreement" value={f.agreement_label ?? ''} maxLength={120} onChange={(e) => setF({ ...f, agreement_label: e.target.value })} />
          {v.can.see_money && (law
            ? <div><span className="field-label">Commission rule</span><p className="small" style={{ margin: '8px 0 0' }}>{v.law_firm_note}</p></div>
            : <TextField label="Commission, % of first-year contract value" type="number" min={0} max={50} step="0.5" value={f.rate_pct ?? ''}
                onChange={(e) => setF({ ...f, rate_pct: e.target.value === '' ? null : Number(e.target.value) })} hint="Leave blank for no commission." />)}
          <TextField label="Contact name" value={f.contact_name ?? ''} maxLength={160} onChange={(e) => setF({ ...f, contact_name: e.target.value })} />
          <TextField label="Contact email" type="email" value={f.contact_email ?? ''} maxLength={254} onChange={(e) => setF({ ...f, contact_email: e.target.value })} />
          <TextField label="Contact phone" value={f.contact_phone ?? ''} maxLength={40} onChange={(e) => setF({ ...f, contact_phone: e.target.value })} />
          {p && <SelectField label="Status" value={f.status ?? 'active'} onChange={(e) => setF({ ...f, status: e.target.value })} options={[{ value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]} />}
        </div>
        <label className="stack-sm"><span className="field-label">Agreement file</span><input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
        <TextArea label="Notes" value={f.notes ?? ''} maxLength={4000} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        <div className="row"><Button variant="primary" disabled={!f.name.trim()} onClick={save}>{p ? 'Save partner' : 'Add partner'}</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function ReferralDialog({ p, onClose, onDone }: { p: PartnerRow; onClose: () => void; onDone: (v: PartnersView) => void }) {
  const opts = useQuery({ queryKey: ['partner-options'], queryFn: partnersApi.options });
  const [direction, setDirection] = useState('in');
  const [opp, setOpp] = useState('');
  const [org, setOrg] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try { onDone(await partnersApi.referral(p.id, { direction, opportunity_id: opp || null, organization_id: opp ? null : org || null, note: note || null })); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Record referral · ${p.name}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Direction" value={direction} onChange={(e) => setDirection(e.target.value)} options={[{ value: 'in', label: `${p.name} referred work to Futran` }, { value: 'out', label: `Futran referred work to ${p.name}` }]} />
        <SelectField label="Opportunity" value={opp} placeholder="None" onChange={(e) => setOpp(e.target.value)} options={opts.data?.opportunities.map((o) => ({ value: o.id, label: o.label })) ?? []} />
        {!opp && <SelectField label="Client" value={org} placeholder="None" onChange={(e) => setOrg(e.target.value)} options={opts.data?.clients.map((c) => ({ value: c.id, label: c.name })) ?? []} />}
        <TextArea label="Note" placeholder={direction === 'out' ? 'For example: legal opinion on LL144 applicability' : ''} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
        {p.is_law_firm && <p className="small muted" style={{ margin: 0 }}>No fees either way with law firms (bar rules).</p>}
        <div className="row"><Button variant="primary" onClick={save}>Record referral</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function VoidDialog({ id, onClose, onDone }: { id: string; onClose: () => void; onDone: (v: PartnersView) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try { onDone(await partnersApi.void(id, reason)); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Void commission" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Why is it void?" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!reason.trim()} onClick={save}>Void commission</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
