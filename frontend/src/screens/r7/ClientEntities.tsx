import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextField, fmtDate } from '@/components/ui';
import { RELATIONSHIPS, hierarchyApi, type EntityNode, type EntityTree, type ImportResult, type Rollup } from '@/api/r7';
import '@/styles/r7.css';

const STAGE_LABELS: Record<string, string> = { proposed: 'Proposed', in_development: 'In development', ready_for_go_live: 'Ready for go-live', live: 'Live', retired: 'Retired' };

function nodeMeta(n: EntityNode): string {
  if (n.depth === 0) return 'Parent · own tenant';
  const bits = [n.relationship_label ?? ''];
  if (n.relationship === 'subsidiary') bits.push(`Roll-up consent: ${n.consented ? 'yes' : 'no'}`);
  if (n.ll144) bits.push(n.ll144.in_scope ? `${n.ll144.roles_note ?? 'LL144 in scope'}${n.ll144.own_public_summary ? ' · own public summary' : ''}` : `${n.ll144.roles_note ? `${n.ll144.roles_note} · ` : ''}LL144 not in scope`);
  return bits.filter(Boolean).join(' · ');
}

export function RollupCounts({ r }: { r: Rollup }) {
  return (
    <div>
      <dl className="r7-counts">
        <div><dt>AI systems</dt><dd>{r.systems_total}</dd></div>
        <div><dt>Live</dt><dd>{r.by_stage.live ?? 0}</dd></div>
        <div><dt>High risk</dt><dd>{r.high_risk}</dd></div>
        <div><dt>Bias audit due</dt><dd>{r.bias_audit_due}</dd></div>
      </dl>
      <p className="small muted" style={{ margin: '8px 0 0' }}>
        {Object.entries(r.by_stage).filter(([k, v]) => v && k !== 'live').map(([k, v]) => `${STAGE_LABELS[k] ?? k}: ${v}`).join(' · ') || 'No other stages.'}
        {r.audit ? ` · Current audit: ${r.audit.status}, ${r.audit.stage}` : ' · No audit under way'}
      </p>
    </div>
  );
}

