import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import type { AgentPanel, AgentRegistration, AgentTool, TrendMonth } from '@/api/wsl';
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Loading, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { agentHelp as H } from '@/help/wsl';
import '@/styles/wsl.css';

const ACCESS = [{ value: 'read', label: 'Reads' }, { value: 'write', label: 'Writes' }, { value: 'act', label: 'Acts' }];

/** The Agent tab of a register system of type agent (spec §21 F14): what the agent may do, the override-rate trend from
 *  its decision log, tools it used that are not registered, and the auditor's completed decision reviews. */
export function AgentTab({ systemId }: { systemId: string }) {
  const key = ['agent', systemId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<AgentPanel>(`/register/${systemId}/agent`) });
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const r = d.registration;
  return (
    <div className="stack">
      {flash && <Alert tone="success">{flash}</Alert>}
      {d.unregistered_tools.length > 0 && <Alert tone="warn">The decision log shows tools that are not in the registration: {d.unregistered_tools.join(', ')}. Add them, or find out why the agent used them.</Alert>}
      {d.flags.map((f) => <Alert key={f} tone="warn">{f}</Alert>)}
      {editing && d.can_edit ? (
        <RegistrationForm systemId={systemId} initial={r} options={d.autonomy_options} onCancel={() => setEditing(false)}
          onSaved={async () => { setEditing(false); await qc.invalidateQueries({ queryKey: key }); setFlash('Registration saved. Changes to what the agent may do are sent to your Chief AI Compliance Officer and the audit team.'); }} />
      ) : (
        <Card title="Registration" actions={d.can_edit ? <Button variant={r ? 'default' : 'primary'} onClick={() => setEditing(true)}>{r ? 'Edit registration' : 'Register this agent'}</Button> : undefined}>
          {!r ? <EmptyState>Not registered yet. Record the tools the agent can call, its permissions, where a person approves, and how to stop it.</EmptyState> : <RegistrationView r={r} />}
        </Card>
      )}
      <Card title="Hand-offs to a person (override rate)">
        <p className="small muted" style={{ marginTop: 0 }}>From the agent's decision log: each month, the share of actions handed to a person. Template question 7.1.04; a rate near zero can mean the human review is a formality.</p>
        <Trend months={d.trend} />
      </Card>
      <Card title="Decision reviews by the auditor">
        {d.reviews.length === 0 ? <p className="small muted" style={{ margin: 0 }}>No completed reviews yet. Futran's auditor draws a random sample of decisions from the log and records a verdict on each.</p> : (
          <ul className="list-rows" style={{ margin: 0 }}>
            {d.reviews.map((x) => <li key={x.id}><span>{x.size} decisions reviewed{x.completed_at ? ` on ${fmtDateTime(x.completed_at)}` : ''}</span><span className="small">{x.summary.appropriate ?? 0} appropriate · {x.summary.inappropriate ?? 0} inappropriate · {x.summary.needs_follow_up ?? 0} to follow up</span></li>)}
          </ul>
        )}
      </Card>
    </div>
  );
}

export function Trend({ months }: { months: TrendMonth[] }) {
  const max = Math.max(1, ...months.map((m) => m.override_rate ?? 0));
  return (
    <div className="wsl-trend" role="list" aria-label="Override rate by month">
      {months.map((m) => (
        <div key={m.month} role="listitem" aria-label={`${m.label}: ${m.total ? `${m.override_rate}% of ${m.total} actions handed to a person` : 'no actions'}`}>
          <div className="v">{m.total ? `${m.override_rate}%` : '—'}</div>
          <div className="bar-wrap"><div className={`bar${m.total ? '' : ' empty'}`} style={{ height: `${m.total ? Math.max(3, ((m.override_rate ?? 0) / max) * 100) : 0}%` }} /></div>
          <div className="m">{m.label}</div>
          <div className="m">{m.total} actions</div>
        </div>
      ))}
    </div>
  );
}

