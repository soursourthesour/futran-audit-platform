import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, errorMessage, fieldErrors } from '@/api/client';
import type { RegSystem } from '@/api/register';
import { DECISIONS, PERIODS, SERIOUS_KINDS, SEVERITIES, useTracing, type Deadline, type Incident, type Trace, type TracingPage } from '@/api/tracing';
import { Alert, Badge, Button, Checkbox, Dialog, Loading, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { incidentHelp as IH, traceHelp as TH } from '@/help/tracing';
import { Lock } from '@/screens/register/RegisterGrid';
import { UnlockDialog } from './UnlockDialog';
import './tracing.css';

const DECISION_TONE = { allowed: 'success', blocked: 'danger', escalated: 'warn' } as const;
const SEVERITY_TONE: Record<string, 'muted' | 'warn' | 'danger'> = { low: 'muted', medium: 'warn', high: 'danger', serious: 'danger' };

// ---- time helpers: the API speaks naive UTC; inputs speak local time
const asUtc = (v: string) => new Date(v.endsWith('Z') || v.includes('+') ? v : `${v}Z`);
function toLocalInput(v: string | null | undefined): string {
  if (!v) return '';
  const d = asUtc(v);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : '');
const nowLocal = () => toLocalInput(new Date().toISOString());

function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), ms); return () => window.clearInterval(t); }, [ms]);
  return now;
}

export function timeLeft(due: string, now: number): { text: string; overdue: boolean; soon: boolean } {
  const diff = asUtc(due).getTime() - now;
  const mins = Math.floor(Math.abs(diff) / 60_000);
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  const span = d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
  return diff < 0 ? { text: `Overdue by ${span}`, overdue: true, soon: false } : { text: `${span} left`, overdue: false, soon: diff < 24 * 3600_000 };
}

function Countdown({ d, now }: { d: Deadline; now: number }) {
  if (d.status !== 'open') return <span className="small muted">{d.status_label}{d.done_at ? ` ${fmtDateTime(d.done_at)}` : ''}</span>;
  const t = timeLeft(d.due_at, now);
  return <span className={`trc-clock ${t.overdue ? (d.binding ? 'is-over' : 'is-soft') : t.soon ? 'is-soon' : ''}`}>{t.text}</span>;
}

// ---------------------------------------------------------------- the tab
export function TracingTab({ s }: { s: RegSystem }) {
  const q = useTracing(s.id);
  const [unlocking, setUnlocking] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  const forbidden = q.error instanceof ApiError && q.error.status === 403;
  if (!q.data && !forbidden) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const p = q.data;
  const state = p?.state ?? s.history?.tracing.state ?? (s.history?.tracing.locked === false ? 'active' : 'locked');
  if (p && state === 'active') return <ActiveTracing s={s} p={p} />;
  if (!p && state === 'active') return <Alert tone="info">The tracing module is active on this system. The Chief AI Compliance Officer, the department's compliance lead and the AI Incident Response Lead use it.</Alert>;
  const t = p ?? { recommended: s.history?.tracing.recommended ?? false, reasons: s.history?.tracing.reasons ?? [], subscription: null, can_request: true, kept: { incidents: 0, traces: 0 } };
  return (
    <div className="stack">
      {flash && <Alert tone="success">{flash}</Alert>}
      <section className="card reg-tracing" aria-labelledby="tracing-h">
        <div className="card-header">
          <h2 id="tracing-h">Tracing and incident module</h2>
          <span className="row" style={{ gap: 6 }}>
            {state === 'requested' ? <Badge tone="navy">Waiting for approval</Badge> : <Badge tone="muted"><Lock /> Add-on · locked</Badge>}
            {t.recommended && <Badge tone="warn">Recommended for this system</Badge>}
          </span>
        </div>
        <div className="card-body stack-sm">
          {t.recommended && <p style={{ margin: 0 }}><strong>Why:</strong> {t.reasons.join(', ')}.</p>}
          <ul className="reg-ticks">
            <li>Every action and decision traced, with who approved it</li>
            <li>Incident register with regulator deadline timers: EU AI Act Art. 73 and 26(5), CERT-In 6 hours, Colorado cure period</li>
            <li>Export of incidents and actions for regulators and Futran</li>
          </ul>
          {state === 'requested' && t.subscription && (
            <Alert tone="info">Asked by {t.subscription.requested_by} on {fmtDate(t.subscription.requested_at)}. Waiting for {t.subscription.approver ?? 'the Executive Sponsor'} to approve ({t.subscription.plan_label}{t.subscription.trial ? ', 30-day trial' : ''}).</Alert>
          )}
          {state === 'locked' && (t.can_request
            ? <div className="row"><Button variant="primary" onClick={() => setUnlocking(true)}>Unlock for this system</Button></div>
            : <p className="small" style={{ margin: 0 }}>Ask your Chief AI Compliance Officer to request the module.</p>)}
          {(t.kept.incidents > 0 || t.kept.traces > 0) && (
            <p className="small" style={{ margin: 0 }}>Kept from when the module was active: {t.kept.incidents} incident{t.kept.incidents === 1 ? '' : 's'} and {t.kept.traces} action{t.kept.traces === 1 ? '' : 's'}.{' '}
              <a href={`/api/v1/register/${s.id}/tracing/export?what=incidents`}>Export incidents</a> · <a href={`/api/v1/register/${s.id}/tracing/export?what=traces`}>Export actions</a></p>
          )}
          <p className="small muted" style={{ margin: 0 }}>Your Executive Sponsor approves the purchase. Buying it never changes audit results; auditors keep reviewing the system independently.</p>
        </div>
      </section>
      {unlocking && <UnlockDialog systemId={s.id} onClose={() => setUnlocking(false)} onSent={(m) => { setUnlocking(false); setFlash(m); void q.refetch(); }} />}
    </div>
  );
}

