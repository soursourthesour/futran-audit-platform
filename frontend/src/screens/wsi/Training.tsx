import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import type { Assignment, PlayerState, TrainingOverview } from '@/api/wsi';
import { Alert, Badge, Button, ButtonLink, Checkbox, Dialog, FieldGroup, Loading, PageHeader, SelectField, TextField, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { TrainingPlayer } from './TrainingPlayer';
import { trainingHelp as H } from '@/help/wsi';
import './wsi.css';

type Row = Assignment & { name: string | null; email: string; department: string | null };
const STATUS: Record<string, { label: string; tone: 'success' | 'navy' | 'muted' }> = { completed: { label: 'Completed', tone: 'success' }, in_progress: { label: 'In progress', tone: 'navy' }, assigned: { label: 'Not started', tone: 'muted' } };

/** AI literacy training `/training` (screen 33): the AI literacy owner, CAICO and Client Admin assign Futran modules and
 *  follow completion by department against the target. */
export function Training() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['training'], queryFn: () => api.get<TrainingOverview>('/training') });
  const rows = useQuery({ queryKey: ['training-rows'], queryFn: () => api.get<{ rows: Row[] }>('/training/assignments') });
  const [assigning, setAssigning] = useState(false);
  const [target, setTarget] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['training'] }), qc.invalidateQueries({ queryKey: ['training-rows'] })]);
  async function act(fn: () => Promise<string>) {
    setBusy(true); setMsg(null);
    try { setMsg({ tone: 'success', text: await fn() }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const by = d.program.target_date ? ` by ${fmtDate(d.program.target_date)}` : '';
  return (
    <div className="page">
      <PageHeader title="AI literacy training" subtitle={`Futran modules · supports EU AI Act Art. 4 and your AI acceptable use policy · target ${d.program.target_pct}%${by}`}
        actions={d.can.manage ? <><Button onClick={() => setTarget(true)}>Set target</Button><Button variant="primary" onClick={() => setAssigning(true)}>Assign modules</Button></> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {d.is_literacy_owner && <Alert tone="info">You hold the AI literacy and training owner role, so you run this screen for your organization.</Alert>}
      <div className="wsi-cards" role="list" aria-label="Modules">
        {d.modules.map((m) => (
          <div key={m.code} className="wsi-card" role="listitem">
            <h3>{m.title}</h3>
            <span className="small muted">{m.minutes} min · {m.audience} · quiz</span>
            <span>{m.assigned ? <><strong>{m.pct}%</strong> complete <span className="small muted">({m.completed} of {m.assigned})</span></> : <span className="muted">Not assigned yet</span>}</span>
            {d.can.manage && <a className="small" href={`/api/v1/training/modules/${m.code}/scorm`}>Export SCORM</a>}
          </div>
        ))}
      </div>
      <div className="wsi-two">
        <section className="card wsi-main" aria-labelledby="tr-dept-h">
          <div className="card-header"><h2 id="tr-dept-h">Completion by department · all assigned modules</h2></div>
          <div className="card-body">
            {d.departments.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nothing assigned yet.</p> : d.departments.map((x) => (
              <div key={x.id ?? 'none'} className="wsi-dep">
                <span>{x.name}</span>
                <div className={`wsi-bar ${x.below_target ? 'below' : ''}`} role="progressbar" aria-valuenow={x.pct ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={`${x.name}: ${x.pct}% complete`}><span style={{ width: `${x.pct ?? 0}%` }} /></div>
                <span style={{ textAlign: 'right' }}>{x.pct}%</span>
              </div>
            ))}
            <p className="small muted" style={{ marginBottom: 0 }}>Target {d.program.target_pct}%; red = below target. Departments below target raise a monitoring alert.</p>
          </div>
        </section>
        <aside className="card wsi-side" aria-labelledby="tr-used-h">
          <div className="card-header"><h2 id="tr-used-h">Where completions are used</h2></div>
          <div className="card-body stack-sm">
            <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.65 }}>
              <li>Named users on Tier 3 systems: <em>training complete</em></li>
              <li>Governance: AI literacy owner role (Art. 4)</li>
              <li>Checklist 4.3: AI governance in onboarding</li>
              <li>Monitoring check: training below target</li>
            </ul>
            {d.can.manage && <div className="row">
              <Button disabled={busy} onClick={() => act(async () => { const r = await api.post<{ reminded: number }>('/training/reminders', {}); return `Reminders sent to ${r.reminded} ${r.reminded === 1 ? 'person' : 'people'}.`; })}>Send reminders</Button>
              <Button disabled={busy} onClick={() => act(async () => { const r = await api.post<{ roles_updated: number }>('/training/evidence'); return r.roles_updated ? 'Completion record saved as evidence on the AI literacy owner role.' : 'Completion record saved. Assign the AI literacy owner under Company roles to attach it there too.'; })}>Save completion record</Button>
            </div>}
            {d.program.evidence.length > 0 && <span className="small muted">{d.program.evidence.length} completion record{d.program.evidence.length === 1 ? '' : 's'} saved.</span>}
          </div>
        </aside>
      </div>
      <section className="card" aria-labelledby="tr-people-h">
        <div className="card-header"><h2 id="tr-people-h">People</h2><span className="small muted">{d.overall.completed} of {d.overall.assigned} assignments complete{d.overall.overdue ? ` · ${d.overall.overdue} overdue` : ''}</span></div>
        <div className="card-body">
          <DataGrid label="Training assignments" rows={rows.data?.rows ?? []} rowId={(r) => r.id} rowLabel={(r) => `${r.name ?? r.email}, ${r.module.title}`} initialSort={{ key: 'name', dir: 'asc' }}
            emptyText="No assignments yet." search={{ label: 'Search people', text: (r) => `${r.name ?? ''} ${r.email}` }}
            filters={[
              { key: 'module', label: 'Module', options: d.modules.map((m) => ({ value: m.code, label: m.title })), test: (r, v) => r.module.code === v },
              { key: 'status', label: 'Status', options: Object.entries(STATUS).map(([value, s]) => ({ value, label: s.label })), test: (r, v) => r.status === v },
              { key: 'dept', label: 'Department', options: d.options.departments.map((x) => ({ value: x.name, label: x.name })), test: (r, v) => r.department === v },
            ]}
            columns={[
              { key: 'name', header: 'Name', value: (r) => r.name ?? r.email },
              { key: 'dept', header: 'Department', value: (r) => r.department ?? '' },
              { key: 'module', header: 'Module', value: (r) => r.module.title },
              { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <><Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>{r.overdue && <span className="small wsi-overdue"> overdue</span>}</> },
              { key: 'score', header: 'Score', value: (r) => r.score ?? -1, render: (r) => (r.score === null ? '—' : `${r.score}%`) },
              { key: 'due', header: 'Due', value: (r) => r.due_date ?? '', render: (r) => fmtDate(r.due_date) },
            ]}
            rowActions={(r) => [
              { label: 'Download certificate', disabled: r.status !== 'completed', onSelect: () => { window.location.href = `/api/v1/training/assignments/${r.id}/certificate`; } },
              { label: 'Copy email address', onSelect: () => { void navigator.clipboard?.writeText(r.email); } },
            ]} />
        </div>
      </section>
      {assigning && <AssignDialog d={d} onClose={() => setAssigning(false)} onDone={async (n) => { setAssigning(false); setMsg({ tone: 'success', text: n ? `Assigned to ${n} ${n === 1 ? 'person' : 'people'}. Each gets a personal link by email.` : 'Everyone chosen already has these modules.' }); await refresh(); }} />}
      {target && <TargetDialog d={d} onClose={() => setTarget(false)} onDone={async () => { setTarget(false); await refresh(); }} />}
    </div>
  );
}

function AssignDialog({ d, onClose, onDone }: { d: TrainingOverview; onClose: () => void; onDone: (n: number) => void }) {
  const [codes, setCodes] = useState<string[]>([]);
  const [kind, setKind] = useState<'departments' | 'role' | 'groups'>('departments');
  const [ids, setIds] = useState<string[]>([]);
  const [role, setRole] = useState('');
  const [due, setDue] = useState('');
  const [remind, setRemind] = useState(true);
  const [preview, setPreview] = useState<{ total: number; label: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const body = () => ({ module_codes: codes, audience: kind === 'role' ? { kind, role } : { kind, ids }, due_date: due || null, reminder_days: remind ? [3, 7] : [] });
  async function go(fn: () => Promise<void>) { setBusy(true); setErr(null); setFe({}); try { await fn(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); } }
  const opts = kind === 'departments' ? d.options.departments : d.options.groups;
  return (
    <Dialog title="Assign modules" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <FieldGroup legend="Modules" help={H.modules} className="stack-sm">
          {d.modules.map((m) => <Checkbox key={m.code} label={`${m.title} (${m.minutes} min)`} checked={codes.includes(m.code)} onChange={(e) => { setCodes(e.target.checked ? [...codes, m.code] : codes.filter((c) => c !== m.code)); setPreview(null); }} />)}
          {fe.module_codes && <div className="error">{fe.module_codes}</div>}
        </FieldGroup>
        <SelectField label="Assign by" help={H.audienceKind} value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setIds([]); setPreview(null); }}
          options={[{ value: 'departments', label: 'Department' }, { value: 'role', label: 'Role' }, { value: 'groups', label: 'Email group' }]} />
        {kind === 'role' ? (
          <SelectField label="Role" help={H.role} value={role} placeholder="Choose a role" onChange={(e) => { setRole(e.target.value); setPreview(null); }} options={d.options.roles} error={fe['audience.role']} />
        ) : (
          <FieldGroup legend={kind === 'departments' ? 'Departments' : 'Groups'} help={kind === 'departments' ? H.departments : H.groups} className="stack-sm">
            {opts.map((o) => <Checkbox key={o.id} label={o.name} checked={ids.includes(o.id)} onChange={(e) => { setIds(e.target.checked ? [...ids, o.id] : ids.filter((x) => x !== o.id)); setPreview(null); }} />)}
            {fe['audience.ids'] && <div className="error">{fe['audience.ids']}</div>}
          </FieldGroup>
        )}
        <TextField label="Due date" help={H.due} type="date" value={due} onChange={(e) => setDue(e.target.value)} error={fe.due_date} />
        <Checkbox label="Remind people who have not finished after 3 and 7 days" help={H.reminders} checked={remind} onChange={(e) => setRemind(e.target.checked)} />
        {preview && <Alert tone="info">{preview.total} {preview.total === 1 ? 'person' : 'people'} in {preview.label}. People who already have a module are not assigned it twice.</Alert>}
        <div className="row">
          <Button disabled={busy || !codes.length} onClick={() => go(async () => { const r = await api.post<{ total: number; label: string }>('/training/assign/preview', body()); setPreview(r); })}>Preview</Button>
          <Button variant="primary" disabled={busy || !codes.length} onClick={() => go(async () => { const r = await api.post<{ assigned: number }>('/training/assign', body()); onDone(r.assigned); })}>{busy ? 'Assigning…' : 'Assign and email links'}</Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Dialog>
  );
}

function TargetDialog({ d, onClose, onDone }: { d: TrainingOverview; onClose: () => void; onDone: () => void }) {
  const [pct, setPct] = useState(String(d.program.target_pct));
  const [date, setDate] = useState(d.program.target_date ?? '');
  const [busy, setBusy] = useState(false);
  const [fe, setFe] = useState<Record<string, string>>({});
  return (
    <Dialog title="Completion target" onClose={onClose}>
      <div className="stack">
        <TextField label="Target completion (%)" help={H.targetPct} type="number" min={1} max={100} value={pct} onChange={(e) => setPct(e.target.value)} error={fe.target_pct} />
        <TextField label="Target date" help={H.targetDate} type="date" value={date} onChange={(e) => setDate(e.target.value)} error={fe.target_date} />
        <div className="row"><Button variant="primary" disabled={busy} onClick={async () => { setBusy(true); try { await api.put('/training/program', { target_pct: Number(pct), target_date: date || null }); onDone(); } catch (e) { setFe(fieldErrors(e)); } finally { setBusy(false); } }}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** My training `/my-training`: the signed-in person's modules. */
export function MyTraining() {
  const q = useQuery({ queryKey: ['my-training'], queryFn: () => api.get<{ assignments: Assignment[]; can_manage: boolean }>('/my-training') });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const a = q.data.assignments;
  return (
    <div className="page page-narrow">
      <PageHeader title="My training" subtitle="AI literacy modules assigned to you." actions={q.data.can_manage ? <ButtonLink to="/training">Manage training</ButtonLink> : undefined} />
      {a.length === 0 ? <p className="muted">Nothing is assigned to you.</p> : (
        <div className="wsi-cards">
          {a.map((x) => (
            <article key={x.id} className="wsi-card" aria-label={x.module.title}>
              <h3>{x.module.title}</h3>
              <span className="small muted">{x.module.minutes} min{x.due_date ? ` · due ${fmtDate(x.due_date)}` : ''}</span>
              <span><Badge tone={STATUS[x.status].tone}>{STATUS[x.status].label}</Badge>{x.score !== null && x.status === 'completed' ? ` ${x.score}%` : ''}</span>
              <Link className={`btn ${x.status === 'completed' ? '' : 'btn-primary'}`} to={`/learn/${x.id}`}>{x.status === 'completed' ? 'Review' : x.status === 'in_progress' ? 'Continue' : 'Start'}</Link>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

/** `/learn/:assignmentId`: the player for a signed-in person. */
export function Learn() {
  const { assignmentId = '' } = useParams();
  const { data: me } = useMe();
  const q = useQuery({ queryKey: ['learn', assignmentId], queryFn: () => api.get<PlayerState>(`/learn/${assignmentId}`) });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <TrainingPlayer state={q.data} base={`/learn/${assignmentId}`} organization={me?.organization.name ?? ''} />
    </div>
  );
}
