import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { type BiasPage, type BiasRun, type GuardrailRun, pct, ratio } from '@/api/wsk';
import { biasHelp } from '@/help/wsk';
import './wsk.css';

const DIMS = [['race', 'Race/ethnicity'], ['sex', 'Sex'], ['intersectional', 'Intersectional']] as const;
const BAND: Record<string, string> = { low: 'Low', medium: 'Medium', high: 'High' };

/** Screen 29: bias test calculator for one audited AI system (NYC Local Law 144, 6 RCNY § 5-301). */
export function BiasTest() {
  const { systemId = '' } = useParams();
  const qc = useQueryClient();
  const key = ['bias', systemId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<BiasPage>(`/systems/${systemId}/bias-tests`) });
  const [runId, setRunId] = useState<string | null>(null);
  const [dim, setDim] = useState<(typeof DIMS)[number][0]>('race');
  const [upload, setUpload] = useState(false);
  const [summary, setSummary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'info'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const s = d.system;
  const run = d.runs.find((r) => r.id === runId) ?? d.runs[0];
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  async function act(path: string, done: (out: never) => string, body?: unknown) {
    if (busy) return;
    setBusy(true); setMsg(null);
    try { const out = await api.post<never>(path, body); setMsg({ tone: 'success', text: done(out) }); await refresh(); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
    finally { setBusy(false); }
  }
  return (
    <div className="page">
      <PageHeader title="Bias test: NYC Local Law 144"
        crumbs={[{ to: `/clients/${s.client_id}/systems`, label: 'AI systems' }, { to: `/systems/${s.id}/assess`, label: `${s.reference_id} ${s.name}` }, { label: 'Bias test' }]}
        subtitle={run ? `${run.method_label} method · ${run.dataset_filename ?? 'data file'} · ${run.validation.rows_valid.toLocaleString()} rows validated · ${run.library_version}` : `${s.client_name ?? ''} · ${s.audit_ref ?? ''}`}
        actions={d.can_run ? <>
          <Button onClick={() => setUpload(true)} variant={run ? 'default' : 'primary'}>{run ? 'Upload new data' : 'Upload data'}</Button>
          {run && d.public_summary_required && <Button variant="primary" disabled={busy || !run} onClick={() => run.excluded_categories.length ? setSummary(true) : void act(`/bias-tests/${run.id}/public-summary`, () => 'The public summary now shows this run’s tables and unknown count.', {})}>Use in public summary</Button>}
        </> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!run ? (
        <Card><EmptyState>No bias test has been run on this system. Upload the applicant or employee data the tool assessed, or use a file the client uploaded to the engagement.</EmptyState></Card>
      ) : (
        <>
          {d.runs.length > 1 && (
            <div style={{ maxWidth: 420, marginBottom: 12 }}>
              <SelectField label="Run" value={run.id} onChange={(e) => setRunId(e.target.value)} options={d.runs.map((r) => ({ value: r.id, label: `${fmtDateTime(r.run_at)} · ${r.dataset_filename ?? ''} · ${r.method_label}` }))} />
            </div>
          )}
          <Tiles run={run} />
          <div className="split" style={{ marginTop: 18 }}>
            <section className="main stack">
              <Card title={`Impact ratios by ${DIMS.find(([k]) => k === dim)?.[1].toLowerCase()} (known categories only)`}>
                <div className="tabs" role="tablist" aria-label="Category">
                  {DIMS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={dim === k} className={dim === k ? 'active' : ''} onClick={() => setDim(k)}>{label}</button>)}
                </div>
                <CategoryTable run={run} dim={dim} />
              </Card>
              {run.validation.warnings.length > 0 && <Alert tone="info">{run.validation.warnings.join(' ')}</Alert>}
              <Guardrails systemId={s.id} canRun={d.can_run} />
            </section>
            <aside className="side stack">
              <Card title="What this run feeds">
                <ul className="feeds">
                  <li>§6.2.06 disparate impact ratio: <strong>{ratio(run.feeds.q_6_2_06)}</strong> (lowest{run.lowest ? `, ${run.lowest.label}` : ''})</li>
                  <li>§5.1a.03 unknown category: <strong>{run.feeds.q_5_1a_03 ?? '—'}%</strong> → proposed rating {BAND[run.feeds.q_5_1a_05 ?? ''] ?? '—'} (§5.1a.05)</li>
                  <li>{run.feeds.below_threshold.length ? `Draft finding: impact ratio below ${run.settings.threshold.toFixed(2)} for ${run.feeds.below_threshold.length} categor${run.feeds.below_threshold.length === 1 ? 'y' : 'ies'}` : `No category below ${run.settings.threshold.toFixed(2)}: no finding to draft`}</li>
                  <li>{d.public_summary_required ? `LL144 public summary tables and unknown count${run.public_summary_at ? ` (used ${fmtDate(run.public_summary_at)})` : ''}` : 'No public summary is required for this engagement'}</li>
                  <li>{s.register_system_id ? `Bias test on the client’s register${run.bias_test_id ? ' (recorded)' : ''}` : 'Not linked to a register system, so it cannot be recorded there'}</li>
                </ul>
                {d.can_run && (
                  <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                    <Button size="sm" disabled={busy} onClick={() => act(`/bias-tests/${run.id}/apply-answers`, (o: { applied: string[]; skipped: { code: string; reason: string }[] }) => `Recorded ${o.applied.join(', ') || 'no answers'}.${o.skipped.length ? ` Not recorded: ${o.skipped.map((x) => `${x.code} (${x.reason})`).join('; ')}` : ''}`)}>Record the answers</Button>
                    <Button size="sm" disabled={busy || run.feeds.draft_findings === 0} onClick={() => act(`/bias-tests/${run.id}/draft-findings`, (o: { created: string[] }) => o.created.length ? 'Draft finding created. It is in Findings for review.' : 'No new finding.')}>Create draft findings ({run.feeds.draft_findings})</Button>
                    {s.register_system_id && <Button size="sm" disabled={busy || !!run.bias_test_id} onClick={() => act(`/bias-tests/${run.id}/record`, () => 'Recorded as a bias test on the client’s register, with the history entry.')}>Record as bias test</Button>}
                  </div>
                )}
                {run.finding_ids.length > 0 && <p className="small" style={{ margin: 0 }}><Link to={`/clients/${s.client_id}/findings`}>Open the draft finding</Link></p>}
              </Card>
              <Card title="Data and retention">
                <p className="small" style={{ margin: 0 }}>Data stays in {s.client_name ?? 'the client'}’s tenant. {run.raw_deleted_at ? `The raw rows were deleted on ${fmtDate(run.raw_deleted_at)}; the results are kept.` : run.keep_raw_data ? 'The client chose to keep the raw rows.' : run.raw_delete_on ? `The raw rows are deleted on ${fmtDate(run.raw_delete_on)}, at the end of the retention period, unless the client chooses to keep them.` : 'The raw rows are deleted at the end of the engagement retention period unless the client chooses to keep them.'}</p>
                <p className="small muted" style={{ margin: 0 }}>Thresholds ({run.settings.threshold.toFixed(2)} impact ratio, {(run.settings.small_share * 100).toFixed(0)}% small-category share) come from the risk methodology. Run by {run.run_by ?? '—'} on {fmtDateTime(run.run_at)}.</p>
              </Card>
            </aside>
          </div>
        </>
      )}
      {upload && <UploadDialog page={d} onClose={() => setUpload(false)} onDone={async (r) => { setUpload(false); setRunId(r.id); setMsg({ tone: 'success', text: `Calculated on ${r.results.total.toLocaleString()} rows.` }); await refresh(); }} />}
      {summary && run && <JustifyDialog run={run} onClose={() => setSummary(false)} onDone={async () => { setSummary(false); setMsg({ tone: 'success', text: 'The public summary now shows this run’s tables, the excluded categories and your justification.' }); await refresh(); }} />}
    </div>
  );
}

