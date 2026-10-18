import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate, fmtDateTime } from '@/components/ui';
import { SignPanel, type SignOffView } from '@/components/SignPanel';
import { SEV_TONE } from '@/screens/futran/FieldworkUseCase';

type Declaration = { kind: string; label: string; signed_by: string; signed_at: string; text: string; commitment: string | null; disputed_refs: string[] };
export type ReportRow = { id: string; version: string; version_label: string; status: string; created_at: string; docx_file_id: string | null; pdf_file_id: string | null; released_to_client_at: string | null; signed_at: string | null; declarations: Declaration[] };
type Roadmap = { id: string; ref: string; action: string; owner: string | null; priority: string; target_date: string | null; how_futran_can_help: string | null; finding_ids: string[]; finding_refs: string[] };
type Ratio = { category: string; group: string; selection_rate: number | null; impact_ratio: number };
type Summary = { ai_system_id: string | null; tool_name: string | null; audit_date: string | null; distribution_date: string | null; data_source: string | null; notes: string | null; unknown_category_count: number | null; impact_ratios: Ratio[]; evidence_file_ids: string[] };
type Data = {
  audit_ref: string; client: string; stage: number; my_name: string;
  reports: ReportRow[];
  narrative: { most_significant_finding_id: string | null; most_significant_text: string | null; strengths: string | null; immediate_actions: string | null; narrative: string | null };
  roadmap: Roadmap[];
  findings: { id: string; ref: string; title: string; severity: string; status: string }[];
  can_edit: boolean; can_generate: boolean;
  lead_review: { report_id: string | null; no_qa: boolean; lead_auditor_text: string; declarations: { kind: string; label: string; holders: string[]; signed_by: string | null; signed_at: string | null; can_sign: boolean }[] };
  release: { released: boolean; unmet: string[]; can_release: boolean };
  final: { sign_off: SignOffView | null; unmet: string[]; can_prepare: boolean };
  public_summary: { required: boolean; summary: Summary | null; text: string | null; sign_off: SignOffView | null; unmet: string[]; can_edit: boolean };
};

