import { useMemo, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { can, useMe, type Me } from '@/api/auth';
import { Alert, Badge, Button, Dialog, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { APPLIES_OPTIONS, STAGE_OPTIONS, STATUS_OPTIONS, appliesLabel, statusTone, type Library, type LawRow } from '@/api/regmaster';
import { bulkHelp as B, libraryHelp as H } from '@/help/regmaster';
import '@/styles/regmaster.css';

/** True when the person can open the refresh and review page for laws (the queue or a run). */
export function canReviewLaws(me: Me | null | undefined) {
  return can(me, 'view_reg_changes', 'run_law_refresh');
}

export function RegTabs({ pending }: { pending?: number }) {
  const { data: me } = useMe();
  const library = can(me, 'view_reg_master');
  const tabs = [
    library && <NavLink key="lib" to="/reg" end>Law library</NavLink>,
    canReviewLaws(me) && <NavLink key="ref" to="/reg/refresh">Refresh and review{pending ? ` (${pending})` : ''}</NavLink>,
    library && <NavLink key="roles" to="/reg/roles">Roles and committees</NavLink>,
  ].filter(Boolean);
  if (tabs.length < 2) return null;  // a single tab is just the page heading again
  return <nav className="reg-tabs" aria-label="Regulatory master">{tabs}</nav>;
}

export function LawLibrary() {
  const [filters, setFilters] = useState({ region: '', status: '', applies_to: '', topic: '', q: '', show: 'library' });
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
  const q = useQuery({ queryKey: ['reg-laws', qs], queryFn: () => api.get<Library>(`/reg/laws?${qs}`) });
  const [bulk, setBulk] = useState<LawRow[] | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [repeal, setRepeal] = useState<LawRow | null>(null);
  const nav = useNavigate();
  const { data: me } = useMe();
  const review = canReviewLaws(me);
  const rows = useMemo(() => (q.data ? q.data.groups.flatMap((g) => g.laws.map((l) => ({ ...l, regionLabel: g.label }))) : []), [q.data]);
  if (q.isLoading && !q.data) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [k]: e.target.value }));
  return (
    <div className="page">
      <PageHeader title="Law library"
        subtitle="Every geography with AI rules in force or enacted: scope, statutory requirements, the roles and committees each law requires, and penalties. Feeds client set-up, the intro letter and every AI system's required roles."
        actions={<>
          {review && <Link className="btn" to="/reg/refresh">Refresh laws with Claude</Link>}
          {d.can_edit && <Button variant="primary" onClick={() => nav('/reg/new')}>Add a law</Button>}
        </>} />
      <RegTabs pending={d.kpis.pending} />
      <p className="small muted" style={{ marginTop: -8 }}>
        {d.last_refresh ? `Last refresh: ${fmtDateTime(d.last_refresh.started_at)} · ${d.last_refresh.open} items open` : 'No refresh has run yet.'}
      </p>
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Geographies tracked</div><div className="value">{d.kpis.geographies}</div></div>
        <div className="tile"><div className="label">Laws and rules</div><div className="value">{d.kpis.laws}</div><div className="hint">{d.kpis.all} in the imported matrix</div></div>
        <div className="tile"><div className="label">Statutory requirements</div><div className="value">{d.kpis.requirements}</div></div>
        <div className="tile"><div className="label">Changes waiting for review</div><div className="value">{d.kpis.pending}</div><div className="hint">{review ? <Link to="/reg/refresh">Open the review queue</Link> : 'The Chief Auditor decides each one'}</div></div>
        <div className="tile"><div className="label">Effective dates in next 90 days</div><div className="value">{d.kpis.upcoming}</div></div>
      </div>
      <div className="reg-filters">
        <TextField label="Search" help={H.search} placeholder="Law, citation or requirement" value={filters.q} onChange={set('q')} />
        <SelectField label="Region" help={H.region} value={filters.region} onChange={set('region')} options={d.regions} placeholder="All regions" />
        <SelectField label="Status" help={H.status} value={filters.status} onChange={set('status')} options={STATUS_OPTIONS} placeholder="All statuses" />
        <SelectField label="Applies to" help={H.appliesTo} value={filters.applies_to} onChange={set('applies_to')} options={APPLIES_OPTIONS} placeholder="Any role" />
        <SelectField label="Topic" help={H.topic} value={filters.topic} onChange={set('topic')} options={d.topics} placeholder="All topics" />
        <SelectField label="Show" help={H.show} value={filters.show} onChange={set('show')} options={[{ value: 'library', label: `Laws with requirements (${d.kpis.library})` }, { value: 'all', label: `All laws in the matrix (${d.kpis.all})` }]} />
      </div>
      <DataGrid
        label="Law library"
        rows={rows}
        rowId={(r) => r.id}
        rowLabel={(r) => r.label}
        selectable={d.can_edit}
        emptyText="No laws match these filters."
        columns={[
          { key: 'law', header: 'Law or rule', value: (r) => r.label, render: (r) => (
            <div style={{ minWidth: 150 }}><Link to={`/reg/${r.id}`}><strong>{r.label}</strong></Link>{r.verify && <> <Badge tone="warn">Verify</Badge></>}
              {(r.citation || r.label !== r.short_name) && <div className="reg-sub">{r.label !== r.short_name ? r.short_name : r.citation}</div>}</div>) },
          { key: 'geography', header: 'Geography', value: (r) => r.geography, render: (r) => <>{r.geography}<div className="reg-sub">{r.regionLabel}</div></> },
          { key: 'status', header: 'Status', value: (r) => r.status_label, render: (r) => <Badge tone={statusTone(r.status)}>{r.status_label || '—'}</Badge> },
          { key: 'effective', header: 'Effective', value: (r) => r.effective_on ?? r.effective, render: (r) => <span className="small">{r.effective || '—'}</span> },
          { key: 'scope', header: 'Scope: who it applies to', value: (r) => r.scope, render: (r) => <div className="small" style={{ minWidth: 220 }}>{r.scope ? (r.scope.length > 160 ? r.scope.slice(0, 157) + '…' : r.scope) : appliesLabel(r.applies_to)}</div> },
          { key: 'reqs', header: 'Requirements', value: (r) => r.requirement_count },
          { key: 'roles', header: 'Roles required', value: (r) => r.role_count },
          { key: 'committee', header: 'Committee or program', value: (r) => r.committee, render: (r) => <span className="small">{r.committee || '—'}</span> },
          { key: 'penalty', header: 'Penalty', value: (r) => r.penalty, render: (r) => <span className="small">{r.penalty ? (r.penalty.length > 90 ? r.penalty.slice(0, 87) + '…' : r.penalty) : '—'}</span> },
          { key: 'last', header: 'Last change', value: (r) => r.last_change, render: (r) => r.pending_count ? <Badge tone="warn">Change proposed</Badge> : <span className="small">{r.last_change}</span> },
        ]}
        bulkActions={d.can_edit ? [
          { label: 'Edit selected', run: (sel) => setBulk(sel) },
          { label: 'Export selected', run: (sel) => exportCsv(sel) },
        ] : [{ label: 'Export selected', run: (sel) => exportCsv(sel) }]}
        rowActions={(r) => [
          { label: 'Open law record', onSelect: () => nav(`/reg/${r.id}`) },
          ...(d.can_edit ? [{ label: 'Edit details', onSelect: () => nav(`/reg/${r.id}/edit`) }, { label: 'Edit requirements and roles', onSelect: () => nav(`/reg/${r.id}#requirements`) }] : [{ label: 'Suggest a change', onSelect: () => nav(`/reg/${r.id}#suggest`) }]),
          { label: 'Refresh this law with Claude', onSelect: () => nav(`/reg/refresh?law=${r.id}`) },
          { label: 'View version history', onSelect: () => nav(`/reg/${r.id}#history`) },
          ...(d.can_edit && r.status !== 'repealed' ? [{ label: 'Mark repealed or lapsed', danger: true, onSelect: () => setRepeal(r) }] : []),
        ]}
      />
      <p className="reg-note">Each status, date and count comes from the last approved version; confirm with counsel before relying on it. The Chief Auditor approves every change. Futran Admin edits and Auditor suggestions become proposed changes. Nothing Claude finds goes live until a person approves it.</p>
      {repeal && <RepealDialog law={repeal} onClose={() => setRepeal(null)} onDone={(m) => { setRepeal(null); setFlash(m); q.refetch(); }} />}
      {bulk && <BulkEdit laws={bulk} onClose={() => setBulk(null)} onDone={(m) => { setBulk(null); setFlash(m); }} />}
    </div>
  );
}

