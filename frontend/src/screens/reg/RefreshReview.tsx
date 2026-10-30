import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { useLawJurisdictions } from '@/api/laws';
import { fmtValue, type ChangeItem, type Queue, type Run, type RunSettings } from '@/api/monitoring';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, WithHelp, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { refreshHelp as H } from '@/help/monitoring';
import { RegTabs } from '@/screens/futran/reg/LawLibrary';
import '@/styles/monitoring.css';

type Msg = { tone: 'success' | 'danger' | 'warn'; text: string } | null;
const CONF_TONE = { high: 'success', medium: 'navy', low: 'warn' } as const;
const STATUS_LABEL: Record<string, string> = { pending: 'Waiting', held: 'Held until adopted', legal_review: 'With legal review', approved: 'Approved', edited_approved: 'Edited and approved', rejected: 'Rejected' };
const STATUS_TONE: Record<string, 'warn' | 'navy' | 'muted' | 'success' | 'danger'> = { pending: 'warn', held: 'muted', legal_review: 'navy', approved: 'success', edited_approved: 'success', rejected: 'muted' };

export function conf(c: ChangeItem) {
  if (c.confidence === 'low') return <Badge tone="warn">Low: needs second review</Badge>;
  return <Badge tone={CONF_TONE[c.confidence]}>{c.confidence === 'high' ? 'High' : 'Medium'}</Badge>;
}