function Tiles({ run }: { run: BiasRun }) {
  const below = run.feeds.below_threshold.length;
  const high = run.feeds.q_5_1a_05 === 'high';
  const r = run.results;
  return (
    <div className="grid-tiles">
      <div className="tile"><div className="label">Applicants</div><div className="value">{r.total.toLocaleString()}</div></div>
      <div className="tile"><div className="label">{run.method === 'scoring_rate' ? 'Scored above the median' : 'Selected'}</div><div className="value">{r.selected_total.toLocaleString()}</div><div className="hint">{pct(r.total ? r.selected_total / r.total : null)} overall{r.median !== null ? ` · median ${r.median}` : ''}</div></div>
      <div className={`tile${high ? ' tile-alert' : ''}`}><div className="label">Unknown sex or race/ethnicity</div><div className="value">{run.unknown_count.toLocaleString()}</div><div className="hint">{run.unknown_pct ?? 0}% of the data · null-compliance {BAND[run.feeds.q_5_1a_05 ?? ''] ?? '—'} (5.1a)</div></div>
      <div className="tile"><div className="label">Below {run.settings.threshold.toFixed(2)} impact ratio</div><div className="value">{below} {below === 1 ? 'category' : 'categories'}</div><div className="hint">Lowest {ratio(run.lowest?.impact_ratio)}{run.lowest ? ` · ${run.lowest.label}` : ''}</div></div>
    </div>
  );
}

