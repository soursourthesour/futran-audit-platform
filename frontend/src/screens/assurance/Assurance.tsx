import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextField, fileUrl, fmtDate, fmtDateTime } from '@/components/ui';
import './assurance.css';

/** G-09 Agent assurance (Release 2 B9). */
type Check = { position: number; item: string | null; result: string; note: string | null; due: string | null };
type Run = {
  id: string; release_ref: string; model_ref: string | null; eval_set_version: string | null; eval_set_size: number | null; eval_set_owner: string | null;
  checks: Check[]; checks_summary: Record<string, number>; redteam: { scenario: string; outcome: string | null; severity: string | null }[]; outcome: string; outcome_label: string;
  letter: { id: string; filename: string } | null; signed_by: string | null; signed_on: string | null; recertification_due: boolean; recertification_reason: string | null;
  recorded_by: string | null; recorded_at: string;
};
type Page = {
  system: { id: string; reference: string; name: string; type: string; stage: string; autonomy: string | null; guardrail_policy_ref: string | null; model: string | null; organization_id: string };
  is_agent: boolean; status: string | null; status_label: string; runs: Run[];
  open_conditions: { item: string; position: number | null; result: string; condition: string | null; due: string | null }[];
  recertification: { due: boolean; reason: string | null; rule: string }; checklist: { position: number; text: string | null }[]; checklist_note: string;
  warden: { agent_label: string; autonomy: string | null; actions_month: number; actions_included: number | null; approvers: number; deployment: string | null; synced_at: string } | null;
  independence_note: string | null; can_record: boolean; can_sync: boolean; can_edit_checklist: boolean; client_name?: string;
};
const TONE: Record<string, 'success' | 'warn' | 'danger' | 'navy' | 'muted'> = { passed: 'success', conditional: 'warn', failed: 'danger', recertification_due: 'navy' };
const OTONE: Record<string, 'success' | 'warn' | 'danger'> = { pass: 'success', conditional: 'warn', fail: 'danger' };
const AUTONOMY: Record<string, string> = { suggest_only: 'suggests only', acts_with_approval: 'acts with approval', autonomous: 'acts on its own' };
const RESULTS = [{ value: 'not_run', label: 'Not run' }, { value: 'pass', label: 'Pass' }, { value: 'conditional', label: 'Conditional' }, { value: 'fail', label: 'Fail' }];

/** The Assurance tab on a client's register record (`/register/:systemId/assurance`), and Futran's page for it
 *  (`/clients/:clientId/register/:systemId/assurance`) where Agent Assure releases are recorded. */