export function RefreshReview() {
  const { data: me } = useMe();
  const [params, setParams] = useSearchParams();
  const kind = params.get('kind') === 'litigation' ? 'litigation' : 'law';
  const [openId, setOpenId] = useState<string | null>(params.get('change'));
  const [msg, setMsg] = useState<Msg>(null);
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ['refresh-runs', kind], queryFn: () => api.get<Run[]>(`/admin/laws/refresh?kind=${kind}`), refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running' || r.status === 'queued') ? 4000 : false) });
  const running = !!runs.data?.some((r) => r.status === 'running' || r.status === 'queued');
  const queue = useQuery({ queryKey: ['reg-changes', kind], queryFn: () => api.get<Queue>(`/reg/changes?kind=${kind}`), refetchInterval: running ? 4000 : false });
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => { if (wasRunning && !running) qc.invalidateQueries({ queryKey: ['reg-changes'] }); setWasRunning(running); }, [running]); // eslint-disable-line react-hooks/exhaustive-deps
  const isChief = hasRole(me ?? undefined, 'chief_auditor');
  const isSecond = hasRole(me ?? undefined, 'qa_reviewer', 'legal_reviewer');
  const canRun = kind === 'law' ? hasRole(me ?? undefined, 'chief_auditor', 'admin') : hasRole(me ?? undefined, 'chief_auditor');
  useEffect(() => setOpenId(params.get('change')), [params]);
  const refresh = () => qc.invalidateQueries({ queryKey: ['reg-changes'] });

  async function bulk(rows: ChangeItem[], action: string) {
    const out = await api.post<{ results: { id: string; ok: boolean; error?: string }[] }>('/reg/changes/bulk', { ids: rows.map((r) => r.id), action });
    const bad = out.results.filter((r) => !r.ok);
    await refresh();
    if (bad.length) throw new Error(`${out.results.length - bad.length} done. ${bad.length} not done: ${bad[0].error}`);
    setMsg({ tone: 'success', text: `${out.results.length} ${out.results.length === 1 ? 'change' : 'changes'} updated.` });
  }

  const columns: GridColumn<ChangeItem>[] = [
    { key: 'type', header: 'Change', value: (c) => c.change_label, render: (c) => <Badge tone={c.change_type === 'new_law' || c.change_type === 'new_case' ? 'navy' : 'default'}>{c.change_label}</Badge> },
    { key: 'law', header: kind === 'law' ? 'Geography and law' : 'Case', value: (c) => `${c.jurisdiction ?? ''} ${c.subject}`,
      render: (c) => <button type="button" className="linklike left" onClick={() => setParams({ ...(kind === 'litigation' ? { kind } : {}), change: c.id })}><strong>{c.subject}</strong><span className="small muted block">{c.jurisdiction}</span></button> },
    { key: 'what', header: 'What changed', value: (c) => c.summary, render: (c) => <span className="clamp-3">{c.summary}</span> },
    { key: 'source', header: 'Source', value: (c) => c.source_host ?? '', render: (c) => <span>{c.source_host ?? '—'}{c.off_allowlist && <span className="block"><Badge tone="warn">Not on the allowlist</Badge></span>}</span> },
    { key: 'conf', header: 'Confidence', value: (c) => c.confidence, render: conf },
    { key: 'impact', header: 'Impact', value: (c) => c.impact.clients, render: (c) => <span className="nowrap">{c.impact.clients} {c.impact.clients === 1 ? 'client' : 'clients'} · {c.impact.systems} {c.impact.systems === 1 ? 'system' : 'systems'}</span> },
    { key: 'status', header: 'Decision', value: (c) => c.status, render: (c) => (
      <span className="stack-xs">
        <Badge tone={STATUS_TONE[c.status] ?? 'muted'}>{STATUS_LABEL[c.status] ?? c.status}</Badge>
        {c.needs_second_review && c.status !== 'approved' && <span className="small muted">{c.second_review.outcome === 'concur' ? `Second review: ${c.second_review.by} concurs` : c.second_review.outcome === 'object' ? `Second review: ${c.second_review.by} objects` : 'Second review needed'}</span>}
      </span>) },
  ];
  const rowActions = (c: ChangeItem): GridRowAction[] => [
    { label: 'Review', onSelect: () => setParams({ ...(kind === 'litigation' ? { kind } : {}), change: c.id }) },
    ...(c.source_url ? [{ label: 'Open source', onSelect: () => window.open(c.source_url!, '_blank', 'noopener') }] : []),
    ...(isChief ? [
      { label: 'Hold until adopted', onSelect: () => bulk([c], 'hold').catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
      { label: 'Send to legal review', onSelect: () => bulk([c], 'legal_review').catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
      { label: 'Reject', danger: true, onSelect: () => bulk([c], 'reject').catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
    ] : []),
  ];
  const items = queue.data?.items ?? [];
  const open = items.find((c) => c.id === openId) ?? null;

  return (
    <div className="page">
      <PageHeader title={kind === 'law' ? 'Refresh laws and review changes' : 'Refresh cases and review updates'}
        subtitle="Claude only proposes. Nothing changes in the law library, the litigation tracker, client letters or AI system roles until the Chief Auditor approves it." />
      <RegTabs pending={kind === 'law' ? queue.data?.counts.open : undefined} />
      <div className="pills" role="tablist" aria-label="What to review" style={{ margin: '12px 0' }}>
        <button type="button" role="tab" className="pill" aria-selected={kind === 'law'} onClick={() => setParams({})}>Laws</button>
        <button type="button" role="tab" className="pill" aria-selected={kind === 'litigation'} onClick={() => setParams({ kind: 'litigation' })}>Litigation</button>
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <Card title={`Changes waiting for review (${queue.data?.counts.open ?? 0})`}>
            {queue.isLoading ? <Loading /> : (
              <DataGrid label="Changes waiting for review" rows={items} rowId={(c) => c.id} rowLabel={(c) => `${c.change_label}: ${c.subject}`} columns={columns}
                selectable={isChief}
                bulkActions={isChief ? [
                  { label: 'Approve selected', run: (rows) => bulk(rows, 'approve') },
                  { label: 'Hold', run: (rows) => bulk(rows, 'hold') },
                  { label: 'Send to legal review', run: (rows) => bulk(rows, 'legal_review') },
                  { label: 'Reject', danger: true, confirm: (rows) => `Reject ${rows.length === 1 ? 'this change' : `${rows.length} changes`}? Rejected changes are not proposed again.`, run: (rows) => bulk(rows, 'reject') },
                ] : []}
                rowActions={rowActions}
                filters={[
                  { key: 'type', label: 'Change type', options: queue.data?.change_types ?? [], test: (c, v) => c.change_type === v },
                  { key: 'conf', label: 'Confidence', options: [{ value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }], test: (c, v) => c.confidence === v },
                  { key: 'status', label: 'Decision', options: [{ value: 'pending', label: 'Waiting' }, { value: 'held', label: 'Held' }, { value: 'legal_review', label: 'With legal review' }], test: (c, v) => c.status === v },
                ]}
                search={{ label: 'Search changes', text: (c) => `${c.subject} ${c.summary} ${c.jurisdiction ?? ''}` }}
                emptyText="Nothing is waiting for review." />
            )}
          </Card>
          {open && <ChangeDetail id={open.id} isChief={isChief} isSecond={isSecond} reviewers={queue.data?.reviewers ?? []} onDone={(t) => { setMsg(t); refresh(); }} onClose={() => setParams(kind === 'litigation' ? { kind } : {})} />}
        </div>
        <div className="side stack">
          {canRun && <RunCard kind={kind} lawId={params.get('law')} onStarted={(t) => { setMsg(t); refresh(); window.setTimeout(() => { refresh(); qc.invalidateQueries({ queryKey: ['refresh-runs'] }); }, 1500); }} />}
          <RunsCard kind={kind} />
        </div>
      </div>
    </div>
  );
}

function ChangeDetail({ id, isChief, isSecond, reviewers, onDone, onClose }: { id: string; isChief: boolean; isSecond: boolean; reviewers: { id: string; name: string }[]; onDone: (m: Msg) => void; onClose: () => void }) {
  const q = useQuery({ queryKey: ['reg-change', id], queryFn: () => api.get<ChangeItem>(`/reg/changes/${id}`) });
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const [notify, setNotify] = useState(true);
  const [letters, setLetters] = useState(true);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [assignee, setAssignee] = useState('');
  useEffect(() => { if (q.data) { setNotify(q.data.notify_clients); setLetters(q.data.update_letters); setValue(typeof q.data.new_value === 'string' ? q.data.new_value : JSON.stringify(q.data.new_value, null, 1)); } }, [q.data]);
  if (q.isLoading || !q.data) return <Loading />;
  const c = q.data;
  const open = ['pending', 'held', 'legal_review'].includes(c.status);
  async function act(action: string, body: Record<string, unknown> = {}) {
    setErr(null);
    try {
      await api.post(`/reg/changes/${c.id}/decide`, { action, note: note || null, notify_clients: notify, update_letters: letters, ...body });
      await qc.invalidateQueries({ queryKey: ['reg-change', id] });
      setEditing(false);
      onDone({ tone: 'success', text: action === 'approve' || action === 'edit_approve' ? `Approved: ${c.summary}` : `Saved: ${STATUS_LABEL[{ hold: 'held', reject: 'rejected', legal_review: 'legal_review' }[action] ?? ''] ?? action}.` });
    } catch (e) { setErr(errorMessage(e)); }
  }
  async function second(outcome: 'concur' | 'object') {
    setErr(null);
    try {
      await api.post(`/reg/changes/${c.id}/second-review`, { outcome, note: reviewNote });
      await qc.invalidateQueries({ queryKey: ['reg-change', id] });
      onDone({ tone: 'success', text: outcome === 'concur' ? 'Your second review is recorded. The Chief Auditor can now approve.' : 'Your objection is recorded.' });
    } catch (e) { setErr(errorMessage(e)); }
  }
  async function assign() {
    setErr(null);
    try { await api.post(`/reg/changes/${c.id}/assign`, { user_id: assignee }); onDone({ tone: 'success', text: 'Reviewer asked.' }); } catch (e) { setErr(errorMessage(e)); }
  }
  function parsed(): unknown {
    const t = value.trim();
    if (t.startsWith('{') || t.startsWith('[')) { try { return JSON.parse(t); } catch { return t; } }
    return t;
  }
  return (
    <Card title={<h2>{c.change_label} · {c.subject}</h2>} actions={<Button size="sm" variant="ghost" onClick={onClose}>Close</Button>}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>{c.jurisdiction} · field <code>{c.field_path}</code> · proposed {fmtDateTime(c.created_at)}{c.seen_count > 1 ? ` · proposed by ${c.seen_count} runs` : ''} · {c.origin === 'claude_refresh' ? 'from a Claude refresh' : c.origin.replace('_', ' ')}</p>
        <div className="compare">
          <div><div className="label">Current{c.base_version_no ? ` (version ${c.base_version_no})` : ''}</div><p>{fmtValue(c.old_value)}</p></div>
          <div className="proposed"><div className="label">Proposed{c.base_version_no ? ` (version ${c.base_version_no + 1})` : ''}</div><p>{fmtValue(c.new_value)}</p></div>
        </div>
        <p style={{ margin: 0 }}>{c.summary}</p>
        <figure className="quote">
          <blockquote>“{c.source_quote}”</blockquote>
          <figcaption className="small">{c.source_url ? <a href={c.source_url} target="_blank" rel="noreferrer noopener">{c.source_host}</a> : '—'} · {conf(c)} {c.off_allowlist && <Badge tone="warn">Source not on the allowlist</Badge>}</figcaption>
        </figure>
        <div>
          <strong>What this affects</strong>
          {!c.impacts?.length ? <p className="small muted">No client is affected yet.</p> : (
            <ul className="impact-list">
              {c.impacts.map((i) => <li key={i.organization_id}><strong>{i.organization_name}</strong>{i.systems.length ? `: ${i.systems.join(', ')}` : ''}{i.roles.length ? ` · roles: ${i.roles.join(', ')}` : ''}{i.letter_update_needed ? ' · intro letter needs an update' : ''}</li>)}
            </ul>
          )}
        </div>
        {c.needs_second_review && (
          <div className="second-review">
            <strong>Second review</strong>
            <p className="small" style={{ margin: '4px 0' }}>{c.second_review.outcome ? `${c.second_review.by} ${c.second_review.outcome === 'concur' ? 'concurs' : 'objects'}: ${c.second_review.note}` : `Needed before approval${c.assigned_reviewer ? `; asked: ${c.assigned_reviewer}` : ''}.`}</p>
            {isSecond && open && (
              <div className="stack-sm">
                <TextArea label="Your review" help={H.secondReview} value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={2} />
                <div className="row"><Button variant="primary" disabled={!reviewNote.trim()} onClick={() => second('concur')}>Concur</Button><Button disabled={!reviewNote.trim()} onClick={() => second('object')}>Object</Button></div>
              </div>
            )}
            {isChief && open && !c.second_review.outcome && reviewers.length > 0 && (
              <div className="row" style={{ alignItems: 'flex-end' }}>
                <div style={{ minWidth: 220 }}><SelectField label="Ask a second reviewer" help={H.reviewer} value={assignee} onChange={(e) => setAssignee(e.target.value)} options={reviewers.map((r) => ({ value: r.id, label: r.name }))} placeholder="Choose" /></div>
                <Button disabled={!assignee} onClick={assign}>Ask</Button>
              </div>
            )}
          </div>
        )}
        {isChief && open ? (
          <div className="stack-sm">
            <Checkbox label="On approval, send a client alert to each affected client (waits in Client alerts for approval)" help={H.notifyClients} checked={notify} onChange={(e) => setNotify(e.target.checked)} />
            {c.kind === 'law' && <Checkbox label="On approval, add this change to the next version of each affected client's intro letter" help={H.updateLetters} checked={letters} onChange={(e) => setLetters(e.target.checked)} />}
            <TextField label="Note (optional)" help={H.note} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row wrap">
              <Button variant="primary" onClick={() => act('approve')}>{c.kind === 'law' ? 'Approve and publish' : 'Approve and update the case'}</Button>
              <Button onClick={() => setEditing(true)}>Edit before approving</Button>
              <Button onClick={() => act('hold')}>Hold until adopted</Button>
              <Button onClick={() => act('legal_review')}>Send to legal review</Button>
              <Button variant="danger" onClick={() => act('reject')}>Reject</Button>
            </div>
          </div>
        ) : !open ? <p className="small muted">{STATUS_LABEL[c.status]}{c.reviewer ? ` by ${c.reviewer}` : ''}{c.review_note ? `: ${c.review_note}` : ''}.</p> : null}
      </div>
      {editing && (
        <Dialog title="Edit before approving" onClose={() => setEditing(false)}>
          <div className="stack">
            <TextArea label="Value to publish" help={H.editValue} value={value} onChange={(e) => setValue(e.target.value)} rows={5} />
            <TextField label="Note (optional)" help={H.note} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row"><Button variant="primary" onClick={() => act('edit_approve', { new_value: parsed() })}>Approve the edited value</Button><Button onClick={() => setEditing(false)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </Card>
  );
}

function RunCard({ kind, lawId, onStarted }: { kind: 'law' | 'litigation'; lawId: string | null; onStarted: (m: Msg) => void }) {
  const s = useQuery({ queryKey: ['refresh-settings', kind], queryFn: () => api.get<RunSettings>(`/admin/laws/refresh-settings/${kind}`) });
  const juris = useLawJurisdictions();
  const [scope, setScope] = useState('all');
  const [codes, setCodes] = useState<string[]>([]);
  const [checks, setChecks] = useState<string[] | null>(null);
  const [sources, setSources] = useState('official');
  const [alertMode, setAlertMode] = useState('setting');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sched, setSched] = useState(false);
  const qc = useQueryClient();
  const law = useQuery({ queryKey: ['law', lawId], enabled: !!lawId && kind === 'law', queryFn: () => api.get<{ jurisdiction_code: string; short_name: string }>(`/laws/${lawId}`) });
  useEffect(() => { if (law.data) { setScope('chosen'); setCodes([law.data.jurisdiction_code]); } }, [law.data]);
  const jOpts = useMemo(() => (juris.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)), [juris.data]);
  if (s.isLoading || !s.data) return <Card title="Run a refresh"><Loading /></Card>;
  const st = s.data;
  const chosen = checks ?? st.checks;
  async function run() {
    setErr(null); setBusy(true);
    try {
      await api.post('/admin/laws/refresh', { kind, scope_mode: scope, jurisdiction_codes: codes, checks: chosen, source_set: sources, alert_recipients: alertMode });
      await qc.invalidateQueries({ queryKey: ['refresh-runs'] });
      onStarted({ tone: 'success', text: 'The refresh has started. Proposals appear in the queue as each geography finishes; you will get an alert when it ends.' });
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="Run a refresh">
      <div className="stack">
        {!st.enabled && <Alert tone="warn">Refresh is switched off. Add an Anthropic API key (ANTHROPIC_API_KEY) to the server's .env file and restart.</Alert>}
        {err && <Alert tone="danger">{err}</Alert>}
        {law.data && <Alert>Checks the geography of {law.data.short_name}. Claude compares every approved law there, so related changes are found too.</Alert>}
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.geographies}>Geographies</WithHelp></legend>
          {[['all', `All ${st.counts.all} geographies`], ['client_geographies', `Only geographies our clients operate in (${st.counts.client_geographies})`], ['chosen', 'Choose geographies']].map(([v, l]) => (
            <label key={v} className="check"><input type="radio" name={`scope-${kind}`} checked={scope === v} onChange={() => setScope(v)} /><span>{l}</span></label>
          ))}
          {scope === 'chosen' && (
            <div className="chip-picker">
              {jOpts.map((j) => { const on = codes.includes(j.code); return <button key={j.code} type="button" className="pill" aria-pressed={on} onClick={() => setCodes(on ? codes.filter((c) => c !== j.code) : [...codes, j.code])}>{j.name}</button>; })}
            </div>
          )}
        </fieldset>
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.checks}>Check for</WithHelp></legend>
          {st.check_options.map((o) => <Checkbox key={o.value} label={o.label} checked={chosen.includes(o.value)} onChange={(e) => setChecks(e.target.checked ? [...chosen, o.value] : chosen.filter((c) => c !== o.value))} />)}
        </fieldset>
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.sources}>Sources</WithHelp></legend>
          <label className="check"><input type="radio" name={`src-${kind}`} checked={sources === 'official'} onChange={() => setSources('official')} /><span>Official sources only ({st.counts.official_sources}): legislatures, regulators, courts, official journals</span></label>
          <label className="check"><input type="radio" name={`src-${kind}`} checked={sources === 'with_secondary'} onChange={() => setSources('with_secondary')} /><span>Official sources plus law-firm alerts ({st.counts.secondary_sources})</span></label>
        </fieldset>
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.alert}>When finished, alert</WithHelp></legend>
          <label className="check"><input type="radio" name={`al-${kind}`} checked={alertMode === 'setting'} onChange={() => setAlertMode('setting')} /><span>{st.alert.recipients_rule === 'runner' ? 'The Chief Auditor who runs it' : 'All Chief Auditors'}, {st.alert.channels.includes('email') ? 'in the app and by email' : 'in the app'}{st.alert.cc_roles.length ? ` (copy ${st.alert.cc_roles.map((r) => (r === 'qa_reviewer' ? 'QA Reviewer' : 'Futran Admin')).join(' and ')})` : ''}</span></label>
          <label className="check"><input type="radio" name={`al-${kind}`} checked={alertMode === 'me'} onChange={() => setAlertMode('me')} /><span>Only me</span></label>
          <Link className="small" to="/staff/alerts">Alert settings</Link>
        </fieldset>
        <Button variant="primary" block disabled={!st.enabled || busy || (scope === 'chosen' && !codes.length) || !chosen.length} onClick={run}>{busy ? 'Starting…' : 'Run refresh with Claude'}</Button>
        <p className="small muted" style={{ margin: 0 }}>{st.schedule_enabled ? `Scheduled every ${st.every_days} days${st.next_due ? `, next ${fmtDateTime(st.next_due)}` : ''}` : 'Schedule off'} · cost cap ${st.cost_cap_usd.toFixed(2)} · <button type="button" className="linklike small" onClick={() => setSched(true)}>change</button></p>
      </div>
      {sched && <ScheduleDialog kind={kind} st={st} onClose={() => setSched(false)} />}
    </Card>
  );
}