function exportCsv(rows: LawRow[]) {
  const head = ['Geography', 'Law', 'Citation', 'Status', 'Effective', 'Requirements', 'Roles required', 'Committee or program', 'Penalty'];
  const esc = (v: unknown) => { const s = String(v ?? ''); const safe = /^[=+\-@]/.test(s) ? `'${s}` : s; return `"${safe.replace(/"/g, '""')}"`; };
  const csv = [head, ...rows.map((r) => [r.geography, r.label, r.citation ?? r.short_name, r.status_label, r.effective, r.requirement_count, r.role_count, r.committee, r.penalty])].map((r) => r.map(esc).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url; a.download = 'law-library.csv'; a.click();
  URL.revokeObjectURL(url);
}

type RolePreview = { role: string; name: string; summary: string; not_set_on: string[]; adds_to_clients: number; adds_to_systems: number };
type RoleLine = { role: string; level: string; needed_by_stage: string; skipNotSet: boolean };

function BulkEdit({ laws, onClose, onDone }: { laws: LawRow[]; onClose: () => void; onDone: (msg: string) => void }) {
  const qc = useQueryClient();
  const roles = useQuery({ queryKey: ['reg-roles', 'all'], queryFn: () => api.get<{ roles: { code: string; name: string }[] }>('/reg/roles?laws=all') });
  const [tracking, setTracking] = useState({ review_due_on: '', refresh_every_days: '', watch: '' });
  const [topic, setTopic] = useState('');
  const [applies, setApplies] = useState('');
  const [lines, setLines] = useState<RoleLine[]>([]);
  const [preview, setPreview] = useState<RolePreview[] | null>(null);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const ids = laws.map((l) => l.id);
  const roleOpts = (roles.data?.roles ?? []).map((r) => ({ value: r.code, label: r.name }));
  const activeLines = lines.filter((l) => l.role && l.level !== 'keep');
  const trackingBody = Object.fromEntries(Object.entries({ review_due_on: tracking.review_due_on || undefined, refresh_every_days: tracking.refresh_every_days ? Number(tracking.refresh_every_days) : undefined, watch: tracking.watch ? tracking.watch === 'yes' : undefined }).filter(([, v]) => v !== undefined));
  const contentCount = activeLines.length + (topic ? 1 : 0) + (applies ? 1 : 0);

  async function check() {
    setErr(null);
    try {
      const r = await api.post<{ roles: RolePreview[] }>('/reg/laws/bulk/preview', { ids, role_levels: activeLines.map((l) => ({ role: l.role, level: l.level, needed_by_stage: l.needed_by_stage || null })) });
      setPreview(r.roles);
    } catch (e) { setErr(errorMessage(e)); }
  }

  async function save() {
    setBusy(true); setErr(null); setErrs({});
    try {
      const notSet = (code: string) => laws.filter((l) => preview?.find((p) => p.role === code)?.not_set_on.includes(l.label)).map((l) => l.id);
      const r = await api.post<{ tracking_applied: number; proposals: number }>('/reg/laws/bulk', {
        ids, tracking: Object.keys(trackingBody).length ? trackingBody : null, topics_add: topic ? [topic] : [], applies_to_add: applies ? [applies] : [], reason: reason || null,
        role_levels: activeLines.map((l) => ({ role: l.role, level: l.level, needed_by_stage: l.needed_by_stage || null, skip: l.skipNotSet ? notSet(l.role) : [] })),
      });
      await qc.invalidateQueries({ queryKey: ['reg-laws'] });
      onDone(`${r.tracking_applied ? `Tracking updated on ${r.tracking_applied} laws. ` : ''}${r.proposals ? `${r.proposals} proposed changes sent to the Chief Auditor.` : 'No content changes to approve.'}`);
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog title={`Edit ${laws.length} selected laws`} onClose={onClose} large>
      <p className="small">{laws.map((l) => l.label).join(' · ')}</p>
      <Alert>Only the fields you change are applied. Changes to law content become proposed changes and need Chief Auditor approval.</Alert>
      {err && <Alert tone="danger">{err}</Alert>}
      <FieldGroup legend="1 · Tracking">
        <div className="reg-form-grid">
          <TextField type="date" label="Next review date" help={B.reviewDate} value={tracking.review_due_on} onChange={(e) => setTracking({ ...tracking, review_due_on: e.target.value })} />
          <SelectField label="Refresh frequency" help={B.frequency} value={tracking.refresh_every_days} onChange={(e) => setTracking({ ...tracking, refresh_every_days: e.target.value })} placeholder="Keep current" options={[{ value: '14', label: 'Every 2 weeks' }, { value: '7', label: 'Weekly (legislature in session)' }, { value: '30', label: 'Monthly' }]} />
          <SelectField label="Watch list" help={B.watch} value={tracking.watch} onChange={(e) => setTracking({ ...tracking, watch: e.target.value })} placeholder="Keep current" options={[{ value: 'yes', label: 'Add to watch list' }, { value: 'no', label: 'Remove from watch list' }]} />
        </div>
      </FieldGroup>
      <FieldGroup legend="2 · Classification">
        <div className="reg-form-grid">
          <SelectField label="Add a topic" help={B.topics} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="No change" options={[{ value: 'hiring', label: 'Hiring and employment' }, { value: 'consumer_decisions', label: 'Consumer decisions' }, { value: 'genai', label: 'Generative AI disclosure' }, { value: 'personal_data', label: 'Personal data' }]} />
          <SelectField label="Applies to (add)" help={B.appliesTo} value={applies} onChange={(e) => setApplies(e.target.value)} placeholder="No change" options={APPLIES_OPTIONS} />
        </div>
      </FieldGroup>
      <FieldGroup legend="3 · Role mapping">
        <p className="small muted">Set one role's level on all selected laws. This updates the role catalogue (M4) once approved.</p>
        {lines.map((l, i) => (
          <div className="reg-form-grid" key={i}>
            <SelectField label="Role" help={B.roleLevel} value={l.role} onChange={(e) => { setPreview(null); setLines(lines.map((x, j) => (j === i ? { ...x, role: e.target.value } : x))); }} options={roleOpts} placeholder="Choose a role" />
            <SelectField label="Set level" help={B.roleLevel} value={l.level} onChange={(e) => { setPreview(null); setLines(lines.map((x, j) => (j === i ? { ...x, level: e.target.value } : x))); }} options={[{ value: 'keep', label: 'Keep current' }, { value: 'required', label: 'Required' }, { value: 'recommended', label: 'Recommended' }, { value: 'not_required', label: 'Not required' }]} />
            <SelectField label="Needed by" help={B.neededBy} value={l.needed_by_stage} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, needed_by_stage: e.target.value } : x)))} options={STAGE_OPTIONS} placeholder="Role default" />
          </div>
        ))}
        <Button size="sm" onClick={() => setLines([...lines, { role: '', level: 'required', needed_by_stage: '', skipNotSet: true }])}>{lines.length ? 'Add another role' : 'Add a role'}</Button>
      </FieldGroup>
      {activeLines.length > 0 && (
        <FieldGroup legend="4 · Check before saving">
          {!preview ? <Button onClick={check}>Check the effect</Button> : preview.map((p) => {
            const line = lines.find((l) => l.role === p.role)!;
            return (
              <div key={p.role} className="stack-sm" style={{ marginBottom: 12 }}>
                <div><strong>{p.name}</strong> · <span className="small">{p.summary}</span></div>
                {p.not_set_on.length > 0 && line.level !== 'not_required' && (
                  <Alert tone="warn">
                    {p.not_set_on.join(', ')} {p.not_set_on.length === 1 ? 'does' : 'do'} not map this role today. Applying it would add the role to {p.adds_to_systems} AI systems at {p.adds_to_clients} clients.
                    <div className="row" style={{ marginTop: 8, gap: 16 }}>
                      <label className="check"><input type="radio" name={`skip-${p.role}`} checked={line.skipNotSet} onChange={() => setLines(lines.map((x) => (x.role === p.role ? { ...x, skipNotSet: true } : x)))} /><span>Skip {p.not_set_on.join(', ')} for this role</span></label>
                      <label className="check"><input type="radio" name={`skip-${p.role}`} checked={!line.skipNotSet} onChange={() => setLines(lines.map((x) => (x.role === p.role ? { ...x, skipNotSet: false } : x)))} /><span>Apply to all {laws.length} anyway</span></label>
                    </div>
                  </Alert>
                )}
              </div>
            );
          })}
        </FieldGroup>
      )}
      {contentCount > 0 && <TextArea label="Reason for change *" help={B.reason} value={reason} onChange={(e) => setReason(e.target.value)} error={errs.reason} rows={2} />}
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginTop: 12 }}>
        <span className="small muted">{Object.keys(trackingBody).length} tracking fields · {contentCount} content changes go to the review queue</span>
        <div className="row"><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || (activeLines.length > 0 && !preview) || (!contentCount && !Object.keys(trackingBody).length)} onClick={save}>Apply and send for approval</Button></div>
      </div>
    </Dialog>
  );
}

function RepealDialog({ law, onClose, onDone }: { law: LawRow; onClose: () => void; onDone: (m: string) => void }) {
  const [f, setF] = useState({ reason: '', source_url: '', source_quote: '' });
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      await api.post(`/reg/laws/${law.id}/proposals`, { changes: [{ field_path: 'repeal', new_value: { status: 'repealed' }, change_type: 'repeal' }], summary: `Mark ${law.label} repealed or lapsed`, reason: f.reason, source_url: f.source_url || null, source_quote: f.source_quote || null });
      onDone(`${law.label}: repeal sent to the Chief Auditor for approval.`);
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Mark ${law.label} repealed or lapsed`} onClose={onClose}>
      <p className="small">This is a proposed change. Clients keep the law until the Chief Auditor approves.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <TextArea label="Reason *" help={B.reason} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} rows={2} />
      <TextField label="Source link" type="url" help="The official page that shows the repeal or lapse." value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} />
      <TextArea label="Quoted passage" help="The words from the source that show the law no longer applies." value={f.source_quote} onChange={(e) => setF({ ...f, source_quote: e.target.value })} rows={2} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="danger" disabled={!f.reason.trim()} onClick={save}>Send for approval</Button></div>
    </Dialog>
  );
}
