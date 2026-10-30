import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, Loading, PageHeader, SelectField, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { caseHelp as H } from '@/help/monitoring';
import { CaseForm } from './CaseForm';
import { STAGE_TONE, lines, type CaseDetail, type CaseList, type CaseRow } from './types';
import '@/styles/monitoring.css';

type Msg = { tone: 'success' | 'danger'; text: string } | null;

export function stageBadge(c: { stage: string; stage_label: string; stage_note: string | null }) {
  return <span className="stack-xs"><Badge tone={STAGE_TONE[c.stage] ?? 'muted'}>{c.stage_label}</Badge>{c.stage_note && <span className="small muted">{c.stage_note}</span>}</span>;
}

/** Choose a Sales owner, then create one opportunity per client with similar AI. */
export function AssignDialog({ onClose, onAssign }: { onClose: () => void; onAssign: (ownerId: string) => Promise<void> }) {
  const q = useQuery({ queryKey: ['opp-owners'], queryFn: () => api.get<{ owners: { id: string; name: string }[] }>('/opportunities') });
  const [owner, setOwner] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (busy) return;  // one click, one set of opportunities
    setBusy(true); setErr(null);
    try { await onAssign(owner); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Assign to Sales" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>Creates an opportunity for each client using similar AI. For a current audit client, the Chief Auditor approves any offer first.</p>
        <SelectField label="Owner" help={H.owner} value={owner} onChange={(e) => setOwner(e.target.value)} options={(q.data?.owners ?? []).map((o) => ({ value: o.id, label: o.name }))} placeholder="Choose" />
        <div className="row"><Button variant="primary" disabled={!owner || busy} onClick={go}>Create opportunities</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

export function Litigation() {
  const { data: me } = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['litigation'], queryFn: () => api.get<CaseList>('/litigation') });
  const [msg, setMsg] = useState<Msg>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<CaseDetail | null>(null);
  const [points, setPoints] = useState<CaseDetail | null>(null);
  const [assign, setAssign] = useState<string[] | null>(null);
  const canEdit = !!q.data?.can_edit;
  const canSell = hasRole(me ?? undefined, 'sales_team', 'chief_auditor');
  const refresh = () => qc.invalidateQueries({ queryKey: ['litigation'] });
  const detail = (id: string) => api.get<CaseDetail>(`/litigation/${id}`);

  async function briefing(ids: string[]) {
    const out = await api.post<{ queued: number }>('/litigation/bulk-briefing', { ids });
    setMsg({ tone: 'success', text: `${out.queued} client ${out.queued === 1 ? 'briefing waits' : 'briefings wait'} for the Chief Auditor in Client alerts.` });
  }
  async function follow(ids: string[], on: boolean) {
    await api.post('/litigation/bulk-follow', { ids, follow: on });
    await refresh();
  }
  function exportCsv(ids?: string[]) { window.location.href = `/api/v1/litigation/export.csv${ids ? `?ids=${ids.join(',')}` : ''}`; }

  const columns: GridColumn<CaseRow>[] = [
    { key: 'name', header: 'Case', value: (c) => c.name, render: (c) => <span><Link to={`/litigation/${c.id}`}><strong>{c.name}</strong></Link>{c.following && <span className="small muted block">Following</span>}</span> },
    { key: 'geo', header: 'Geography', value: (c) => c.geography ?? '' },
    { key: 'area', header: 'Law or area', value: (c) => c.area },
    { key: 'court', header: 'Court', value: (c) => c.court ?? '' },
    { key: 'about', header: 'What it is about', value: (c) => c.description ?? '', render: (c) => <span className="clamp-3">{c.description}</span> },
    { key: 'stage', header: 'Stage', value: (c) => c.stage_label, render: stageBadge },
    { key: 'updated', header: 'Last checked', value: (c) => c.last_update_on ?? '', render: (c) => <span className="nowrap">{c.last_update_on ?? '—'}</span> },
    { key: 'clients', header: 'Clients with similar AI', value: (c) => c.clients_count, render: (c) => (c.clients_count ? <span>{c.clients_count} {c.clients_count === 1 ? 'client' : 'clients'}{c.match_summary && <span className="small muted block">{c.match_summary}</span>}</span> : <span className="muted">None</span>) },
  ];
  const rowActions = (c: CaseRow): GridRowAction[] => [
    { label: 'Open case', onSelect: () => nav(`/litigation/${c.id}`) },
    ...(canEdit ? [{ label: 'Edit', onSelect: () => detail(c.id).then(setEditing) }] : []),
    { label: 'Talking points', onSelect: () => detail(c.id).then(setPoints) },
    { label: 'Clients with similar AI', onSelect: () => nav(`/litigation/${c.id}#clients`) },
    { label: 'Send client briefing', onSelect: () => briefing([c.id]).catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
    ...(canSell ? [{ label: 'Create opportunity', onSelect: () => setAssign([c.id]) }] : []),
    { label: c.following ? 'Stop following' : 'Follow updates', onSelect: () => follow([c.id], !c.following) },
  ];
  const lr = q.data?.last_refresh;
  return (
    <div className="page">
      <PageHeader title="AI litigation tracker" subtitle="Court cases and decisions that shape how AI laws are read. Use them to explain risk to clients and to see which clients use similar AI. Visible to the Chief Auditor, Auditors and Sales Team; clients receive briefings, not the tracker."
        actions={canEdit ? <><Link className="btn" to="/reg/refresh?kind=litigation">Refresh with Claude</Link><Button variant="primary" onClick={() => setAdding(true)}>Add case</Button></> : undefined} />
      <p className="small muted">
        {lr ? <>Last refresh {fmtDateTime(lr.started_at)} · {lr.open ? <Link to="/reg/refresh?kind=litigation">{lr.open} {lr.open === 1 ? 'update' : 'updates'} waiting for review</Link> : 'nothing waiting for review'}{lr.alert_status ? ` · ${lr.alert_status}` : ''}</> : 'No litigation refresh has run yet.'}
        {canEdit && <> · <Link to="/staff/alerts">alert settings</Link></>}
      </p>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card>
        {q.isLoading || !q.data ? <Loading /> : (
          <DataGrid label="Cases" rows={q.data.items} rowId={(c) => c.id} rowLabel={(c) => c.name} columns={columns} selectable
            bulkActions={[
              { label: 'Send client briefing', run: (rows) => briefing(rows.map((r) => r.id)) },
              ...(canSell ? [{ label: 'Assign to Sales', run: async (rows: CaseRow[]) => setAssign(rows.map((r) => r.id)) }] : []),
              { label: 'Follow', run: (rows) => follow(rows.map((r) => r.id), true) },
              { label: 'Export', run: (rows) => exportCsv(rows.map((r) => r.id)) },
            ]}
            rowActions={rowActions}
            filters={[
              { key: 'geo', label: 'Geography', options: q.data.filters.geographies.map((g) => ({ value: g, label: g })), test: (c, v) => c.geography === v },
              { key: 'area', label: 'Law or area', options: q.data.filters.areas.map((a) => ({ value: a, label: a })), test: (c, v) => c.area === v },
              { key: 'stage', label: 'Stage', options: q.data.filters.stages, test: (c, v) => c.stage === v },
            ]}
            search={{ label: 'Search cases', text: (c) => `${c.name} ${c.area} ${c.court ?? ''} ${c.description ?? ''}` }}
            initialSort={{ key: 'geo', dir: 'asc' }}
            emptyText="No cases yet." />
        )}
        <p className="small muted">Stages come from the last approved refresh or edit. Check the court record before sharing a stage with a client. Each case links to its sources.</p>
      </Card>
      {adding && <CaseForm onClose={() => setAdding(false)} onSaved={(c) => { setAdding(false); refresh(); nav(`/litigation/${c.id}`); }} />}
      {editing && <CaseForm initial={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
      {points && (
        <Dialog title={`Talking points · ${points.name}`} onClose={() => setPoints(null)}>
          <TalkingPoints c={points} />
        </Dialog>
      )}
      {assign && <AssignDialog onClose={() => setAssign(null)} onAssign={async (owner) => {
        const out = await api.post<{ created: number }>('/litigation/bulk-assign', { ids: assign, owner_id: owner });
        setAssign(null);
        setMsg({ tone: 'success', text: `${out.created} ${out.created === 1 ? 'opportunity' : 'opportunities'} created.` });
      }} />}
    </div>
  );
}

export function TalkingPoints({ c }: { c: CaseDetail }) {
  return (
    <div className="talking">
      <div><h3>For the Chief Auditor and Sales Team</h3><ul>{lines(c.talking_points_futran).map((l, i) => <li key={i}>{l}</li>)}</ul></div>
      <div><h3>For the client's Chief AI Compliance Officer (sent in the briefing)</h3><ul>{lines(c.talking_points_client).map((l, i) => <li key={i}>{l}</li>)}</ul></div>
      <p className="small muted">Not legal advice. Clients should confirm with counsel.</p>
    </div>
  );
}