// ---------------------------------------------------------------- unlocked
function ActiveTracing({ s, p }: { s: RegSystem; p: TracingPage }) {
  const qc = useQueryClient();
  const now = useNow();
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger' | 'info'; text: string } | null>(null);
  const [panel, setPanel] = useState<{ inc?: Incident; traceIds?: string[]; prefill?: string } | null>(null);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['tracing', s.id] }), qc.invalidateQueries({ queryKey: ['trc-traces', s.id] }), qc.invalidateQueries({ queryKey: ['register'] }), qc.invalidateQueries({ queryKey: ['register-history', s.id] })]);
  const k = p.kpis!;
  const sub = p.subscription;
  const current = panel?.inc ? p.incidents.find((i) => i.id === panel.inc!.id) ?? panel.inc : undefined;
  return (
    <div className="stack">
      <div className="trc-head">
        <div className="reg-chips">
          <Badge tone="success">Tracing module · active</Badge>
          {sub && <span className="small">{sub.plan_label}{sub.trial_ends_on ? ` · trial until ${fmtDate(sub.trial_ends_on)}` : ''}</span>}
          {p.system.guardrail_policy_ref && <span className="small">GuardRail policy {p.system.guardrail_policy_ref}</span>}
          {p.law_families.length > 0 && <span className="small">Deadline rules: {p.law_families.map((f) => p.family_labels[f]).join(' · ')}</span>}
        </div>
        <div className="row">
          <a className="btn" href={`/api/v1/register/${s.id}/tracing/export?what=incidents`}>Export for regulator</a>
          {p.can_manage_incidents && <Button variant="primary" onClick={() => setPanel({})}>Report an incident</Button>}
        </div>
      </div>
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      {p.law_families.length === 0 && <Alert tone="info">No EU, Colorado or Indian law is in scope for this system, so no regulator deadlines are set. Add a law on the Details tab if one applies.</Alert>}
      <div className="reg-kpis" role="list" aria-label="Tracing summary">
        <Kpi n={k.actions_24h} label="Actions in last 24 hours" />
        <Kpi n={k.blocked_24h} label="Blocked by GuardRail or a control" tone={k.blocked_24h ? 'warn' : undefined} />
        <Kpi n={k.escalated_24h} label="Handed to a person" />
        <Kpi n={k.open_incidents} label={k.open_incidents === 1 ? 'Open incident' : 'Open incidents'} tone={k.open_incidents ? 'warn' : undefined} />
        <Kpi n={k.deadlines_missed} label="Reporting deadlines missed" tone={k.deadlines_missed ? 'danger' : undefined} />
      </div>
      <TraceCard s={s} p={p} onRaise={(ids, text) => setPanel({ traceIds: ids, prefill: text })} setFlash={setFlash} onChanged={refresh} />
      <div className="trc-split">
        <IncidentsCard s={s} p={p} now={now} selected={current?.id} onOpen={(inc) => setPanel({ inc })} setFlash={setFlash} onChanged={refresh} />
        {panel && <IncidentPanel key={current?.id ?? `new-${panel.traceIds?.join() ?? ''}`} s={s} p={p} inc={current} traceIds={panel.traceIds} prefill={panel.prefill} now={now}
          onClose={() => setPanel(null)} onSaved={async (inc, msg) => { await refresh(); setPanel(inc ? { inc } : null); setFlash({ tone: 'success', text: msg }); }} />}
      </div>
    </div>
  );
}

