import { useMemo, useState, type ReactNode } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { SOURCE_OPTIONS, TYPE_OPTIONS, useAiSystems, type AiList, type AiRow, type AiSource } from '@/api/aiSystems';
import { GATE_TONE, IMPACT, STAGES, TIER_LABEL, TIER_TONE, TYPES, labelOf, type RegSystem } from '@/api/register';
import { Alert, Badge, Button, Checkbox, Dialog, EmptyState, FieldHelp, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import { DataGrid, RowMenu, type GridColumn, type GridFilter, type GridRowAction } from '@/components/ui/DataGrid';
import { systemHelp as H } from '@/help/register';
import { ACCOUNT_LABELS, AddTool, type Tool } from '@/screens/client/Inventory';
import { CarriedBanner } from '@/screens/wsk/Carried';
import { BulkEdit, type BulkMode } from './RegisterBulk';
import './register.css';

type Preset = 'standard' | 'roles' | 'bias' | 'all';
const PRESETS: { value: Preset; label: string }[] = [{ value: 'standard', label: 'Standard' }, { value: 'roles', label: 'Roles view' }, { value: 'bias', label: 'Bias and data view' }, { value: 'all', label: 'All columns' }];

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

const dash = <span className="muted">—</span>;
const ifSystem = (render: (s: RegSystem) => ReactNode) => (r: AiRow) => (r.system ? render(r.system) : dash);
const sysValue = (v: (s: RegSystem) => string | number | null | undefined) => (r: AiRow) => (r.system ? v(r.system) : '');
/** Filters a page address can preset: the old AI inventory and AI systems pages redirect here with them (11-10 U1). */
const URL_FILTERS = ['type', 'systype', 'source', 'dept', 'stage', 'tier', 'audit', 'registered', 'law', 'roles'];

function toolDetail(t: Tool) {
  return [ACCOUNT_LABELS[t.account_type] ?? t.account_type, t.declared_count ? `declared by ${t.declared_count}` : '', t.training_on_inputs === 'unknown' ? 'training on inputs not known' : ''].filter(Boolean).join(' · ');
}

function NameCell({ r }: { r: AiRow }) {
  if (r.system) return <SystemCell s={r.system} />;
  const to = r.kind === 'tool' ? (r.in_register_as ? `/register/${r.in_register_as.id}` : null) : r.open;
  const sub = r.tool ? toolDetail(r.tool) : r.use_case ? (r.use_case.tools.join(', ') || 'No tool chosen yet') : null;
  return (
    <div>
      {to ? <Link to={to}><strong>{r.name}</strong></Link> : <strong>{r.name}</strong>}
      {sub && <div className="small muted">{sub}</div>}
      {r.use_case?.status === 'returned' && r.use_case.returned_comment && <div className="small" style={{ color: 'var(--warn)' }}>{r.use_case.returned_comment}</div>}
    </div>
  );
}

function StageCell({ r }: { r: AiRow }) {
  if (!r.stage_label) return dash;
  const tone = r.system ? (r.system.stage === 'live' ? 'navy' : r.system.stage === 'retired' ? 'muted' : 'default')
    : r.stage === 'tool:approved' || r.stage === 'uc:dept_approved' ? 'success' : r.stage === 'tool:not_approved' || r.stage === 'uc:returned' ? 'warn' : r.stage === 'uc:submitted' ? 'navy' : 'muted';
  return <Badge tone={tone}>{r.stage_label}</Badge>;
}

function AuditCell({ r }: { r: AiRow }) {
  if (r.in_audit === null) return dash;
  if (!r.in_audit) return <span className="small muted">Not in the audit</span>;
  if (!r.audit) return <span className="small">In the audit</span>;
  return (
    <div className="small">
      <div>{r.audit.reference_id} · {r.audit.status_label}</div>
      {r.audit.can_answer && r.audit.applicable !== undefined && <div className="muted">{r.audit.answered} of {r.audit.applicable} answered</div>}
    </div>
  );
}

const deptText = (r: AiRow) => (r.company_wide ? 'Company-wide' : r.departments.map((d) => d.name).join(', '));

/** 11-10 U1: the client's one list of AI — register systems, inventory tools and agents, use cases and the systems in the
 *  current audit — with filters and one Add. Each row keeps the actions it had on its old screen. */
export function RegisterGrid() {
  const { search } = useLocation();
  return <AiSystemsList key={search} />;  // a new address (a redirect or a link with a filter preset) starts from its own filters
}

function AiSystemsList() {
  const q = useAiSystems();
  const { data: me } = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [preset, setPreset] = useState<Preset>('standard');
  const [bulk, setBulk] = useState<{ mode: BulkMode; rows: RegSystem[] } | null>(null);
  const [importing, setImporting] = useState(false);
  const [addingTool, setAddingTool] = useState(false);
  const [addMenu, setAddMenu] = useState<HTMLElement | null>(null);
  const [retire, setRetire] = useState<RegSystem | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [pulling, setPulling] = useState(false);  // Import from inventory in flight
  const [showFolded, setShowFolded] = useState(params.get('all') === '1');

  const d = q.data;
  const lawOptions = useMemo(() => {
    const m = new Map<string, string>();
    d?.rows.forEach((r) => r.system?.laws.forEach((l) => m.set(l.regulation_id, l.short_name)));
    return [...m].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [d]);
  const initialFilters = useMemo(() => {
    const out: Record<string, string> = {};
    URL_FILTERS.forEach((k) => { const v = params.get(k); if (v) out[k] = v; });
    return Object.keys(out).length ? out : undefined;
  }, [params]);

  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!d) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const reg = d.register;
  const inv = d.inventory;
  const deptName = me?.roles.find((r) => r.role === 'dept_compliance_lead' && r.scope_id)?.scope_id;
  const myDept = reg?.departments.find((x) => x.id === deptName)?.name;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['ai-systems'] }), qc.invalidateQueries({ queryKey: ['register'] }), qc.invalidateQueries({ queryKey: ['inventory'] })]);

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

  const folded = d.rows.filter((r) => r.in_register_as).length;
  const rows = showFolded ? d.rows : d.rows.filter((r) => !r.in_register_as);
  const hasAudit = d.rows.some((r) => r.in_audit !== null);
  const lawsCell = (s: RegSystem) => s.laws.length ? s.laws.map((l) => l.short_name).join(' · ') : <span className="muted">None chosen</span>;
  const col: Record<string, GridColumn<AiRow>> = {
    name: { key: 'name', header: 'AI system', value: (r) => r.name, render: (r) => <NameCell r={r} />, width: '220px' },
    type: { key: 'type', header: 'Type', value: (r) => r.type_label, render: (r) => <><span>{r.type_label}</span>{r.subtype && <div className="small muted">{r.subtype}{r.system?.type === 'agent' ? ` · ${r.system.sourcing_label}` : ''}</div>}</> },
    source: { key: 'source', header: 'Where it came from', value: (r) => r.source_label, render: (r) => <><span>{r.source_label}</span>{r.in_register_as && <div className="small muted">In the register as {r.in_register_as.name}</div>}</> },
    dept: { key: 'dept', header: 'Department', value: deptText, render: (r) => deptText(r) || <span className="muted">Not assigned</span> },
    stage: { key: 'stage', header: 'Stage or status', value: (r) => (r.system ? STAGES.findIndex((x) => x.value === r.system!.stage) : 100 + (r.stage_label ?? '').charCodeAt(0)), render: (r) => <StageCell r={r} /> },
    risk: { key: 'risk', header: 'Risk', value: (r) => r.tier ?? 0, render: (r) => r.tier ? <Badge tone={TIER_TONE[r.tier]}>{TIER_LABEL[r.tier]}</Badge> : dash },
    audit: { key: 'audit', header: 'Current audit', value: (r) => (r.in_audit ? 1 : 0), render: (r) => <AuditCell r={r} /> },
    vendor: { key: 'vendor', header: 'Vendor / provider', value: sysValue((s) => s.vendor?.name ?? s.ai_provider_label ?? ''), render: ifSystem((s) => <>{s.vendor?.name ?? (s.sourcing === 'in_house' ? 'Built in-house' : '—')}{s.ai_provider_label && <div className="small muted">{s.vendor ? `Built on ${s.ai_provider_label}` : s.ai_provider_label}</div>}</>) },
    model: { key: 'model', header: 'Model or algorithm', value: sysValue((s) => s.model_name ?? s.algorithm_label ?? ''), render: ifSystem((s) => <>{s.model_name ?? s.algorithm_label ?? '—'}{s.model_name && s.algorithm_label && <div className="small muted">{s.algorithm_label}</div>}</>) },
    laws: { key: 'laws', header: 'Laws that apply', value: sysValue((s) => s.laws.map((l) => l.short_name).join(', ')), render: ifSystem((s) => <span className="small">{lawsCell(s)}</span>) },
    bias: { key: 'bias', header: 'Last bias test', value: sysValue((s) => s.bias.last_tested_on ?? ''), render: ifSystem((s) => <>{s.bias.last_tested_on ?? (s.bias.label === 'Not required' ? 'Not required' : s.bias.label === 'Not done' ? 'Not done' : '—')}<div className={`small ${s.bias.overdue ? 'reg-danger' : 'muted'}`}>{s.bias.last_tested_on || s.bias.label === 'Not done' ? s.bias.label : s.bias.label === 'Not required' ? 'No decisions about people' : s.bias.label}</div></>) },
    biasDue: { key: 'biasDue', header: 'Next bias test', value: sysValue((s) => s.bias.next_due ?? s.bias_next_due ?? ''), render: ifSystem((s) => s.bias.next_due ?? s.bias_next_due ?? '—') },
    nullc: { key: 'nullc', header: 'Null-compliance flag', value: sysValue((s) => (s.bias.null_compliance ? 1 : 0)), render: ifSystem((s) => s.bias.null_compliance ? <Badge tone="danger">Over 50% unknown</Badge> : '—') },
    consent: { key: 'consent', header: 'Data consent', value: sysValue((s) => s.consent.label), render: ifSystem((s) => <span className={s.consent.missing ? 'reg-danger' : undefined}>{s.consent.label}</span>) },
    dataUsed: { key: 'dataUsed', header: 'Data used', value: sysValue((s) => s.data.data_categories.length), render: ifSystem((s) => <span className="small">{s.data.data_categories.length ? s.data.data_categories.join(', ').replace(/_/g, ' ') : '—'}</span>) },
    subjects: { key: 'subjects', header: 'Whose data', value: sysValue((s) => s.data.data_subjects.join(', ')), render: ifSystem((s) => <span className="small">{s.data.data_subjects.join(', ') || '—'}</span>) },
    retention: { key: 'retention', header: 'Retention', value: sysValue((s) => s.data.retention_period ?? ''), render: ifSystem((s) => s.data.retention_period ?? '—') },
    roles: { key: 'roles', header: 'Required roles', value: sysValue((s) => s.roles.no_such_person * 100 + s.roles.pending_committee), render: ifSystem((s) => <RolesCell s={s} />) },
    nsp: { key: 'nsp', header: 'No such person', value: sysValue((s) => s.roles.no_such_person), render: ifSystem((s) => s.roles.no_such_person || '—') },
    pending: { key: 'pending', header: 'Pending committee', value: sysValue((s) => s.roles.pending_committee), render: ifSystem((s) => s.roles.pending_committee || '—') },
    gate: { key: 'gate', header: 'Go-live gate', value: sysValue((s) => s.gate.label), render: ifSystem((s) => <Badge tone={GATE_TONE[s.gate.state] ?? 'muted'}>{s.gate.label}</Badge>) },
    owner: { key: 'owner', header: 'System owner', value: sysValue((s) => s.owner?.name ?? ''), render: ifSystem((s) => s.owner?.name ?? '—') },
    impact: { key: 'impact', header: 'Decisions about people', value: sysValue((s) => labelOf(IMPACT, s.decision_impact)), render: ifSystem((s) => <span className="small">{labelOf(IMPACT, s.decision_impact) || '—'}</span>) },
  };
  const auditCol = hasAudit ? ['audit'] : [];
  const sets: Record<Preset, string[]> = {
    standard: reg ? ['name', 'type', 'source', 'dept', 'stage', 'risk', ...auditCol, 'vendor', 'laws', 'roles', 'gate'] : ['name', 'type', 'source', 'dept', 'stage', 'risk', ...auditCol],
    roles: ['name', 'type', 'dept', 'stage', 'roles', 'nsp', 'pending', 'gate', 'owner'],
    bias: ['name', 'type', 'risk', 'impact', 'bias', 'biasDue', 'nullc', 'dataUsed', 'subjects', 'consent', 'retention'],
    all: ['name', 'type', 'source', 'dept', 'vendor', 'model', 'stage', 'risk', ...auditCol, 'impact', 'laws', 'bias', 'biasDue', 'nullc', 'dataUsed', 'subjects', 'consent', 'retention', 'roles', 'nsp', 'pending', 'gate', 'owner'],
  };
  const columns = sets[reg ? preset : 'standard'].map((key) => col[key]);

  const importAction = (r: AiRow) => (reg?.can.import_inventory && !r.in_register_as && (r.kind === 'tool' || r.use_case?.status === 'dept_approved')
    ? [{ label: 'Import new inventory items into the register', onSelect: () => void importInventory(), disabled: pulling }] : []);
  const auditAction = (r: AiRow) => (r.audit?.can_answer ? [{ label: 'Answer the audit questions', onSelect: () => nav(`/systems/${r.audit!.system_id}`) }] : []);
  const registerAction = (r: AiRow) => (r.in_register_as ? [{ label: `Open ${r.in_register_as.name} in the register`, onSelect: () => nav(`/register/${r.in_register_as!.id}`) }] : []);
  function rowActions(r: AiRow): GridRowAction[] {
    const s = r.system;
    if (s) return [
      { label: 'Open and edit', onSelect: () => nav(`/register/${s.id}`) },
      ...auditAction(r),
      { label: 'Edit governance roles', onSelect: () => nav(`/register/${s.id}/roles`) },
      { label: 'Record a bias test', onSelect: () => nav(`/register/${s.id}/history?add=bias_test`), disabled: !s.can_record_history },
      { label: 'Upload evidence', onSelect: () => nav(`/register/${s.id}/evidence`), disabled: !s.can_edit && !s.can_record_history },
      { label: 'Submit for go-live approval', onSelect: () => act(() => api.post(`/register/${s.id}/go-live/submit`), `${s.name} was sent to the Chief AI Compliance Officer for go-live approval.`), disabled: !s.can_submit_go_live || !['in_development', 'ready_for_go_live'].includes(s.stage) || !!s.go_live.requested_at },
      { label: 'Duplicate', onSelect: () => act(() => api.post(`/register/${s.id}/duplicate`), `${s.name} was copied as a new proposed system.`), disabled: !s.can_edit },
      { label: 'View change history', onSelect: () => nav(`/register/${s.id}/changes`) },
      { label: 'Retire this system', danger: true, onSelect: () => setRetire(s), disabled: !s.can_edit || s.stage === 'retired' },
    ];
    if (r.kind === 'system') return auditAction(r);  // a system in the current audit that is not on a register row this person sees
    if (r.tool) {
      const t = r.tool;
      const mark = (status: string, label: string) => ({ label, disabled: t.approval_status === status, onSelect: () => act(() => api.patch(`/tools/${t.id}`, { approval_status: status }), `${r.name} is marked ${TOOL_STATUS[status].toLowerCase()}.`) });
      return [
        ...registerAction(r),
        ...(r.can.approve_tool ? [mark('approved', 'Approve'), mark('not_approved', 'Mark not approved'), mark('unreviewed', 'Mark unreviewed')] : []),
        ...(inv?.can_add_use_case ? [{ label: 'Add a use case', onSelect: () => nav('/inventory/new') }] : []),
        ...importAction(r),
      ];
    }
    const uc = r.use_case!;
    return [
      { label: r.can.review_use_case ? 'Review and approve' : 'Open the use case', onSelect: () => nav(`/inventory/${uc.id}`) },
      ...registerAction(r),
      ...importAction(r),
    ];
  }
  const regRows = (rows: AiRow[]) => rows.map((r) => r.system!);
  const onlySystems = (rows: AiRow[]) => rows.every((r) => !!r.system);
  const editable = (rows: AiRow[]) => onlySystems(rows) && rows.every((r) => r.system!.can_edit);
  const tierOpts = [3, 2, 1].map((t) => ({ value: String(t), label: TIER_LABEL[t] }));
  const roleOpts = [{ value: 'gap', label: 'Has a gap (no such person)' }, { value: 'pending_committee', label: 'Pending committee' }, { value: 'complete', label: 'Complete' }];
  const deptOpts = (() => {
    const m = new Map<string, string>();
    d.rows.forEach((r) => r.departments.forEach((x) => m.set(x.id, x.name)));
    const out = [...m].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
    return d.rows.some((r) => r.company_wide) ? [...out, { value: '_cw', label: 'Company-wide' }] : out;
  })();
  const stageOpts = (() => {
    const m = new Map<string, string>();
    STAGES.forEach((x) => { if (d.rows.some((r) => r.system?.stage === x.value)) m.set(x.value, x.label); });
    d.rows.forEach((r) => { if (!r.system && r.stage && r.stage_label) m.set(r.stage, r.stage_label); });
    return [...m].map(([value, label]) => ({ value, label }));
  })();
  const filters: GridFilter<AiRow>[] = [
    { key: 'type', label: 'Type', options: TYPE_OPTIONS, test: (r, v) => (v === 'inventory' ? r.kind !== 'system' : r.kind === v) },
    { key: 'source', label: 'Where it came from', options: SOURCE_OPTIONS, test: (r, v) => r.sources.includes(v as AiSource) },
    ...(deptOpts.length ? [{ key: 'dept', label: 'Department', options: deptOpts, test: (r: AiRow, v: string) => (v === '_cw' ? r.company_wide : r.departments.some((x) => x.id === v)) }] : []),
    { key: 'stage', label: 'Stage or status', options: stageOpts, test: (r, v) => r.stage === v },
    { key: 'tier', label: 'Risk tier', options: tierOpts, test: (r, v) => String(r.tier) === v },
    ...(hasAudit ? [{ key: 'audit', label: 'Current audit', options: [{ value: 'yes', label: 'In the current audit' }, { value: 'no', label: 'Not in the current audit' }], test: (r: AiRow, v: string) => (v === 'yes' ? !!r.in_audit : r.in_audit === false) }] : []),
    ...(reg ? [
      { key: 'registered', label: 'Register', options: [{ value: 'no', label: 'Not yet registered' }, { value: 'yes', label: 'In the register' }], test: (r: AiRow, v: string) => (v === 'no' ? r.registered === false : r.registered === true) },
      { key: 'systype', label: 'Kind of system', options: TYPES, test: (r: AiRow, v: string) => r.system?.type === v },
      { key: 'law', label: 'Law', options: lawOptions, test: (r: AiRow, v: string) => !!r.system?.laws.some((l) => l.regulation_id === v) },
      { key: 'roles', label: 'Governance roles', options: roleOpts, test: (r: AiRow, v: string) => { const x = r.system?.roles; return !!x && (v === 'gap' ? x.no_such_person > 0 : v === 'pending_committee' ? x.pending_committee > 0 : x.filled === x.required); } },
    ] : []),
  ];
  const addItems: GridRowAction[] = [
    ...(reg?.can.edit ? [{ label: 'AI system', onSelect: () => nav('/register/new') }] : []),
    ...(inv?.can_add_tool ? [{ label: 'Tool or agent', onSelect: () => setAddingTool(true) }] : []),
    ...(inv?.can_add_use_case ? [{ label: 'Use case', onSelect: () => nav('/inventory/new') }] : []),
    ...(reg?.can.edit ? [{ label: 'Import AI systems from a file', onSelect: () => setImporting(true) }] : []),
  ];
  const subtitle = reg && !reg.can.org_wide
    ? `Every AI app, agent, vendor tool and AI model used in ${myDept ?? 'your department'}, with the AI inventory and the systems in the current audit. Company-wide tools are shown read-only.`
    : reg ? 'Every AI app, agent, vendor tool, AI model and use case in the company: the register, the AI inventory and the systems in the current audit, in one list.'
      : 'The AI tools, agents and use cases in the AI inventory, and the systems in the current audit you answer for.';
  const k = reg?.kpis;

  return (
    <div className="page reg-page">
      <PageHeader title="AI systems" subtitle={subtitle}
        actions={<>
          {reg?.can.import_inventory && <span className="reg-btn-help"><Button onClick={importInventory} disabled={pulling}>Import from inventory</Button><FieldHelp label="What the inventory import copies">{H.importInventory}</FieldHelp></span>}
          {reg && <Button onClick={() => exportCsv()}>Export</Button>}
          {addItems.length > 0 && <Button variant="primary" aria-haspopup="menu" aria-expanded={!!addMenu} onClick={(e) => setAddMenu(addMenu ? null : e.currentTarget)}>Add</Button>}
        </>} />
      {addMenu && <RowMenu label="Add" items={addItems} anchor={addMenu} onClose={(refocus) => { const a = addMenu; setAddMenu(null); if (refocus) a.focus(); }} />}
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      {k && (
        <div className="reg-kpis" role="list" aria-label="Register summary">
          <Kpi n={k.systems} label="AI systems" />
          <Kpi n={k.agents} label="AI agents" />
          <Kpi n={k.go_live_blocked} label="Go-live blocked" tone={k.go_live_blocked ? 'danger' : undefined} />
          <Kpi n={k.roles_no_person} label="Required roles with no person" tone={k.roles_no_person ? 'danger' : undefined} />
          <Kpi n={k.bias_overdue} label="Bias test overdue" tone={k.bias_overdue ? 'warn' : undefined} />
          <Kpi n={k.consent_missing} label="Consent missing" tone={k.consent_missing ? 'warn' : undefined} />
        </div>
      )}
      {d.audit && <AuditPanel a={d.audit} />}
      <section className="card">
        <div className="card-body stack">
          <div className="reg-listbar">
            {reg && <div className="reg-preset"><SelectField label="Columns" help="Choose which columns to show. The Roles view adds the gap counts; the Bias and data view adds tests, data and consent. Register columns are blank for inventory items." value={preset} onChange={(e) => setPreset(e.target.value as Preset)} options={PRESETS} /></div>}
            {inv && <p className="small muted" style={{ margin: 0 }}>Use cases by tier: Tier 3: {inv.tiers['3'] ?? 0} · Tier 2: {inv.tiers['2'] ?? 0} · Tier 1: {inv.tiers['1'] ?? 0}. The proposed tier is calculated from the answers; Futran sets the final tier.</p>}
            {folded > 0 && <Checkbox label={`Also show inventory items already in the register (${folded})`} checked={showFolded} onChange={(e) => setShowFolded(e.target.checked)} />}
          </div>
          {d.rows.length === 0 ? (
            <EmptyState>
              Nothing here yet. {reg?.can.import_inventory ? 'Import from the inventory, ' : ''}{addItems.length ? 'use Add to add an AI system, tool or use case.' : ''}
            </EmptyState>
          ) : (
            <DataGrid label="AI systems" rows={rows} rowId={(r) => r.key} rowLabel={(r) => r.name} columns={columns} selectable={!!reg} initialFilters={initialFilters}
              rowClassName={(r) => (r.system?.stage === 'retired' ? 'dg-muted' : undefined)}
              search={{ label: 'Search', placeholder: 'Name, vendor, model or tool', text: (r) => [r.name, r.detail, r.system?.vendor?.name, r.system?.model_name, r.system?.reference, r.system?.ai_provider_label, r.use_case?.tools.join(' '), r.audit?.reference_id].filter(Boolean).join(' ') }}
              filters={filters}
              bulkActions={reg ? [
                { label: 'Edit selected', run: (rs) => setBulk({ mode: 'all', rows: regRows(rs) }), available: editable },
                { label: 'Assign an AI compliance role', run: (rs) => setBulk({ mode: 'roles', rows: regRows(rs) }), available: (rs) => onlySystems(rs) && rs.every((r) => r.system!.can_fill_roles) },
                { label: 'Change stage', run: (rs) => setBulk({ mode: 'stage', rows: regRows(rs) }), available: editable },
                { label: 'Add or remove a law', run: (rs) => setBulk({ mode: 'laws', rows: regRows(rs) }), available: (rs) => onlySystems(rs) && rs.every((r) => r.system!.can_add_law) },
                { label: 'Request bias test', run: (rs) => setBulk({ mode: 'bias', rows: regRows(rs) }), available: editable },
                { label: 'Export selected', run: (rs) => exportCsv(regRows(rs)), available: onlySystems },
              ] : undefined}
              rowActions={rowActions} />
          )}
          <p className="small muted" style={{ margin: 0 }}>
            {d.rows.length} items in all{folded > 0 && !showFolded ? `, ${folded} of them shown on their system’s row` : ''}. {reg ? 'Required roles counts only the roles the laws on each system require. ' : ''}
            {reg && !reg.can.org_wide && 'You can add, edit and bulk edit your department\'s AI systems, fill their roles from the company\'s user list and submit a system for go-live approval. Company-wide roles and tools are managed by the Chief AI Compliance Officer, who also approves go-live.'}
          </p>
        </div>
      </section>
      {bulk && reg && <BulkEdit mode={bulk.mode} rows={bulk.rows} people={reg.people} departments={reg.departments} onClose={() => setBulk(null)}
        onDone={(m) => { setBulk(null); void refresh(); setFlash({ tone: 'success', text: m }); }} />}
      {importing && <CsvImport onClose={() => setImporting(false)} onDone={(m) => { setImporting(false); void refresh(); setFlash({ tone: 'success', text: m }); }} />}
      {addingTool && me && <AddTool clientId={me.organization.id} onClose={() => setAddingTool(false)} onDone={(m) => setFlash({ tone: 'success', text: m })} />}
      {retire && <RetireDialog s={retire} onClose={() => setRetire(null)} onDone={() => { setRetire(null); void refresh(); setFlash({ tone: 'success', text: `${retire.name} was retired.` }); }} />}
    </div>
  );
}

