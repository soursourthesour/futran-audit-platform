import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useLawJurisdictions } from '@/api/laws';
import { Alert, Badge, Button, ButtonLink, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { projectHelp as H } from '@/help/regupdates';
import '@/styles/monitoring.css';
import '@/styles/regupdates.css';

type Law = { regulation_id: string; name: string; matched: boolean; reason: string };
type Assess = { tier: number; tier_reason: string; depth: string; depth_sections: string[]; depth_text: string; feature_labels: string[]; laws: Law[] };
type Row = {
  id: string; reference: string; project_name: string; department_id: string | null; department_name: string | null; status: string; status_label: string; proposed_tier: number | null;
  assessment_depth: string | null; decision: string | null; decision_label: string | null; tool_or_vendor: string | null; planned_go_live: string | null; submitted_by_name: string | null;
  submitted_at: string | null; decided_at: string | null; register_system_id: string | null; opinion_opportunity_id: string | null; open_conditions: number; matched_law_count: number;
};
type Intake = { purpose?: string | null; tool_or_vendor?: string | null; system_type?: string | null; sourcing?: string | null; planned_go_live?: string | null; jurisdiction_ids?: string[];
  data_categories?: string[] | null; data_subjects?: string[] | null; decision_impact?: string | null; public_facing?: boolean | null; autonomy?: string | null; user_count?: number | null };
type Project = Row & {
  intake: Intake; jurisdictions: { id: string; name: string }[]; depth_sections: string[]; depth_text: string; matched_regulations: Law[]; tier_reason: string | null;
  decision_note: string | null; decided_by_name: string | null; register_system: { id: string; reference: string; name: string; stage: string } | null;
  reviews: { step: string; step_label: string; reviewer_name: string | null; recommendation: string; recommendation_label: string; comment: string | null; reviewed_at: string }[];
  dpo_required: boolean; reviewer_names: { department: string[]; dpo: string[]; caico: string[] };
  conditions: { id: string; text: string; owner_name: string | null; due_on: string | null; status: string; met_note: string | null; can_mark_met: boolean; can_close: boolean }[];
  can_edit: boolean; can_review_department: boolean; can_review_dpo: boolean; can_decide: boolean; can_request_opinion: boolean;
};
type ListData = { rows: Row[]; can_submit: boolean; departments: { id: string; name: string }[]; register_systems: { id: string; label: string }[]; people: { id: string; name: string }[] };

const TIERS: Record<number, string> = { 1: 'Tier 1 · Baseline', 2: 'Tier 2 · Elevated', 3: 'Tier 3 · High-risk' };
const STATUS_TONE: Record<string, 'muted' | 'warn' | 'success' | 'navy' | 'danger'> = { draft: 'muted', in_review: 'warn', decided: 'success', withdrawn: 'muted' };
const DECISION_TONE: Record<string, 'success' | 'warn' | 'danger'> = { approved: 'success', approved_with_conditions: 'warn', rejected: 'danger' };
const TYPES = [{ value: 'genai_chat_tool', label: 'Generative AI chat tool' }, { value: 'vendor_app', label: 'Vendor app with AI' }, { value: 'embedded_feature', label: 'Embedded AI feature' },
  { value: 'agent', label: 'AI agent' }, { value: 'foundation_model_api', label: 'Foundation model / API' }, { value: 'in_house_model', label: 'In-house model' }];
const SOURCING = [{ value: 'vendor', label: 'Bought from a vendor' }, { value: 'in_house', label: 'Built in-house' }, { value: 'contractor', label: 'Built by a contractor' },
  { value: 'shadow', label: 'Free or personal tool' }];
const DATA = [{ value: 'personal', label: 'Personal information' }, { value: 'health', label: 'Health information' }, { value: 'biometric', label: 'Biometric data (face, voice)' },
  { value: 'sensitive', label: 'Sensitive categories (race, sex, age)' }, { value: 'children', label: "Children's data" }, { value: 'confidential', label: 'Company confidential' }];
const SUBJECTS = [{ value: 'customers', label: 'Customers' }, { value: 'employees', label: 'Employees' }, { value: 'candidates', label: 'Job candidates' }, { value: 'public', label: 'Members of the public' }];
const DECISIONS = [{ value: 'consequential', label: 'Makes or substantially assists consequential decisions' }, { value: 'informs', label: 'Informs people; a person can always take over' },
  { value: 'none', label: 'No decisions about people' }];
const AUTONOMY = [{ value: 'suggest_only', label: 'Suggests only' }, { value: 'acts_with_approval', label: 'Acts with approval' }, { value: 'autonomous', label: 'Acts on its own' }];

function tierClass(t: number | null | undefined) { return t ? `ru-tier t${t}` : 'ru-tier'; }

export function ProjectsList() {
  const q = useQuery({ queryKey: ['projects'], queryFn: () => api.get<ListData>('/projects') });
  const nav = useNavigate();
  const d = q.data;
  const columns: GridColumn<Row>[] = [
    { key: 'name', header: 'Project', value: (r) => r.project_name, render: (r) => <span className="stack-xs"><Link to={`/projects/${r.id}`}><strong>{r.project_name}</strong></Link><span className="small muted">{r.reference} · {r.tool_or_vendor ?? '—'}</span></span> },
    { key: 'dept', header: 'Department', value: (r) => r.department_name ?? '' },
    { key: 'tier', header: 'Proposed tier', value: (r) => r.proposed_tier ?? 0, render: (r) => (r.proposed_tier ? <Badge tone={r.proposed_tier === 3 ? 'danger' : r.proposed_tier === 2 ? 'warn' : 'success'}>{TIERS[r.proposed_tier]}</Badge> : '—') },
    { key: 'laws', header: 'Laws matched', value: (r) => r.matched_law_count },
    { key: 'golive', header: 'Planned go-live', value: (r) => r.planned_go_live ?? '', render: (r) => fmtDate(r.planned_go_live) },
    { key: 'status', header: 'Status', value: (r) => r.decision_label ?? r.status_label, render: (r) => (
      <span className="stack-xs"><Badge tone={r.decision ? DECISION_TONE[r.decision] : STATUS_TONE[r.status]}>{r.decision_label ?? r.status_label}</Badge>
        {r.open_conditions > 0 && <span className="small muted">{r.open_conditions} {r.open_conditions === 1 ? 'condition' : 'conditions'} open</span>}</span>) },
  ];
  return (
    <div className="page">
      <PageHeader title="New AI projects" subtitle="Assess any AI tool before you buy or deploy it. The Department Compliance Lead and the Data Protection Officer review it; the Chief AI Compliance Officer decides."
        actions={d?.can_submit ? <ButtonLink to="/projects/new" variant="primary">New AI project</ButtonLink> : undefined} />
      {!d ? <Loading /> : (
        <Card>
          <DataGrid label="New AI projects" rows={d.rows} rowId={(r) => r.id} rowLabel={(r) => r.project_name} columns={columns}
            rowActions={(r) => [{ label: 'Open', onSelect: () => nav(`/projects/${r.id}`) }, ...(r.register_system_id ? [{ label: 'Open register system', onSelect: () => nav(`/register/${r.register_system_id}`) }] : [])]}
            filters={[{ key: 'status', label: 'Status', options: [{ value: 'draft', label: 'Draft' }, { value: 'in_review', label: 'In review' }, { value: 'decided', label: 'Decided' }], test: (r, v) => r.status === v },
              { key: 'tier', label: 'Tier', options: [1, 2, 3].map((t) => ({ value: String(t), label: TIERS[t] })), test: (r, v) => String(r.proposed_tier) === v }]}
            search={{ label: 'Search projects', text: (r) => `${r.project_name} ${r.tool_or_vendor ?? ''} ${r.department_name ?? ''}` }}
            emptyText="No AI projects yet. Submit one before buying or deploying an AI tool." />
        </Card>)}
    </div>
  );
}

type Form = { project_name: string; department_id: string; purpose: string; tool_or_vendor: string; system_type: string; sourcing: string; planned_go_live: string; jurisdiction_ids: string[];
  data_categories: string[] | null; data_subjects: string[]; decision_impact: string; public_facing: boolean | null; autonomy: string };

function toForm(p: Project | null, deptDefault: string): Form {
  const i = p?.intake ?? {};
  return { project_name: p?.project_name ?? '', department_id: p?.department_id ?? deptDefault, purpose: i.purpose ?? '', tool_or_vendor: i.tool_or_vendor ?? '', system_type: i.system_type ?? '',
    sourcing: i.sourcing ?? 'vendor', planned_go_live: i.planned_go_live ?? '', jurisdiction_ids: i.jurisdiction_ids ?? [], data_categories: i.data_categories ?? null,
    data_subjects: i.data_subjects ?? [], decision_impact: i.decision_impact ?? '', public_facing: i.public_facing ?? null, autonomy: i.autonomy ?? '' };
}

function body(f: Form) {
  return { ...f, system_type: f.system_type || null, decision_impact: f.decision_impact || null, planned_go_live: f.planned_go_live || null, autonomy: f.system_type === 'agent' ? f.autonomy || null : null };
}

export function ProjectNew() {
  const list = useQuery({ queryKey: ['projects'], queryFn: () => api.get<ListData>('/projects') });
  if (!list.data) return <div className="page"><Loading /></div>;
  return <ProjectEditor p={null} list={list.data} />;
}

export function ProjectPage() {
  const { projectId } = useParams();
  const q = useQuery({ queryKey: ['project', projectId], queryFn: () => api.get<Project>(`/projects/${projectId}`) });
  const list = useQuery({ queryKey: ['projects'], queryFn: () => api.get<ListData>('/projects') });
  if (q.isError) return <div className="page"><PageHeader title="New AI project" /><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  if (!q.data || !list.data) return <div className="page"><Loading /></div>;
  return q.data.can_edit ? <ProjectEditor p={q.data} list={list.data} /> : <ProjectView p={q.data} list={list.data} />;
}

function ProjectEditor({ p, list }: { p: Project | null; list: ListData }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [f, setF] = useState<Form>(() => toForm(p, list.departments[0]?.id ?? ''));
  const [live, setLive] = useState<Assess | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { api.post<Assess>('/projects/assess', body(f)).then(setLive).catch(() => undefined); }, 350);
    return () => window.clearTimeout(timer.current);
  }, [f]);
  async function save(submit: boolean) {
    setBusy(true); setErr(null); setErrs({});
    try {
      const saved = p ? await api.patch<Project>(`/projects/${p.id}`, body(f)) : await api.post<Project>('/projects', body(f));
      if (submit) await api.post(`/projects/${saved.id}/submit`);
      await qc.invalidateQueries({ queryKey: ['projects'] });
      await qc.invalidateQueries({ queryKey: ['project', saved.id] });
      nav(`/projects/${saved.id}`, { state: { flash: submit ? 'Submitted for review. The reviewers have been told.' : 'Draft saved.' } });
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: '/projects', label: 'New AI projects' }, { label: p ? p.reference : 'New' }]} title="New AI project: assess before go-live"
        subtitle="Submit before buying or deploying any AI tool. The tier and laws update as you answer." />
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="ru-layout">
        <section className="ru-main">
          <Card>
            <form className="stack" onSubmit={(e) => e.preventDefault()}>
              <div className="grid-2">
                <TextField label="Project name *" help={H.name} value={f.project_name} onChange={(e) => set('project_name', e.target.value)} error={errs.project_name} />
                <SelectField label="Department *" help={H.department} value={f.department_id} onChange={(e) => set('department_id', e.target.value)} options={list.departments.map((d) => ({ value: d.id, label: d.name }))} error={errs.department_id} />
                <TextField label="Tool or vendor *" help={H.tool} value={f.tool_or_vendor} onChange={(e) => set('tool_or_vendor', e.target.value)} error={errs.tool_or_vendor} />
                <TextField label="Planned go-live" type="date" help={H.goLive} value={f.planned_go_live} onChange={(e) => set('planned_go_live', e.target.value)} error={errs.planned_go_live} />
                <SelectField label="Type of AI *" help={H.type} value={f.system_type} onChange={(e) => set('system_type', e.target.value)} options={TYPES} placeholder="Choose" error={errs.system_type} />
                <SelectField label="Bought or built *" help={H.sourcing} value={f.sourcing} onChange={(e) => set('sourcing', e.target.value)} options={SOURCING} error={errs.sourcing} />
              </div>
              {f.system_type === 'agent' && <SelectField label="How much it acts on its own" help={H.autonomy} value={f.autonomy} onChange={(e) => set('autonomy', e.target.value)} options={AUTONOMY} placeholder="Choose" />}
              <TextArea label="Purpose *" help={H.purpose} rows={2} value={f.purpose} onChange={(e) => set('purpose', e.target.value)} error={errs.purpose} />
              <PlacePicker value={f.jurisdiction_ids} onChange={(v) => set('jurisdiction_ids', v)} error={errs.jurisdiction_ids} />
              <FieldGroup legend="Data it will use *" help={H.data}>
                <div className="ru-checks">
                  {DATA.map((o) => <Checkbox key={o.value} label={o.label} checked={(f.data_categories ?? []).includes(o.value)}
                    onChange={(e) => set('data_categories', e.target.checked ? [...(f.data_categories ?? []), o.value] : (f.data_categories ?? []).filter((v) => v !== o.value))} />)}
                  <Checkbox label="None of these" checked={f.data_categories !== null && f.data_categories.length === 0} onChange={(e) => set('data_categories', e.target.checked ? [] : null)} />
                </div>
                {errs.data_categories && <div className="error">{errs.data_categories}</div>}
              </FieldGroup>
              <FieldGroup legend="Whose data, or whom it affects" help={H.subjects}>
                <div className="ru-checks">{SUBJECTS.map((o) => <Checkbox key={o.value} label={o.label} checked={f.data_subjects.includes(o.value)}
                  onChange={(e) => set('data_subjects', e.target.checked ? [...f.data_subjects, o.value] : f.data_subjects.filter((v) => v !== o.value))} />)}</div>
              </FieldGroup>
              <FieldGroup legend="Decisions about people *" help={H.decisions}>
                <div className="radio-group">{DECISIONS.map((o) => <label key={o.value} className="radio-pill"><input type="radio" name="decision" checked={f.decision_impact === o.value} onChange={() => set('decision_impact', o.value)} />{o.label}</label>)}</div>
                {errs.decision_impact && <div className="error">{errs.decision_impact}</div>}
              </FieldGroup>
              <FieldGroup legend="Will it talk directly to the public?" help={H.publicFacing}>
                <div className="radio-group">
                  <label className="radio-pill"><input type="radio" name="public" checked={f.public_facing === true} onChange={() => set('public_facing', true)} />Yes, users chat with it</label>
                  <label className="radio-pill"><input type="radio" name="public" checked={f.public_facing === false} onChange={() => set('public_facing', false)} />No</label>
                </div>
              </FieldGroup>
            </form>
          </Card>
        </section>
        <aside className="ru-aside">
          <LivePanel a={live} />
          <Card title="Reviewers">
            <ol className="ru-laws">
              <li>Department Compliance Lead</li>
              <li>Data Protection Officer</li>
              <li>Chief AI Compliance Officer · decision</li>
            </ol>
            <p className="small muted">Outcome: approved, approved with conditions, or rejected. Conditions are tracked like commitments.</p>
            <div className="stack-sm">
              <Button variant="primary" block disabled={busy} onClick={() => save(true)}>Submit for review</Button>
              <Button block disabled={busy} onClick={() => save(false)}>Save draft</Button>
            </div>
          </Card>
          <TriggerNote />
        </aside>
      </div>
    </div>
  );
}

