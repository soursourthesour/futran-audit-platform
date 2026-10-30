import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { GATE_TONE, IMPACT, STAGES, TIER_LABEL, TIER_TONE, TYPES, labelOf, useRegister, type RegSystem } from '@/api/register';
import { Alert, Badge, Button, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { systemHelp as H } from '@/help/register';
import { BulkEdit, type BulkMode } from './RegisterBulk';
import './register.css';

type Preset = 'standard' | 'roles' | 'bias' | 'all';
const PRESETS: { value: Preset; label: string }[] = [{ value: 'standard', label: 'Standard (13)' }, { value: 'roles', label: 'Roles view' }, { value: 'bias', label: 'Bias and data view' }, { value: 'all', label: 'All columns' }];

export function Lock() {
  return <span className="reg-lock" aria-label="Read-only" title="Read-only"><svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M4 7V5a4 4 0 1 1 8 0v2h1v8H3V7h1Zm2 0h4V5a2 2 0 1 0-4 0v2Z" /></svg></span>;
}

export function RolesCell({ s }: { s: RegSystem }) {
  const r = s.roles;
  const gaps = r.no_such_person + r.pending_committee;
  const pct = r.required ? Math.round((r.filled / r.required) * 100) : 100;
  const notes: string[] = [];
  if (r.no_such_person) notes.push(`${r.no_such_person} no such person`);
  if (r.pending_committee) notes.push(`${r.pending_committee} pending`);
  if (!gaps && r.not_answered && s.stage !== 'live') notes.push(`${r.not_answered} not answered`);
  return (
    <div className="reg-roles">
      <div><strong>{r.filled} / {r.required}</strong></div>
      <div className="reg-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} className={gaps ? 'gap' : ''} /></div>
      <div className={`small ${gaps ? 'reg-danger' : 'muted'}`}>{notes.length ? notes.join(' · ') : r.required ? 'Complete' : 'None required yet'}</div>
    </div>
  );
}

function SystemCell({ s }: { s: RegSystem }) {
  return (
    <div>
      <Link to={`/register/${s.id}`}><strong>{s.name}</strong></Link>{!s.can_edit && <Lock />}
      <div className="small muted">{s.company_wide ? 'Company-wide · managed by the Chief AI Compliance Officer' : s.owner ? `Owner: ${s.owner.name}` : 'No owner yet'}</div>
    </div>
  );
}

export function RegisterGrid() {
  const q = useRegister();
  const { data: me } = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [preset, setPreset] = useState<Preset>('standard');
  const [bulk, setBulk] = useState<{ mode: BulkMode; rows: RegSystem[] } | null>(null);
  const [importing, setImporting] = useState(false);
  const [retire, setRetire] = useState<RegSystem | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [pulling, setPulling] = useState(false);  // Import from inventory in flight

  const d = q.data;
  const lawOptions = useMemo(() => {
    const m = new Map<string, string>();
    d?.systems.forEach((s) => s.laws.forEach((l) => m.set(l.regulation_id, l.short_name)));
    return [...m].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [d]);

  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!d) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const deptName = me?.roles.find((r) => r.role === 'dept_compliance_lead' && r.scope_id)?.scope_id;
  const myDept = d.departments.find((x) => x.id === deptName)?.name;
  const refresh = () => qc.invalidateQueries({ queryKey: ['register'] });

  async function act(fn: () => Promise<unknown>, ok: string) {
    setFlash(null);
    try { await fn(); await refresh(); setFlash({ tone: 'success', text: ok }); } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function importInventory() {
    if (pulling) return;
    setFlash(null); setPulling(true);
    try {
      const r = await api.post<{ created: number; already_in_register: number }>('/register/import-inventory');
      await refresh();
      setFlash({ tone: 'success', text: `${r.created} AI systems added from the inventory as Proposed. ${r.already_in_register} were already in the register.` });
    } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); } finally { setPulling(false); }
  }
  function exportCsv(rows?: RegSystem[]) {
    const ids = rows ? `?ids=${rows.map((r) => r.id).join(',')}` : '';
    window.location.assign(`/api/v1/register/export.csv${ids}`);
  }

  const k = d.kpis;
  const lawsCell = (s: RegSystem) => s.laws.length ? s.laws.map((l) => l.short_name).join(' · ') : <span className="muted">None chosen</span>;
  const col: Record<string, GridColumn<RegSystem>> = {
    name: { key: 'name', header: 'AI system', value: (s) => s.name, render: (s) => <SystemCell s={s} /> },
    type: { key: 'type', header: 'Type', value: (s) => s.type_label, render: (s) => <>{s.type_label}{s.type === 'agent' && <div className="small muted">{s.sourcing_label}</div>}</> },
    vendor: { key: 'vendor', header: 'Vendor / provider', value: (s) => s.vendor?.name ?? s.ai_provider_label ?? '', render: (s) => <>{s.vendor?.name ?? (s.sourcing === 'in_house' ? 'Built in-house' : '—')}{s.ai_provider_label && <div className="small muted">{s.vendor ? `Built on ${s.ai_provider_label}` : s.ai_provider_label}</div>}</> },
    model: { key: 'model', header: 'Model or algorithm', value: (s) => s.model_name ?? s.algorithm_label ?? '', render: (s) => <>{s.model_name ?? s.algorithm_label ?? '—'}{s.model_name && s.algorithm_label && <div className="small muted">{s.algorithm_label}</div>}</> },
    stage: { key: 'stage', header: 'Stage', value: (s) => STAGES.findIndex((x) => x.value === s.stage), render: (s) => <Badge tone={s.stage === 'live' ? 'navy' : s.stage === 'retired' ? 'muted' : 'default'}>{s.stage_label}</Badge> },
    risk: { key: 'risk', header: 'Risk', value: (s) => s.risk_tier ?? 0, render: (s) => s.risk_tier ? <Badge tone={TIER_TONE[s.risk_tier]}>{TIER_LABEL[s.risk_tier]}</Badge> : '—' },
    laws: { key: 'laws', header: 'Laws that apply', value: (s) => s.laws.map((l) => l.short_name).join(', '), render: (s) => <span className="small">{lawsCell(s)}</span> },
    bias: { key: 'bias', header: 'Last bias test', value: (s) => s.bias.last_tested_on ?? '', render: (s) => <>{s.bias.last_tested_on ?? (s.bias.label === 'Not required' ? 'Not required' : s.bias.label === 'Not done' ? 'Not done' : '—')}<div className={`small ${s.bias.overdue ? 'reg-danger' : 'muted'}`}>{s.bias.last_tested_on || s.bias.label === 'Not done' ? s.bias.label : s.bias.label === 'Not required' ? 'No decisions about people' : s.bias.label}</div></> },
    biasDue: { key: 'biasDue', header: 'Next bias test', value: (s) => s.bias.next_due ?? s.bias_next_due ?? '', render: (s) => s.bias.next_due ?? s.bias_next_due ?? '—' },
    nullc: { key: 'nullc', header: 'Null-compliance flag', value: (s) => (s.bias.null_compliance ? 1 : 0), render: (s) => s.bias.null_compliance ? <Badge tone="danger">Over 50% unknown</Badge> : '—' },
    consent: { key: 'consent', header: 'Data consent', value: (s) => s.consent.label, render: (s) => <span className={s.consent.missing ? 'reg-danger' : undefined}>{s.consent.label}</span> },
    dataUsed: { key: 'dataUsed', header: 'Data used', value: (s) => s.data.data_categories.length, render: (s) => <span className="small">{s.data.data_categories.length ? s.data.data_categories.join(', ').replace(/_/g, ' ') : '—'}</span> },
    subjects: { key: 'subjects', header: 'Whose data', value: (s) => s.data.data_subjects.join(', '), render: (s) => <span className="small">{s.data.data_subjects.join(', ') || '—'}</span> },
    retention: { key: 'retention', header: 'Retention', value: (s) => s.data.retention_period ?? '', render: (s) => s.data.retention_period ?? '—' },
    roles: { key: 'roles', header: 'Required roles', value: (s) => s.roles.no_such_person * 100 + s.roles.pending_committee, render: (s) => <RolesCell s={s} /> },
    nsp: { key: 'nsp', header: 'No such person', value: (s) => s.roles.no_such_person, render: (s) => s.roles.no_such_person || '—' },
    pending: { key: 'pending', header: 'Pending committee', value: (s) => s.roles.pending_committee, render: (s) => s.roles.pending_committee || '—' },
    gate: { key: 'gate', header: 'Go-live gate', value: (s) => s.gate.label, render: (s) => <Badge tone={GATE_TONE[s.gate.state] ?? 'muted'}>{s.gate.label}</Badge> },
    owner: { key: 'owner', header: 'System owner', value: (s) => s.owner?.name ?? '', render: (s) => s.owner?.name ?? '—' },
    dept: { key: 'dept', header: 'Department', value: (s) => s.department?.name ?? (s.company_wide ? 'Company-wide' : ''), render: (s) => s.department?.name ?? (s.company_wide ? 'Company-wide' : <span className="muted">Not assigned</span>) },
    impact: { key: 'impact', header: 'Decisions about people', value: (s) => labelOf(IMPACT, s.decision_impact), render: (s) => <span className="small">{labelOf(IMPACT, s.decision_impact) || '—'}</span> },
  };
  const showDept = d.can.org_wide;
  const sets: Record<Preset, string[]> = {
    standard: ['name', 'type', 'vendor', 'model', 'stage', 'risk', 'laws', 'bias', 'consent', 'roles', 'gate'],
    roles: ['name', ...(showDept ? ['dept'] : []), 'stage', 'roles', 'nsp', 'pending', 'gate', 'owner'],
    bias: ['name', 'risk', 'impact', 'bias', 'biasDue', 'nullc', 'dataUsed', 'subjects', 'consent', 'retention'],
    all: ['name', ...(showDept ? ['dept'] : []), 'type', 'vendor', 'model', 'stage', 'risk', 'impact', 'laws', 'bias', 'biasDue', 'nullc', 'dataUsed', 'subjects', 'consent', 'retention', 'roles', 'nsp', 'pending', 'gate', 'owner'],
  };
  const columns = sets[preset].map((key) => col[key]);

  const rowActions = (s: RegSystem): GridRowAction[] => [
    { label: 'Open and edit', onSelect: () => nav(`/register/${s.id}`) },
    { label: 'Edit governance roles', onSelect: () => nav(`/register/${s.id}/roles`) },
    { label: 'Record a bias test', onSelect: () => nav(`/register/${s.id}/history?add=bias_test`), disabled: !s.can_record_history },
    { label: 'Upload evidence', onSelect: () => nav(`/register/${s.id}/evidence`), disabled: !s.can_edit && !s.can_record_history },
    { label: 'Submit for go-live approval', onSelect: () => act(() => api.post(`/register/${s.id}/go-live/submit`), `${s.name} was sent to the Chief AI Compliance Officer for go-live approval.`), disabled: !s.can_submit_go_live || !['in_development', 'ready_for_go_live'].includes(s.stage) || !!s.go_live.requested_at },
    { label: 'Duplicate', onSelect: () => act(() => api.post(`/register/${s.id}/duplicate`), `${s.name} was copied as a new proposed system.`), disabled: !s.can_edit },
    { label: 'View change history', onSelect: () => nav(`/register/${s.id}/changes`) },
    { label: 'Retire this system', danger: true, onSelect: () => setRetire(s), disabled: !s.can_edit || s.stage === 'retired' },
  ];
  const editable = (rows: RegSystem[]) => rows.every((r) => r.can_edit);
  const tierOpts = [3, 2, 1].map((t) => ({ value: String(t), label: TIER_LABEL[t] }));
  const roleOpts = [{ value: 'gap', label: 'Has a gap (no such person)' }, { value: 'pending_committee', label: 'Pending committee' }, { value: 'complete', label: 'Complete' }];
  const initialFilters = params.get('roles') ? { roles: params.get('roles')! } : undefined;

  return (
    <div className="page reg-page">
      <PageHeader title="AI system register"
        subtitle={d.can.org_wide ? 'Every AI app, agent, vendor tool and AI model used across the company.' : `Every AI app, agent, vendor tool and AI model used in ${myDept ?? 'your department'}. Company-wide tools are shown read-only.`}
        actions={<>
          {d.can.edit && <Button onClick={() => setImporting(true)}>Import from CSV</Button>}
          {d.can.import_inventory && <Button onClick={importInventory} disabled={pulling}>Import from inventory</Button>}
          <Button onClick={() => exportCsv()}>Export</Button>
          {d.can.edit && <Link className="btn btn-primary" to="/register/new">Add AI system</Link>}
        </>} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <div className="reg-kpis" role="list" aria-label="Register summary">
        <Kpi n={k.systems} label="AI systems" />
        <Kpi n={k.agents} label="AI agents" />
        <Kpi n={k.go_live_blocked} label="Go-live blocked" tone={k.go_live_blocked ? 'danger' : undefined} />
        <Kpi n={k.roles_no_person} label="Required roles with no person" tone={k.roles_no_person ? 'danger' : undefined} />
        <Kpi n={k.bias_overdue} label="Bias test overdue" tone={k.bias_overdue ? 'warn' : undefined} />
        <Kpi n={k.consent_missing} label="Consent missing" tone={k.consent_missing ? 'warn' : undefined} />
      </div>
      <section className="card">
        <div className="card-body stack">
          <div className="reg-preset">
            <SelectField label="Columns" help="Choose which columns to show. The Roles view adds the gap counts; the Bias and data view adds tests, data and consent." value={preset} onChange={(e) => setPreset(e.target.value as Preset)} options={PRESETS} />
          </div>
          {d.systems.length === 0 ? (
            <EmptyState>
              No AI systems yet. {d.can.import_inventory ? 'Import them from the inventory, ' : ''}{d.can.edit ? 'add one, or import a CSV.' : ''}
            </EmptyState>
          ) : (
            <DataGrid label="AI systems" rows={d.systems} rowId={(s) => s.id} rowLabel={(s) => s.name} columns={columns} selectable initialFilters={initialFilters}
              rowClassName={(s) => (s.stage === 'retired' ? 'dg-muted' : undefined)}
              search={{ label: 'Search', placeholder: 'Name, vendor or model', text: (s) => [s.name, s.vendor?.name, s.model_name, s.reference, s.ai_provider_label].filter(Boolean).join(' ') }}
              filters={[
                { key: 'type', label: 'Type', options: TYPES, test: (s, v) => s.type === v },
                { key: 'stage', label: 'Stage', options: STAGES, test: (s, v) => s.stage === v },
                { key: 'tier', label: 'Risk tier', options: tierOpts, test: (s, v) => String(s.risk_tier) === v },
                { key: 'law', label: 'Law', options: lawOptions, test: (s, v) => s.laws.some((l) => l.regulation_id === v) },
                { key: 'roles', label: 'Governance roles', options: roleOpts, test: (s, v) => (v === 'gap' ? s.roles.no_such_person > 0 : v === 'pending_committee' ? s.roles.pending_committee > 0 : s.roles.filled === s.roles.required) },
                ...(showDept ? [{ key: 'dept', label: 'Department', options: [...d.departments.map((x) => ({ value: x.id, label: x.name })), { value: '_cw', label: 'Company-wide' }], test: (s: RegSystem, v: string) => (v === '_cw' ? s.company_wide : s.department?.id === v) }] : []),
              ]}
              bulkActions={[
                { label: 'Edit selected', run: (rows) => setBulk({ mode: 'all', rows }), available: editable },
                { label: 'Assign a role', run: (rows) => setBulk({ mode: 'roles', rows }), available: (rows) => rows.every((r) => r.can_fill_roles) },
                { label: 'Change stage', run: (rows) => setBulk({ mode: 'stage', rows }), available: editable },
                { label: 'Add or remove a law', run: (rows) => setBulk({ mode: 'laws', rows }), available: (rows) => rows.every((r) => r.can_add_law) },
                { label: 'Request bias test', run: (rows) => setBulk({ mode: 'bias', rows }), available: editable },
                { label: 'Export selected', run: (rows) => exportCsv(rows) },
              ]}
              rowActions={rowActions} />
          )}
          <p className="small muted" style={{ margin: 0 }}>
            Showing {d.systems.length} systems. Required roles counts only the roles the laws on each system require.
            {!d.can.org_wide && ' You can add, edit and bulk edit your department\'s AI systems, fill their roles from the company\'s user list and submit a system for go-live approval. Company-wide roles and tools are managed by the Chief AI Compliance Officer, who also approves go-live.'}
          </p>
        </div>
      </section>
      {bulk && <BulkEdit mode={bulk.mode} rows={bulk.rows} people={d.people} departments={d.departments} onClose={() => setBulk(null)}
        onDone={(m) => { setBulk(null); void refresh(); setFlash({ tone: 'success', text: m }); }} />}
      {importing && <CsvImport onClose={() => setImporting(false)} onDone={(m) => { setImporting(false); void refresh(); setFlash({ tone: 'success', text: m }); }} />}
      {retire && <RetireDialog s={retire} onClose={() => setRetire(null)} onDone={() => { setRetire(null); void refresh(); setFlash({ tone: 'success', text: `${retire.name} was retired.` }); }} />}
    </div>
  );
}

