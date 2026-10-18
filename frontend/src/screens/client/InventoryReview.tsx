import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Loading, PageHeader, TextArea, fmtDateTime } from '@/components/ui';
import { SignPanel, type SignOffView } from '@/components/SignPanel';
import { STATUS_LABELS, tierBadge, useInventory } from '@/screens/client/Inventory';

type Block = { sign_off: (SignOffView & { version: number }) | null; unmet: string[]; can_submit: boolean; can_correct: boolean };
type Review = {
  client: string; audit_ref: string; stage: number; departments: ({ id: string; name: string } & Block)[]; signoff3: Block; signoff4: Block;
  representation: string; snapshot: { version: number; locked_at: string; use_cases: number } | null;
};

function statusBadge(b: Block) {
  const s = b.sign_off?.status;
  if (s === 'approved') return <Badge tone="success">Approved</Badge>;
  if (s === 'returned') return <Badge tone="danger">Returned</Badge>;
  if (s) return <Badge tone="warn">Awaiting signatures</Badge>;
  return <Badge tone="muted">Not started</Badge>;
}

/** Screen 15: Stage 4 client review — department inventories, data categories, management representation. */
export function InventoryReview() {
  const { data: me } = useMe();
  const cid = me?.organization.id ?? '';
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['review', cid], queryFn: () => api.get<Review>(`/clients/${cid}/review`), enabled: !!cid });
  const inv = useInventory(cid);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [correcting, setCorrecting] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  if (q.isLoading || !q.data) return <div className="page">{q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />}</div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries();
  async function submit(number: number, scope?: string) {
    setMsg(null);
    try { await api.post(`/clients/${cid}/signoffs/${number}/submit`, scope ? { scope_ref: scope } : {}); await refresh(); setMsg({ tone: 'success', text: 'Sent for signature. The next signer has been notified.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function correct(soId: string) {
    setMsg(null);
    try { await api.post(`/signoffs/${soId}/correct`, { reason }); setCorrecting(null); setReason(''); await refresh(); setMsg({ tone: 'success', text: 'A new version is open for signature. The signed version is kept.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const approvedDepts = d.departments.filter((x) => x.sign_off?.status === 'approved').length;
  const ucs = inv.data?.use_cases ?? [];

  const blockBody = (b: Block, number: number, scope?: string, submitLabel = 'Send for signature') => (
    <div className="stack">
      {b.sign_off && <SignPanel signOffId={b.sign_off.id} hideTitle onSigned={refresh} agreeText={number === 4 ? 'I make this representation on behalf of management.' : number === 2 ? 'I have reviewed this department’s use cases and approve the inventory.' : 'I have reviewed the data categories for the Tier 2 and Tier 3 use cases.'} />}
      {b.unmet.length > 0 && (!b.sign_off || b.sign_off.status === 'returned') && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{b.unmet.map((u) => <li key={u}>{u}</li>)}</ul>}
      {b.can_submit && <div><Button variant="primary" onClick={() => submit(number, scope)}>{submitLabel}</Button></div>}
      {b.can_correct && b.sign_off && (correcting === b.sign_off.id ? (
        <div className="stack-sm">
          <TextArea label="Why it needs to change" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row" style={{ gap: 8 }}><Button onClick={() => correct(b.sign_off!.id)}>Open a new version</Button><Button variant="ghost" onClick={() => setCorrecting(null)}>Cancel</Button></div>
        </div>
      ) : <div><Button variant="ghost" size="sm" onClick={() => setCorrecting(b.sign_off!.id)}>Correct with a reason</Button></div>)}
    </div>
  );

  return (
    <div className="page">
      <PageHeader title="AI inventory review" subtitle="Stage 4. Department Leads approve their inventories, the data categories are reviewed, then management signs the representation. Signing sign-off 4 locks the inventory as a snapshot and Futran's fieldwork begins." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Sign-off 2 · Department inventories</div><div className="value">{approvedDepts} / {d.departments.length}</div><div className="hint">Department Leads approved</div></div>
        <div className="tile"><div className="label">Sign-off 3 · Data categories</div><div className="value" style={{ fontSize: 22 }}>{statusBadge(d.signoff3)}</div><div className="hint">{d.signoff3.sign_off?.parties.map((p) => p.role_label).join(' → ')}</div></div>
        <div className="tile"><div className="label">Sign-off 4 · Management representation</div><div className="value" style={{ fontSize: 22 }}>{statusBadge(d.signoff4)}</div><div className="hint">{d.signoff4.sign_off?.parties.map((p) => p.role_label).join(' → ')}</div></div>
        <div className="tile"><div className="label">Inventory snapshot</div><div className="value" style={{ fontSize: 22 }}>{d.snapshot ? `Locked v${d.snapshot.version}` : 'Not locked'}</div><div className="hint">{d.snapshot ? fmtDateTime(d.snapshot.locked_at) : 'locks when sign-off 4 is signed'}</div></div>
      </div>
      <div className="stack">
        <Card title={`Use cases · ${ucs.length}`} actions={<span className="small muted">Tier 3: {inv.data?.tiers['3'] ?? 0} · Tier 2: {inv.data?.tiers['2'] ?? 0} · Tier 1: {inv.data?.tiers['1'] ?? 0}</span>}>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Use case</th><th>Department</th><th>Tool · account</th><th>Proposed tier</th><th>Status</th></tr></thead>
            <tbody>{ucs.map((u) => <tr key={u.id}><td><strong>{u.name}</strong></td><td>{u.department}</td><td className="small">{u.tools.join(', ')}</td><td>{tierBadge(u.proposed_tier)}</td><td><Badge tone={STATUS_LABELS[u.status]?.tone ?? 'muted'}>{STATUS_LABELS[u.status]?.label ?? u.status}</Badge></td></tr>)}</tbody>
          </table></div>
        </Card>
        <Card title="Sign-off 2 · Department inventories">
          <div className="stack">
            {d.departments.map((x) => (
              <div key={x.id} className="stack-sm" style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
                <div className="row" style={{ justifyContent: 'space-between' }}><strong>{x.name}</strong>{statusBadge(x)}</div>
                {blockBody(x, 2, x.id, 'Send to the Department Lead')}
              </div>
            ))}
          </div>
        </Card>
        <Card title="Sign-off 3 · Data categories for Tier 2–3 use cases">{blockBody(d.signoff3, 3)}</Card>
        <Card title="Sign-off 4 · Management representation">
          <div className="stack">
            {!d.signoff4.sign_off && <blockquote className="statement">{d.representation}</blockquote>}
            {blockBody(d.signoff4, 4, undefined, 'I have reviewed the inventory: send for signature')}
          </div>
        </Card>
      </div>
    </div>
  );
}
