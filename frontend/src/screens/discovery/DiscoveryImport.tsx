import { useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { importBase, useImportPage, type Analysis, type ExportTypeRow, type ImportPage, type ImportRow, type ImportTool } from '@/api/discoveryImport';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDateTime } from '@/components/ui';
import './discovery.css';

const STEPS = ['Export type', 'Upload', 'Map columns', 'Review tools'];
const STATUS: Record<string, { tone: 'warn' | 'success' | 'muted'; label: string }> = {
  new: { tone: 'warn', label: 'New' }, confirmed: { tone: 'success', label: 'In inventory' }, mapped: { tone: 'success', label: 'Mapped' }, dismissed: { tone: 'muted', label: 'Dismissed' },
};

/** G-05 Discovery import. `/e/:engagementId/discovery/import` for the Futran auditor on the engagement; `/integrations/import`
 *  for the Client Admin. Standard admin exports become discovered tools (signal "manual import") with the usual
 *  confirm / dismiss flow; each file is kept as an evidence item with its SHA-256. */
export function DiscoveryImport() {
  const { engagementId } = useParams();
  const q = useImportPage(engagementId);
  const qc = useQueryClient();
  const base = importBase(engagementId);
  const [step, setStep] = useState(0);
  const [typeKey, setTypeKey] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [presetName, setPresetName] = useState('');
  const [err, setErr] = useState<{ text: string; fields: Record<string, string> } | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissing, setDismissing] = useState<ImportTool | null>(null);
  const [matching, setMatching] = useState<{ imp: ImportRow; index: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const d = q.data;
  const et = d?.export_types.find((t) => t.value === typeKey);
  const presets = useMemo(() => (d?.presets ?? []).filter((p) => p.export_type === typeKey), [d, typeKey]);

  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!d) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;

  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr({ text: errorMessage(e), fields: fieldErrors(e) }); } finally { setBusy(false); }
  };
  const form = (m: Record<string, string> | null, presetId?: string) => {
    const f = new FormData();
    f.append('export_type', typeKey);
    if (m) f.append('mapping', JSON.stringify(m));
    if (presetId) f.append('preset_id', presetId);
    if (file) f.append('file', file);
    return f;
  };
  const analyse = (m: Record<string, string> | null, next: number, presetId?: string) => run(async () => {
    const a = await api.upload<Analysis>(`${base}/import/analyse`, form(m, presetId));
    setAnalysis(a); setMapping(a.mapping); setStep(next);
  });
  const commit = () => run(async () => {
    const f = form(mapping);
    if (presetName.trim()) f.append('save_preset', presetName.trim());
    const r = await api.upload<ImportRow>(`${base}/imports`, f);
    setFlash(`Imported ${r.filename}: ${r.rows_matched} of ${r.rows_read} rows matched, ${r.tools_found} AI tool and department pair${r.tools_found === 1 ? '' : 's'}. Stored as evidence with SHA-256 ${r.sha256.slice(0, 12)}…`);
    setStep(0); setTypeKey(''); setFile(null); setAnalysis(null); setMapping({}); setPresetName('');
    await qc.invalidateQueries({ queryKey: ['discovery-import'] });
  });
  const decide = (t: ImportTool) => run(async () => {
    if (engagementId) await api.post(`${base}/tools/${t.id}/confirm`);
    else await api.post(`/discovered-tools/${t.id}/confirm`);
    setFlash(`${t.product} confirmed and added to the client's AI inventory.`);
    await qc.invalidateQueries({ queryKey: ['discovery-import'] });
  });

  const crumbs = d.engagement ? [{ to: `/clients/${d.engagement.client_id}`, label: d.engagement.client_name }, { label: 'Discovery import' }]
    : [{ to: '/integrations', label: 'Integrations' }, { label: 'Import an admin export' }];
  const evidenceCount = d.imports.filter((i) => i.evidence_file_id).length;
  const matched = d.imports.reduce((a, i) => a + i.rows_matched, 0);
  const read = d.imports.reduce((a, i) => a + i.rows_read, 0);
  const findings = collectFindings(d);

  return (
    <div className="page dsc-page">
      <PageHeader crumbs={crumbs} title="Discovery import"
        subtitle={<>{d.engagement ? <>{d.engagement.client_name} · {d.engagement.name}{d.engagement.audit_ref ? ` · ${d.engagement.audit_ref}` : ''}<br /></> : null}
          Manual bridge until automatic connectors ship. Same discovered-tools flow, signal “manual import”.</>} />
      {flash && <Alert tone="success">{flash}</Alert>}

      <section className="card" aria-labelledby="dimp-steps-h">
        <div className="card-header"><h2 id="dimp-steps-h">Import an admin export</h2></div>
        <div className="card-body stack">
          <ol className="dimp-steps" aria-label="Import steps">
            {STEPS.map((s, i) => <li key={s} className={i === step ? 'current' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}><span>{i + 1}</span>{s}</li>)}
          </ol>
          {err && <Alert tone="danger">{err.text}{Object.values(err.fields).length > 0 && <ul className="dimp-errs">{Object.values(err.fields).map((m) => <li key={m}>{m}</li>)}</ul>}</Alert>}

          {step === 0 && (
            <fieldset className="dimp-types">
              <legend className="small muted">Choose the export you have. Expense and proxy files keep only a summary of the AI rows; every other file is kept as it is.</legend>
              {d.export_types.map((t) => (
                <label key={t.value} className={`dimp-type${typeKey === t.value ? ' on' : ''}`}>
                  <input type="radio" name="export_type" value={t.value} checked={typeKey === t.value} onChange={() => setTypeKey(t.value)} />
                  <span className="stack-xs"><strong>{t.label}</strong><span className="small muted">{t.source} · {t.parsed_into}</span></span>
                </label>
              ))}
              <div className="row"><Button variant="primary" disabled={!typeKey} onClick={() => setStep(1)}>Next: upload</Button></div>
            </fieldset>
          )}

          {step === 1 && et && (
            <div className="stack">
              <p style={{ margin: 0 }}><strong>{et.label}</strong> <span className="muted small">from {et.source}</span></p>
              <label className="field"><span className="label">File (CSV or Excel .xlsx) *</span>
                <input ref={inputRef} type="file" accept=".csv,.txt,.xlsx" aria-label="Export file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
              {presets.length > 0 && <p className="small muted" style={{ margin: 0 }}>Saved mappings for this export: {presets.map((p) => p.name).join(', ')}. Choose one on the next step.</p>}
              <div className="row"><Button onClick={() => setStep(0)}>Back</Button><Button variant="primary" disabled={!file || busy} onClick={() => analyse(null, 2)}>{busy ? 'Reading…' : 'Next: map columns'}</Button></div>
            </div>
          )}

          {step === 2 && et && analysis && (
            <MapStep et={et} a={analysis} mapping={mapping} setMapping={setMapping} presets={presets} fieldErr={err?.fields ?? {}}
              presetName={presetName} setPresetName={setPresetName} busy={busy}
              onPreset={(id) => analyse(null, 2, id)} onBack={() => setStep(1)} onNext={() => analyse(mapping, 3)} />
          )}

          {step === 3 && et && analysis && (
            <ReviewStep et={et} a={analysis} busy={busy} onBack={() => setStep(2)} onImport={commit} />
          )}
        </div>
      </section>

      <div className="dimp-kpis">
        <Card title="Files imported"><p className="small" style={{ margin: 0 }}>{d.imports.length ? d.imports.map((i) => `${i.export_label} (${i.filename.endsWith('.xlsx') ? 'Excel' : 'CSV'})`).join(' · ') : 'None yet'}</p></Card>
        <Card title="Evidence"><p className="small" style={{ margin: 0 }}>{evidenceCount} file{evidenceCount === 1 ? '' : 's'} stored with SHA-256</p></Card>
        <Card title="Vendor dictionary"><p className="small" style={{ margin: 0 }}>Matched {matched.toLocaleString()} of {read.toLocaleString()} rows</p></Card>
      </div>

      <ToolsTable d={d} busy={busy} onConfirm={decide} onDismiss={setDismissing} onMatch={(imp, index) => setMatching({ imp, index })} />

      {d.engagement && <section className="card" aria-labelledby="dimp-opp-h">
        <div className="card-header"><h2 id="dimp-opp-h">Opportunities raised for Sales (after the finding is final)</h2></div>
        <div className="card-body">
          {findings.length === 0 ? <EmptyState>No findings for Sales yet. Copilot licences, agents, undeclared paid AI tools and EU-scoped high-risk tools are raised here.</EmptyState> : (
            <ul className="dimp-findings">
              {findings.map((f) => (
                <li key={f.key}><span>{f.label} → <strong>{f.service}</strong></span>
                  {f.opportunity_id ? <Badge tone="success">Raised</Badge> : <Badge tone="muted">Raised when one of its tools is confirmed</Badge>}</li>
              ))}
            </ul>
          )}
        </div>
      </section>}

      <ImportsLog imports={d.imports} />
      {dismissing && <DismissDialog t={dismissing} base={base} futran={!!engagementId} onClose={() => setDismissing(null)} onDone={async (m) => { setDismissing(null); setFlash(m); await qc.invalidateQueries({ queryKey: ['discovery-import'] }); }} />}
      {matching && <MatchDialog d={d} base={base} {...matching} onClose={() => setMatching(null)} onDone={async (m) => { setMatching(null); setFlash(m); await qc.invalidateQueries({ queryKey: ['discovery-import'] }); }} />}
      {!engagementId && <p className="small muted">Back to <Link to="/integrations">Integrations and AI discovery</Link>.</p>}
    </div>
  );
}