export function ClientEntities() {
  const { clientId = '' } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['entities', clientId], queryFn: () => hierarchyApi.tree(clientId) });
  const [sel, setSel] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const t = q.data;
  useEffect(() => { if (t && !sel) setSel(t.nodes.find((n) => n.id === clientId)?.id ?? t.root.id); }, [t, sel, clientId]);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !t) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const node = t.nodes.find((n) => n.id === sel) ?? t.nodes[0];
  const set = (tree: EntityTree) => qc.setQueryData(['entities', clientId], tree);
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: `/clients/${t.root.id}`, label: t.root.name }]} title="Entities and end-clients"
        subtitle="Parent, subsidiaries, end-clients and vendor customers. Each entity is its own tenant."
        actions={t.can_manage ? <><Button onClick={() => setImporting(true)}>Import end-clients (CSV)</Button><Button variant="primary" onClick={() => setAdding(true)}>Add entity</Button></> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <Card title="Hierarchy">
            <ul className="r7-tree" aria-label="Entities in this group">
              {t.nodes.map((n) => (
                <li key={n.id} style={{ paddingLeft: n.depth * 24 }}>
                  <button type="button" className="r7-node" aria-pressed={n.id === node.id} onClick={() => setSel(n.id)}>
                    {n.depth > 0 && <span className="r7-branch" aria-hidden="true">└</span>}
                    <span>
                      <span className="r7-name">{n.name}</span>
                      <span className="r7-meta" style={{ display: 'block' }}>{nodeMeta(n)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="r7-note">Each entity is its own tenant. The parent sees roll-up only where the child's CAICO consents. Every share is logged.</p>
          </Card>
        </div>
        <div className="side stack">
          <EntityPanel key={node.id} tree={t} node={node} onTree={set} onMsg={setMsg} />
          <Card title="LL144 pricing">
            <p className="small" style={{ margin: 0 }}>End-clients in LL144 scope: <strong>{t.ll144.in_scope}</strong> of {t.ll144.end_clients}. AEDTs used for them: {t.ll144.aedts}.</p>
            <p className="small muted" style={{ margin: '6px 0 0' }}>L-09 pricing counts the end-clients in scope.</p>
          </Card>
        </div>
      </div>
      {adding && <AddEntity tree={t} clientId={clientId} onClose={() => setAdding(false)} onDone={(tree, text) => { set(tree); setAdding(false); setMsg({ tone: 'success', text }); }} />}
      {importing && <ImportDialog clientId={clientId} onClose={() => setImporting(false)} onDone={async (n) => { setImporting(false); await qc.invalidateQueries({ queryKey: ['entities', clientId] }); setMsg({ tone: 'success', text: `${n} ${n === 1 ? 'entity' : 'entities'} added.` }); }} />}
    </div>
  );
}

function EntityPanel({ tree, node, onTree, onMsg }: { tree: EntityTree; node: EntityNode; onTree: (t: EntityTree) => void; onMsg: (m: { tone: 'success' | 'danger'; text: string } | null) => void }) {
  const [rel, setRel] = useState(node.relationship ?? '');
  const [scope, setScope] = useState({
    ll144_in_scope: node.ll144?.in_scope ?? false, aedt_system_ids: node.ll144?.aedts.map((a) => a.id) ?? [], roles_note: node.ll144?.roles_note ?? '',
    own_public_summary: node.ll144?.own_public_summary ?? false, vendor_allows_summary: node.ll144?.vendor_allows_summary ?? false,
  });
  const [busy, setBusy] = useState(false);
  const manage = tree.can_manage && node.depth > 0;
  async function run(fn: () => Promise<EntityTree>, ok: string) {
    if (busy) return;
    setBusy(true); onMsg(null);
    try { onTree(await fn()); onMsg({ tone: 'success', text: ok }); } catch (e) { onMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const endClient = node.relationship === 'end_client' || node.relationship === 'customer_of_vendor';
  return (
    <Card title={<h2>Selected · {node.name}</h2>}>
      <div className="stack">
        {node.depth === 0 ? <p className="small" style={{ margin: 0 }}>Parent of the group. Its own tenant; it sees roll-up counts of a subsidiary only while that subsidiary's CAICO consents.</p> : (
          <fieldset className="stack-sm" disabled={!manage || busy}>
            <legend>Relationship</legend>
            {RELATIONSHIPS.map((r) => (
              <label key={r.value} className="check"><input type="radio" name="rel" checked={rel === r.value} onChange={() => setRel(r.value)} /><span>{r.label}</span></label>
            ))}
            {manage && rel !== node.relationship && <Button size="sm" onClick={() => run(() => hierarchyApi.relationship(node.id, rel), 'Relationship saved.')}>Save relationship</Button>}
          </fieldset>
        )}
        {node.relationship === 'subsidiary' && (
          <div>
            <strong className="small">Roll-up consent</strong>
            {node.consent ? (
              <p className="small" style={{ margin: '4px 0 0' }}><Badge tone="success">Given</Badge> by {node.consent.given_by} on {fmtDate(node.consent.given_at)}. The subsidiary's CAICO can withdraw it at any time.</p>
            ) : <p className="small muted" style={{ margin: '4px 0 0' }}>Not given. Only the subsidiary's CAICO can give it, from their own Group page.</p>}
            {node.rollup && <RollupCounts r={node.rollup} />}
          </div>
        )}
        {endClient && (
          <fieldset className="stack-sm" disabled={!manage || busy}>
            <legend>LL144 scope</legend>
            <Checkbox label="AEDTs are used for NYC roles placed at this client" checked={scope.ll144_in_scope} onChange={(e) => setScope({ ...scope, ll144_in_scope: e.target.checked })} />
            {scope.ll144_in_scope && (
              <div className="r7-check-list" role="group" aria-label="AEDTs used for this client">
                {tree.parent_systems.length === 0 ? <span className="small muted">The parent has no AI systems in its register yet.</span> : tree.parent_systems.map((s) => (
                  <Checkbox key={s.id} label={s.name} checked={scope.aedt_system_ids.includes(s.id)}
                    onChange={(e) => setScope({ ...scope, aedt_system_ids: e.target.checked ? [...scope.aedt_system_ids, s.id] : scope.aedt_system_ids.filter((x) => x !== s.id) })} />
                ))}
              </div>
            )}
            <TextField label="Roles and locations" placeholder="For example: NYC roles only" value={scope.roles_note} maxLength={300} onChange={(e) => setScope({ ...scope, roles_note: e.target.value })} />
            {scope.ll144_in_scope && <Checkbox label="This client gets its own public summary" checked={scope.own_public_summary} onChange={(e) => setScope({ ...scope, own_public_summary: e.target.checked })} />}
            {node.relationship === 'customer_of_vendor' && <Checkbox label="The vendor lets this customer read the summary that names it" checked={scope.vendor_allows_summary} onChange={(e) => setScope({ ...scope, vendor_allows_summary: e.target.checked })} />}
            {manage && <Button size="sm" onClick={() => run(() => hierarchyApi.scope(node.id, { ...scope, roles_note: scope.roles_note || null }), 'LL144 scope saved.')}>Save LL144 scope</Button>}
            <p className="small muted" style={{ margin: 0 }}>Billing: counted in L-09 ({tree.ll144.in_scope} of {tree.ll144.end_clients} end-clients in LL144 scope).</p>
          </fieldset>
        )}
        {manage && <Button variant="ghost" size="sm" disabled={busy} onClick={() => run(() => hierarchyApi.unlink(node.id), `${node.name} is no longer in this group.`)}>Remove from group</Button>}
      </div>
    </Card>
  );
}

function AddEntity({ tree, clientId, onClose, onDone }: { tree: EntityTree; clientId: string; onClose: () => void; onDone: (t: EntityTree, text: string) => void }) {
  const [mode, setMode] = useState<'new' | 'existing'>('new');
  const [name, setName] = useState('');
  const [rel, setRel] = useState('end_client');
  const [parent, setParent] = useState(tree.root.id);
  const [child, setChild] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const clients = useQuery({ queryKey: ['clients-for-link'], queryFn: () => api.get<{ clients: { id: string; name: string }[] }>('/clients'), enabled: mode === 'existing' });
  const inTree = new Set(tree.nodes.map((n) => n.id));
  async function save() {
    setErr(null);
    try {
      if (mode === 'new') {
        const out = await hierarchyApi.add(clientId, { name, relationship: rel, parent_id: parent });
        onDone(out.tree, `${name} added as its own tenant.`);
      } else {
        const out = await hierarchyApi.link(parent, { child_id: child, relationship: rel });
        onDone(out, 'Client added to the group.');
      }
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Add entity" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="pills" role="tablist" aria-label="New or existing">
          <button type="button" role="tab" className="pill" aria-selected={mode === 'new'} onClick={() => setMode('new')}>New entity</button>
          <button type="button" role="tab" className="pill" aria-selected={mode === 'existing'} onClick={() => setMode('existing')}>An existing client</button>
        </div>
        {mode === 'new' ? <TextField label="Name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /> : (
          <SelectField label="Client" value={child} placeholder="Choose a client" onChange={(e) => setChild(e.target.value)}
            options={(clients.data?.clients ?? []).filter((c) => !inTree.has(c.id)).map((c) => ({ value: c.id, label: c.name }))} />
        )}
        <SelectField label="Relationship" value={rel} onChange={(e) => setRel(e.target.value)} options={RELATIONSHIPS} />
        <SelectField label="Under" value={parent} onChange={(e) => setParent(e.target.value)} options={tree.nodes.map((n) => ({ value: n.id, label: `${'— '.repeat(n.depth)}${n.name}` }))} />
        <p className="small muted" style={{ margin: 0 }}>The entity is its own tenant with no users or audit until Futran sets them up. Placing it here gives nobody access to its data.</p>
        <div className="row"><Button variant="primary" disabled={mode === 'new' ? !name.trim() : !child} onClick={save}>Add entity</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function ImportDialog({ clientId, onClose, onDone }: { clientId: string; onClose: () => void; onDone: (n: number) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function check(f: File) {
    setFile(f); setErr(null); setPreview(null);
    try { setPreview(await hierarchyApi.importCsv(clientId, f, false)); } catch (e) { setErr(errorMessage(e)); }
  }
  async function apply() {
    if (!file) return;
    try { const out = await hierarchyApi.importCsv(clientId, file, true); onDone(out.created); } catch (e) { setErr(errorMessage(e)); }
  }
  const fresh = preview?.rows.filter((r) => r.status === 'new').length ?? 0;
  return (
    <Dialog title="Import end-clients (CSV)" onClose={onClose} wide>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>Columns: <code>name</code> (required), <code>relationship</code> (end_client, subsidiary or customer_of_vendor; end_client if blank), <code>ll144_in_scope</code> (yes or no), <code>roles_note</code>.</p>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => e.target.files?.[0] && check(e.target.files[0])} />
        {err && <Alert tone="danger">{err}</Alert>}
        {preview && (
          <>
            {preview.errors.length > 0 && <Alert tone="warn">{preview.errors.map((e) => `Row ${e.row}: ${e.message}`).join(' ')}</Alert>}
            {preview.rows.length === 0 ? <EmptyState>No rows to import.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Row</th><th>Name</th><th>Relationship</th><th>LL144</th><th>Status</th></tr></thead>
                <tbody>{preview.rows.map((r) => <tr key={r.row}><td>{r.row}</td><td>{r.name}</td><td>{RELATIONSHIPS.find((x) => x.value === r.relationship)?.label}</td><td>{r.ll144_in_scope ? 'In scope' : 'No'}</td><td>{r.status === 'new' ? 'New' : 'Already in the group'}</td></tr>)}</tbody>
              </table></div>
            )}
            <div className="row"><Button variant="primary" disabled={!fresh} onClick={apply}>Import {fresh} {fresh === 1 ? 'entity' : 'entities'}</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
          </>
        )}
      </div>
    </Dialog>
  );
}