function ScheduleDialog({ kind, st, onClose }: { kind: string; st: RunSettings; onClose: () => void }) {
  const [on, setOn] = useState(st.schedule_enabled);
  const [days, setDays] = useState(String(st.every_days));
  const [cap, setCap] = useState(String(st.cost_cap_usd));
  const [scope, setScope] = useState(st.scope_mode === 'chosen' ? 'all' : st.scope_mode);
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();
  async function save() {
    setErr(null);
    try {
      await api.put(`/admin/laws/refresh-settings/${kind}`, { schedule_enabled: on, every_days: Number(days), cost_cap_usd: Number(cap), scope_mode: scope });
      await qc.invalidateQueries({ queryKey: ['refresh-settings', kind] });
      onClose();
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Schedule and cost cap" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>{H.schedule}</p>
        <Checkbox label="Run on a schedule" checked={on} onChange={(e) => setOn(e.target.checked)} />
        <TextField label="Every (days)" help={H.everyDays} type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} />
        <SelectField label="Geographies" help={H.geographies} value={scope} onChange={(e) => setScope(e.target.value)} options={[{ value: 'all', label: 'All geographies' }, { value: 'client_geographies', label: 'Only client geographies' }]} />
        <TextField label="Cost cap per run (US dollars)" help={H.costCap} type="number" min={0.5} step={0.5} value={cap} onChange={(e) => setCap(e.target.value)} />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

const STATUS_RUN: Record<string, ['navy' | 'danger' | 'warn' | 'success' | 'muted', string]> = {
  queued: ['navy', 'Starting'], running: ['navy', 'Running'], failed: ['danger', 'Failed'], capped: ['warn', 'Stopped at cost cap'], completed: ['success', 'Finished'],
};

function RunsCard({ kind }: { kind: string }) {
  const runs = useQuery({ queryKey: ['refresh-runs', kind], queryFn: () => api.get<Run[]>(`/admin/laws/refresh?kind=${kind}`), refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running' || r.status === 'queued') ? 4000 : false) });
  const [openRun, setOpenRun] = useState<string | null>(null);
  const last = runs.data?.find((r) => !r.legacy);
  return (
    <>
      {last && (
        <Card title={`Last run · ${fmtDateTime(last.started_at)}`}>
          <ol className="steps">
            <li>Read {last.sources_read} sources across {last.jurisdictions.length} {last.jurisdictions.length === 1 ? 'geography' : 'geographies'}</li>
            <li>Compared against {last.records_compared} approved {kind === 'law' ? 'law records' : 'case records'}</li>
            <li>Proposed {last.proposals_created} {last.proposals_created === 1 ? 'change' : 'changes'}, each with a source quote{last.proposals_merged ? `; ${last.proposals_merged} matched earlier proposals` : ''}</li>
            <li>{last.status === 'running' || last.status === 'queued' ? 'Running…' : last.open ? `${last.open} waiting for Chief Auditor review` : 'Nothing waiting'}</li>
          </ol>
          <div className="row wrap" style={{ gap: 6 }}>
            {Object.entries(last.counts).filter(([, v]) => v).map(([k, v]) => <Badge key={k}>{last.count_labels?.[k] ?? k}: {v}</Badge>)}
          </div>
          <p className="small muted">{last.started_by_name} · {last.model_id ?? '—'} · prompt {last.prompt_version} · ${(last.cost_usd ?? 0).toFixed(2)}{last.cost_cap_usd ? ` of $${last.cost_cap_usd.toFixed(2)} cap` : ''}{last.alert_status ? ` · ${last.alert_status}` : ''}</p>
          {last.warnings.length > 0 && <details className="small"><summary>{last.warnings.length} {last.warnings.length === 1 ? 'note' : 'notes'} from the run</summary><ul>{last.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
          {last.error && <Alert tone="danger">{last.error}</Alert>}
        </Card>
      )}
      <Card title="Recent runs">
        {runs.isLoading ? <Loading /> : !runs.data?.length ? <EmptyState>No runs yet.</EmptyState> : (
          <ul className="run-list">
            {runs.data.slice(0, 12).map((r) => {
              const [tone, label] = STATUS_RUN[r.status] ?? ['muted', r.status];
              return (
                <li key={r.id}>
                  <button type="button" className="linklike left" onClick={() => setOpenRun(r.id)}>
                    <span>{fmtDateTime(r.started_at)}{r.trigger === 'scheduled' ? ' · scheduled' : ''}{r.legacy ? ' · earlier law update' : ''}</span>
                    <span className="small muted block">{r.jurisdictions.slice(0, 3).join(', ')}{r.jurisdictions.length > 3 ? ` and ${r.jurisdictions.length - 3} more` : ''}</span>
                  </button>
                  <Badge tone={tone}>{label}</Badge>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      {openRun && <RunDialog id={openRun} onClose={() => setOpenRun(null)} />}
    </>
  );
}

function RunDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['refresh-run', id], queryFn: () => api.get<Run & { responses?: { jurisdiction: string; outcome: string; accepted: number; merged: number; skipped: number; cost_usd: number; sources: number }[] }>(`/admin/laws/refresh/${id}`) });
  return (
    <Dialog title="Refresh run" onClose={onClose} large>
      {q.isLoading || !q.data ? <Loading /> : (
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>{fmtDateTime(q.data.started_at)} · {q.data.started_by_name ?? '—'} · {q.data.model_id ?? q.data.model ?? '—'}{q.data.prompt_version ? ` · prompt ${q.data.prompt_version}` : ''}{q.data.cost_usd !== undefined ? ` · $${q.data.cost_usd.toFixed(2)}` : ''}</p>
          {q.data.error && <Alert tone="danger">{q.data.error}</Alert>}
          {q.data.legacy ? (
            <>
              <Alert>An earlier law update run. Its proposals are kept for the record.</Alert>
              <div className="table-wrap"><table className="table"><thead><tr><th>Change</th><th>Jurisdiction</th><th>Proposal</th><th>Status</th></tr></thead>
                <tbody>{(q.data.proposals ?? []).map((p) => <tr key={p.id}><td>{p.change_type}</td><td>{p.jurisdiction}</td><td style={{ whiteSpace: 'normal' }}>{p.rationale}</td><td>{p.status}</td></tr>)}</tbody></table></div>
            </>
          ) : (
            <div className="table-wrap"><table className="table"><thead><tr><th>Geography</th><th>Sources</th><th>Reply</th><th>New</th><th>Merged</th><th>Skipped</th><th>Cost</th></tr></thead>
              <tbody>{(q.data.responses ?? []).map((r, i) => <tr key={i}><td>{r.jurisdiction}</td><td>{r.sources}</td><td>{r.outcome === 'rejected' ? <Badge tone="danger">Rejected: not schema JSON</Badge> : 'Accepted'}</td><td>{r.accepted}</td><td>{r.merged}</td><td>{r.skipped}</td><td>${r.cost_usd.toFixed(2)}</td></tr>)}</tbody></table></div>
          )}
          {q.data.warnings.length > 0 && <ul className="small">{q.data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </div>
      )}
    </Dialog>
  );
}