function CategoryTable({ run, dim }: { run: BiasRun; dim: 'race' | 'sex' | 'intersectional' }) {
  const t = run.results.tables[dim];
  const scoring = run.method === 'scoring_rate';
  const labels = run.results.has_labels;
  return (
    <>
      <div className="table-wrap"><table className="table bias-table">
        <caption className="sr-only">{`${t.label} categories`}</caption>
        <thead><tr><th>Category</th><th className="num">Applicants</th><th className="num">{scoring ? 'Above median' : 'Selected'}</th><th className="num">{scoring ? 'Scoring rate' : 'Selection rate'}</th><th className="num">Impact ratio</th>{labels && <th className="num">Equal opportunity difference</th>}<th className="num">Parity difference</th></tr></thead>
        <tbody>
          {t.categories.map((c) => (
            <tr key={c.key} className={c.excluded ? 'muted' : undefined}>
              <td>{c.label}<div>{c.below_threshold ? <Badge tone="danger">Below {run.settings.threshold.toFixed(2)}</Badge> : c.excluded ? <Badge tone="muted">{`Under ${(run.settings.small_share * 100).toFixed(0)}% of data`}</Badge> : t.reference === c.key ? <Badge tone="navy">Most selected</Badge> : null}</div></td><td className="num">{c.applicants.toLocaleString()}</td><td className="num">{c.selected.toLocaleString()}</td><td className="num">{pct(c.rate)}</td>
              <td className="num">{c.excluded ? 'excluded' : ratio(c.impact_ratio)}</td>{labels && <td className="num">{ratio(c.equal_opportunity_difference)}</td>}<td className="num">{c.parity_difference === null ? '—' : `${(c.parity_difference * 100).toFixed(1)} pts`}</td>
            </tr>
          ))}
          <tr className="muted"><td>Unknown<div className="small">not in the calculation</div></td><td className="num">{t.unknown.toLocaleString()}</td><td className="num">{t.unknown_selected.toLocaleString()}</td><td className="num">{pct(t.unknown ? t.unknown_selected / t.unknown : null)}</td><td className="num">—</td>{labels && <td />}<td /></tr>
        </tbody>
      </table></div>
      {t.note && <Alert tone="info">{t.note}</Alert>}
      <p className="small muted" style={{ margin: 0 }}>Impact ratio = the category’s {scoring ? 'scoring' : 'selection'} rate ÷ the rate of the {scoring ? 'highest scoring' : 'most selected'} category (6 RCNY § 5-300). Categories other than Hispanic or Latino are not Hispanic or Latino.</p>
    </>
  );
}

function UploadDialog({ page, onClose, onDone }: { page: BiasPage; onClose: () => void; onDone: (r: BiasRun) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [method, setMethod] = useState('selection_rate');
  const [source, setSource] = useState('');
  const [fileId, setFileId] = useState('');
  const [exclude, setExclude] = useState(page.settings.exclude_small);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rows, setRows] = useState<{ row?: number; message: string }[]>([]);
  const fe = (e: unknown) => fieldErrors(e);
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit() {
    if (busy) return;
    const f = fileRef.current?.files?.[0];
    if (!f && !fileId) { setErrors({ file: 'Choose a CSV file or a file the client uploaded.' }); return; }
    const form = new FormData();
    if (f) form.append('file', f); else form.append('file_id', fileId);
    form.append('method', method); form.append('data_source', source); form.append('exclude_small', String(exclude));
    setBusy(true); setErr(null); setRows([]); setErrors({});
    try { onDone(await api.upload<BiasRun>(`/systems/${page.system.id}/bias-tests`, form)); }
    catch (e) {
      setErr(errorMessage(e)); setErrors(fe(e));
      const list = (e as { errors?: { row?: number; message: string; field: string }[] }).errors ?? [];
      setRows(list.filter((x) => x.row !== undefined));
    } finally { setBusy(false); }
  }
  return (
    <Dialog title="Upload applicant data" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {rows.length > 0 && (
          <div className="validation-list" role="region" aria-label="Validation report"><strong className="small">Validation report</strong>
            <ul className="small">{rows.slice(0, 50).map((r, i) => <li key={i}>{r.message}</li>)}</ul>{rows.length > 50 && <p className="small muted">{rows.length - 50} more not shown.</p>}</div>
        )}
        <TextField ref={fileRef} label="Data file (CSV)" help={biasHelp.file} type="file" accept=".csv,text/csv" disabled={busy || !!fileId} error={errors.file} onChange={() => setErrors({})} />
        {page.engagement_files.length > 0 && <SelectField label="Or use a file the client uploaded" help={biasHelp.existing} value={fileId} onChange={(e) => setFileId(e.target.value)} placeholder="None" error={errors.file_id}
          options={page.engagement_files.map((f) => ({ value: f.id, label: `${f.filename} (${fmtDate(f.uploaded_at)})` }))} />}
        <SelectField label="Method" help={biasHelp.method} value={method} onChange={(e) => setMethod(e.target.value)} error={errors.method}
          options={[{ value: 'selection_rate', label: 'Selection rate (the tool selects or classifies)' }, { value: 'scoring_rate', label: 'Scoring rate (the tool gives a score)' }]} />
        <TextArea label="Source and explanation of the data" help={biasHelp.dataSource} value={source} onChange={(e) => setSource(e.target.value)} rows={3} />
        <Checkbox label={`Exclude categories under ${(page.settings.small_share * 100).toFixed(0)}% of the data from the impact ratios`} help={biasHelp.excludeSmall} checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={submit}>{busy ? 'Calculating…' : 'Validate and calculate'}</Button></div>
      </div>
    </Dialog>
  );
}