function collectFindings(d: ImportPage) {
  const by = new Map<string, { key: string; label: string; service: string; opportunity_id: string | null }>();
  for (const i of [...d.imports].reverse()) for (const f of i.findings ?? []) by.set(f.key, { key: f.key, label: f.label, service: f.service, opportunity_id: f.opportunity_id ?? by.get(f.key)?.opportunity_id ?? null });
  return [...by.values()];
}

function MapStep({ et, a, mapping, setMapping, presets, fieldErr, presetName, setPresetName, busy, onPreset, onBack, onNext }: {
  et: ExportTypeRow; a: Analysis; mapping: Record<string, string>; setMapping: (m: Record<string, string>) => void; presets: { id: string; name: string }[];
  fieldErr: Record<string, string>; presetName: string; setPresetName: (v: string) => void; busy: boolean; onPreset: (id: string) => void; onBack: () => void; onNext: () => void;
}) {
  const options = [{ value: '', label: 'Not in this file' }, ...a.headers.filter(Boolean).map((h) => ({ value: h, label: h }))];
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>{a.filename}: {a.rows_read.toLocaleString()} rows, {a.headers.length} columns. The columns were matched from their headings; check each one.</p>
      {presets.length > 0 && <SelectField label="Use a saved mapping" value="" placeholder="Choose a saved mapping" options={presets.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => e.target.value && onPreset(e.target.value)} />}
      <div className="dimp-map">
        {et.fields.map((f) => (
          <SelectField key={f.key} label={`${f.label}${f.required ? ' *' : ''}`} value={mapping[f.key] ?? ''} options={options} error={fieldErr[`mapping.${f.key}`]}
            onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })} />
        ))}
      </div>
      <TextField label="Save this mapping as (optional)" hint="Saved mappings are offered the next time this export type is imported." value={presetName} onChange={(e) => setPresetName(e.target.value)} />
      <div className="row"><Button onClick={onBack}>Back</Button><Button variant="primary" disabled={busy} onClick={onNext}>{busy ? 'Reading…' : 'Next: preview'}</Button></div>
    </div>
  );
}

