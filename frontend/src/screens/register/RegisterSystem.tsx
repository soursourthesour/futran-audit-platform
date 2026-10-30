import { useEffect, useState } from 'react';
import { Link, NavLink, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { GATE_TONE, TIER_LABEL, TIER_TONE, useRegister, useRegSystem, type Change, type EvidenceFile, type RegSystem, type Register } from '@/api/register';
import { Alert, Badge, Button, Dialog, EmptyState, Loading, PageHeader, TextArea, TextField, fmtDate, fmtDateTime, fileUrl } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { historyHelp, systemHelp as H } from '@/help/register';
import { AgentActions, Card, DataConsent, ImpactField, VendorModel, WhatItIs, emptyForm, formFrom, payload, scrollToError, type Form } from './SystemForm';
import { LawSearch } from './LawSearch';
import { RolesTab } from './RolesTab';
import { FirstEntryQuestions, HistoryTab, TracingTab } from './HistoryTab';
import { Lock } from './RegisterGrid';
import './register.css';

export type Tab = 'details' | 'roles' | 'history' | 'tracing' | 'evidence' | 'changes';

export function RegisterSystemPage({ tab }: { tab: Tab }) {
  const { systemId = '' } = useParams();
  const q = useRegSystem(systemId);
  const reg = useRegister();
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [deciding, setDeciding] = useState(false);
  useEffect(() => setFlash(null), [tab]);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const s = q.data;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['register'] }), qc.invalidateQueries({ queryKey: ['register-roles', systemId] }), qc.invalidateQueries({ queryKey: ['register-history', systemId] })]);
  const canSubmit = s.can_submit_go_live && ['in_development', 'ready_for_go_live'].includes(s.stage) && !s.go_live.requested_at;
  const awaiting = s.stage === 'ready_for_go_live' && !!s.go_live.requested_at;
  async function submit() {
    setFlash(null);
    try { await api.post(`/register/${s.id}/go-live/submit`); await refresh(); setFlash({ tone: 'success', text: 'Sent to the AI Compliance Officer for go-live approval.' }); }
    catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  const gaps = s.roles.no_such_person + s.roles.pending_committee + (s.stage !== 'proposed' ? s.roles.not_answered : 0);
  const tabs: [Tab, string, string][] = [
    ['details', 'Details', `/register/${s.id}`],
    ['roles', 'Governance roles', `/register/${s.id}/roles`],
    ['history', 'History and requirements', `/register/${s.id}/history`],
    ['tracing', 'Tracing', `/register/${s.id}/tracing`],
    ['evidence', 'Evidence', `/register/${s.id}/evidence`],
    ['changes', 'Change history', `/register/${s.id}/changes`],
  ];
  return (
    <div className="page reg-page">
      <PageHeader crumbs={[{ to: '/register', label: 'AI system register' }, { label: s.name }]}
        title={<>{s.name}{!s.can_edit && <Lock />}</>}
        subtitle={<span className="reg-chips">
          <span>{s.type_label} · {s.sourcing_label.toLowerCase()}</span>
          {(s.ai_provider_label || s.model_name) && <span>{[s.ai_provider_label, s.model_name].filter(Boolean).join(' · ')}</span>}
          {s.risk_tier && <Badge tone={TIER_TONE[s.risk_tier]}>{TIER_LABEL[s.risk_tier]}</Badge>}
          <span>Stage: {s.stage_label}{s.live_since ? ` since ${fmtDate(s.live_since)}` : ''}</span>
          <span>{s.roles.filled} of {s.roles.required} required roles filled</span>
          {s.laws.length > 0 && <span>{s.laws.map((l) => l.short_name).join(' · ')}</span>}
        </span>}
        actions={<>
          {canSubmit && <Button variant="primary" onClick={submit}>Submit for go-live approval</Button>}
          {awaiting && s.can_approve_go_live && <Button variant="primary" onClick={() => setDeciding(true)}>Review go-live</Button>}
        </>} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      {awaiting && <Alert tone="info">Submitted for go-live approval by {s.go_live.requested_by?.name ?? 'a Department Head'} on {fmtDateTime(s.go_live.requested_at)}. The AI Compliance Officer approves it.</Alert>}
      {(s.gate.state === 'blocked' || s.gate.state === 'live_finding') && tab !== 'roles' && (
        <Alert tone="danger">
          <strong>{s.gate.state === 'blocked' ? 'Go-live blocked' : 'Live with gaps: the auditor will raise a finding'}:</strong> {[...s.gate.roles, ...s.gate.requirements].join('; ')}.
        </Alert>
      )}
      {s.stage === 'retired' && <Alert tone="info">Retired. {s.retired_reason}</Alert>}
      <nav className="tabs reg-tabs" aria-label="AI system sections">
        {tabs.map(([k, label, to]) => (
          <NavLink key={k} to={to} end className={tab === k ? 'active' : ''} aria-current={tab === k ? 'page' : undefined}>
            {label}{k === 'roles' && gaps > 0 && <span className="reg-count" aria-label={`${gaps} gaps`}>{gaps}</span>}{k === 'tracing' && <Lock />}
          </NavLink>
        ))}
      </nav>
      {tab === 'details' && reg.data && <DetailsTab s={s} d={reg.data} onSaved={async (m) => { await refresh(); setFlash({ tone: 'success', text: m }); }} />}
      {tab === 'details' && !reg.data && <Loading />}
      {tab === 'roles' && <RolesTab s={s} onChanged={refresh} />}
      {tab === 'history' && <HistoryTab s={s} onChanged={refresh} />}
      {tab === 'tracing' && <TracingTab s={s} />}
      {tab === 'evidence' && <EvidenceTab s={s} />}
      {tab === 'changes' && <ChangesTab s={s} />}
      {deciding && <GoLiveDialog s={s} onClose={() => setDeciding(false)} onDone={async (m) => { setDeciding(false); await refresh(); setFlash({ tone: 'success', text: m }); }} />}
    </div>
  );
}