function RegistrationView({ r }: { r: AgentRegistration }) {
  return (
    <div className="stack">
      <div className="table-wrap"><table className="wsl-tools">
        <thead><tr><th>Tool</th><th>What it does</th><th>Access</th><th>Approval</th></tr></thead>
        <tbody>{r.tools.map((t) => <tr key={t.name}><td><code>{t.name}</code></td><td>{t.description ?? '—'}</td><td>{ACCESS.find((a) => a.value === t.access)?.label}</td><td>{t.needs_approval ? <Badge tone="navy">A person approves</Badge> : <span className="muted">None</span>}</td></tr>)}</tbody>
      </table></div>
      <dl className="kv-stacked">
        <dt>Autonomy</dt><dd>{r.autonomy_label}</dd>
        <dt>Permissions</dt><dd>{r.permissions.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{r.permissions.map((p) => <li key={p}>{p}</li>)}</ul> : '—'}</dd>
        <dt>Approval points</dt><dd>{r.approval_points.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{r.approval_points.map((p) => <li key={p}>{p}</li>)}</ul> : '—'}</dd>
        <dt>Kill switch</dt><dd>{r.kill_switch ?? '—'}{r.kill_switch_tested_on && <div className="small muted">Last tested {fmtDate(r.kill_switch_tested_on)}</div>}</dd>
        <dt>Rate limits</dt><dd>{r.rate_limits ?? '—'}</dd>
        <dt>Version</dt><dd>{r.version}{r.updated_at ? ` · ${fmtDateTime(r.updated_at)}` : ''}</dd>
      </dl>
    </div>
  );
}

function RegistrationForm({ systemId, initial, options, onCancel, onSaved }: { systemId: string; initial: AgentRegistration | null; options: { value: string; label: string }[]; onCancel: () => void; onSaved: () => void }) {
  const [tools, setTools] = useState<AgentTool[]>(initial?.tools.length ? initial.tools : [{ name: '', description: '', access: 'read', needs_approval: false }]);
  const [permissions, setPermissions] = useState((initial?.permissions ?? []).join('\n'));
  const [approvals, setApprovals] = useState((initial?.approval_points ?? []).join('\n'));
  const [autonomy, setAutonomy] = useState(initial?.autonomy_level ?? '');
  const [kill, setKill] = useState(initial?.kill_switch ?? '');
  const [tested, setTested] = useState(initial?.kill_switch_tested_on ?? '');
  const [rate, setRate] = useState(initial?.rate_limits ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const lines = (v: string) => v.split('\n').map((x) => x.trim()).filter(Boolean);
  const setTool = (i: number, t: Partial<AgentTool>) => setTools(tools.map((x, j) => (j === i ? { ...x, ...t } : x)));
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    try {
      await api.put(`/register/${systemId}/agent`, { tools: tools.filter((t) => t.name.trim()), permissions: lines(permissions), approval_points: lines(approvals), autonomy_level: autonomy, kill_switch: kill, kill_switch_tested_on: tested || null, rate_limits: rate });
      onSaved();
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Card title={initial ? 'Edit registration' : 'Register this agent'}>
      <div className="stack">
        <fieldset className="stack-sm">
          <legend>Tools it can call *</legend>
          <p className="small muted" style={{ margin: 0 }}>{H.tools}</p>
          {tools.map((t, i) => (
            <div key={i} className="wsl-tool-row">
              <TextField label={`Tool ${i + 1} name`} value={t.name} onChange={(e) => setTool(i, { name: e.target.value })} placeholder="crm.create_lead" />
              <TextField label="What it does" value={t.description ?? ''} onChange={(e) => setTool(i, { description: e.target.value })} />
              <SelectField label="Access" value={t.access} options={ACCESS} onChange={(e) => setTool(i, { access: e.target.value as AgentTool['access'] })} />
              <Checkbox label="A person approves" help={H.needsApproval} checked={t.needs_approval} onChange={(e) => setTool(i, { needs_approval: e.target.checked })} />
              <Button type="button" variant="ghost" aria-label={`Remove tool ${i + 1}`} onClick={() => setTools(tools.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          {fe.tools && <span className="error">{fe.tools}</span>}
          <div><Button type="button" size="sm" onClick={() => setTools([...tools, { name: '', description: '', access: 'read', needs_approval: false }])}>Add a tool</Button></div>
        </fieldset>
        <SelectField label="Autonomy *" help={H.autonomy} value={autonomy} placeholder="Choose" options={options} onChange={(e) => setAutonomy(e.target.value)} error={fe.autonomy_level} />
        <TextArea label="Permissions" help={H.permissions} value={permissions} onChange={(e) => setPermissions(e.target.value)} error={fe.permissions} />
        <TextArea label="Approval points" help={H.approvalPoints} value={approvals} onChange={(e) => setApprovals(e.target.value)} error={fe.approval_points} />
        <TextArea label="Kill switch" help={H.killSwitch} value={kill} onChange={(e) => setKill(e.target.value)} />
        <div className="grid-2">
          <TextField label="Kill switch last tested" help={H.killTested} type="date" value={tested} onChange={(e) => setTested(e.target.value)} error={fe.kill_switch_tested_on} />
          <TextField label="Rate limits" help={H.rateLimits} value={rate} onChange={(e) => setRate(e.target.value)} maxLength={300} />
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save registration'}</Button><Button onClick={onCancel}>Cancel</Button></div>
      </div>
    </Card>
  );
}