function TriggerNote() {
  return <Card><p className="small" style={{ margin: 0 }}><strong>Reassessment triggers after go-live:</strong> new version, new data type, new jurisdiction or population, vendor change, failed monitoring check, regulatory update, 12 months elapsed.</p></Card>;
}

function LivePanel({ a }: { a: Assess | null }) {
  if (!a) return <Card><Loading label="Working out the tier…" /></Card>;
  const matched = a.laws.filter((l) => l.matched);
  const near = a.laws.filter((l) => !l.matched);
  return (
    <>
      <section className={tierClass(a.tier)} aria-live="polite" aria-label="Proposed tier">
        <div className="ru-tier-label">Proposed tier</div>
        <div className="ru-tier-value">{TIERS[a.tier]}</div>
        <div className="small">{a.tier_reason[0].toUpperCase() + a.tier_reason.slice(1)}. {a.depth_text}</div>
      </section>
      <Card title="Laws matched from the law matrix">
        {a.laws.length === 0 ? <EmptyState>Say where the users are to see which laws apply.</EmptyState> : (
          <ul className="ru-laws">
            {matched.map((l) => <li key={l.regulation_id}>{l.name} <span className="small muted">· {l.reason}</span></li>)}
            {near.map((l) => <li key={l.regulation_id} className="no">{l.name}: <span>{l.reason.replace(/^Not matched: /, 'not matched, ')}</span></li>)}
          </ul>)}
      </Card>
    </>
  );
}