function JustifyDialog({ run, onClose, onDone }: { run: BiasRun; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const excluded = (['sex', 'race', 'intersectional'] as const).flatMap((d) => run.results.tables[d].categories.filter((c) => c.excluded).map((c) => `${c.label} (${c.applicants})`));
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await api.post(`/bias-tests/${run.id}/public-summary`, { justification: text }); onDone(); }
    catch (e) { setErr(fieldErrors(e).justification ?? errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Use in public summary" onClose={onClose}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>These categories are excluded from the impact ratios: {excluded.join(', ')}. Their applicants and rates are published with your justification.</p>
        <TextArea label="Justification for the exclusion" help={biasHelp.justification} value={text} onChange={(e) => setText(e.target.value)} error={err ?? undefined} rows={3} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={save}>Use in public summary</Button></div>
      </div>
    </Dialog>
  );
}

function Guardrails({ systemId, canRun }: { systemId: string; canRun: boolean }) {
  const qc = useQueryClient();
  const key = ['guardrails', systemId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<{ runs: GuardrailRun[]; prompt_set_version: string }>(`/systems/${systemId}/guardrail-tests`) });
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const runs = q.data?.runs ?? [];
  const last = runs[0];
  async function go(path: string, body: unknown) {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await api.post(path, body); setNote(''); await qc.invalidateQueries({ queryKey: key }); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="GenAI guardrail tests" actions={<span className="small muted">Prompt set {q.data?.prompt_set_version ?? ''} · sandbox adapter</span>}>
      <p className="small" style={{ margin: 0 }}>Prompt injection, jailbreak, data leakage, harmful output and PII echo prompts. Runs use the in-platform sandbox; a live run against the client’s endpoint needs the platform setting and the client’s written permission. Results are suggestions for §8.1.05 and checklist 8.4 until accepted.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      {canRun && <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}><div style={{ flex: '1 1 240px' }}><TextField label="System under test" help={biasHelp.endpointLabel} value={label} onChange={(e) => setLabel(e.target.value)} /></div><Button disabled={busy} onClick={() => go(`/systems/${systemId}/guardrail-tests`, { endpoint_label: label })}>Run the prompt set</Button></div>}
      {last && (
        <>
          <p className="small" style={{ margin: 0 }}><strong>{last.suggestion.text}</strong> {last.endpoint_label ? `${last.endpoint_label} · ` : ''}{fmtDateTime(last.run_at)} · <Badge tone={last.status === 'accepted' ? 'success' : last.status === 'rejected' ? 'muted' : 'warn'}>{last.status === 'suggested' ? 'Suggestion' : last.status === 'accepted' ? 'Accepted' : 'Rejected'}</Badge></p>
          <div className="table-wrap"><table className="table"><thead><tr><th>Prompt</th><th>Category</th><th>Result</th><th>Why</th></tr></thead>
            <tbody>{last.results.map((r) => <tr key={r.id}><td>{r.id} {r.title}</td><td className="small">{r.category.replace('_', ' ')}</td><td>{r.passed ? <Badge tone="success">Passed</Badge> : <Badge tone="danger">Failed</Badge>}</td><td className="small">{r.reason}</td></tr>)}</tbody></table></div>
          {canRun && last.status === 'suggested' && (
            <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 240px' }}><TextField label="Note" help={biasHelp.decisionNote} value={note} onChange={(e) => setNote(e.target.value)} /></div>
              <Button variant="primary" disabled={busy} onClick={() => go(`/guardrail-tests/${last.id}/decision`, { decision: 'accept', note })}>Accept results</Button>
              <Button disabled={busy} onClick={() => go(`/guardrail-tests/${last.id}/decision`, { decision: 'reject', note })}>Reject</Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
