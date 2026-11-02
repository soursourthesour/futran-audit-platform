import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, Loading, PageHeader, SelectField, TextArea, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { CONFIDENCE_LABEL, FEATURE_LABEL, STATUS_LABEL, citeText, statusTone, useAISwitch, type AISwitch, type Interaction } from '@/api/ai';
import { aiSwitchHelp, copilotHelp } from '@/help/ai';
import { DecideRow, Quote } from './Copilot';
import './copilot.css';

type Log = {
  engagement: { id: string; audit_ref: string; client_id: string; client: string }; switch: AISwitch;
  totals: { suggestions: number; pending: number; accepted: number; edited: number; rejected: number; unsupported: number; calls: number };
  rows: Interaction[];
};

/** The engagement's AI interaction log (spec §21 rule 3): every suggestion, the model and prompt version, the inputs,
 *  the citations and who decided it. Chief Auditor, Lead Auditor and QA. */
export function AILog() {
  const { engagementId = '' } = useParams();
  const q = useQuery({ queryKey: ['ai-log', engagementId], queryFn: () => api.get<Log>(`/engagements/${engagementId}/ai-log`) });
  const [open, setOpen] = useState<Interaction | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const t = d.totals;
  const columns: GridColumn<Interaction>[] = [
    { key: 'at', header: 'When', value: (r) => r.created_at ?? '', render: (r) => fmtDateTime(r.created_at) },
    { key: 'feature', header: 'Feature', value: (r) => FEATURE_LABEL[r.feature] ?? r.feature },
    { key: 'system', header: 'System', value: (r) => r.system ?? 'Engagement' },
    { key: 'target', header: 'Item', value: (r) => r.target_code ?? '' },
    { key: 'status', header: 'Status', value: (r) => STATUS_LABEL[r.status], render: (r) => <Badge tone={statusTone(r.status)}>{STATUS_LABEL[r.status]}</Badge> },
    { key: 'confidence', header: 'Confidence', value: (r) => (r.confidence ? CONFIDENCE_LABEL[r.confidence] : '') },
    { key: 'by', header: 'Requested by', value: (r) => r.requested_by ?? '' },
    { key: 'decided', header: 'Decided by', value: (r) => r.decided_by ?? '', render: (r) => r.decided_by ? <>{r.decided_by}<div className="small muted">{fmtDateTime(r.decided_at)}</div></> : <span className="muted">Not decided</span> },
    { key: 'model', header: 'Model', value: (r) => `${r.provider} · ${r.model}` },
  ];
  const features = [...new Set(d.rows.map((r) => r.feature))];
  return (
    <div className="page">
      <PageHeader title="AI interaction log" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${d.engagement.client_id}`, label: `${d.engagement.client} · ${d.engagement.audit_ref}` }, { label: 'AI interaction log' }]}
        subtitle={d.switch.enabled ? <>AI enabled by {d.switch.enabled_by} on {fmtDateTime(d.switch.enabled_at)} · client consent: {d.switch.consent_note}</> : 'AI features are off for this engagement. Earlier interactions stay on record.'} />
      <div className="cp-tiles" style={{ marginTop: 12 }}>
        <div className="cp-tile"><div className="cp-n">{t.calls}</div><div className="small">model calls</div></div>
        <div className="cp-tile"><div className="cp-n">{t.suggestions}</div><div className="small">suggestions</div></div>
        <div className="cp-tile ok"><div className="cp-n">{t.accepted + t.edited}</div><div className="small">accepted ({t.edited} with edits)</div></div>
        <div className="cp-tile"><div className="cp-n">{t.rejected}</div><div className="small">rejected</div></div>
        <div className={`cp-tile ${t.unsupported ? 'danger' : ''}`}><div className="cp-n">{t.unsupported}</div><div className="small">unsupported (no passage found)</div></div>
        <div className={`cp-tile ${t.pending ? 'warn' : ''}`}><div className="cp-n">{t.pending}</div><div className="small">waiting for a decision</div></div>
      </div>
      <DataGrid label="AI interactions" rows={d.rows} rowId={(r) => r.id} rowLabel={(r) => `${FEATURE_LABEL[r.feature]} ${r.target_code ?? ''}`} columns={columns}
        initialSort={{ key: 'at', dir: 'desc' }} search={{ label: 'Search the log', text: (r) => `${r.target_code ?? ''} ${r.requested_by ?? ''} ${r.decided_by ?? ''} ${JSON.stringify(r.output)}` }}
        filters={[{ key: 'feature', label: 'Feature', options: features.map((f) => ({ value: f, label: FEATURE_LABEL[f] ?? f })), test: (r, v) => r.feature === v },
          { key: 'status', label: 'Status', options: Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label })), test: (r, v) => r.status === v }]}
        rowActions={(r) => [{ label: 'View details', onSelect: () => setOpen(r) }]} emptyText="No AI interactions on this engagement yet." />
      {open && (
        <Dialog title={`${FEATURE_LABEL[open.feature]}${open.target_code ? ` · ${open.target_code}` : ''}`} onClose={() => setOpen(null)} wide>
          <dl className="reg-kv">
            <dt>Status</dt><dd>{STATUS_LABEL[open.status]}{open.reason ? `: ${open.reason}` : ''}</dd>
            <dt>Model</dt><dd>{open.provider} · {open.model} · prompt {open.prompt_version}</dd>
            <dt>Requested</dt><dd>{open.requested_by} · {fmtDateTime(open.created_at)}</dd>
            {open.decided_by && <><dt>Decided</dt><dd>{open.decided_by} · {fmtDateTime(open.decided_at)}</dd></>}
            {open.result_refs.length > 0 && <><dt>Wrote</dt><dd>{open.result_refs.map((r) => r.type.replace('_', ' ')).join(', ')}</dd></>}
          </dl>
          <h3 style={{ fontSize: '1rem' }}>Output</h3>
          <pre className="small" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: 'var(--bg)', padding: 8 }}>{JSON.stringify(open.output, null, 2)}</pre>
          <h3 style={{ fontSize: '1rem' }}>Citations</h3>
          {open.citations.length ? open.citations.map((c, n) => <Quote key={n} c={c} />) : <p className="small muted">None.</p>}
          <p className="small muted">{open.citations.map(citeText).filter(Boolean).length} source{open.citations.length === 1 ? '' : 's'} checked against the document text.</p>
        </Dialog>
      )}
    </div>
  );
}

/** The Chief Auditor's switch on the client page (rule 4), with the consent note, and the engagement summary. */
export function AIFeaturesCard({ engagementId }: { engagementId: string }) {
  const qc = useQueryClient();
  const sw = useAISwitch(engagementId);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const d = sw.data;
  if (!d || (!d.can_manage && !d.enabled)) return null;
  async function save(enabled: boolean) {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await api.put(`/engagements/${engagementId}/ai`, { enabled, consent_note: note }); await qc.invalidateQueries({ queryKey: ['ai-switch', engagementId] }); setEditing(false); }
    catch (e) { setErr(fieldErrors(e).consent_note ?? errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="AI features" actions={<Badge tone={d.enabled ? 'success' : 'muted'}>{d.enabled ? 'On' : 'Off'}</Badge>}>
      <p className="small" style={{ marginTop: 0 }}>{aiSwitchHelp.enabled}</p>
      {d.enabled ? <p className="small">Turned on by {d.enabled_by} on {fmtDateTime(d.enabled_at)}. Client consent: {d.consent_note}</p>
        : <p className="small muted">Off. The copilot and "Explain this question" are hidden for this engagement.</p>}
      {err && <Alert tone="danger">{err}</Alert>}
      {d.can_manage && !d.enabled && !editing && <Button onClick={() => setEditing(true)}>Turn on AI features</Button>}
      {d.can_manage && !d.enabled && editing && (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); save(true); }}>
          <TextArea label="Where the client consented" help={aiSwitchHelp.consent} value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          <div className="row" style={{ gap: 8 }}><Button type="button" onClick={() => setEditing(false)}>Cancel</Button><Button variant="primary" type="submit" disabled={busy}>Turn on</Button></div>
        </form>
      )}
      {d.enabled && <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {d.can_view_log && <Link className="btn" to={`/engagements/${engagementId}/ai-log`}>View AI interaction log</Link>}
        {d.can_manage && <Button disabled={busy} onClick={() => save(false)}>Turn off</Button>}
      </div>}
      {d.enabled && d.can_use_copilot && <EngagementSummary engagementId={engagementId} />}
    </Card>
  );
}

function EngagementSummary({ engagementId }: { engagementId: string }) {
  const [kind, setKind] = useState('engagement');
  const [s, setS] = useState<Interaction | null>(null);
  const [text, setText] = useState('');
  const [useInReport, setUseInReport] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function write() {
    if (busy) return;
    setBusy(true); setErr(null);
    try { const r = await api.post<Interaction>(`/engagements/${engagementId}/copilot/summary`, { kind }); setS(r); setText(r.output.summary ?? ''); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="stack-sm" style={{ marginTop: 12, borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
      <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 200 }}><SelectField label="Summary" help={copilotHelp.summaryKind} value={kind} options={[{ value: 'engagement', label: 'This engagement' }, { value: 'client', label: 'The client' }]} onChange={(e) => setKind(e.target.value)} /></div>
        <Button disabled={busy} onClick={write}>{busy ? 'Writing…' : 'Write a summary with the copilot'}</Button>
      </div>
      {err && <Alert tone="danger">{err}</Alert>}
      {s && <div className="cp-card">
        <div className="cp-head"><span className="small muted">Suggested summary · relies on {s.citations.map((c) => c.label).join(', ') || 'nothing cited'}</span><Badge tone={statusTone(s.status)}>{STATUS_LABEL[s.status]}</Badge></div>
        {s.status === 'suggested' ? <>
          <TextArea label="Summary text" help={copilotHelp.summaryEdit} value={text} onChange={(e) => setText(e.target.value)} rows={5} />
          <Checkbox label="Use it as the executive summary narrative of the report" help={copilotHelp.useInReport} checked={useInReport} onChange={(e) => setUseInReport(e.target.checked)} />
          <DecideRow i={s} body={{ use_in_report: useInReport, summary: text }} onDone={setS} />
        </> : <p style={{ margin: 0 }}>{s.output.summary}</p>}
        {s.status === 'unsupported' && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>The summary relies on records that do not exist. Write it again or write your own.</p>}
      </div>}
    </div>
  );
}