const PRIORITY = [{ value: 'critical', label: 'Critical' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }];
const REPORT_STATUS: Record<string, { label: string; tone: 'muted' | 'navy' | 'success' }> = { draft: { label: 'Futran only', tone: 'muted' }, released: { label: 'With the client', tone: 'navy' }, final: { label: 'Final', tone: 'success' } };
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/** Screen 18: the report workspace — executive summary, roadmap, versions, declarations, sign-offs 7 and 8. */
export function FinalReport() {
  const { clientId = '' } = useParams();
  const key = ['report', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/clients/${clientId}/report`) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string; list?: string[] } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await refresh(); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e), list: Object.values(fieldErrors(e)) }); }
  };
  const approved = d.findings.filter((f) => f.status === 'approved');
  return (
    <div className="page">
      <PageHeader title="Final report" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client} · ${d.audit_ref}` }, { label: 'Report' }]}
        subtitle={`Stage ${d.stage}. Draft v0.1 → lead review v0.2 → client v1.0 → final v1.1.`} />
      {msg && <Alert tone={msg.tone}>{msg.text}{msg.list && msg.list.length > 0 && <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{msg.list.map((m) => <li key={m}>{m}</li>)}</ul>}</Alert>}
      <div className="split" style={{ marginTop: 16 }}>
        <div className="main stack">
          <SummaryCard clientId={clientId} d={d} approved={approved} onSaved={() => { refresh(); setMsg({ tone: 'success', text: 'Executive summary saved.' }); }} />
          <RoadmapCard clientId={clientId} d={d} approved={approved} run={run} />
          <Card title="Report versions" actions={d.can_generate && <div className="row" style={{ gap: 8 }}>
            <Button size="sm" onClick={() => run(() => api.post(`/clients/${clientId}/report/generate`, { version: 'v0.1' }), 'Draft v0.1 generated.')}>Generate draft v0.1</Button>
            <Button size="sm" variant="primary" onClick={() => run(() => api.post(`/clients/${clientId}/report/generate`, { version: 'v0.2' }), 'Lead review v0.2 generated. It is ready for the declarations.')}>Generate lead review v0.2</Button>
          </div>}>
            {d.reports.length === 0 ? <EmptyState>No version generated yet.</EmptyState> : <ReportTable rows={d.reports} />}
          </Card>
          {d.public_summary.required && <PublicSummaryCard clientId={clientId} d={d} run={run} />}
        </div>
        <div className="side stack">
          <Card title="Declarations · lead review v0.2">
            <div className="stack">
              <blockquote className="statement small">{d.lead_review.lead_auditor_text}</blockquote>
              {!d.lead_review.report_id && <p className="small muted" style={{ margin: 0 }}>Generate the lead review version (v0.2) after sign-off 5. The declarations are signed on it.</p>}
              {d.lead_review.declarations.map((x) => <DeclarationRow key={x.kind} x={x} reportId={d.lead_review.report_id} myName={d.my_name} run={run} />)}
              {d.lead_review.no_qa && <p className="small muted" style={{ margin: 0 }}>No QA Reviewer assigned. The report records this.</p>}
              <hr />
              {d.release.released ? <Alert tone="success">The client draft (v1.0) has been released to the client.</Alert> : (
                <>
                  {d.release.unmet.length > 0 && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{d.release.unmet.map((m) => <li key={m}>{m}</li>)}</ul>}
                  <div><Button variant="primary" disabled={!d.release.can_release} onClick={() => run(() => api.post(`/clients/${clientId}/report/release`), 'The client draft (v1.0) is released. The client has been told.')}>Release client draft v1.0</Button></div>
                </>
              )}
            </div>
          </Card>
          <Card title="Sign-off 7 · Final report">
            <div className="stack">
              <p className="small muted" style={{ margin: 0 }}>Prepared by the auditor after sign-off 6. The Chief Auditor signs; the client then acknowledges receipt.</p>
              {d.final.sign_off && <SignPanel signOffId={d.final.sign_off.id} hideTitle onSigned={refresh} agreeText="I approve and issue the final report." />}
              {d.final.unmet.length > 0 && !d.final.sign_off && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{d.final.unmet.map((m) => <li key={m}>{m}</li>)}</ul>}
              {d.final.can_prepare && <div><Button variant="primary" onClick={() => run(() => api.post(`/clients/${clientId}/report/final`), 'Final report v1.1 prepared and sent to the Chief Auditor.')}>Prepare final v1.1 and send for signature</Button></div>}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function ReportTable({ rows }: { rows: ReportRow[] }) {
  return (
    <div className="table-wrap"><table className="table">
      <thead><tr><th>Version</th><th>Status</th><th>Created</th><th>Files</th><th>Declarations</th></tr></thead>
      <tbody>{rows.map((r) => {
        const st = REPORT_STATUS[r.status] ?? REPORT_STATUS.draft;
        return (
          <tr key={r.id}>
            <td><strong>{r.version_label}</strong></td>
            <td><Badge tone={st.tone}>{st.label}</Badge>{r.released_to_client_at && <div className="small muted">Released {fmtDate(r.released_to_client_at)}</div>}</td>
            <td>{fmtDateTime(r.created_at)}</td>
            <td>{r.pdf_file_id && <a href={fileUrl(r.pdf_file_id)}>PDF</a>}{r.docx_file_id && <> · <a href={fileUrl(r.docx_file_id)}>Word</a></>}</td>
            <td className="small">{r.declarations.length === 0 ? '—' : r.declarations.map((x) => `${x.label}: ${x.signed_by}`).join('; ')}</td>
          </tr>
        );
      })}</tbody>
    </table></div>
  );
}