function PlacePicker({ value, onChange, error }: { value: string[]; onChange: (v: string[]) => void; error?: string }) {
  const jur = useLawJurisdictions();
  const [q, setQ] = useState('');
  const all = useMemo(() => jur.data ?? [], [jur.data]);
  const names = new Map(all.map((j) => [j.id, j.name]));
  const shown = all.filter((j) => !value.includes(j.id) && j.name.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 40);
  return (
    <FieldGroup legend="Users located in *" help={H.jurisdictions}>
      <div className="ru-picker" aria-label="Chosen places">
        {value.map((id) => <span key={id} className="chip">{names.get(id) ?? '…'}<button type="button" aria-label={`Remove ${names.get(id) ?? 'place'}`} onClick={() => onChange(value.filter((v) => v !== id))}>×</button></span>)}
      </div>
      <TextField label="Find a place" help={H.jurisdictions} value={q} onChange={(e) => setQ(e.target.value)} placeholder="For example New York" />
      {q.trim().length > 0 && (
        <div className="ru-places" role="group" aria-label="Matching places">{shown.length === 0 ? <span className="small muted">No match.</span> : shown.map((j) => (
          <button key={j.id} type="button" className="ru-place" aria-label={`Add ${j.name}`} onClick={() => { onChange([...value, j.id]); setQ(''); }}>{j.name}</button>))}</div>)}
      {error && <div className="error">{error}</div>}
    </FieldGroup>
  );
}