function ReviewStep({ et, a, busy, onBack, onImport }: { et: ExportTypeRow; a: Analysis; busy: boolean; onBack: () => void; onImport: () => void }) {
  return (
    <div className="stack">
      <p style={{ margin: 0 }}><strong>Vendor dictionary:</strong> matched {a.rows_matched.toLocaleString()} of {a.rows_read.toLocaleString()} rows · {a.tools.length} AI tool and department pair{a.tools.length === 1 ? '' : 's'}
        {a.unmatched.length > 0 && <> · {a.unmatched.length} unmatched row{a.unmatched.length === 1 ? '' : 's'} that look like AI tools</>}
        {a.summary_only && a.unmatched_count > 0 && <> · {a.unmatched_count.toLocaleString()} other row{a.unmatched_count === 1 ? '' : 's'} not kept or shown</>}</p>
      {!a.attestation_exists && <Alert tone="warn">No attestation has been run for this client yet, so every tool counts as undeclared.</Alert>}
      <div className="table-wrap"><table className="table" aria-label="Tools this file will add">
        <thead><tr><th>Tool found</th><th>Vendor</th><th>Department</th><th className="num">Users</th><th>Detail</th><th>Declared in attestation?</th></tr></thead>
        <tbody>
          {a.tools.map((t) => <tr key={`${t.vendor_key}|${t.department}`}><td><strong>{t.product}</strong><div className="small muted">{t.category}</div></td><td>{t.vendor}</td><td>{t.department}</td><td className="num">{t.user_count}</td><td className="small">{t.detail ?? '—'}</td>
            <td>{t.declared ? 'Yes' : <Badge tone="danger">No · undeclared</Badge>}</td></tr>)}
          {a.unmatched.map((u) => <tr key={`u|${u.name}|${u.department}`}><td><Badge tone="muted">Unmatched</Badge> “{u.name}”</td><td>Unknown</td><td>{u.department ?? '—'}</td><td className="num">{u.user_count}</td><td className="small">Match it after the import</td><td>—</td></tr>)}
          {a.tools.length === 0 && a.unmatched.length === 0 && <tr><td colSpan={6} className="muted">No AI tools in this file. Check the column mapping.</td></tr>}
        </tbody>
      </table></div>
      <details><summary className="small">{a.summary_only ? `First ${a.preview.length} matched rows as read` : `First ${a.preview.length} rows as read`}</summary>
        <div className="table-wrap"><table className="table" aria-label="Rows as read">
          <thead><tr>{et.fields.map((f) => <th key={f.key}>{f.label}</th>)}<th>Matched to</th></tr></thead>
          <tbody>{a.preview.map((r, i) => <tr key={i}>{et.fields.map((f) => <td key={f.key} className="small">{r.cells[f.key] || '—'}</td>)}<td className="small">{r.match ?? <span className="muted">No match</span>}</td></tr>)}</tbody>
        </table></div>
      </details>
      <p className="small muted" style={{ margin: 0 }}>{a.summary_only ? 'Only a summary of the AI rows is kept as evidence (no names, no other spending or browsing); ' : 'The file is kept as an evidence item; '}
        the SHA-256 of the file as uploaded is {a.sha256.slice(0, 16)}…</p>
      <div className="row"><Button onClick={onBack}>Back</Button><Button variant="primary" disabled={busy} onClick={onImport}>{busy ? 'Importing…' : 'Import and keep as evidence'}</Button></div>
    </div>
  );
}