function GoLiveDialog({ s, onClose, onDone }: { s: RegSystem; onClose: () => void; onDone: (m: string) => void }) {
  const [comment, setComment] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function decide(approve: boolean) {
    setErr(null);
    try { await api.post(`/register/${s.id}/go-live/decide`, { approve, comment }); onDone(approve ? `${s.name} is live.` : `${s.name} was returned to ${s.go_live.requested_by?.name ?? 'the Department Head'}.`); }
    catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Go-live: ${s.name}`} onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0 }}>{s.gate.state === 'blocked' ? 'This system is blocked. Approval will be refused until the gaps are resolved.' : 'Every role needed by go-live is filled and no pre-go-live requirement is open.'}</p>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Comment" help="Required when returning it. Saved to the change history and sent to the person who submitted it." value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="row"><Button variant="primary" onClick={() => decide(true)}>Approve go-live</Button><Button onClick={() => decide(false)}>Return</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DetailsTab({ s, d, onSaved }: { s: RegSystem; d: Register; onSaved: (m: string) => void }) {
  const [f, setF] = useState<Form>(() => formFrom(s));
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(formFrom(s)), [s]);
  const ro = !s.can_edit;
  async function save() {
    setBusy(true); setErr(null); setFe({});
    try { await api.patch(`/register/${s.id}`, { ...payload(f), reason }); setReason(''); onSaved('Saved. Each change is in the change history.'); }
    catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); scrollToError(); } finally { setBusy(false); }
  }
  const props = { f, set: setF, fe, d, disabled: ro, editing: true };
  return (
    <div className="stack">
      {ro && <Alert tone="info">{s.company_wide ? 'Company-wide tool, managed by the AI Compliance Officer. You can read it but not change it.' : 'You can read this system but not change it.'}</Alert>}
      {err && <Alert tone="danger">{err}</Alert>}
      <WhatItIs {...props} n={1} />
      <VendorModel {...props} n={2} />
      {f.type === 'agent' && <AgentActions {...props} n={3} />}
      <DataConsent {...props} n={f.type === 'agent' ? 4 : 3} />
      <LawsCard s={s} n={f.type === 'agent' ? 5 : 4} f={f} set={setF} fe={fe} ro={ro} onChanged={() => onSaved('Laws updated. Required roles were recalculated.')} />
      <BiasCard s={s} n={f.type === 'agent' ? 6 : 5} f={f} set={setF} ro={ro} />
      {!ro && (
        <section className="card"><div className="card-body stack">
          <TextField label="Reason for change" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional for a single edit" />
          <div className="row"><Button variant="primary" disabled={busy} onClick={save}>Save changes</Button><Link className="btn" to={`/register/${s.id}/roles`}>Fill governance roles</Link></div>
        </div></section>
      )}
    </div>
  );
}

function LawsCard({ s, n, f, set, fe, ro, onChanged }: { s: RegSystem; n: number; f: Form; set: (f: Form) => void; fe: Record<string, string>; ro: boolean; onChanged: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [removing, setRemoving] = useState<RegSystem['laws'][number] | null>(null);
  const [reason, setReason] = useState('');
  async function add(regulation_id: string) {
    setErr(null);
    try { await api.post(`/register/${s.id}/laws`, { regulation_id }); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  async function remove() {
    if (!removing) return;
    try { await api.post(`/register/${s.id}/laws/${removing.id}/remove`, { reason }); setRemoving(null); setReason(''); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  async function decide(link: RegSystem['laws'][number], approve: boolean) {
    try { await api.post(`/register/${s.id}/laws/${link.id}/decide`, { approve }); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card n={n} title="Laws and risk">
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="stack-sm">
        <div className="field-label"><strong>Laws that apply</strong></div>
        <div className="reg-lawchips">
          {s.laws.length === 0 && <span className="muted small">None chosen yet. Required roles are worked out from the laws you choose.</span>}
          {s.laws.map((l) => (
            <span key={l.id} className={`chip ${l.status === 'removal_pending' ? 'reg-chip-pending' : ''}`}>
              {l.short_name}{l.status === 'removal_pending' && <em className="small"> · removal waiting for approval</em>}
              {!ro && l.status === 'active' && s.can_add_law && <button type="button" className="linklike reg-x" aria-label={`Remove ${l.short_name}`} onClick={() => setRemoving(l)}>×</button>}
              {l.status === 'removal_pending' && s.can_remove_law && <><button type="button" className="linklike small" onClick={() => decide(l, true)}>Approve removal</button> · <button type="button" className="linklike small" onClick={() => decide(l, false)}>Keep</button></>}
            </span>
          ))}
          {(s.suggested_laws ?? []).map((l) => (
            <span key={l.regulation_id} className="chip reg-chip-suggest" title={l.reason ?? undefined}>Suggested: {l.short_name}{s.can_add_law && !ro && <button type="button" className="linklike small" onClick={() => add(l.regulation_id)}>Add</button>}</span>
          ))}
        </div>
        <p className="small muted" style={{ margin: 0 }}>Suggested from the company's locations and the laws found in scope for it.</p>
      </div>
      {s.can_add_law && !ro && <LawSearch label="Add a law" help={H.addLaw} exclude={s.laws.map((l) => l.regulation_id)} onPick={(l) => add(l.id)} />}
      <ImpactField f={f} set={set} fe={fe} disabled={ro} />
      <p className="small" style={{ margin: 0 }}>{s.risk_tier ? <>Risk tier is calculated: <Badge tone={TIER_TONE[s.risk_tier]}>{TIER_LABEL[s.risk_tier]}</Badge> ({s.risk_tier_reason}). It updates when you save.</> : 'The risk tier is calculated when you save.'}</p>
      {removing && (
        <Dialog title={`Remove ${removing.short_name}`} onClose={() => setRemoving(null)}>
          <div className="stack">
            {!s.can_remove_law && <p style={{ margin: 0 }}>Removing a law needs the AI Compliance Officer's approval. The law stays on the system until then.</p>}
            <TextArea label="Why it no longer applies *" help={H.removeLaw} value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="row"><Button variant="danger" onClick={remove}>{s.can_remove_law ? 'Remove the law' : 'Ask to remove'}</Button><Button onClick={() => setRemoving(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </Card>
  );
}

function BiasCard({ s, n, f, set, ro }: { s: RegSystem; n: number; f: Form; set: (f: Form) => void; ro: boolean }) {
  return (
    <Card n={n} title="Bias testing" aside={s.can_record_history ? <Link className="btn btn-sm" to={`/register/${s.id}/history?add=bias_test`}>Record a bias test</Link> : undefined}>
      <div className="grid-2">
        <div className="stack-sm">
          <strong className="small">Last bias test</strong>
          <span>{s.bias.last_tested_on ? fmtDate(s.bias.last_tested_on) : 'None recorded yet'}</span>
          <span className={`small ${s.bias.overdue ? 'reg-danger' : 'muted'}`}>{s.bias.label}{s.bias.result ? ` · ${s.bias.result}` : ''}</span>
          {s.bias.null_compliance && <Badge tone="danger">Over half the records have unknown sex or race: possible null compliance</Badge>}
        </div>
        <TextField label="Next test due" help={H.biasNextDue} type="date" value={f.bias_next_due} disabled={ro} hint="Before go-live, then every 12 months" onChange={(e) => set({ ...f, bias_next_due: e.target.value })} />
      </div>
    </Card>
  );
}

// ---- new system: a step-by-step form
export function RegisterNew() {
  const reg = useRegister();
  const { data: me } = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const myDept = me?.roles.find((r) => r.role === 'dept_compliance_lead' && r.scope_id)?.scope_id ?? '';
  const [f, setF] = useState<Form>(() => emptyForm(myDept));
  const [laws, setLaws] = useState<{ id: string; name: string }[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (myDept && !f.department_id) setF((x) => ({ ...x, department_id: myDept })); }, [myDept]); // eslint-disable-line react-hooks/exhaustive-deps
  if (reg.isLoading) return <div className="page"><Loading /></div>;
  if (!reg.data) return <div className="page"><Alert tone="danger">{errorMessage(reg.error)}</Alert></div>;
  const d = reg.data;
  const agent = f.type === 'agent';
  const steps = ['What it is', 'Vendor and model', ...(agent ? ['What the agent can do'] : []), 'Data and consent', 'Laws and risk', 'History to date'];
  const name = steps[step];
  async function save(go: 'roles' | 'stay') {
    setBusy(true); setErr(null); setFe({});
    try {
      const s = await api.post<RegSystem>('/register', { ...payload(f), regulation_ids: laws.map((l) => l.id), ...(Object.keys(answers).length ? { history_answers: answers } : {}) });
      await qc.invalidateQueries({ queryKey: ['register'] });
      nav(go === 'roles' ? `/register/${s.id}/roles` : `/register/${s.id}`);
    } catch (e) {
      setErr(errorMessage(e)); const x = fieldErrors(e); setFe(x);
      if (x.name || x.type || x.sourcing || x.department_id || x.stage) setStep(0);
      scrollToError();
    } finally { setBusy(false); }
  }
  const props = { f, set: setF, fe, d };
  return (
    <div className="page reg-page page-narrow">
      <PageHeader crumbs={[{ to: '/register', label: 'AI system register' }, { label: 'Add an AI system' }]} title="Add an AI system" subtitle={`Step ${step + 1} of ${steps.length}: ${name}`} />
      <ol className="reg-steps" aria-label="Steps">
        {steps.map((t, i) => <li key={t} className={i === step ? 'current' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>{t}</li>)}
      </ol>
      {err && <Alert tone="danger">{err}</Alert>}
      {name === 'What it is' && <WhatItIs {...props} />}
      {name === 'Vendor and model' && <VendorModel {...props} />}
      {name === 'What the agent can do' && <AgentActions {...props} />}
      {name === 'Data and consent' && <DataConsent {...props} />}
      {name === 'Laws and risk' && (
        <Card title="Laws and risk">
          <div className="reg-lawchips">
            {laws.length === 0 && <span className="muted small">No law chosen yet.</span>}
            {laws.map((l) => <span key={l.id} className="chip">{l.name}<button type="button" className="linklike reg-x" aria-label={`Remove ${l.name}`} onClick={() => setLaws((x) => x.filter((y) => y.id !== l.id))}>×</button></span>)}
          </div>
          <LawSearch label="Add a law" help={H.laws} exclude={laws.map((l) => l.id)} onPick={(l) => setLaws((x) => [...x, l])} />
          <p className="small muted" style={{ margin: 0 }}>After saving, the system shows the laws found in scope for the company as suggestions.</p>
          <ImpactField f={f} set={setF} fe={fe} />
        </Card>
      )}
      {name === 'History to date' && (
        <Card title="History to date">
          <FirstEntryQuestions stage={f.stage} answers={answers} onChange={setAnswers} help={historyHelp} />
          <p className="small muted" style={{ margin: 0 }}>Each Yes is added to the history log after saving, where you record the details and evidence.</p>
        </Card>
      )}
      <div className="row reg-step-actions">
        {step > 0 && <Button onClick={() => setStep(step - 1)}>Back</Button>}
        <Button disabled={busy || !f.name.trim()} onClick={() => save('stay')}>Save draft</Button>
        {step < steps.length - 1 ? <Button variant="primary" onClick={() => setStep(step + 1)}>Next</Button> : <Button variant="primary" disabled={busy} onClick={() => save('roles')}>Save and fill governance roles</Button>}
      </div>
    </div>
  );
}

// ---- evidence and change history
function EvidenceTab({ s }: { s: RegSystem }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['register-evidence', s.id], queryFn: () => api.get<EvidenceFile[]>(`/register/${s.id}/evidence`) });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append('file', file);
    try { await api.upload(`/register/${s.id}/evidence`, fd); await qc.invalidateQueries({ queryKey: ['register-evidence', s.id] }); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const can = s.can_edit || s.can_record_history || s.can_fill_roles;
  return (
    <section className="card"><div className="card-header"><h2>Evidence</h2></div><div className="card-body stack">
      <p className="small muted" style={{ margin: 0 }}>Contracts, data processing agreements, model cards, consent records, appointment letters and test reports for this system. Auditors see these when they review it.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      {can && <TextField label="Upload a file" help="PDF, Word, Excel, CSV, images or ZIP, up to the size limit." type="file" disabled={busy} onChange={(e) => void upload(e.target.files?.[0])} />}
      {q.isLoading ? <Loading /> : !q.data?.length ? <EmptyState>No files yet.</EmptyState> : (
        <ul className="list-rows">{q.data.map((f) => <li key={f.id} className="reg-file"><a href={fileUrl(f.id)}>{f.filename}</a><span className="small muted">{fmtDateTime(f.uploaded_at)}{f.uploaded_by ? ` · ${f.uploaded_by}` : ''}</span></li>)}</ul>
      )}
    </div></section>
  );
}

function ChangesTab({ s }: { s: RegSystem }) {
  const q = useQuery({ queryKey: ['register-changes', s.id], queryFn: () => api.get<Change[]>(`/register/${s.id}/changes`) });
  if (q.isLoading) return <Loading />;
  return (
    <section className="card"><div className="card-header"><h2>Change history</h2></div><div className="card-body">
      <DataGrid label="Changes" rows={q.data ?? []} rowId={(c) => c.id} initialSort={{ key: 'at', dir: 'desc' }} emptyText="No changes yet."
        search={{ label: 'Search changes', text: (c) => `${c.field_label} ${c.old_value ?? ''} ${c.new_value ?? ''} ${c.reason ?? ''} ${c.user}` }}
        columns={[
          { key: 'at', header: 'When', value: (c) => c.at, render: (c) => fmtDateTime(c.at) },
          { key: 'field', header: 'What', value: (c) => c.field_label },
          { key: 'old', header: 'Was', value: (c) => c.old_value ?? '', render: (c) => <span className="small">{c.old_value ?? '—'}</span> },
          { key: 'new', header: 'Now', value: (c) => c.new_value ?? '', render: (c) => <span className="small">{c.new_value ?? '—'}</span> },
          { key: 'reason', header: 'Reason', value: (c) => c.reason ?? '', render: (c) => <span className="small">{c.reason ?? '—'}{c.batch_id && <Badge tone="muted">bulk edit</Badge>}</span> },
          { key: 'user', header: 'By', value: (c) => c.user },
        ]} />
    </div></section>
  );
}

export { GATE_TONE };