function ProjectView({ p, list }: { p: Project; list: ListData }) {
  const qc = useQueryClient();
  const flash = (useLocation().state as { flash?: string } | null)?.flash;
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(flash ? { tone: 'success', text: flash } : null);
  const [review, setReview] = useState<'department' | 'dpo' | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [metting, setMetting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['project', p.id] }); await qc.invalidateQueries({ queryKey: ['projects'] }); };
  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    try { await fn(); await refresh(); setMsg({ tone: 'success', text: done }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const i = p.intake;
  const reviewed = new Map(p.reviews.map((r) => [r.step, r]));
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: '/projects', label: 'New AI projects' }, { label: p.reference }]} title={p.project_name}
        subtitle={`${p.reference} · ${p.department_name ?? ''} · ${p.status_label}${p.submitted_by_name ? ` · submitted by ${p.submitted_by_name}` : ''}`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="ru-layout">
        <section className="ru-main">
          {p.decision && (
            <Card title="Decision">
              <div className="row"><Badge tone={DECISION_TONE[p.decision]}>{p.decision_label}</Badge><span className="small muted">{p.decided_by_name} · {fmtDate(p.decided_at)}</span></div>
              {p.decision_note && <p>{p.decision_note}</p>}
              {p.register_system && <p className="small">In the register as <Link to={`/register/${p.register_system.id}`}>{p.register_system.reference} {p.register_system.name}</Link> ({p.register_system.stage}).</p>}
            </Card>)}
          {p.conditions.length > 0 && (
            <Card title="Conditions">
              {p.conditions.map((c) => (
                <div key={c.id} className="ru-trigger">
                  <div className="row"><Badge tone={c.status === 'closed' ? 'success' : c.status === 'met' ? 'navy' : 'warn'}>{c.status === 'closed' ? 'Closed' : c.status === 'met' ? 'Met, to confirm' : 'Open'}</Badge><strong>{c.text}</strong></div>
                  <span className="small muted">{c.owner_name ?? 'No owner'}{c.due_on && ` · due ${fmtDate(c.due_on)}`}</span>
                  {c.met_note && <span className="small" style={{ whiteSpace: 'pre-line' }}>{c.met_note}</span>}
                  <div className="row wrap">
                    {c.can_mark_met && <Button size="sm" onClick={() => setMetting(c.id)}>Mark met</Button>}
                    {c.can_close && <Button size="sm" variant="primary" disabled={busy} onClick={() => run(() => api.post(`/projects/${p.id}/conditions/${c.id}/close`, {}), 'Condition closed.')}>Confirm and close</Button>}
                  </div>
                </div>))}
            </Card>)}
          <Card title="Intake">
            <dl className="kv">
              <dt>Purpose</dt><dd>{i.purpose}</dd>
              <dt>Tool or vendor</dt><dd>{i.tool_or_vendor}</dd>
              <dt>Type</dt><dd>{TYPES.find((t) => t.value === i.system_type)?.label ?? '—'} · {SOURCING.find((t) => t.value === i.sourcing)?.label ?? ''}</dd>
              <dt>Planned go-live</dt><dd>{fmtDate(i.planned_go_live)}</dd>
              <dt>Users located in</dt><dd>{p.jurisdictions.map((j) => j.name).join(', ') || '—'}</dd>
              <dt>Data</dt><dd>{(i.data_categories ?? []).map((v) => DATA.find((d) => d.value === v)?.label ?? v).join(', ') || 'None of these'}</dd>
              <dt>Whose data</dt><dd>{(i.data_subjects ?? []).map((v) => SUBJECTS.find((d) => d.value === v)?.label ?? v).join(', ') || '—'}</dd>
              <dt>Decisions about people</dt><dd>{DECISIONS.find((d) => d.value === i.decision_impact)?.label ?? '—'}</dd>
              <dt>Talks to the public</dt><dd>{i.public_facing ? 'Yes' : 'No'}</dd>
            </dl>
          </Card>
          <Card title="Reviews">
            {(['department', 'dpo'] as const).filter((s) => s === 'department' || p.dpo_required).map((step) => {
              const r = reviewed.get(step);
              const names = step === 'department' ? p.reviewer_names.department : p.reviewer_names.dpo;
              const mine = step === 'department' ? p.can_review_department : p.can_review_dpo;
              return (
                <div key={step} className="ru-trigger">
                  <div className="row"><strong>{step === 'department' ? 'Department Compliance Lead' : 'Data Protection Officer'}</strong><span className="small muted">{names.join(', ') || 'Nobody holds this role'}</span></div>
                  {r ? <span><Badge tone={r.recommendation === 'reject' ? 'danger' : r.recommendation === 'approve' ? 'success' : 'warn'}>{r.recommendation_label}</Badge> {r.reviewer_name} · {fmtDate(r.reviewed_at)}{r.comment && <span className="block small">{r.comment}</span>}</span>
                    : <span className="small muted">Waiting</span>}
                  {mine && <div><Button size="sm" onClick={() => setReview(step)}>{r ? 'Change my review' : 'Record my review'}</Button></div>}
                </div>);
            })}
            <div className="ru-trigger"><div className="row"><strong>Chief AI Compliance Officer · decision</strong><span className="small muted">{p.reviewer_names.caico.join(', ')}</span></div>
              {p.can_decide && <div><Button variant="primary" onClick={() => setDeciding(true)}>Decide</Button></div>}</div>
          </Card>
        </section>
        <aside className="ru-aside">
          <section className={tierClass(p.proposed_tier)} aria-label="Proposed tier">
            <div className="ru-tier-label">Proposed tier</div>
            <div className="ru-tier-value">{p.proposed_tier ? TIERS[p.proposed_tier] : '—'}</div>
            <div className="small">{p.tier_reason ? p.tier_reason[0].toUpperCase() + p.tier_reason.slice(1) + '. ' : ''}{p.depth_text}</div>
          </section>
          <Card title="Laws matched from the law matrix">
            <ul className="ru-laws">{p.matched_regulations.map((l) => <li key={l.regulation_id} className={l.matched ? '' : 'no'}>{l.name} <span className="small muted">· {l.reason}</span></li>)}</ul>
          </Card>
          {(p.can_request_opinion || p.opinion_opportunity_id) && (
            <Card title="Independent opinion">
              <p className="small" style={{ marginTop: 0 }}>For Tier 3 projects, Futran can give an independent opinion before go-live. This is a separate, billable engagement.</p>
              {p.opinion_opportunity_id ? <Badge tone="success">Requested; Futran will be in touch</Badge>
                : <Button disabled={busy} onClick={() => run(() => api.post(`/projects/${p.id}/opinion`), 'Futran has been asked for an independent opinion.')}>Ask Futran for an independent opinion</Button>}
            </Card>)}
          <TriggerNote />
        </aside>
      </div>
      {review && <ReviewDialog p={p} step={review} onClose={() => setReview(null)} onDone={async (t) => { setReview(null); await refresh(); setMsg({ tone: 'success', text: t }); }} />}
      {deciding && <DecideDialog p={p} list={list} onClose={() => setDeciding(false)} onDone={async (t) => { setDeciding(false); await refresh(); setMsg({ tone: 'success', text: t }); }} />}
      {metting && <MetDialog pid={p.id} cid={metting} onClose={() => setMetting(null)} onDone={async () => { setMetting(null); await refresh(); setMsg({ tone: 'success', text: 'Marked met. The Chief AI Compliance Officer confirms it.' }); }} />}
    </div>
  );
}