export function AssurancePanel({ systemId, clientId }: { systemId: string; clientId?: string }) {
  const path = clientId ? `/clients/${clientId}/register/${systemId}/assurance` : `/register/${systemId}/assurance`;
  const q = useQuery({ queryKey: ['assurance', path], queryFn: () => api.get<Page>(path) });
  const qc = useQueryClient();
  const [recording, setRecording] = useState(false);
  const [letterFor, setLetterFor] = useState<Run | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const done = async (m: string) => { setFlash(m); setRecording(false); setLetterFor(null); setSyncing(false); await qc.invalidateQueries({ queryKey: ['assurance'] }); await qc.invalidateQueries({ queryKey: ['register'] }); };
  const latest = d.runs[0];
  if (!d.is_agent) return <EmptyState>Agent Assure records are kept for agents.</EmptyState>;
  return (
    <div className="stack aa-page">
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="aa-head">
        <span className="small">Agent{d.system.autonomy ? ` · ${AUTONOMY[d.system.autonomy] ?? d.system.autonomy}` : ''}{d.system.guardrail_policy_ref ? ` · GuardRail policy ${d.system.guardrail_policy_ref}` : ''}</span>
        <Badge tone={d.status ? TONE[d.status] : 'muted'}>{d.status_label}</Badge>
        {d.can_record && <div className="row aa-actions"><Button variant="primary" onClick={() => setRecording(true)}>Record a release</Button>{d.can_sync && <Button onClick={() => setSyncing(true)}>AgentWarden sync</Button>}</div>}
      </div>
      {d.independence_note && <Alert tone="info">{d.independence_note}</Alert>}
      {d.recertification.due && <Alert tone="warn">Re-certification due: {d.recertification.reason}. Record a new Agent Assure run for this release.</Alert>}

      <Card title="Release history">
        {d.runs.length === 0 ? <EmptyState>No Agent Assure record yet.{d.can_record ? ' Record the first release.' : ' Futran records each release of this agent here.'}</EmptyState> : (
          <div className="table-wrap"><table className="table" aria-label="Release history">
            <thead><tr><th>Release</th><th>Model</th><th>Gold eval set</th><th>15-point check</th><th>Red team</th><th>Outcome</th><th>Letter</th></tr></thead>
            <tbody>{d.runs.map((r, i) => (
              <tr key={r.id}>
                <td><strong>{r.release_ref}</strong>{i === 0 && <span className="small muted"> (current)</span>}<div className="small muted">{fmtDate(r.recorded_at)}</div></td>
                <td className="small">{r.model_ref ?? '—'}</td>
                <td className="small">{[r.eval_set_version, r.eval_set_size != null ? `${r.eval_set_size.toLocaleString()} cases` : null].filter(Boolean).join(' · ') || '—'}{r.eval_set_owner && <div className="muted">{r.eval_set_owner}</div>}</td>
                <td className="small">{summary(r)}</td>
                <td className="small">{r.redteam.length ? `${r.redteam.length} scenario${r.redteam.length === 1 ? '' : 's'}${sev(r)}` : '—'}</td>
                <td><Badge tone={OTONE[r.outcome]}>{r.outcome_label}</Badge>{r.recertification_due && <div className="small aa-warn">Re-certification due</div>}</td>
                <td className="small">{r.letter ? <><a href={fileUrl(r.letter.id)}>PDF</a><div className="muted">{r.signed_by}{r.signed_on ? `, ${fmtDate(r.signed_on)}` : ''}</div></> : d.can_record ? <Button size="sm" onClick={() => setLetterFor(r)}>Add letter</Button> : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>

      {latest && (
        <Card title={`${latest.release_ref} · open conditions`}>
          {d.open_conditions.length === 0 ? <EmptyState>No open conditions.</EmptyState> : (
            <div className="table-wrap"><table className="table" aria-label="Open conditions">
              <thead><tr><th>Item</th><th>Result</th><th>Condition</th><th>Due</th></tr></thead>
              <tbody>{d.open_conditions.map((c, i) => <tr key={i}><td>{c.item}</td><td><Badge tone={c.result === 'fail' || c.result === 'high' || c.result === 'critical' ? 'danger' : 'warn'}>{cap(c.result)}</Badge></td><td>{c.condition ?? '—'}</td><td className="small">{c.due ?? '—'}</td></tr>)}</tbody>
            </table></div>
          )}
        </Card>
      )}

      <div className="aa-grid">
        <Card title="AgentWarden licence">
          {d.warden ? (
            <dl className="details">
              <dt>Protected</dt><dd>{d.warden.autonomy ? AUTONOMY[d.warden.autonomy] ?? d.warden.autonomy : 'Yes'}</dd>
              <dt>Actions this month</dt><dd>{d.warden.actions_month.toLocaleString()}{d.warden.actions_included ? ` of ${d.warden.actions_included.toLocaleString()} included` : ''}</dd>
              <dt>Approver seats</dt><dd>{d.warden.approvers}</dd>
              <dt>Deployment</dt><dd>{d.warden.deployment === 'vpc' ? 'VPC' : d.warden.deployment === 'saas' ? 'SaaS' : '—'}</dd>
              <dt>Last sync</dt><dd>{fmtDateTime(d.warden.synced_at)} (CSV until the AgentWarden API exists)</dd>
            </dl>
          ) : <EmptyState>Not protected by AgentWarden, or no licence sync yet.</EmptyState>}
        </Card>
        <Card title="Re-certification"><p className="small" style={{ margin: 0 }}>{d.recertification.rule} It is raised through the platform's reassessment triggers.</p></Card>
      </div>

      <details className="card aa-list"><summary className="card-header"><strong>15-point pre-deploy check</strong></summary>
        <div className="card-body stack-sm"><p className="small muted" style={{ margin: 0 }}>{d.checklist_note}</p>
          <ol className="aa-points">{d.checklist.map((c) => <li key={c.position}>{c.text ?? <span className="muted">Not supplied yet</span>}</li>)}</ol>
          {d.can_edit_checklist && <p className="small" style={{ margin: 0 }}><Link to="/staff/admin/service-templates?tab=assurance">Edit the 15-point list</Link></p>}
        </div>
      </details>

      {recording && clientId && <RecordDialog clientId={clientId} systemId={systemId} d={d} onClose={() => setRecording(false)} onDone={done} />}
      {letterFor && clientId && <LetterDialog clientId={clientId} systemId={systemId} run={letterFor} onClose={() => setLetterFor(null)} onDone={done} />}
      {syncing && clientId && <WardenDialog clientId={clientId} onClose={() => setSyncing(false)} onDone={done} />}
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' ');
function summary(r: Run) {
  const s = r.checks_summary;
  const parts = [s.pass && `${s.pass} pass`, s.conditional && `${s.conditional} condition${s.conditional === 1 ? '' : 's'}`, s.fail && `${s.fail} fail`, s.not_run && `${s.not_run} not run`].filter(Boolean);
  return parts.join(' · ') || '—';
}
function sev(r: Run) {
  const n: Record<string, number> = {};
  r.redteam.forEach((x) => { if (x.severity) n[x.severity] = (n[x.severity] ?? 0) + 1; });
  const parts = ['critical', 'high', 'medium', 'low'].filter((k) => n[k]).map((k) => `${n[k]} ${k}`);
  return parts.length ? ` · ${parts.join(', ')}` : '';
}

function RecordDialog({ clientId, systemId, d, onClose, onDone }: { clientId: string; systemId: string; d: Page; onClose: () => void; onDone: (m: string) => void }) {
  const [f, setF] = useState({ release_ref: '', model_ref: d.system.model ?? '', eval_set_version: '', eval_set_size: '', eval_set_owner: '', outcome: '' });
  const [checks, setChecks] = useState<Record<number, { result: string; note: string; due: string }>>({});
  const [red, setRed] = useState<{ scenario: string; outcome: string; severity: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const save = async () => {
    setErr(null); setFe({});
    try {
      await api.post(`/clients/${clientId}/register/${systemId}/assurance/runs`, {
        ...f, eval_set_size: f.eval_set_size === '' ? null : Number(f.eval_set_size),
        checks: Object.entries(checks).map(([p, c]) => ({ position: Number(p), result: c.result, note: c.note, due: c.due })),
        redteam: red.filter((r) => r.scenario.trim()),
      });
      onDone(`Release ${f.release_ref} recorded. The register's pre-release testing now follows this record.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  };
  return (
    <Dialog title={`Record an Agent Assure release · ${d.system.name}`} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="Release *" placeholder="v1.2" value={f.release_ref} onChange={(e) => setF({ ...f, release_ref: e.target.value })} error={fe.release_ref} />
          <TextField label="Model tested" value={f.model_ref} onChange={(e) => setF({ ...f, model_ref: e.target.value })} />
          <TextField label="Gold eval set version" value={f.eval_set_version} onChange={(e) => setF({ ...f, eval_set_version: e.target.value })} />
          <TextField label="Gold eval set size (cases)" type="number" min={0} value={f.eval_set_size} onChange={(e) => setF({ ...f, eval_set_size: e.target.value })} error={fe.eval_set_size} />
          <TextField label="Gold eval set owner" value={f.eval_set_owner} onChange={(e) => setF({ ...f, eval_set_owner: e.target.value })} />
          <SelectField label="Outcome *" value={f.outcome} placeholder="Choose" options={[{ value: 'pass', label: 'Pass' }, { value: 'conditional', label: 'Conditional pass' }, { value: 'fail', label: 'Fail' }]} onChange={(e) => setF({ ...f, outcome: e.target.value })} error={fe.outcome} />
        </div>
        <fieldset className="aa-fieldset"><legend>15-point pre-deploy check</legend>
          <p className="small muted" style={{ margin: 0 }}>{d.checklist_note}</p>
          {fe.checks && <Alert tone="danger">{fe.checks}</Alert>}
          <div className="table-wrap"><table className="table" aria-label="15-point check results">
            <thead><tr><th>#</th><th>Item</th><th>Result</th><th>Condition or note</th><th>Due</th></tr></thead>
            <tbody>{d.checklist.map((c) => {
              const v = checks[c.position] ?? { result: 'not_run', note: '', due: '' };
              const set = (k: string, val: string) => setChecks({ ...checks, [c.position]: { ...v, [k]: val } });
              return (
                <tr key={c.position}><td>{c.position}</td><td className="small">{c.text ?? <span className="muted">Not supplied yet</span>}</td>
                  <td><select aria-label={`Result for point ${c.position}`} value={v.result} onChange={(e) => set('result', e.target.value)}>{RESULTS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></td>
                  <td><input aria-label={`Note for point ${c.position}`} value={v.note} onChange={(e) => set('note', e.target.value)} /></td>
                  <td><input aria-label={`Due for point ${c.position}`} value={v.due} onChange={(e) => set('due', e.target.value)} /></td></tr>
              );
            })}</tbody>
          </table></div>
        </fieldset>
        <fieldset className="aa-fieldset"><legend>Red-team scenarios</legend>
          {fe.redteam && <Alert tone="danger">{fe.redteam}</Alert>}
          {red.map((r, i) => (
            <div key={i} className="aa-red">
              <TextField label="Scenario" value={r.scenario} onChange={(e) => setRed(red.map((x, j) => (j === i ? { ...x, scenario: e.target.value } : x)))} />
              <TextField label="What happened" value={r.outcome} onChange={(e) => setRed(red.map((x, j) => (j === i ? { ...x, outcome: e.target.value } : x)))} />
              <SelectField label="Severity" value={r.severity} placeholder="None" options={['low', 'medium', 'high', 'critical'].map((s) => ({ value: s, label: cap(s) }))} onChange={(e) => setRed(red.map((x, j) => (j === i ? { ...x, severity: e.target.value } : x)))} />
            </div>
          ))}
          <div><Button size="sm" onClick={() => setRed([...red, { scenario: '', outcome: '', severity: '' }])}>Add scenario</Button></div>
        </fieldset>
        <div className="row"><Button variant="primary" onClick={save}>Save record</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function LetterDialog({ clientId, systemId, run, onClose, onDone }: { clientId: string; systemId: string; run: Run; onClose: () => void; onDone: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [by, setBy] = useState('');
  const [on, setOn] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title={`Assurance letter · ${run.release_ref}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <label className="field"><span className="label">Signed letter (PDF) *</span><input type="file" accept=".pdf,.docx" aria-label="Assurance letter" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
        <TextField label="Signed by *" value={by} onChange={(e) => setBy(e.target.value)} />
        <TextField label="Signed on *" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!file} onClick={async () => {
          const f = new FormData(); f.append('file', file as File); f.append('signed_by', by); f.append('signed_on', on);
          try { await api.upload(`/clients/${clientId}/register/${systemId}/assurance/runs/${run.id}/letter`, f); onDone(`Assurance letter added to ${run.release_ref}.`); } catch (e) { setErr(errorMessage(e)); }
        }}>Save letter</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function WardenDialog({ clientId, onClose, onDone }: { clientId: string; onClose: () => void; onDone: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title="AgentWarden licence sync" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small" style={{ margin: 0 }}>Upload the AgentWarden licence export (CSV) for this client: Agent (register reference such as AIS-001, or name), Autonomy, Actions this month, Actions included, Approver seats, Deployment (SaaS or VPC). The API replaces this when it exists.</p>
        <label className="field"><span className="label">AgentWarden CSV *</span><input type="file" accept=".csv,.xlsx" aria-label="AgentWarden CSV" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
        <div className="row"><Button variant="primary" disabled={!file} onClick={async () => {
          const f = new FormData(); f.append('file', file as File);
          try {
            const r = await api.upload<{ matched: number; unmatched: string[] }>(`/clients/${clientId}/agentwarden/sync`, f);
            onDone(`AgentWarden sync: ${r.matched} agent${r.matched === 1 ? '' : 's'} updated.${r.unmatched.length ? ` Not in the register: ${r.unmatched.join(', ')}.` : ''}`);
          } catch (e) { setErr(errorMessage(e)); }
        }}>Sync</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** Futran's page for one agent's assurance: `/clients/:clientId/register/:systemId/assurance`. */
export function FutranAssurancePage() {
  const { clientId = '', systemId = '' } = useParams();
  const q = useQuery({ queryKey: ['assurance', `/clients/${clientId}/register/${systemId}/assurance`], queryFn: () => api.get<Page>(`/clients/${clientId}/register/${systemId}/assurance`) });
  const s = q.data?.system;
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: `/clients/${clientId}`, label: q.data?.client_name ?? 'Client' }, { to: `/clients/${clientId}/agents`, label: 'Agent oversight' }, { label: s ? `${s.reference} ${s.name}` : 'Agent' }]}
        title={s ? `${s.name} · Assurance` : 'Agent assurance'} subtitle={s ? `${s.reference}${s.model ? ` · ${s.model}` : ''}` : undefined} />
      <AssurancePanel clientId={clientId} systemId={systemId} />
    </div>
  );
}