/** The retired AI inventory (/inventory) and AI systems (/systems) addresses: the one list with a filter preset. Other
 *  parameters on the old address are kept, and the inventory's old tab parameter becomes the matching type filter. */
export function ListPreset({ preset }: { preset: Record<string, string> }) {
  const { search } = useLocation();
  const p = new URLSearchParams(search);
  const tab = p.get('tab');
  p.delete('tab');
  const out = new URLSearchParams({ ...preset, ...(tab === 'tools' ? { type: 'tool' } : tab === 'use_cases' ? { type: 'use_case' } : {}) });
  p.forEach((v, k) => { if (!out.has(k)) out.set(k, v); });
  return <Navigate to={`/register?${out.toString()}`} replace />;
}

const TOOL_STATUS: Record<string, string> = { approved: 'Approved', not_approved: 'Not approved', unreviewed: 'Unreviewed' };

/** The old AI systems page's header: the current audit, locked answers and the organisation-wide §4 questions. */
function AuditPanel({ a }: { a: NonNullable<AiList['audit']> }) {
  return (
    <section className="card" aria-label="About the current audit">
      <div className="card-body stack-sm">
        <p style={{ margin: 0 }}><strong>Current audit {a.audit_ref}.</strong> Describe each AI system in scope before fieldwork: open the system and choose Answer the audit questions (the Current audit filter lists them). The auditor checks your answers in interviews, so answer as things are today, not as planned.</p>
        <CarriedBanner engagementId={a.engagement_id} />
        {a.locked && <Alert tone="info">Your answers were locked when management representation was signed. Ask the auditor if something must change.</Alert>}
        {a.can_answer_governance_questions && <p className="small" style={{ margin: 0 }}><Link to="/systems/governance">Governance and accountability questions (§4)</Link> — answered once for the whole organization.</p>}
      </div>
    </section>
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
  const [warnings, setWarnings] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (!file) { setErr('Choose a CSV or Excel file.'); return; }
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api.upload<{ created: number; errors: { row: number; field: string; message: string }[]; warnings?: { message: string }[] }>('/register/import', fd);
      const notes = (r.warnings ?? []).map((w) => w.message);
      setWarnings(notes);
      if (r.errors.length) setErrors(r.errors); else onDone(`${r.created} AI system${r.created === 1 ? '' : 's'} imported.${notes.length ? ` ${notes.join(' ')}` : ''}`);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Import AI systems from a file" onClose={onClose} wide>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>The template has a column for each field of the Add an AI system form, in the same order; columns marked * are required. Each row is checked as the form checks it, and nothing is imported until every row is correct. Live is not accepted: import those systems as Ready for go-live and submit them.</p>
        <div className="row reg-templates">
          <a className="btn btn-sm" href="/api/v1/register/import-template.xlsx">Download the template (Excel, with instructions)</a>
          <a className="btn btn-sm" href="/api/v1/register/import-template.csv">Download the template (CSV)</a>
          <FieldHelp label="Import template">{H.importTemplate}</FieldHelp>
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="CSV or Excel file" help={H.importFile} type="file" accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setErrors([]); setWarnings([]); }} />
        {errors.length > 0 && warnings.length > 0 && <Alert tone="info">{warnings.join(' ')}</Alert>}
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
