import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { vaultApi, type Hold, type VaultView } from '@/api/r7';
import '@/styles/r7.css';

/** G-10 Evidence vault and retention: storage used vs plan, retention tier, legal holds and the 90-day deletion countdown. */
export function Vault() {
  const { clientId = '' } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['vault', clientId], queryFn: () => vaultApi.get(clientId) });
  const [placing, setPlacing] = useState(false);
  const [releasing, setReleasing] = useState<Hold | null>(null);
  const [tier, setTier] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const v = q.data;
  const set = (nv: VaultView, text: string) => { qc.setQueryData(['vault', clientId], nv); setMsg({ tone: 'success', text }); };
  const s = v.storage;
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: `/clients/${clientId}`, label: v.client.name }]} title="Evidence vault and retention"
        actions={v.can.manage_holds ? <Button variant="primary" onClick={() => setPlacing(true)}>Place legal hold</Button> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="r7-kpis">
        <div className="r7-kpi">
          <div className="label">Storage used</div>
          <div className="value">{s.used_gb.toLocaleString('en-US', { maximumFractionDigits: 2 })} GB</div>
          <div className="sub">{s.limit_gb != null ? `of ${s.limit_gb} GB in plan${s.plan_code ? ` (${s.plan_code})` : ''}` : 'No storage limit on an ordered plan'}</div>
          {s.pct != null && <div className={`r7-bar${s.pct >= 90 ? ' warn' : ''}`} role="img" aria-label={`${s.pct}% of the plan`}><span style={{ width: `${Math.min(100, s.pct)}%` }} /></div>}
        </div>
        <div className="r7-kpi">
          <div className="label">Retention tier</div>
          <div className="value">{v.retention.years} years</div>
          <div className="sub">{v.retention.is_default ? 'Platform default' : `Since ${fmtDate(v.retention.effective_from)}`}{v.retention.kept_longer_by_letter ? ` · ${v.retention.kept_longer_by_letter} ${v.retention.kept_longer_by_letter === 1 ? 'engagement keeps' : 'engagements keep'} a longer period from the letter` : ''}{v.can.set_tier && <> · <button type="button" className="r7-link" onClick={() => setTier(true)}>Change</button></>}</div>
        </div>
        <div className="r7-kpi">
          <div className="label">Legal holds</div>
          <div className="value">{v.active_holds} active</div>
          <div className="sub">Billed per matter (M-06e)</div>
        </div>
        <div className="r7-kpi">
          <div className="label">Due for deletion, 90 days</div>
          <div className="value">{v.countdown.total} items</div>
          <div className="sub">{v.countdown.held} held, {v.countdown.will_delete} will delete</div>
        </div>
      </div>
      <Card title="Legal holds">
        {v.holds.length === 0 ? <EmptyState>No legal holds. The Chief Auditor places one on the client's request; it blocks deletion of everything in its scope until released.</EmptyState> : (
          <div className="table-wrap"><table className="table stack-table">
            <thead><tr><th>Hold</th><th>Matter</th><th>Scope</th><th>Set by</th><th>Set on</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{v.holds.map((h) => (
              <tr key={h.id}>
                <td><strong>{h.ref}</strong><div className="small muted">{h.name}</div></td>
                <td>{h.matter_ref ?? '—'}<div className="small muted">{h.reason}</div></td>
                <td className="small">{h.scope_label}</td>
                <td>{h.set_by}</td>
                <td>{fmtDate(h.set_at)}</td>
                <td>{h.active ? <Badge tone="warn">Active · deletion blocked</Badge> : <><Badge tone="muted">Released {fmtDate(h.released_at)}</Badge><div className="small muted">{h.released_by}: {h.release_reason}</div></>}</td>
                <td>{h.active && v.can.manage_holds && <Button size="sm" onClick={() => setReleasing(h)}>Release</Button>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      <Card title="Deletion countdown">
        {v.countdown.items.length === 0 ? <EmptyState>Nothing is due for deletion in the next 90 days.</EmptyState> : (
          <div className="table-wrap"><table className="table stack-table">
            <thead><tr><th>Item</th><th>Engagement</th><th>Type</th><th>Delete on</th><th>Hold</th></tr></thead>
            <tbody>{v.countdown.items.map((i) => (
              <tr key={`${i.item_type}-${i.id}`}>
                <td>{i.filename}</td><td>{i.engagement}</td><td>{i.kind}</td>
                <td>{fmtDate(i.delete_on)}{i.notified_on ? <div className="small muted">Notice sent {fmtDate(i.notified_on)}</div> : <div className="small muted">Notice goes out with the next daily run</div>}</td>
                <td>{i.hold ? <Badge tone="warn">{i.hold}</Badge> : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        <p className="r7-note">Engagement evidence is deleted at the end of the retention period, never sooner than 90 days after a notice to the Chief Auditor and the client's CAICO. Items under an active legal hold are kept until it is released. Reports and signed documents are not deleted here.</p>
      </Card>
      {placing && <PlaceHold v={v} clientId={clientId} onClose={() => setPlacing(false)} onDone={(nv) => { setPlacing(false); set(nv, 'Legal hold placed. Deletion of everything in its scope is blocked.'); }} />}
      {releasing && <ReleaseHold hold={releasing} clientId={clientId} onClose={() => setReleasing(null)} onDone={(nv) => { setReleasing(null); set(nv, `${releasing.ref} released.`); }} />}
      {tier && <TierDialog v={v} clientId={clientId} onClose={() => setTier(false)} onDone={(nv) => { setTier(false); set(nv, 'Retention tier saved.'); }} />}
    </div>
  );
}

function PlaceHold({ v, clientId, onClose, onDone }: { v: VaultView; clientId: string; onClose: () => void; onDone: (v: VaultView) => void }) {
  const [f, setF] = useState({ name: '', matter_ref: '', reason: '' });
  const [eids, setEids] = useState<string[]>([]);
  const [sids, setSids] = useState<string[]>([]);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const toggle = (list: string[], id: string, on: boolean) => (on ? [...list, id] : list.filter((x) => x !== id));
  async function save() {
    setErr(null);
    try { onDone(await vaultApi.hold(clientId, { ...f, scope: { engagement_ids: eids, system_ids: sids, from: from || null, to: to || null } })); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Place legal hold" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Name" placeholder="For example: Client counsel request" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <TextField label="Matter reference" value={f.matter_ref} maxLength={200} onChange={(e) => setF({ ...f, matter_ref: e.target.value })} />
        <TextArea label="Why" hint="Who asked for the hold and why." value={f.reason} maxLength={4000} onChange={(e) => setF({ ...f, reason: e.target.value })} />
        <fieldset className="stack-sm">
          <legend>Scope</legend>
          <p className="small muted" style={{ margin: 0 }}>Leave everything blank to hold all of this client's records. Each choice narrows the hold.</p>
          <strong className="small">Engagements</strong>
          <div className="r7-check-list">{v.scope_options.engagements.map((e) => <Checkbox key={e.id} label={`${e.name}${e.audit_ref ? ` (${e.audit_ref})` : ''}`} checked={eids.includes(e.id)} onChange={(ev) => setEids(toggle(eids, e.id, ev.target.checked))} />)}</div>
          {v.scope_options.systems.length > 0 && <>
            <strong className="small">AI systems</strong>
            <div className="r7-check-list">{v.scope_options.systems.map((s) => <Checkbox key={s.id} label={`${s.reference} ${s.name}${s.engagement ? ` · ${s.engagement}` : ''}`} checked={sids.includes(s.id)} onChange={(ev) => setSids(toggle(sids, s.id, ev.target.checked))} />)}</div>
          </>}
          <div className="grid-2">
            <TextField label="Items from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            <TextField label="Items up to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </fieldset>
        <div className="row"><Button variant="primary" disabled={!f.name.trim() || !f.reason.trim()} onClick={save}>Place legal hold</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function ReleaseHold({ hold, clientId, onClose, onDone }: { hold: Hold; clientId: string; onClose: () => void; onDone: (v: VaultView) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try { onDone(await vaultApi.release(clientId, hold.id, reason)); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Release ${hold.ref}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small" style={{ margin: 0 }}>Items past their retention date that only this hold kept are deleted by a later daily run, once their 90-day notice period is over.</p>
        <TextArea label="Why is the hold released?" value={reason} maxLength={4000} onChange={(e) => setReason(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!reason.trim()} onClick={save}>Release hold</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function TierDialog({ v, clientId, onClose, onDone }: { v: VaultView; clientId: string; onClose: () => void; onDone: (v: VaultView) => void }) {
  const [years, setYears] = useState(String(v.retention.years));
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try { onDone(await vaultApi.tier(clientId, Number(years), reason)); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Retention tier" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Keep engagement evidence for" value={years} onChange={(e) => setYears(e.target.value)} options={v.retention.tiers.map((t) => ({ value: String(t), label: `${t} years after the engagement is completed${t === 7 ? ' (default)' : ''}` }))} />
        <TextField label="Reason" placeholder="For example: M-06c uplift ordered" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
        <p className="small muted" style={{ margin: 0 }}>A tier can lengthen retention but never shorten it: each engagement keeps at least the period its engagement letter states. Nothing is deleted sooner than 90 days after its notice.</p>
        {v.retention.history.length > 0 && <p className="small muted" style={{ margin: 0 }}>Earlier: {v.retention.history.map((h) => `${h.years} years from ${fmtDate(h.effective_from)} (${h.set_by})`).join('; ')}</p>}
        <div className="row"><Button variant="primary" onClick={save}>Save tier</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