function SummaryCard({ clientId, d, approved, onSaved }: { clientId: string; d: Data; approved: Data['findings']; onSaved: () => void }) {
  const [v, setV] = useState(d.narrative);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setV(d.narrative), [d.narrative]);
  const set = (k: keyof Data['narrative']) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const counts = ['critical', 'high', 'medium', 'low', 'observation'].map((s) => [s, approved.filter((f) => f.severity === s).length] as const);
  async function save() {
    setErr(null);
    try { await api.put(`/clients/${clientId}/report/summary`, v); onSaved(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card title="Executive summary">
      <div className="stack">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>{counts.map(([s, n]) => <Badge key={s} tone={SEV_TONE[s]}>{cap(s === 'observation' ? 'observations' : s)}: {n}</Badge>)}</div>
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Most significant finding" value={v.most_significant_finding_id ?? ''} disabled={!d.can_edit} onChange={set('most_significant_finding_id')}
          options={[{ value: '', label: 'Choose a finding' }, ...approved.map((f) => ({ value: f.id, label: `${f.ref} ${f.title}` }))]} />
        <TextArea label="Its potential impact" value={v.most_significant_text ?? ''} disabled={!d.can_edit} onChange={set('most_significant_text')} />
        <TextArea label="Greatest strengths observed" help="Required before the lead review version. Always include genuine positives." value={v.strengths ?? ''} disabled={!d.can_edit} onChange={set('strengths')} />
        <TextArea label="Immediate actions required (within 30 days)" help="Critical findings are listed automatically." value={v.immediate_actions ?? ''} disabled={!d.can_edit} onChange={set('immediate_actions')} />
        <TextArea label="Overall assessment" value={v.narrative ?? ''} disabled={!d.can_edit} onChange={set('narrative')} />
        {d.can_edit && <div><Button variant="primary" onClick={save}>Save executive summary</Button></div>}
        {!d.can_edit && d.release.released && <p className="small muted" style={{ margin: 0 }}>The executive summary is fixed: the client draft has been released.</p>}
      </div>
    </Card>
  );
}

const EMPTY_ITEM = { action: '', owner: '', priority: 'high', target_date: '', how_futran_can_help: '', finding_ids: [] as string[] };

function RoadmapCard({ clientId, d, approved, run }: { clientId: string; d: Data; approved: Data['findings']; run: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const [item, setItem] = useState(EMPTY_ITEM);
  const [adding, setAdding] = useState(false);
  const toggle = (id: string) => setItem({ ...item, finding_ids: item.finding_ids.includes(id) ? item.finding_ids.filter((x) => x !== id) : [...item.finding_ids, id] });
  return (
    <Card title="Remediation roadmap" actions={d.can_edit && !adding && <Button size="sm" onClick={() => setAdding(true)}>Add item</Button>}>
      <div className="stack">
        {d.roadmap.length === 0 ? <EmptyState>No roadmap items yet.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Ref</th><th>Recommended action</th><th>Owner</th><th>Priority</th><th>Target date</th><th>How Futran can help</th>{d.can_edit && <th />}</tr></thead>
            <tbody>{d.roadmap.map((r) => (
              <tr key={r.id}>
                <td style={{ whiteSpace: 'nowrap' }}>{r.ref}</td><td>{r.action}{r.finding_refs.length > 0 && <div className="small muted">{r.finding_refs.join(', ')}</div>}</td><td>{r.owner ?? '—'}</td>
                <td><Badge tone={SEV_TONE[r.priority]}>{cap(r.priority)}</Badge></td><td>{fmtDate(r.target_date)}</td><td>{r.how_futran_can_help ?? '—'}</td>
                {d.can_edit && <td><Button size="sm" variant="ghost" onClick={() => run(() => api.delete(`/roadmap-items/${r.id}`), `${r.ref} removed.`)}>Remove</Button></td>}
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {adding && (
          <div className="stack-sm">
            <TextArea label="Recommended action" value={item.action} onChange={(e) => setItem({ ...item, action: e.target.value })} />
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <TextField label="Responsible owner" value={item.owner} onChange={(e) => setItem({ ...item, owner: e.target.value })} />
              <SelectField label="Priority" value={item.priority} options={PRIORITY} onChange={(e) => setItem({ ...item, priority: e.target.value })} />
              <TextField label="Target date" type="date" value={item.target_date} onChange={(e) => setItem({ ...item, target_date: e.target.value })} />
            </div>
            <TextArea label="How Futran can help" value={item.how_futran_can_help} onChange={(e) => setItem({ ...item, how_futran_can_help: e.target.value })} />
            {approved.length > 0 && <fieldset className="small"><legend>Findings addressed</legend>{approved.map((f) => <label key={f.id} className="check"><input type="checkbox" checked={item.finding_ids.includes(f.id)} onChange={() => toggle(f.id)} /><span>{f.ref} {f.title}</span></label>)}</fieldset>}
            <div className="row" style={{ gap: 8 }}>
              <Button variant="primary" onClick={() => run(async () => { await api.post(`/clients/${clientId}/report/roadmap`, { ...item, target_date: item.target_date || null }); setItem(EMPTY_ITEM); setAdding(false); }, 'Roadmap item added.')}>Add to roadmap</Button>
              <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function DeclarationRow({ x, reportId, myName, run }: { x: Data['lead_review']['declarations'][number]; reportId: string | null; myName: string; run: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const [name, setName] = useState('');
  return (
    <div className="stack-sm">
      <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
        <span><strong>{x.label}</strong> <span className="small muted">{x.holders.join(', ') || 'Not on the team'}</span></span>
        {x.signed_by ? <Badge tone="success">Signed</Badge> : <Badge tone="warn">Not signed</Badge>}
      </div>
      {x.signed_by && <span className="small muted">{x.signed_by}, {fmtDateTime(x.signed_at)}</span>}
      {x.can_sign && reportId && (
        <div className="row" style={{ gap: 8, alignItems: 'flex-end' }}>
          <TextField label="Type your full name to sign" placeholder={myName} value={name} onChange={(e) => setName(e.target.value)} />
          <Button variant="primary" disabled={!name.trim()} onClick={() => run(() => api.post(`/reports/${reportId}/declarations`, { kind: x.kind, typed_name: name }), `${x.label} declaration signed.`)}>Sign</Button>
        </div>
      )}
    </div>
  );
}

function PublicSummaryCard({ clientId, d, run }: { clientId: string; d: Data; run: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const s = d.public_summary;
  const init = s.summary ?? { ai_system_id: null, tool_name: '', audit_date: '', distribution_date: '', data_source: '', notes: '', unknown_category_count: null, impact_ratios: [], evidence_file_ids: [] };
  const [v, setV] = useState<Summary>(init);
  const [ratios, setRatios] = useState<{ category: string; group: string; selection_rate: string; impact_ratio: string }[]>(init.impact_ratios.map((r) => ({ category: r.category, group: r.group, selection_rate: r.selection_rate == null ? '' : String(r.selection_rate), impact_ratio: String(r.impact_ratio) })));
  const so = s.sign_off;
  const save = () => run(() => api.put(`/clients/${clientId}/public-summary`, { ...v, impact_ratios: ratios.filter((r) => r.category || r.group || r.impact_ratio).map((r) => ({ ...r, selection_rate: r.selection_rate === '' ? null : r.selection_rate })) }), 'Public summary saved.');
  return (
    <Card title="Public summary · sign-off 8">
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>The employer publishes this summary. The Chief AI Compliance Officer approves the wording before release. Impact ratios are entered from the bias audit.</p>
        {s.can_edit ? (
          <>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <TextField label="Tool" value={v.tool_name ?? ''} onChange={(e) => setV({ ...v, tool_name: e.target.value })} />
              <TextField label="Audit date" type="date" value={v.audit_date ?? ''} onChange={(e) => setV({ ...v, audit_date: e.target.value })} />
              <TextField label="Distribution date" type="date" value={v.distribution_date ?? ''} onChange={(e) => setV({ ...v, distribution_date: e.target.value })} />
              <TextField label="Unknown category (count)" inputMode="numeric" value={v.unknown_category_count ?? ''} onChange={(e) => setV({ ...v, unknown_category_count: e.target.value === '' ? null : Number(e.target.value) })} />
            </div>
            <TextArea label="Data used" value={v.data_source ?? ''} onChange={(e) => setV({ ...v, data_source: e.target.value })} />
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Category</th><th>Group</th><th>Selection rate</th><th>Impact ratio</th><th /></tr></thead>
              <tbody>{ratios.map((r, i) => (
                <tr key={i}>
                  {(['category', 'group', 'selection_rate', 'impact_ratio'] as const).map((k) => <td key={k}><input className="input" aria-label={k.replace('_', ' ')} value={r[k]} onChange={(e) => setRatios(ratios.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x))} /></td>)}
                  <td><Button size="sm" variant="ghost" onClick={() => setRatios(ratios.filter((_, j) => j !== i))}>Remove</Button></td>
                </tr>
              ))}</tbody>
            </table></div>
            <div className="row" style={{ gap: 8 }}>
              <Button size="sm" onClick={() => setRatios([...ratios, { category: '', group: '', selection_rate: '', impact_ratio: '' }])}>Add impact ratio</Button>
              <Button variant="primary" onClick={save}>Save public summary</Button>
            </div>
            {s.unmet.length > 0 && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{s.unmet.map((m) => <li key={m}>{m}</li>)}</ul>}
            <div><Button disabled={s.unmet.length > 0} onClick={() => run(() => api.post(`/clients/${clientId}/signoffs/8/submit`, {}), 'Public summary sent to the CAICO for sign-off 8.')}>Send to the CAICO for sign-off 8</Button></div>
          </>
        ) : !so && s.text && <pre className="statement small" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{s.text}</pre>}
        {so && <SignPanel signOffId={so.id} hideTitle onSigned={() => undefined} />}
      </div>
    </Card>
  );
}
