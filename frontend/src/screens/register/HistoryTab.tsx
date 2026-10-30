import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { HISTORY_TYPES, type HistoryEntry, type HistoryPage, type RegSystem, type RequirementRow, type Requirements, type Tracing } from '@/api/register';
import { Alert, Badge, Button, Checkbox, Dialog, FieldGroup, Loading, SelectField, TextArea, TextField, fmtDate, fmtDateTime, fileUrl } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { historyHelp as H, requirementHelp as R } from '@/help/register';
import { Lock } from './RegisterGrid';

const QUESTIONS: [string, string][] = [
  ['bias_tests', 'Have any bias tests been done?'],
  ['deployment_tests', 'Was it tested before release (user acceptance, red team, security)?'],
  ['approvals', 'Was its use approved by anyone (a manager, a committee, a policy owner)?'],
  ['notices', 'Have notices been given or consents collected from the people it affects?'],
];
const ANSWERS = [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }];
const REQ_STATUS = [{ value: 'met', label: 'Met' }, { value: 'partly_met', label: 'Partly met' }, { value: 'not_met', label: 'Not met' }, { value: 'not_applicable', label: 'Not applicable' }];
const REQ_TONE: Record<string, 'success' | 'warn' | 'danger' | 'muted'> = { met: 'success', partly_met: 'warn', not_met: 'danger', not_applicable: 'muted' };
const TYPE_FOR_ANSWER: Record<string, string> = { incidents: 'incident', bias_tests: 'bias_test', deployment_tests: 'deployment_test', approvals: 'approval', notices: 'notice_consent' };

export function FirstEntryQuestions({ stage, liveSince, answers, onChange, help }: { stage: string; liveSince?: string | null; answers: Record<string, string>; onChange: (a: Record<string, string>) => void; help: typeof H }) {
  const since = stage === 'live' && liveSince ? `Since this system went live on ${fmtDate(liveSince)}` : stage === 'live' ? 'Since this system went live' : 'So far';
  return (
    <div className="stack">
      <FieldGroup legend={`${since}, have there been any incidents, complaints or errors?`} help={help.incidentsQuestion}>
        <div className="stack-sm">
          <label className="radio-pill reg-radio"><input type="radio" name="q-incidents" checked={answers.incidents === 'yes'} onChange={() => onChange({ ...answers, incidents: 'yes' })} />Yes. They are added to the history log.</label>
          <label className="radio-pill reg-radio"><input type="radio" name="q-incidents" checked={answers.incidents === 'no'} onChange={() => onChange({ ...answers, incidents: 'no' })} />No, none known. The system owner signs a statement.</label>
        </div>
      </FieldGroup>
      {QUESTIONS.map(([k, q]) => (
        <FieldGroup key={k} legend={q} help={help.otherQuestions}>
          <div className="radio-group">{ANSWERS.map((a) => <label key={a.value} className="radio-pill"><input type="radio" name={`q-${k}`} checked={answers[k] === a.value} onChange={() => onChange({ ...answers, [k]: a.value })} />{a.label}</label>)}</div>
        </FieldGroup>
      ))}
    </div>
  );
}

export function TracingCard({ t, compact }: { t: Tracing; compact?: boolean }) {
  return (
    <section className="card reg-tracing" aria-labelledby="tracing-h">
      <div className="card-header">
        <h2 id="tracing-h">Tracing and incident module</h2>
        <span className="row" style={{ gap: 6 }}><Badge tone="muted"><Lock /> Add-on · locked</Badge>{t.recommended && <Badge tone="warn">Recommended for this system</Badge>}</span>
      </div>
      <div className="card-body stack-sm">
        {t.recommended && <p style={{ margin: 0 }}><strong>Why:</strong> {t.reasons.join(', ')}.</p>}
        {!compact && (
          <ul className="reg-ticks">
            <li>Every action and decision traced, with who approved it</li>
            <li>Incident reporting with regulator deadline timers</li>
            <li>Drift and bias alerts between audits</li>
            <li>Audit-ready export for regulators and Futran</li>
          </ul>
        )}
        <div className="row"><Button disabled title="Available when the tracing add-on is offered for your account">Unlock for this system</Button></div>
        <p className="small muted" style={{ margin: 0 }}>Your Executive Sponsor approves the purchase. Buying it never changes audit results; auditors keep reviewing the system independently.</p>
      </div>
    </section>
  );
}