function ToolsTable({ d, busy, onConfirm, onDismiss, onMatch }: { d: ImportPage; busy: boolean; onConfirm: (t: ImportTool) => void; onDismiss: (t: ImportTool) => void; onMatch: (imp: ImportRow, i: number) => void }) {
  const unmatched = d.imports.flatMap((imp) => imp.unmatched.map((u, i) => ({ imp, i, u }))).filter((x) => !x.u.matched_tool_id);
  return (
    <section className="card" aria-labelledby="dimp-tools-h">
      <div className="card-header"><h2 id="dimp-tools-h">Discovered tools from imports · {d.tools.length}</h2></div>
      <div className="card-body">
        {d.tools.length === 0 && unmatched.length === 0 ? <EmptyState>No tools imported yet.</EmptyState> : (
          <div className="table-wrap"><table className="table" aria-label="Discovered tools from imports">
            <thead><tr><th>Tool found</th><th>Vendor</th><th>Signal</th><th>Department</th><th className="num">Users</th><th>Declared in attestation?</th><th>Action</th></tr></thead>
            <tbody>
              {d.tools.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.product}</strong><div className="small muted">{t.category}</div></td><td>{t.vendor}</td><td className="small">{t.signal_label}</td><td>{t.department}</td><td className="num">{t.user_count}</td>
                  <td>{t.declared ? 'Yes' : <Badge tone={t.status === 'dismissed' ? 'muted' : 'danger'}>No · undeclared</Badge>}</td>
                  <td>{t.status === 'new' && d.can_decide
                    ? <div className="row dsc-decide"><Button size="sm" variant="primary" disabled={busy} onClick={() => onConfirm(t)} aria-label={`Confirm ${t.product}, ${t.department}`}>Confirm</Button><Button size="sm" onClick={() => onDismiss(t)} aria-label={`Dismiss ${t.product}, ${t.department}`}>Dismiss</Button></div>
                    : <span className="stack-xs"><Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge>{t.dismiss_reason && <span className="small muted dsc-clamp">{t.dismiss_reason}</span>}</span>}</td>
                </tr>
              ))}
              {unmatched.map(({ imp, i, u }) => (
                <tr key={`${imp.id}-${i}`}><td><Badge tone="muted">Unmatched</Badge> “{u.name}”</td><td>Unknown</td><td className="small">Manual import · {imp.export_label}</td><td>{u.department ?? '—'}</td><td className="num">{u.user_count}</td><td>—</td>
                  <td>{d.can_decide ? <Button size="sm" onClick={() => onMatch(imp, i)}>Match vendor</Button> : '—'}</td></tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </section>
  );
}

function ImportsLog({ imports }: { imports: ImportRow[] }) {
  if (!imports.length) return null;
  return (
    <section className="card" aria-labelledby="dimp-log-h">
      <div className="card-header"><h2 id="dimp-log-h">Import log and evidence</h2></div>
      <div className="card-body"><div className="table-wrap"><table className="table" aria-label="Import log">
        <thead><tr><th>When</th><th>Export</th><th>File</th><th>Rows matched</th><th>SHA-256</th><th>Evidence</th><th>By</th></tr></thead>
        <tbody>{imports.map((i) => (
          <tr key={i.id}><td className="small">{fmtDateTime(i.imported_at)}</td><td>{i.export_label}</td><td className="small">{i.filename}</td><td>{i.rows_matched} of {i.rows_read}</td>
            <td><code className="small dimp-hash" title={i.sha256}>{i.sha256.slice(0, 16)}…</code></td>
            <td className="small">{i.evidence_file_id ? <a href={fileUrl(i.evidence_file_id)}>{i.summary_only ? 'AI rows summary' : 'File'}</a> : '—'}</td><td className="small">{i.imported_by ?? '—'}</td></tr>
        ))}</tbody>
      </table></div></div>
    </section>
  );
}

function DismissDialog({ t, base, futran, onClose, onDone }: { t: ImportTool; base: string; futran: boolean; onClose: () => void; onDone: (m: string) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title={`Dismiss ${t.product}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Reason *" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} hint="Say why this is not an AI tool the client's people use for work." />
        <div className="row"><Button variant="danger" onClick={async () => {
          try { await api.post(futran ? `${base}/tools/${t.id}/dismiss` : `/discovered-tools/${t.id}/dismiss`, { reason }); onDone(`${t.product} dismissed.`); } catch (e) { setErr(errorMessage(e)); }
        }}>Dismiss</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function MatchDialog({ d, base, imp, index, onClose, onDone }: { d: ImportPage; base: string; imp: ImportRow; index: number; onClose: () => void; onDone: (m: string) => void }) {
  const u = imp.unmatched[index];
  const [vendorKey, setVendorKey] = useState('');
  const [vendor, setVendor] = useState('');
  const [product, setProduct] = useState(u.name);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title={`Match “${u.name}”`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="AI product from the vendor dictionary" value={vendorKey} placeholder="Not in the dictionary" options={d.vendors.map((v) => ({ value: v.key, label: v.label }))} onChange={(e) => setVendorKey(e.target.value)} />
        {!vendorKey && <div className="grid-2"><TextField label="Vendor *" value={vendor} onChange={(e) => setVendor(e.target.value)} /><TextField label="Product *" value={product} onChange={(e) => setProduct(e.target.value)} /></div>}
        <div className="row"><Button variant="primary" onClick={async () => {
          try {
            await api.post(`${base}/imports/${imp.id}/unmatched/${index}/match`, vendorKey ? { vendor_key: vendorKey } : { vendor, product });
            onDone(`“${u.name}” matched and added to the discovered tools.`);
          } catch (e) { setErr(errorMessage(e)); }
        }}>Match</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