function Kpi({ n, label, tone }: { n: number; label: string; tone?: 'danger' | 'warn' }) {
  return <div className={`tile reg-kpi ${tone ? `reg-kpi-${tone}` : ''}`} role="listitem"><div className="value">{n}</div><div className="label">{label}</div></div>;
}

export function RetireDialog({ s, onClose, onDone }: { s: RegSystem; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await api.post(`/register/${s.id}/retire`, { reason }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Retire ${s.name}`} onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0 }}>A retired system stays in the register and its history is kept. It no longer counts in the summary.</p>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Reason *" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="row"><Button variant="danger" onClick={go} disabled={busy}>Retire this system</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function CsvImport({ onClose, onDone }: { onClose: () => void; onDone: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<{ row: number; field: string; message: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (!file) { setErr('Choose a CSV file.'); return; }
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api.upload<{ created: number; errors: { row: number; field: string; message: string }[] }>('/register/import', fd);
      if (r.errors.length) setErrors(r.errors); else onDone(`${r.created} AI systems imported.`);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Import AI systems from CSV" onClose={onClose} wide>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>Use the template's columns. Each row is checked as the form checks it, and nothing is imported until every row is correct. Live is not accepted: import those systems as Ready for go-live and submit them. <a href="/api/v1/register/import-template.csv">Download the template</a></p>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="CSV file" help={H.importFile} type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setErrors([]); }} />
        {errors.length > 0 && (
          <div className="stack-sm">
            <Alert tone="danger">{errors.length} problem{errors.length === 1 ? '' : 's'} found. Fix them in the file and import it again.</Alert>
            <div className="table-wrap"><table className="table"><thead><tr><th>Row</th><th>Column</th><th>Problem</th></tr></thead>
              <tbody>{errors.map((e, i) => <tr key={i}><td>{e.row}</td><td>{e.field}</td><td>{e.message}</td></tr>)}</tbody></table></div>
          </div>
        )}
        <div className="row"><Button variant="primary" disabled={busy} onClick={go}>Import</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

export function Section({ title, children, aside }: { title: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return <section className="card"><div className="card-header"><h2>{title}</h2>{aside}</div><div className="card-body stack">{children}</div></section>;
}