function Kpi({ n, label, tone }: { n: number; label: string; tone?: 'warn' | 'danger' }) {
  return <div className={`tile reg-kpi ${tone ? `reg-kpi-${tone}` : ''}`} role="listitem"><div className="value">{n.toLocaleString('en-US')}</div><div className="label">{label}</div></div>;
}

// ---------------------------------------------------------------- action trace
function TraceCard({ s, p, onRaise, setFlash, onChanged }: { s: RegSystem; p: TracingPage; onRaise: (ids: string[], text: string) => void; setFlash: (f: { tone: 'success' | 'danger' | 'info'; text: string } | null) => void; onChanged: () => unknown }) {
  const [decision, setDecision] = useState('');
  const [period, setPeriod] = useState('24h');
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<Trace | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const q = useQuery({ queryKey: ['trc-traces', s.id, decision, period], queryFn: () => api.get<{ rows: Trace[] }>(`/register/${s.id}/tracing/traces?period=${period}${decision ? `&decision=${decision}` : ''}`) });
  const rows = q.data?.rows ?? (period === '24h' && !decision ? p.traces : []);
  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true); setFlash(null);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api.upload<{ added: number; skipped: number }>(`/register/${s.id}/tracing/traces/import`, fd);
      await onChanged();
      setFlash({ tone: 'success', text: `${r.added} action${r.added === 1 ? '' : 's'} imported from ${file.name}${r.skipped ? `; ${r.skipped} already held were skipped` : ''}.` });
    } catch (e) {
      const errs = e instanceof ApiError ? e.errors.slice(0, 6).map((x) => `${x.field}: ${x.message}`).join(' ') : '';
      setFlash({ tone: 'danger', text: `${errorMessage(e)} ${errs}`.trim() });
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ''; }
  }
  async function sync() {
    setBusy(true); setFlash(null);
    try {
      const r = await api.post<{ added: number; skipped: number }>(`/register/${s.id}/tracing/guardrail-sync`);
      await onChanged();
      setFlash({ tone: 'success', text: `GuardRail: ${r.added} new action${r.added === 1 ? '' : 's'}${r.skipped ? `, ${r.skipped} already held` : ''}.` });
    } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  function exportRows(list: Trace[]) {
    const esc = (v: string) => { const x = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v; return /[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x; };
    const head = ['Time', 'Session', 'Action', 'Tool', 'Data touched', 'Decision', 'Policy', 'Approver or note', 'Agent'];
    const lines = [head.join(','), ...list.map((t) => [t.at, t.session_id ?? '', t.action, t.tool ?? '', t.data_touched ?? '', t.decision_label, t.policy_ref ?? '', t.approver ?? '', t.agent_identity ?? ''].map(esc).join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a'); a.href = url; a.download = `${s.reference}-actions.csv`; a.click(); URL.revokeObjectURL(url);
  }
  const raise = (list: Trace[]) => onRaise(list.map((t) => t.id), list.length === 1 ? `${list[0].action} (${list[0].decision_label.toLowerCase()}, session ${list[0].session_id ?? 'not recorded'})` : `${list.length} actions: ${list.map((t) => t.action).slice(0, 3).join('; ')}`);
  return (
    <section className="card" aria-labelledby="trc-actions-h">
      <div className="card-header trc-card-head">
        <h2 id="trc-actions-h">Action trace</h2>
        <div className="trc-filters">
          <SelectField label="Decision" help={TH.decision} value={decision} placeholder="All" onChange={(e) => setDecision(e.target.value)} options={DECISIONS} />
          <SelectField label="Period" help={TH.period} value={period} onChange={(e) => setPeriod(e.target.value)} options={PERIODS} />
        </div>
      </div>
      <div className="card-body stack">
        {p.can_record_traces && (
          <div className="trc-tools">
            <TextField ref={fileRef} label="Import actions (CSV or JSON)" help={TH.importFile} type="file" accept=".csv,.json,text/csv,application/json" disabled={busy} onChange={(e) => void upload(e.target.files?.[0])} />
            <div className="row">
              <Button onClick={() => setAdding(true)}>Add an action</Button>
              {p.system.guardrail_policy_ref && <Button disabled={busy || p.guardrail_connected === false} onClick={sync} title={p.guardrail_connected === false ? 'GuardRail is not connected for this platform' : undefined}>Sync from GuardRail</Button>}
            </div>
          </div>
        )}
        <DataGrid label="Action trace" rows={rows} rowId={(t) => t.id} rowLabel={(t) => `${t.action}, ${fmtDateTime(t.at)}`} selectable initialSort={{ key: 'at', dir: 'desc' }}
          emptyText={q.isLoading ? 'Loading…' : 'No actions in this period. Import the agent\'s logs, sync from GuardRail or add an action by hand.'}
          search={{ label: 'Search actions', text: (t) => `${t.session_id ?? ''} ${t.action} ${t.tool ?? ''} ${t.data_touched ?? ''} ${t.policy_ref ?? ''} ${t.approver ?? ''}` }}
          columns={[
            { key: 'at', header: 'Time', value: (t) => t.at, render: (t) => <span className="trc-nowrap">{fmtDateTime(t.at)}</span> },
            { key: 'session', header: 'Session', value: (t) => t.session_id ?? '' },
            { key: 'action', header: 'Action', value: (t) => t.action },
            { key: 'tool', header: 'Tool', value: (t) => t.tool ?? '', render: (t) => t.tool ? <code className="small">{t.tool}</code> : '—' },
            { key: 'data', header: 'Data touched', value: (t) => t.data_touched ?? '', render: (t) => <span className="small">{t.data_touched ?? '—'}</span> },
            { key: 'decision', header: 'Decision', value: (t) => t.decision_label, render: (t) => <Badge tone={DECISION_TONE[t.decision]}>{t.decision_label}</Badge> },
            { key: 'policy', header: 'Policy', value: (t) => t.policy_ref ?? '', render: (t) => <span className="small">{t.policy_ref ?? '—'}</span> },
            { key: 'approver', header: 'Approver or note', value: (t) => t.approver ?? '', render: (t) => <span className="small">{t.approver ?? '—'}</span> },
          ]}
          bulkActions={[...(p.can_manage_incidents ? [{ label: 'Raise an incident', run: (list: Trace[]) => raise(list) }] : []), { label: 'Export', run: (list: Trace[]) => exportRows(list) }]}
          rowActions={(t) => [
            { label: 'Open full trace', onSelect: () => setOpen(t) },
            { label: 'Raise an incident', disabled: !p.can_manage_incidents, onSelect: () => raise([t]) },
            { label: 'Export', onSelect: () => exportRows([t]) },
          ]} />
        <p className="small muted" style={{ margin: 0 }}>Each action is logged with the agent's identity and kept for the retention period set by the records retention owner. Actions are never edited or deleted.</p>
      </div>
      {adding && <AddTraceDialog s={s} onClose={() => setAdding(false)} onSaved={async () => { setAdding(false); await onChanged(); setFlash({ tone: 'success', text: 'Action added to the trace.' }); }} />}
      {open && <TraceDialog t={open} rows={rows} onClose={() => setOpen(null)} />}
    </section>
  );
}

function TraceDialog({ t, rows, onClose }: { t: Trace; rows: Trace[]; onClose: () => void }) {
  const session = t.session_id ? rows.filter((r) => r.session_id === t.session_id).sort((a, b) => a.at.localeCompare(b.at)) : [t];
  const field = (label: string, v: string | null) => <div><dt>{label}</dt><dd>{v || '—'}</dd></div>;
  return (
    <Dialog title={`Action at ${fmtDateTime(t.at)}`} onClose={onClose} wide>
      <div className="stack">
        <dl className="trc-dl">
          {field('Action', t.action)}{field('Decision', t.decision_label)}{field('Session', t.session_id)}{field('Tool', t.tool)}{field('Data touched', t.data_touched)}
          {field('Policy', t.policy_ref)}{field('Approver or note', t.approver)}{field('Agent', t.agent_identity)}{field('Source', t.source === 'guardrail' ? 'GuardRail feed' : t.source === 'manual' ? 'Added by hand' : `${t.source.toUpperCase()} import`)}{field('Event id', t.external_id)}
        </dl>
        {session.length > 1 && (
          <>
            <h3 style={{ margin: 0, fontSize: 15 }}>Session {t.session_id}: {session.length} actions</h3>
            <ol className="trc-session">{session.map((r) => <li key={r.id} className={r.id === t.id ? 'is-this' : undefined}><span className="small muted">{fmtDateTime(r.at)}</span> {r.action} <Badge tone={DECISION_TONE[r.decision]}>{r.decision_label}</Badge></li>)}</ol>
          </>
        )}
      </div>
    </Dialog>
  );
}

function AddTraceDialog({ s, onClose, onSaved }: { s: RegSystem; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ at: nowLocal(), session_id: '', action: '', tool: '', data_touched: '', decision: 'allowed', policy_ref: s.guardrail_policy_ref ?? '', approver: '', agent_identity: '' });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setErr(null); setFe({});
    try { await api.post(`/register/${s.id}/tracing/traces`, { ...f, at: fromLocalInput(f.at) }); onSaved(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title="Add an action" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="Time *" help={TH.at} type="datetime-local" value={f.at} onChange={set('at')} error={fe.at} />
          <SelectField label="Decision *" help={TH.decisionField} value={f.decision} onChange={set('decision')} options={DECISIONS} error={fe.decision} />
        </div>
        <TextField label="Action *" help={TH.action} value={f.action} onChange={set('action')} error={fe.action} />
        <div className="grid-2">
          <TextField label="Session" help={TH.session} value={f.session_id} onChange={set('session_id')} />
          <TextField label="Tool" help={TH.tool} value={f.tool} onChange={set('tool')} />
          <TextField label="Data touched" help={TH.data} value={f.data_touched} onChange={set('data_touched')} />
          <TextField label="Policy" help={TH.policy} value={f.policy_ref} onChange={set('policy_ref')} />
          <TextField label="Approver or note" help={TH.approver} value={f.approver} onChange={set('approver')} />
          <TextField label="Agent" help={TH.agent} value={f.agent_identity} onChange={set('agent_identity')} />
        </div>
        <div className="row"><Button variant="primary" onClick={save}>Add action</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- incidents
function regulatorCheck(i: Incident): string {
  const live = i.deadlines.filter((d) => d.status !== 'withdrawn');
  if (!live.length) return i.serious_kind === 'none' ? 'Not reportable' : 'No regulator rule in scope';
  return [...new Set(live.map((d) => `${d.recipient} (${d.citation.replace(/, with Art\. 26\(5\)$/, '')})`))].join(' · ');
}

function nextOpen(i: Incident): Deadline | undefined {
  return i.deadlines.filter((d) => d.status === 'open').sort((a, b) => a.due_at.localeCompare(b.due_at))[0];
}

function IncidentsCard({ s, p, now, selected, onOpen, setFlash, onChanged }: { s: RegSystem; p: TracingPage; now: number; selected?: string; onOpen: (i: Incident) => void; setFlash: (f: { tone: 'success' | 'danger'; text: string } | null) => void; onChanged: () => unknown }) {
  const [assigning, setAssigning] = useState<Incident[] | null>(null);
  const [owner, setOwner] = useState('');
  function exportRows(list: Incident[]) {
    const esc = (v: string) => { const x = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v; return /[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x; };
    const lines = [['ID', 'Found', 'What happened', 'Severity', 'Status', 'Regulator check', 'Next deadline', 'Owner'].join(','),
      ...list.map((i) => [i.code, i.found_at, i.description, i.severity_label, i.status_label, regulatorCheck(i), nextOpen(i)?.due_at ?? '', i.owner ?? ''].map(esc).join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a'); a.href = url; a.download = `${s.reference}-incidents.csv`; a.click(); URL.revokeObjectURL(url);
  }
  async function assign() {
    if (!assigning) return;
    try {
      const r = await api.post<{ updated: number }>(`/register/${s.id}/tracing/incidents/bulk`, { ids: assigning.map((i) => i.id), owner_id: owner || null });
      setAssigning(null); await onChanged(); setFlash({ tone: 'success', text: `Owner set on ${r.updated} incident${r.updated === 1 ? '' : 's'}.` });
    } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  const can = p.can_manage_incidents;
  return (
    <section className="card trc-incidents" aria-labelledby="trc-inc-h">
      <div className="card-header"><h2 id="trc-inc-h">Incidents ({p.incidents.length})</h2></div>
      <div className="card-body">
        <DataGrid label="Incidents" rows={p.incidents} rowId={(i) => i.id} rowLabel={(i) => i.code} selectable initialSort={{ key: 'opened', dir: 'desc' }}
          rowClassName={(i) => (i.id === selected ? 'is-selected' : undefined)}
          emptyText="No incidents recorded. Report one as soon as it is found: regulator clocks start then."
          columns={[
            { key: 'id', header: 'ID', value: (i) => i.code, render: (i) => <button type="button" className="linklike" onClick={() => onOpen(i)}>{i.code}</button> },
            { key: 'opened', header: 'Found', value: (i) => i.found_at, render: (i) => <span className="trc-nowrap">{fmtDate(i.found_at)}</span> },
            { key: 'what', header: 'What happened', value: (i) => i.description, render: (i) => <span className="trc-clamp">{i.description}</span> },
            { key: 'severity', header: 'Severity', value: (i) => i.severity_label, render: (i) => <Badge tone={SEVERITY_TONE[i.severity]}>{i.severity_label}</Badge> },
            { key: 'status', header: 'Status', value: (i) => i.status_label, render: (i) => <span className="small">{i.status_label}{i.closed_on ? ` ${fmtDate(i.closed_on)}` : ''}</span> },
            { key: 'check', header: 'Regulator check', value: (i) => regulatorCheck(i), render: (i) => <span className="small">{regulatorCheck(i)}</span> },
            { key: 'deadline', header: 'Deadline', value: (i) => nextOpen(i)?.due_at ?? '', render: (i) => { const d = nextOpen(i); return d ? <span className="stack-xs"><Countdown d={d} now={now} /><span className="small muted">{d.recipient}</span></span> : <span className="muted">—</span>; } },
            { key: 'owner', header: 'Owner', value: (i) => i.owner ?? '', render: (i) => i.owner ?? <span className="muted">—</span> },
          ]}
          bulkActions={[...(can ? [{ label: 'Assign owner', run: (list: Incident[]) => { setOwner(''); setAssigning(list); } }] : []), { label: 'Export', run: (list: Incident[]) => exportRows(list) }]}
          rowActions={(i) => [
            { label: can && i.status !== 'closed' ? 'Open and edit' : 'Open', onSelect: () => onOpen(i) },
            { label: 'Record a notice', disabled: !can || i.status === 'closed' || !i.deadlines.some((d) => d.status === 'open'), onSelect: () => onOpen(i) },
            { label: 'Open history entry', disabled: !i.history_entry_id, onSelect: () => { window.location.assign(`/register/${s.id}/history?entry=${i.history_entry_id}`); } },
            { label: 'Export', onSelect: () => exportRows([i]) },
          ]} />
      </div>
      {assigning && (
        <Dialog title={`Assign an owner to ${assigning.length} incident${assigning.length === 1 ? '' : 's'}`} onClose={() => setAssigning(null)}>
          <div className="stack">
            <SelectField label="Owner" help={IH.bulkOwner} value={owner} placeholder="No owner" onChange={(e) => setOwner(e.target.value)} options={p.people.map((u) => ({ value: u.id, label: u.job_title ? `${u.name} · ${u.job_title}` : u.name }))} />
            <div className="row"><Button variant="primary" onClick={assign}>Assign</Button><Button onClick={() => setAssigning(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </section>
  );
}

type IForm = { description: string; found_at: string; severity: string; serious_kind: string; risk_to_rights: boolean; cyber_incident: boolean; ag_notice_received_on: string;
  people_affected: string; cause: string; containment: string; fix: string; owner_id: string; history_entry_id: string };

function formOf(i?: Incident, prefill?: string): IForm {
  return {
    description: i?.description ?? prefill ?? '', found_at: i ? toLocalInput(i.found_at) : nowLocal(), severity: i?.severity ?? 'medium', serious_kind: i?.serious_kind ?? 'none',
    risk_to_rights: i?.risk_to_rights ?? false, cyber_incident: i?.cyber_incident ?? false, ag_notice_received_on: i?.ag_notice_received_on ?? '',
    people_affected: i?.people_affected?.toString() ?? '', cause: i?.cause ?? '', containment: i?.containment ?? '', fix: i?.fix ?? '', owner_id: i?.owner_id ?? '', history_entry_id: '',
  };
}

function IncidentPanel({ s, p, inc, traceIds, prefill, now, onClose, onSaved }: { s: RegSystem; p: TracingPage; inc?: Incident; traceIds?: string[]; prefill?: string; now: number; onClose: () => void; onSaved: (i: Incident | null, msg: string) => void }) {
  const [f, setF] = useState<IForm>(() => formOf(inc, prefill));
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState(false);
  const box = useRef<HTMLElement>(null);
  useEffect(() => { box.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); box.current?.querySelector<HTMLElement>('textarea, input')?.focus({ preventScroll: true }); }, []);
  const ro = !p.can_manage_incidents || inc?.status === 'closed';
  const fam = new Set(p.law_families);
  const set = <K extends keyof IForm>(k: K, v: IForm[K]) => setF({ ...f, [k]: v });
  const people = useMemo(() => p.people.map((u) => ({ value: u.id, label: u.job_title ? `${u.name} · ${u.job_title}` : u.name })), [p.people]);
  async function save() {
    setBusy(true); setErr(null); setFe({});
    const body: Record<string, unknown> = { ...f, found_at: fromLocalInput(f.found_at), people_affected: f.people_affected === '' ? null : f.people_affected, owner_id: f.owner_id || null,
      ag_notice_received_on: f.ag_notice_received_on || null };
    if (inc) delete body.history_entry_id; else { body.history_entry_id = f.history_entry_id || null; body.trace_ids = traceIds ?? []; }
    try {
      const out = inc ? await api.patch<Incident>(`/register/${s.id}/tracing/incidents/${inc.id}`, body) : await api.post<Incident>(`/register/${s.id}/tracing/incidents`, body);
      const n = out.deadlines.filter((d) => d.status === 'open').length;
      onSaved(out, inc ? `${out.code} saved.` : `${out.code} recorded and added to the history log.${n ? ` ${n} notice${n === 1 ? '' : 's'} to make; the Incident Response Lead has been told.` : ''}`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  return (
    <aside ref={box} className="card trc-panel" aria-labelledby="trc-panel-h">
      <div className="card-header">
        <h2 id="trc-panel-h">{inc ? `${inc.code} · ${inc.status_label}` : 'Report an incident'}</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>Close panel</Button>
      </div>
      <div className="card-body stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {traceIds && traceIds.length > 0 && !inc && <p className="small" style={{ margin: 0 }}>Raised from {traceIds.length} traced action{traceIds.length === 1 ? '' : 's'}; they are linked to the incident.</p>}
        <fieldset disabled={ro} className="reg-plain stack">
          <TextArea label="What happened *" help={IH.description} rows={3} value={f.description} onChange={(e) => set('description', e.target.value)} error={fe.description} />
          <div className="grid-2 trc-grid">
            <TextField label="Found on *" help={IH.foundAt} type="datetime-local" value={f.found_at} onChange={(e) => set('found_at', e.target.value)} error={fe.found_at} />
            <SelectField label="Severity *" help={IH.severity} value={f.severity} onChange={(e) => set('severity', e.target.value)} options={SEVERITIES} error={fe.severity} />
          </div>
          {fam.has('eu_ai_act') && <>
            <SelectField label="Serious incident under the EU AI Act?" help={IH.serious} value={f.serious_kind} onChange={(e) => set('serious_kind', e.target.value)} options={SERIOUS_KINDS} error={fe.serious_kind} />
            <Checkbox label="Using the system may present a risk to health, safety or fundamental rights (Art. 79(1))" help={IH.risk} checked={f.risk_to_rights} onChange={(e) => set('risk_to_rights', e.target.checked)} />
          </>}
          {fam.has('india') && <Checkbox label="A cyber security incident of a kind listed by CERT-In (Annexure I)" help={IH.cyber} checked={f.cyber_incident} onChange={(e) => set('cyber_incident', e.target.checked)} />}
          {fam.has('colorado') && <TextField label="Colorado AG notice of violation received on" help={IH.agNotice} type="date" value={f.ag_notice_received_on} onChange={(e) => set('ag_notice_received_on', e.target.value)} error={fe.ag_notice_received_on} />}
          <div className="grid-2 trc-grid">
            <TextField label="People affected" help={IH.people} type="number" min={0} inputMode="numeric" value={f.people_affected} onChange={(e) => set('people_affected', e.target.value)} error={fe.people_affected} />
            <SelectField label="Owner" help={IH.owner} value={f.owner_id} placeholder="No owner yet" onChange={(e) => set('owner_id', e.target.value)} options={people} error={fe.owner_id} />
          </div>
          <TextField label="Cause" help={IH.cause} value={f.cause} onChange={(e) => set('cause', e.target.value)} />
          <TextArea label="Containment" help={IH.containment} rows={2} value={f.containment} onChange={(e) => set('containment', e.target.value)} />
          <TextArea label="Fix" help={IH.fix} rows={2} value={f.fix} onChange={(e) => set('fix', e.target.value)} />
          {!inc && p.history_incidents.length > 0 && (
            <SelectField label="Already in the history log?" help={IH.history} value={f.history_entry_id} placeholder="No, add a new history entry" onChange={(e) => set('history_entry_id', e.target.value)}
              options={p.history_incidents.map((h) => ({ value: h.id, label: `${fmtDate(h.occurred_on)}: ${h.summary.slice(0, 70)}` }))} error={fe.history_entry_id} />
          )}
        </fieldset>
        {inc && <Notices s={s} inc={inc} now={now} ro={ro} onChanged={(i, m) => onSaved(i, m)} />}
        {inc?.history_entry_id && <p className="small" style={{ margin: 0 }}><Link to={`/register/${s.id}/history?entry=${inc.history_entry_id}`}>Open the history log entry</Link></p>}
        {!ro && (
          <div className="row trc-panel-actions">
            <Button variant="primary" disabled={busy} onClick={save}>{inc ? 'Save' : 'Record incident'}</Button>
            {inc && <Button onClick={() => setClosing(true)}>Close incident</Button>}
          </div>
        )}
      </div>
      {closing && inc && <CloseDialog s={s} inc={inc} fix={f.fix} onClose={() => setClosing(false)} onDone={(i) => { setClosing(false); onSaved(i, `${i.code} closed.`); }} />}
    </aside>
  );
}

function Notices({ s, inc, now, ro, onChanged }: { s: RegSystem; inc: Incident; now: number; ro: boolean; onChanged: (i: Incident, msg: string) => void }) {
  const [acting, setActing] = useState<{ d: Deadline; mode: 'done' | 'not_applicable' } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rows = inc.deadlines.filter((d) => d.status !== 'withdrawn');
  async function reopen(d: Deadline) {
    setErr(null);
    try { onChanged(await api.post<Incident>(`/register/${s.id}/tracing/deadlines/${d.id}`, { action: 'reopen' }), `Notice to ${d.recipient} reopened.`); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <section className="trc-notices" aria-labelledby={`notices-${inc.id}`}>
      <h3 id={`notices-${inc.id}`}>Who must be told</h3>
      {err && <Alert tone="danger">{err}</Alert>}
      {rows.length === 0 ? <p className="small muted" style={{ margin: 0 }}>No regulator or provider notice is needed on what is recorded. If that changes, update the incident and the deadlines appear here.</p> : (
        <ul className="trc-notice-list">
          {rows.map((d) => (
            <li key={d.id} className={`trc-notice ${d.status === 'open' && d.overdue && d.binding ? 'is-over' : ''}`}>
              <div className="trc-notice-top"><strong>{d.recipient}</strong><Countdown d={d} now={now} /></div>
              <div className="small">{d.citation} · {d.period_text} · due {fmtDateTime(d.due_at)}</div>
              {!d.statutory && <div className="small muted">The law says {d.rule_code === 'eu_art26_risk' ? '"without undue delay"' : '"immediately"'}; the date is the platform's target.</div>}
              {!d.binding && <div className="small muted">{d.binding_note}</div>}
              <details className="small"><summary>Source text</summary><blockquote className="trc-quote">“{d.quote}”</blockquote><a href={d.source_url} target="_blank" rel="noreferrer">Official source</a></details>
              {d.status === 'done' && <div className="small">Made {fmtDateTime(d.done_at)}{d.reference ? ` · ref. ${d.reference}` : ''}</div>}
              {d.status === 'not_applicable' && <div className="small">Not applicable: {d.na_reason}</div>}
              {!ro && (d.status === 'open'
                ? <div className="row"><Button size="sm" onClick={() => setActing({ d, mode: 'done' })}>Record as made</Button><Button size="sm" variant="ghost" onClick={() => setActing({ d, mode: 'not_applicable' })}>Not applicable</Button></div>
                : <div className="row"><Button size="sm" variant="ghost" onClick={() => reopen(d)}>Reopen</Button></div>)}
            </li>
          ))}
        </ul>
      )}
      {acting && <NoticeDialog s={s} d={acting.d} mode={acting.mode} onClose={() => setActing(null)} onDone={(i, m) => { setActing(null); onChanged(i, m); }} />}
    </section>
  );
}

function NoticeDialog({ s, d, mode, onClose, onDone }: { s: RegSystem; d: Deadline; mode: 'done' | 'not_applicable'; onClose: () => void; onDone: (i: Incident, msg: string) => void }) {
  const [at, setAt] = useState(nowLocal());
  const [reference, setReference] = useState('');
  const [reason, setReason] = useState('');
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null); setFe({});
    try {
      const body = mode === 'done' ? { action: 'done', done_at: fromLocalInput(at), reference } : { action: 'not_applicable', reason };
      onDone(await api.post<Incident>(`/register/${s.id}/tracing/deadlines/${d.id}`, body), mode === 'done' ? `Notice to ${d.recipient} recorded.` : `Notice to ${d.recipient} marked not applicable.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={mode === 'done' ? `Record the notice to ${d.recipient}` : `Not applicable: ${d.recipient}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {mode === 'done' ? <>
          <TextField label="Made on *" help={IH.doneAt} type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} error={fe.done_at} />
          <TextField label="Reference" help={IH.reference} value={reference} onChange={(e) => setReference(e.target.value)} />
        </> : <TextArea label="Why it does not apply *" help={IH.naReason} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} error={fe.reason} />}
        <div className="row"><Button variant="primary" onClick={save}>{mode === 'done' ? 'Record notice' : 'Mark not applicable'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function CloseDialog({ s, inc, fix, onClose, onDone }: { s: RegSystem; inc: Incident; fix: string; onClose: () => void; onDone: (i: Incident) => void }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [fx, setFx] = useState(fix);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function close() {
    setErr(null); setFe({});
    try { onDone(await api.post<Incident>(`/register/${s.id}/tracing/incidents/${inc.id}/close`, { closed_on: on, fix: fx })); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={`Close ${inc.code}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Closed on *" help={IH.closedOn} type="date" value={on} onChange={(e) => setOn(e.target.value)} error={fe.closed_on} />
        <TextArea label="Fix" help={IH.fix} rows={3} value={fx} onChange={(e) => setFx(e.target.value)} />
        <p className="small muted" style={{ margin: 0 }}>Every notice that applies must be recorded as made, or marked not applicable with a reason, before the incident can close.</p>
        <div className="row"><Button variant="primary" onClick={close}>Close incident</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