export function TracingTab({ s }: { s: RegSystem }) {
  const t = s.history?.tracing ?? { locked: true, recommended: false, reasons: [] };
  return <TracingCard t={t} />;
}

export function HistoryTab({ s, onChanged }: { s: RegSystem; onChanged: () => unknown }) {
  const q = useQuery({ queryKey: ['register-history', s.id], queryFn: () => api.get<HistoryPage>(`/register/${s.id}/history`) });
  const rq = useQuery({ queryKey: ['register-reqs', s.id], queryFn: () => api.get<Requirements>(`/register/${s.id}/requirements`) });
  const [params, setParams] = useSearchParams();
  const [entry, setEntry] = useState<{ type: string; e?: HistoryEntry } | null>(null);
  const [linking, setLinking] = useState<HistoryEntry[] | null>(null);
  const [deleting, setDeleting] = useState<HistoryEntry[] | null>(null);
  const [req, setReq] = useState<RequirementRow | null>(null);
  const [typeFilter, setTypeFilter] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  useEffect(() => { const add = params.get('add'); if (add) { setEntry({ type: add }); params.delete('add'); setParams(params, { replace: true }); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (q.data) setAnswers(q.data.answers); }, [q.data]);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const h = q.data;
  const reqs = rq.data;
  const refresh = async () => { await Promise.all([q.refetch(), rq.refetch()]); await onChanged(); };
  async function saveAnswers() {
    setFlash(null);
    try {
      await api.post(`/register/${s.id}/history-answers`, answers);
      await refresh();
      const yes = Object.entries(answers).filter(([, v]) => v === 'yes').map(([k]) => k);
      setFlash({ tone: 'success', text: yes.length ? 'Answers saved. Add an entry for each Yes below.' : 'Answers saved.' });
      if (yes.length) setEntry({ type: TYPE_FOR_ANSWER[yes[0]] });
    } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  const rows = typeFilter ? h.entries.filter((e) => e.type === typeFilter) : h.entries;
  const reqCode = (id: string) => reqs?.rows.find((r) => r.id === id)?.code ?? id;
  function exportEntries(list: HistoryEntry[]) {
    const esc = (v: string) => { const x = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v; return /[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x; };
    const lines = [['date', 'type', 'what happened', 'result', 'requirements', 'recorded by'].join(','), ...list.map((e) => [e.occurred_on, e.type_label, e.summary, e.result ?? '', e.requirement_ids.map(reqCode).join(' '), e.recorded_by ?? ''].map(esc).join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a'); a.href = url; a.download = `${s.reference}-history.csv`; a.click(); URL.revokeObjectURL(url);
  }
  const answered = !!h.answers.incidents;
  return (
    <div className="stack">
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <section className="card">
        <div className="card-header"><h2>{answered ? 'History to date' : 'Asked when this system was first entered'}</h2>{answered && <Badge tone="muted">Answered</Badge>}</div>
        <div className="card-body stack">
          <fieldset disabled={!h.can_record} className="reg-plain"><FirstEntryQuestions stage={s.stage} liveSince={s.live_since} answers={answers} onChange={setAnswers} help={H} /></fieldset>
          {h.can_record && <div className="row"><Button variant="primary" onClick={saveAnswers} disabled={!answers.incidents}>Save answers</Button></div>}
          {h.statement && <Statement s={s} st={h.statement} isOwner={h.is_owner} onSigned={refresh} />}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>History log ({h.entries.length})</h2>
          <div className="row">
            <SelectField label="Type" help="Show one kind of entry." value={typeFilter} placeholder="All types" onChange={(e) => setTypeFilter(e.target.value)} options={HISTORY_TYPES} />
            {h.can_record && <AddEntryButton onPick={(type) => setEntry({ type })} />}
          </div>
        </div>
        <div className="card-body">
          <DataGrid label="History log" rows={rows} rowId={(e) => e.id} rowLabel={(e) => `${e.type_label} of ${fmtDate(e.occurred_on)}`} selectable={h.can_record}
            emptyText="No entries yet. Add incidents, tests, approvals, notices and model changes as they happen." initialSort={{ key: 'date', dir: 'desc' }}
            columns={[
              { key: 'date', header: 'Date', value: (e) => e.occurred_on, render: (e) => fmtDate(e.occurred_on) },
              { key: 'type', header: 'Type', value: (e) => e.type_label, render: (e) => <>{e.type_label}{e.severity_label && <div className="small muted">{e.severity_label}</div>}</> },
              { key: 'what', header: 'What happened', value: (e) => e.summary },
              { key: 'result', header: 'Result or resolution', value: (e) => e.result ?? '', render: (e) => <span className="small">{e.result ?? '—'}</span> },
              { key: 'req', header: 'Requirement', value: (e) => e.requirement_ids.length, render: (e) => <span className="small">{e.requirement_ids.map(reqCode).join(', ') || '—'}</span> },
              { key: 'evidence', header: 'Evidence', value: (e) => e.evidence.length, render: (e) => e.evidence.length ? e.evidence.map((f) => <div key={f.id}><a className="small" href={fileUrl(f.id)}>{f.filename}</a></div>) : <span className="muted">—</span> },
              { key: 'by', header: 'Recorded by', value: (e) => e.recorded_by ?? '' },
            ]}
            bulkActions={h.can_record ? [
              { label: 'Link to a requirement', run: (list) => setLinking(list) },
              { label: 'Export', run: (list) => exportEntries(list) },
              { label: 'Delete', danger: true, run: (list) => setDeleting(list) },
            ] : [{ label: 'Export', run: (list) => exportEntries(list) }]}
            rowActions={(e) => [
              { label: h.can_record ? 'Open and edit entry' : 'Open entry', onSelect: () => setEntry({ type: e.type, e }) },
              { label: 'Attach evidence', disabled: !h.can_record, onSelect: () => setEntry({ type: e.type, e }) },
              { label: 'Link to a requirement', disabled: !h.can_record, onSelect: () => setLinking([e]) },
              { label: 'Delete entry', danger: true, disabled: !h.can_record, onSelect: () => setDeleting([e]) },
            ]} />
        </div>
      </section>

      <section className="card">
        <div className="card-header"><h2>Requirements checklist{reqs ? ` · ${reqs.met} of ${reqs.total} met` : ''}</h2><span className="small muted">From the laws on this system (regulatory master)</span></div>
        <div className="card-body stack-sm">
          {!reqs ? <Loading /> : (
            <DataGrid label="Requirements checklist" rows={reqs.rows} rowId={(r) => r.id} rowLabel={(r) => r.code}
              emptyText={s.laws.length ? 'The laws on this system list no requirements yet.' : 'Choose the laws that apply on the Details tab to see their requirements.'}
              columns={[
                { key: 'code', header: 'ID', value: (r) => r.code },
                { key: 'text', header: 'Requirement', value: (r) => r.text, render: (r) => <>{r.text}{r.citation && <div className="small muted">{r.citation}</div>}</> },
                { key: 'law', header: 'Law', value: (r) => r.law },
                { key: 'status', header: 'Status', value: (r) => r.status_label, render: (r) => <><Badge tone={REQ_TONE[r.status]}>{r.status_label}</Badge>{r.carried_from_previous_version && <div className="small muted">From the previous law version</div>}</> },
                { key: 'evidence', header: 'Evidence', sortable: false, render: (r) => <span className="small">{[...r.history_entries.map((e) => `${HISTORY_TYPES.find((x) => x.value === e.type)?.label}, ${fmtDate(e.occurred_on)}`), ...r.evidence.map((f) => f.filename)].join('; ') || r.note || '—'}</span> },
                { key: 'needed', header: 'Needed by', value: (r) => r.needed_by_label, render: (r) => <>{r.needed_by_label}{r.gate && r.status === 'not_met' && <div className="small reg-danger">Blocks go-live</div>}</> },
              ]}
              rowActions={(r) => [{ label: 'Update status', disabled: !reqs.can_edit, onSelect: () => setReq(r) }]} />
          )}
          <p className="small muted" style={{ margin: 0 }}>A requirement needed before use or go-live that is Not met counts toward the go-live gate, like a missing role.</p>
        </div>
      </section>

      <TracingCard t={h.tracing} />

      {entry && <EntryDialog s={s} type={entry.type} e={entry.e} readOnly={!h.can_record} reqs={reqs?.rows ?? []} onClose={() => setEntry(null)} onSaved={async () => { setEntry(null); await refresh(); }} />}
      {linking && <LinkDialog s={s} entries={linking} reqs={reqs?.rows ?? []} onClose={() => setLinking(null)} onDone={async () => { setLinking(null); await refresh(); }} />}
      {deleting && <DeleteDialog s={s} entries={deleting} onClose={() => setDeleting(null)} onDone={async () => { setDeleting(null); await refresh(); }} />}
      {req && <RequirementDialog s={s} r={req} entries={h.entries} onClose={() => setReq(null)} onDone={async () => { setReq(null); await refresh(); }} />}
    </div>
  );
}

function AddEntryButton({ onPick }: { onPick: (t: string) => void }) {
  const [open, setOpen] = useState(false);
  const [t, setT] = useState('incident');
  if (!open) return <Button variant="primary" onClick={() => setOpen(true)}>Add entry</Button>;
  return (
    <div className="row" style={{ alignItems: 'flex-end' }}>
      <SelectField label="Kind of entry" help={H.type} value={t} onChange={(e) => setT(e.target.value)} options={HISTORY_TYPES} />
      <Button variant="primary" onClick={() => { setOpen(false); onPick(t); }}>Add</Button>
    </div>
  );
}

function Statement({ s, st, isOwner, onSigned }: { s: RegSystem; st: NonNullable<HistoryPage['statement']>; isOwner: boolean; onSigned: () => unknown }) {
  const [name, setName] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function sign() {
    setErr(null);
    try { await api.post(`/register/${s.id}/no-incident/sign`, { typed_name: name }); await onSigned(); } catch (e) { setErr(errorMessage(e)); setName(''); }
  }
  return (
    <div className="stack-sm">
      <strong>No-incident statement</strong>
      <blockquote className="statement">{st.statement}</blockquote>
      {st.signed_at ? <p className="small" style={{ margin: 0 }}>Signed by {st.signed_by} on {fmtDateTime(st.signed_at)}.</p>
        : isOwner ? (
          <div className="stack-sm">
            {err && <Alert tone="danger">{err}</Alert>}
            <div className="row" style={{ alignItems: 'flex-end' }}><TextField label="Type your name to sign" help={H.signName} value={name} onChange={(e) => setName(e.target.value)} /><Button variant="primary" onClick={sign}>Sign statement</Button></div>
          </div>
        ) : <Alert tone="warn">{st.owner ? `Waiting for ${st.owner}, the system owner, to sign.` : 'Name a system owner on the Details tab; they sign this statement.'}</Alert>}
    </div>
  );
}

type Field = { key: string; label: string; kind: 'text' | 'textarea' | 'date' | 'number' | 'bool' | 'select'; options?: { value: string; label: string }[]; help: string };
const TESTERS = [{ value: 'independent', label: 'Independent auditor' }, { value: 'internal', label: 'Internal team' }, { value: 'vendor', label: 'Vendor (their own audit)' }];
const FIELDS: Record<string, Field[]> = {
  incident: [
    { key: 'people_affected', label: 'People affected', kind: 'number', help: H.peopleAffected }, { key: 'cause', label: 'Cause', kind: 'text', help: H.cause },
    { key: 'containment', label: 'Containment and fix', kind: 'textarea', help: H.containment }, { key: 'closed_on', label: 'Date closed', kind: 'date', help: H.closedOn },
    { key: 'reportable', label: 'Reportable to a regulator or the people affected', kind: 'bool', help: H.reportable }, { key: 'law', label: 'Law', kind: 'text', help: H.law },
    { key: 'deadline', label: 'Reporting deadline', kind: 'date', help: H.deadline }, { key: 'reported_on', label: 'Date reported', kind: 'date', help: H.reportedOn },
    { key: 'provider_told', label: 'AI provider told (EU AI Act Art. 26(5))', kind: 'bool', help: H.providerTold },
  ],
  bias_test: [
    { key: 'tester_type', label: 'Tested by *', kind: 'select', options: TESTERS, help: H.tester }, { key: 'tester_name', label: 'Tester name', kind: 'text', help: H.testerName },
    { key: 'method', label: 'Method', kind: 'text', help: H.method }, { key: 'groups_tested', label: 'Groups tested', kind: 'text', help: H.groups },
    { key: 'result', label: 'Result *', kind: 'select', options: [{ value: 'passed', label: 'Passed' }, { value: 'flagged', label: 'Flagged' }, { value: 'inconclusive', label: 'Inconclusive' }], help: H.biasResult },
    { key: 'unknown_share', label: 'Share of records with unknown sex or race (%)', kind: 'number', help: H.unknownShare }, { key: 'next_due', label: 'Next test due', kind: 'date', help: H.nextDue },
  ],
  deployment_test: [
    { key: 'kind', label: 'Kind of test', kind: 'select', options: [{ value: 'user_acceptance', label: 'User acceptance' }, { value: 'agentassure', label: 'AgentAssure' }, { value: 'red_team', label: 'Red team' }, { value: 'security', label: 'Security' }], help: H.kind },
    { key: 'sample_size', label: 'Sample size', kind: 'number', help: H.sampleSize },
  ],
  impact_assessment: [{ key: 'law', label: 'Law', kind: 'text', help: H.law }, { key: 'outcome', label: 'Outcome', kind: 'text', help: H.outcome }, { key: 'next_due', label: 'Next due', kind: 'date', help: H.nextDue }],
  notice_consent: [{ key: 'audience', label: 'Audience', kind: 'text', help: H.audience }, { key: 'channel', label: 'Channel', kind: 'text', help: H.channel }, { key: 'version', label: 'Version', kind: 'text', help: H.version }],
  model_change: [{ key: 'old_version', label: 'Old version', kind: 'text', help: H.oldVersion }, { key: 'new_version', label: 'New version', kind: 'text', help: H.newVersion }, { key: 'reassessment_needed', label: 'Re-assessment needed', kind: 'bool', help: H.reassessment }],
  approval: [{ key: 'approver', label: 'Approver', kind: 'text', help: H.approver }, { key: 'scope', label: 'Scope', kind: 'text', help: H.scope }],
};
const SEVERITIES = [{ value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' }, { value: 'high', label: 'High' }, { value: 'serious', label: 'Serious (EU AI Act Art. 73)' }];

function EntryDialog({ s, type, e, readOnly, reqs, onClose, onSaved }: { s: RegSystem; type: string; e?: HistoryEntry; readOnly: boolean; reqs: RequirementRow[]; onClose: () => void; onSaved: () => unknown }) {
  const [f, setF] = useState({ occurred_on: e?.occurred_on ?? '', summary: e?.summary ?? '', result: e?.result ?? '', severity: e?.severity ?? '', details: { ...(e?.details ?? {}) } as Record<string, string | number | boolean>, requirement_ids: e?.requirement_ids ?? [] as string[], reason: '' });
  const [files, setFiles] = useState<{ id: string; filename: string }[]>(e?.evidence ?? []);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const label = HISTORY_TYPES.find((x) => x.value === type)?.label ?? 'Entry';
  const setD = (k: string, v: string | number | boolean | undefined) => setF((x) => { const d = { ...x.details }; if (v === undefined || v === '') delete d[k]; else d[k] = v; return { ...x, details: d }; });
  async function upload(file?: File) {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try { const r = await api.upload<{ id: string; filename: string }>(`/register/${s.id}/evidence`, fd); setFiles((x) => [...x, r]); } catch (ex) { setErr(errorMessage(ex)); }
  }
  async function save() {
    setBusy(true); setErr(null); setFe({});
    const body = { type, occurred_on: f.occurred_on, summary: f.summary, result: f.result || null, ...(type === 'incident' ? { severity: f.severity } : {}), details: f.details, requirement_ids: f.requirement_ids, evidence_ids: files.map((x) => x.id) };
    try {
      if (e) await api.patch(`/register/${s.id}/history/${e.id}`, { ...body, reason: f.reason }); else await api.post(`/register/${s.id}/history`, body);
      await onSaved();
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={e ? `${label} of ${fmtDate(e.occurred_on)}` : `Add ${label.toLowerCase()}`} onClose={onClose} large>
      <fieldset disabled={readOnly} className="reg-plain stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label={type === 'incident' ? 'Date found *' : 'Date *'} help={H.date} type="date" value={f.occurred_on} onChange={(x) => setF({ ...f, occurred_on: x.target.value })} error={fe.occurred_on} />
          {type === 'incident' && <SelectField label="Severity *" help={H.severity} value={f.severity} placeholder="Choose" onChange={(x) => setF({ ...f, severity: x.target.value })} options={SEVERITIES} error={fe.severity} />}
        </div>
        <TextArea label={type === 'incident' ? 'What happened *' : 'Summary *'} help={H.summary} value={f.summary} onChange={(x) => setF({ ...f, summary: x.target.value })} error={fe.summary} />
        <div className="grid-2">
          {(FIELDS[type] ?? []).map((fl) => {
            const v = f.details[fl.key];
            const err2 = fe[`details.${fl.key}`] ?? fe[fl.key];
            if (fl.kind === 'bool') return <Checkbox key={fl.key} label={fl.label} help={fl.help} checked={v === true} onChange={(x) => setD(fl.key, x.target.checked)} />;
            if (fl.kind === 'select') return <SelectField key={fl.key} label={fl.label} help={fl.help} value={String(v ?? '')} placeholder="Choose" onChange={(x) => setD(fl.key, x.target.value)} options={fl.options ?? []} error={err2} />;
            if (fl.kind === 'textarea') return <TextArea key={fl.key} label={fl.label} help={fl.help} value={String(v ?? '')} onChange={(x) => setD(fl.key, x.target.value)} error={err2} />;
            return <TextField key={fl.key} label={fl.label} help={fl.help} type={fl.kind === 'date' ? 'date' : 'text'} inputMode={fl.kind === 'number' ? 'decimal' : undefined} value={String(v ?? '')} onChange={(x) => setD(fl.key, fl.kind === 'number' ? (x.target.value === '' ? '' : x.target.value) : x.target.value)} error={err2} />;
          })}
        </div>
        <TextArea label={type === 'incident' ? 'Resolution' : 'Result'} help={H.result} value={f.result} onChange={(x) => setF({ ...f, result: x.target.value })} />
        {reqs.length > 0 && (
          <FieldGroup legend="Requirements it helps prove" help={H.requirements}>
            <div className="grid-2">{reqs.map((r) => <Checkbox key={r.id} label={`${r.code} · ${r.text}`} checked={f.requirement_ids.includes(r.id)} onChange={() => setF({ ...f, requirement_ids: f.requirement_ids.includes(r.id) ? f.requirement_ids.filter((x) => x !== r.id) : [...f.requirement_ids, r.id] })} />)}</div>
          </FieldGroup>
        )}
        <div className="stack-sm">
          {files.map((x) => <div key={x.id} className="small"><a href={fileUrl(x.id)}>{x.filename}</a> <button type="button" className="linklike" onClick={() => setFiles((y) => y.filter((z) => z.id !== x.id))}>Remove</button></div>)}
          {!readOnly && <TextField label="Attach evidence" help={H.evidence} type="file" onChange={(x) => void upload(x.target.files?.[0])} />}
        </div>
        {e && !readOnly && <TextField label="Reason for change" help={H.deleteReason.replace('deleted', 'changed')} value={f.reason} onChange={(x) => setF({ ...f, reason: x.target.value })} />}
        <div className="row">{!readOnly && <Button variant="primary" disabled={busy} onClick={save}>Save entry</Button>}<Button onClick={onClose}>{readOnly ? 'Close' : 'Cancel'}</Button></div>
      </fieldset>
    </Dialog>
  );
}

function LinkDialog({ s, entries, reqs, onClose, onDone }: { s: RegSystem; entries: HistoryEntry[]; reqs: RequirementRow[]; onClose: () => void; onDone: () => unknown }) {
  const [rid, setRid] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    try { await api.post(`/register/${s.id}/history/bulk`, { entry_ids: entries.map((e) => e.id), action: 'link_requirement', requirement_id: rid }); await onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Link ${entries.length} entr${entries.length === 1 ? 'y' : 'ies'} to a requirement`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Requirement" help={H.requirements} value={rid} placeholder="Choose" onChange={(e) => setRid(e.target.value)} options={reqs.map((r) => ({ value: r.id, label: `${r.code} · ${r.text}` }))} />
        <div className="row"><Button variant="primary" disabled={!rid} onClick={go}>Link</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DeleteDialog({ s, entries, onClose, onDone }: { s: RegSystem; entries: HistoryEntry[]; onClose: () => void; onDone: () => unknown }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    try { await api.post(`/register/${s.id}/history/bulk`, { entry_ids: entries.map((e) => e.id), action: 'delete', reason }); await onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Delete ${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Reason *" help={H.deleteReason} value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="row"><Button variant="danger" onClick={go}>Delete</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function RequirementDialog({ s, r, entries, onClose, onDone }: { s: RegSystem; r: RequirementRow; entries: HistoryEntry[]; onClose: () => void; onDone: () => unknown }) {
  const [f, setF] = useState({ status: r.status, note: r.note ?? '', history_entry_ids: r.history_entries.map((e) => e.id) });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    try { await api.put(`/register/${s.id}/requirements/${r.id}`, f); await onDone(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={`${r.code} · ${r.law}`} onClose={onClose} wide>
      <div className="stack">
        <p style={{ margin: 0 }}>{r.text}</p>
        {r.evidence_text && <p className="small muted" style={{ margin: 0 }}>Evidence expected: {r.evidence_text}</p>}
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Status" help={R.status} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} options={REQ_STATUS} error={fe.status} />
        <TextArea label="Note" help={R.note} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} error={fe.note} />
        {entries.length > 0 && (
          <FieldGroup legend="History entries that prove it" help={R.entries}>
            <div className="stack-sm">{entries.map((e) => <Checkbox key={e.id} label={`${e.type_label}, ${fmtDate(e.occurred_on)}: ${e.summary}`} checked={f.history_entry_ids.includes(e.id)} onChange={() => setF({ ...f, history_entry_ids: f.history_entry_ids.includes(e.id) ? f.history_entry_ids.filter((x) => x !== e.id) : [...f.history_entry_ids, e.id] })} />)}</div>
          </FieldGroup>
        )}
        <div className="row"><Button variant="primary" onClick={go}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