function ReviewDialog({ p, step, onClose, onDone }: { p: Project; step: 'department' | 'dpo'; onClose: () => void; onDone: (t: string) => void }) {
  const [rec, setRec] = useState('approve');
  const [comment, setComment] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/projects/${p.id}/reviews`, { step, recommendation: rec, comment }); onDone('Review recorded.'); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Review ${p.project_name}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <FieldGroup legend="Recommendation *" help={H.recommendation}>
          <div className="radio-group">{[['approve', 'Approve'], ['approve_with_conditions', 'Approve with conditions'], ['reject', 'Reject']].map(([v, l]) => (
            <label key={v} className="radio-pill"><input type="radio" name="rec" checked={rec === v} onChange={() => setRec(v)} />{l}</label>))}</div>
        </FieldGroup>
        <TextArea label="Comment" help={H.reviewComment} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Record review</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

type Cond = { text: string; owner_user_id: string; due_on: string };

function DecideDialog({ p, list, onClose, onDone }: { p: Project; list: ListData; onClose: () => void; onDone: (t: string) => void }) {
  const [decision, setDecision] = useState('approved');
  const [note, setNote] = useState('');
  const [link, setLink] = useState('');
  const [conds, setConds] = useState<Cond[]>([{ text: '', owner_user_id: '', due_on: '' }]);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null); setErrs({});
    try {
      await api.post(`/projects/${p.id}/decide`, { decision, note, link_register_system_id: link || null,
        conditions: decision === 'approved_with_conditions' ? conds.filter((c) => c.text.trim()).map((c) => ({ ...c, owner_user_id: c.owner_user_id || null, due_on: c.due_on || null })) : [] });
      onDone(decision === 'rejected' ? 'Project rejected. The submitter has been told.' : 'Project approved and added to the AI system register.');
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Decide: ${p.project_name}`} onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <FieldGroup legend="Decision *" help={H.decision}>
          <div className="radio-group">{[['approved', 'Approve'], ['approved_with_conditions', 'Approve with conditions'], ['rejected', 'Reject']].map(([v, l]) => (
            <label key={v} className="radio-pill"><input type="radio" name="decision" checked={decision === v} onChange={() => setDecision(v)} />{l}</label>))}</div>
        </FieldGroup>
        {decision === 'approved_with_conditions' && (
          <FieldGroup legend="Conditions *">
            {conds.map((c, n) => (
              <div key={n} className="grid-3">
                <TextField label={`Condition ${n + 1}`} help={H.conditionText} value={c.text} onChange={(e) => setConds(conds.map((x, k) => (k === n ? { ...x, text: e.target.value } : x)))} error={errs[`conditions.${n}.text`]} />
                <SelectField label="Owner" help={H.conditionOwner} value={c.owner_user_id} onChange={(e) => setConds(conds.map((x, k) => (k === n ? { ...x, owner_user_id: e.target.value } : x)))}
                  options={list.people.map((u) => ({ value: u.id, label: u.name }))} placeholder="Choose" />
                <TextField label="Due" type="date" help={H.conditionDue} value={c.due_on} onChange={(e) => setConds(conds.map((x, k) => (k === n ? { ...x, due_on: e.target.value } : x)))} />
              </div>))}
            {errs.conditions && <div className="error">{errs.conditions}</div>}
            <div><Button size="sm" onClick={() => setConds([...conds, { text: '', owner_user_id: '', due_on: '' }])}>Add a condition</Button></div>
          </FieldGroup>)}
        {decision !== 'rejected' && <SelectField label="Existing register system" help={H.linkSystem} value={link} onChange={(e) => setLink(e.target.value)} options={list.register_systems.map((s) => ({ value: s.id, label: s.label }))} placeholder="Add as a new proposed system" />}
        <TextArea label={decision === 'rejected' ? 'Reasons *' : 'Reasons'} help={H.decisionNote} rows={3} value={note} onChange={(e) => setNote(e.target.value)} error={errs.note} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Record decision</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function MetDialog({ pid, cid, onClose, onDone }: { pid: string; cid: string; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/projects/${pid}/conditions/${cid}/met`, { note }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Mark the condition met" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="How it was met *" help={H.metNote} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Mark met</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
