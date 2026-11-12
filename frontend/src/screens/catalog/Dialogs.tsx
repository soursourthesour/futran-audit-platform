import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, errorMessage, fieldErrors } from '@/api/client';
import type { Change, Grid, ImportPreview, Suggestion } from '@/api/catalog';
import { Alert, Badge, Button, Checkbox, Dialog, fmtDate, fmtDateTime, Loading, SelectField, TextArea, TextField } from '@/components/ui';

const errText = (e: unknown) => (e instanceof ApiError && e.errors.length ? e.errors.map((x) => x.message).join(' ') : errorMessage(e));
const isWarningOnly = (e: unknown) => e instanceof ApiError && e.status === 422 && e.errors.length > 0 && e.errors.every((x) => (x as { kind?: string }).kind === 'warning');

export function ConfirmWarnings({ warnings, onCancel, onConfirm }: { warnings: { message: string }[]; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog title="Check these changes" onClose={onCancel}>
      <ul className="stack-sm">{warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
      <p className="muted small">Save anyway if these are intended.</p>
      <div className="row"><Button variant="primary" onClick={onConfirm}>Save anyway</Button><Button onClick={onCancel}>Go back</Button></div>
    </Dialog>
  );
}

/** A value in the history: long text (deliverables, descriptions, notes) shows its start and opens in full. */
function Val({ text }: { text: string }) {
  if (!text) return <>—</>;
  if (text.length <= 90) return <>{text}</>;
  return <details><summary>{text.slice(0, 70).replace(/\s+\S*$/, '')}…</summary><div className="pre small">{text}</div></details>;
}

function ChangeTable({ rows, showCode }: { rows: Change[]; showCode?: boolean }) {
  if (!rows.length) return <p className="muted">No changes.</p>;
  return (
    <div className="table-scroll">
      <table className="table compact">
        <thead><tr><th>Version</th><th>When</th>{showCode && <th>Code</th>}<th>Field</th><th>Old value</th><th>New value</th><th>Reason</th><th>By</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>v{r.version}</td><td className="nowrap">{fmtDateTime(r.at)}</td>{showCode && <td><strong>{r.code}</strong></td>}
              <td>{r.field === 'created' ? 'Item added' : r.label}</td>
              <td className="clip"><Val text={r.field === 'created' ? '' : r.old_display} /></td><td className="clip"><Val text={r.new_display} /></td>
              <td>{r.reason}</td><td>{r.by}{r.confirmed_by && <span className="small muted block">Confirmed by {r.confirmed_by}</span>}</td>
              <td>{r.status === 'applied' ? 'Applied' : r.status === 'pending' ? `From ${fmtDate(r.effective_from)}` : r.status === 'awaiting_check' ? 'Second check' : 'Not applied'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['catalog-history', code], queryFn: () => api.get<{ items: Change[] }>(`/catalog/items/${code}/history`) });
  return (
    <Dialog title={`History · ${code}`} onClose={onClose} large>
      {q.data ? <ChangeTable rows={q.data.items} /> : <Loading />}
    </Dialog>
  );
}

export function ChangeLogDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ code: '', user_id: '', version: '', field: '', since: '', q: '' });
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const q = useQuery({ queryKey: ['catalog-log', qs], queryFn: () => api.get<{ items: Change[]; people: { id: string; name: string }[]; versions: { version: number; reason: string }[] }>(`/catalog/changes${qs ? `?${qs}` : ''}`) });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog title="Change log" onClose={onClose} large>
      <div className="catalog-filters">
        <label className="field-inline">Code<input value={f.code} onChange={set('code')} aria-label="Filter by code" placeholder="A-02b" /></label>
        <label className="field-inline">Person<select value={f.user_id} onChange={set('user_id')} aria-label="Filter by person"><option value="">Anyone</option>{q.data?.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="field-inline">Version<select value={f.version} onChange={set('version')} aria-label="Filter by version"><option value="">All</option>{q.data?.versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}</select></label>
        <label className="field-inline">Since<input type="date" value={f.since} onChange={set('since')} aria-label="Changed since" /></label>
        <label className="field-inline">Search<input type="search" value={f.q} onChange={set('q')} aria-label="Search the change log" /></label>
        <a className="btn" href={`/api/v1/catalog/changes/export.xlsx${qs ? `?${qs}` : ''}`} download>Export Excel</a>
      </div>
      {q.data ? <ChangeTable rows={q.data.items} showCode /> : <Loading />}
    </Dialog>
  );
}

export function AddItemDialog({ g, onClose, onDone }: { g: Grid; onClose: () => void; onDone: (t: string, code: string) => void }) {
  const [v, setV] = useState<Record<string, string>>({ code: '', product: g.enums.products[0], name: '', billing: 'one_time', pricing_unit: '', basis: '$', periods_per_year: '1', low: '', list_price: '', high: '', deliverables: '', description: '', reason: '' });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState('');
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  async function submit() {
    const body: Record<string, unknown> = Object.fromEntries(Object.entries(v).filter(([k, x]) => x !== '' || ['code', 'name', 'reason'].includes(k)));
    try {
      const it = await api.post<{ code: string }>('/catalog/items', body);
      onDone(`${it.code} added as Proposed and available. Review it in the side panel.`, it.code);
    } catch (e) { setErrs(fieldErrors(e)); setErr(errText(e)); }
  }
  return (
    <Dialog title="Add item" onClose={onClose} large>
      <p className="small muted">New items start as Proposed and available. Codes look like XX-00 with an optional letter, and must be unique.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="form-grid">
        <TextField label="Code" value={v.code} onChange={set('code')} error={errs.code} placeholder="A-15" />
        <SelectField label="Product" value={v.product} onChange={set('product')} options={g.enums.products.map((p) => ({ value: p, label: p }))} error={errs.product} />
        <TextField label="Line item" value={v.name} onChange={set('name')} error={errs.name} />
        <SelectField label="Billing" value={v.billing} onChange={set('billing')} options={Object.entries(g.enums.billing).map(([value, label]) => ({ value, label }))} />
        <TextField label="Pricing unit" value={v.pricing_unit} onChange={set('pricing_unit')} placeholder="per source" />
        <SelectField label="Basis" value={v.basis} onChange={set('basis')} options={[{ value: '$', label: '$' }, { value: '%', label: '%' }]} />
        <TextField label="Periods per year" value={v.periods_per_year} onChange={set('periods_per_year')} inputMode="numeric" error={errs.periods_per_year} />
        <TextField label="Low" value={v.low} onChange={set('low')} inputMode="decimal" error={errs.low} />
        <TextField label="List" value={v.list_price} onChange={set('list_price')} inputMode="decimal" error={errs.list_price} />
        <TextField label="High" value={v.high} onChange={set('high')} inputMode="decimal" error={errs.high} />
      </div>
      <TextArea label="Deliverables — what the client gets" rows={5} value={v.deliverables} onChange={set('deliverables')} />
      <TextField label="Short proposal description" value={v.description} onChange={set('description')} />
      <TextField label="Reason" value={v.reason} onChange={set('reason')} error={errs.reason} placeholder="Why this item is added" />
      <div className="row"><Button variant="primary" onClick={submit}>Add item</Button><Button onClick={onClose}>Cancel</Button></div>
    </Dialog>
  );
}

export function DuplicateDialog({ code, onClose, onDone }: { code: string; onClose: () => void; onDone: (t: string, code: string) => void }) {
  const [newCode, setNewCode] = useState('');
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  async function submit() {
    try {
      const it = await api.post<{ code: string }>(`/catalog/items/${code}/duplicate`, { new_code: newCode, name: name || null, reason });
      onDone(`${it.code} added as a copy of ${code} (Proposed).`, it.code);
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <Dialog title={`Duplicate ${code}`} onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      <TextField label="New code" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="A-02d" />
      <TextField label="Line item (optional)" value={name} onChange={(e) => setName(e.target.value)} hint="Leave empty to keep the same name." />
      <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row"><Button variant="primary" onClick={submit}>Duplicate</Button><Button onClick={onClose}>Cancel</Button></div>
    </Dialog>
  );
}

export function RetireDialog({ g, code, restore, onClose, onDone }: { g: Grid; code: string; restore?: boolean; onClose: () => void; onDone: (t: string) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const rules = g.rule_flags.filter((r) => r.line_code === code);
  async function submit() {
    try {
      await api.post(`/catalog/items/${code}/${restore ? 'restore' : 'retire'}`, { reason });
      onDone(restore ? `${code} restored.` : `${code} retired. It stays on old estimates and proposals but can't be added to new ones.`);
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <Dialog title={`${restore ? 'Restore' : 'Retire'} ${code}`} onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      {!restore && <p>A retired item can't be added to new estimates or proposals but stays on old ones. Nothing is deleted; you can restore it later.</p>}
      {!restore && rules.length > 0 && <Alert tone="warn">Mapping rules {rules.map((r) => r.rule_code).join(', ')} point to {code}; they will be flagged for repair.</Alert>}
      <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row"><Button variant={restore ? 'primary' : 'danger'} onClick={submit}>{restore ? 'Restore' : 'Retire'}</Button><Button onClick={onClose}>Cancel</Button></div>
    </Dialog>
  );
}

export function BulkDialog({ g, codes, onClose, onDone }: { g: Grid; codes: string[]; onClose: () => void; onDone: (t: string) => void }) {
  const [kind, setKind] = useState<'percent' | 'amount' | 'set'>('percent');
  const [field, setField] = useState('list_price');
  const [amount, setAmount] = useState('5');
  const [value, setValue] = useState('');
  const [rounding, setRounding] = useState('100');
  const [reason, setReason] = useState('');
  const [effMode, setEffMode] = useState<'now' | 'date'>('now');
  const [effDate, setEffDate] = useState('');
  const [preview, setPreview] = useState<{ code: string; field: string; value: unknown }[] | null>(null);
  const [err, setErr] = useState('');
  const [warn, setWarn] = useState<{ message: string }[] | null>(null);
  const setFields = [['sellable_status', 'Sellable status'], ['price_status', 'Price status'], ['delivery_mode', 'Delivery mode'], ['billing', 'Billing'], ['product', 'Product']];
  const priceFields = [['list_price', 'List'], ['low', 'Low'], ['high', 'High'], ['prices', 'Low, List and High']];
  const op = () => (kind === 'set' ? { kind, field, value } : { kind, field, amount: Number(amount), rounding: rounding ? Number(rounding) : null });
  const byCode = useMemo(() => Object.fromEntries(g.items.map((i) => [i.code, i])), [g.items]);
  async function look() {
    try { setPreview((await api.post<{ changes: { code: string; field: string; value: unknown }[] }>('/catalog/bulk/preview', { codes, op: op(), reason: 'preview' })).changes); setErr(''); }
    catch (e) { setErr(errText(e)); }
  }
  async function save(confirm = false) {
    try {
      const v = await api.post<{ version: number; change_count: number }>('/catalog/bulk', { codes, op: op(), reason, effective_from: effMode === 'date' ? effDate : null, confirm_warnings: confirm });
      onDone(`Bulk edit saved as version ${v.version}: ${v.change_count} change(s).`);
    } catch (e) { if (isWarningOnly(e)) setWarn((e as ApiError).errors); else setErr(errText(e)); }
  }
  const optsFor = (f: string) => {
    const e = g.enums as unknown as Record<string, Record<string, string> | string[]>;
    const m = f === 'product' ? g.enums.products : e[f];
    return Array.isArray(m) ? m.map((x) => ({ value: x, label: x })) : Object.entries(m ?? {}).map(([value, label]) => ({ value, label }));
  };
  return (
    <Dialog title={`Bulk edit ${codes.length} item${codes.length === 1 ? '' : 's'}`} onClose={onClose} large>
      {err && <Alert tone="danger">{err}</Alert>}
      <p className="small muted">{codes.join(', ')}</p>
      <div className="form-grid">
        <SelectField label="Change" value={kind} onChange={(e) => { const k = e.target.value as typeof kind; setKind(k); setField(k === 'set' ? 'sellable_status' : 'list_price'); setPreview(null); }}
          options={[{ value: 'percent', label: 'Prices by %' }, { value: 'amount', label: 'Prices by an amount' }, { value: 'set', label: 'Set a field' }]} />
        <SelectField label="Field" value={field} onChange={(e) => { setField(e.target.value); setValue(''); setPreview(null); }} options={(kind === 'set' ? setFields : priceFields).map(([value, label]) => ({ value, label }))} />
        {kind === 'set' ? (
          <SelectField label="New value" value={value} placeholder="Choose…" onChange={(e) => { setValue(e.target.value); setPreview(null); }} options={optsFor(field)} />
        ) : (
          <>
            <TextField label={kind === 'percent' ? 'By % (use − to lower)' : 'By $ (use − to lower)'} value={amount} onChange={(e) => { setAmount(e.target.value); setPreview(null); }} inputMode="decimal" />
            <SelectField label="Round to the nearest" value={rounding} onChange={(e) => { setRounding(e.target.value); setPreview(null); }}
              options={[{ value: '', label: 'No rounding' }, { value: '10', label: '$10' }, { value: '50', label: '$50' }, { value: '100', label: '$100' }]} />
          </>
        )}
      </div>
      <Button onClick={look}>Preview</Button>
      {preview && (
        <div className="table-scroll">
          <table className="table compact" aria-label="Bulk edit preview">
            <thead><tr><th>Code</th><th>Field</th><th>Now</th><th>After</th></tr></thead>
            <tbody>{preview.map((c) => {
              const it = byCode[c.code];
              const now = it ? (it as unknown as Record<string, unknown>)[c.field] : '';
              return <tr key={`${c.code}${c.field}`}><td>{c.code}</td><td>{g.enums.fields[c.field] ?? c.field}</td><td>{String(now ?? '—')}</td><td className="cell-changed-text"><strong>{String(c.value ?? '—')}</strong></td></tr>;
            })}</tbody>
          </table>
        </div>
      )}
      <div className="form-grid">
        <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <SelectField label="Effective" value={effMode} onChange={(e) => setEffMode(e.target.value as 'now' | 'date')} options={[{ value: 'now', label: 'Now' }, { value: 'date', label: 'From a date…' }]} />
        {effMode === 'date' && <TextField label="Effective date" type="date" value={effDate} onChange={(e) => setEffDate(e.target.value)} />}
      </div>
      <div className="row"><Button variant="primary" onClick={() => save(false)} disabled={!preview}>Save bulk edit</Button><Button onClick={onClose}>Cancel</Button></div>
      {warn && <ConfirmWarnings warnings={warn} onCancel={() => setWarn(null)} onConfirm={() => { setWarn(null); save(true); }} />}
    </Dialog>
  );
}

export function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (t: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [p, setP] = useState<ImportPreview | null>(null);
  const [retireMissing, setRetireMissing] = useState(true);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [warn, setWarn] = useState<{ message: string }[] | null>(null);
  async function upload() {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    setBusy(true);
    try { setP(await api.upload<ImportPreview>('/catalog/import', form)); setErr(''); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function toggleRetire(v: boolean) {
    setRetireMissing(v);
    if (p) setP(await api.get<ImportPreview>(`/catalog/imports/${p.id}?retire_missing=${v}`));
  }
  async function save(confirm = false) {
    try {
      const r = await api.post<{ version: number; added: number; changed: number; retired: number; restored: number }>(`/catalog/imports/${p!.id}/save`, { reason, retire_missing: retireMissing, confirm_warnings: confirm });
      onDone(`Imported as version ${r.version}: ${r.added} added, ${r.changed} change${r.changed === 1 ? '' : 's'}, ${r.retired} retired${r.restored ? `, ${r.restored} restored` : ''}.`);
    } catch (e) { if (isWarningOnly(e)) setWarn((e as ApiError).errors); else setErr(errText(e)); }
  }
  async function discard() {
    if (p) await api.post(`/catalog/imports/${p.id}/discard`).catch(() => undefined);
    onClose();
  }
  return (
    <Dialog title="Import Excel" onClose={discard} large>
      {err && <Alert tone="danger">{err}</Alert>}
      {!p ? (
        <div className="stack-sm">
          <p>Upload the master price list workbook (.xlsx). The Master Price List sheet is read: code, product, line item, pricing unit, billing, basis, periods/yr, low, list, high, price status, notes, deliverables, sellable status, delivery mode, platform feature / release, included quantities, engagement type and entitlement key. Nothing is saved until you check the preview.</p>
          <label className="field-inline">Workbook<input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Workbook to import" /></label>
          <div className="row"><Button variant="primary" onClick={upload} disabled={!file || busy}>{busy ? 'Reading…' : 'Preview import'}</Button><Button onClick={onClose}>Cancel</Button></div>
        </div>
      ) : (
        <div className="stack-sm import-preview">
          <p><strong>{p.filename}</strong>: {p.rows} rows read. Preview against catalog version {p.base_version}.</p>
          <div className="row">
            <Badge tone="success">{p.adds.length} to add</Badge><Badge tone="navy">{p.changes.length} change{p.changes.length === 1 ? '' : 's'}</Badge>
            <Badge tone="warn">{p.retirements.length} to retire</Badge>{p.restores.length > 0 && <Badge tone="navy">{p.restores.length} to restore</Badge>}
            {p.errors.length > 0 && <Badge tone="danger">{p.errors.length} problems</Badge>}
          </div>
          {p.errors.length > 0 && (
            <Alert tone="danger">Fix these rows in the workbook and upload it again:<ul>{p.errors.map((e, i) => <li key={i}>{e.row ? `Row ${e.row}: ` : ''}{e.message}</li>)}</ul></Alert>
          )}
          {p.warnings.length > 0 && <Alert tone="warn"><ul>{p.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul></Alert>}
          {p.adds.length > 0 && <section><h3>Items to add</h3><ul className="cols-2">{p.adds.map((a) => <li key={a.code}><strong>{a.code}</strong> {a.name}</li>)}</ul></section>}
          {p.changes.length > 0 && (
            <section><h3>Changes</h3>
              <div className="table-scroll"><table className="table compact" aria-label="Changes in the workbook">
                <thead><tr><th>Code</th><th>Field</th><th>Now</th><th>In the workbook</th></tr></thead>
                <tbody>{p.changes.map((c, i) => <tr key={i}><td>{c.code}</td><td>{c.label}</td><td className="clip">{c.old_display || '—'}</td><td className="clip cell-changed-text">{c.new_display || '—'}</td></tr>)}</tbody>
              </table></div>
            </section>
          )}
          <section>
            <h3>Retirements</h3>
            <Checkbox label="Retire items that are not in the workbook" checked={retireMissing} onChange={(e) => toggleRetire(e.target.checked)} />
            {p.retirements.length > 0 ? <ul className="cols-2">{p.retirements.map((r) => <li key={r.code}><strong>{r.code}</strong> {r.name}{r.missing ? ' (not in the workbook)' : ''}</li>)}</ul> : <p className="muted small">None.</p>}
          </section>
          <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Load the R2 master price list" />
          <div className="row"><Button variant="primary" onClick={() => save(false)} disabled={!p.can_save}>Save import</Button><Button onClick={discard}>Discard</Button></div>
        </div>
      )}
      {warn && <ConfirmWarnings warnings={warn} onCancel={() => setWarn(null)} onConfirm={() => { setWarn(null); save(true); }} />}
    </Dialog>
  );
}

export function SuggestDialog({ g, code, onClose, onDone }: { g: Grid; code?: string; onClose: () => void; onDone: (t: string) => void }) {
  const [field, setField] = useState(code ? 'list_price' : 'new_item');
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  async function submit() {
    try {
      await api.post('/catalog/suggestions', { item_code: code ?? null, field, suggested_value: value, reason });
      onDone('Suggestion sent to the Price List Owners.');
    } catch (e) { setErr(errText(e)); }
  }
  const opts = Object.entries(g.enums.suggestion_fields).filter(([k]) => (code ? k !== 'new_item' : k === 'new_item' || k === 'other')).map(([value, label]) => ({ value, label }));
  return (
    <Dialog title={code ? `Suggest a change · ${code}` : 'Suggest a new item'} onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      <p className="small muted">The Price List Owners (CEO and President) get this as a task with your reason. Nothing changes until they decide.</p>
      <SelectField label="What to change" value={field} onChange={(e) => setField(e.target.value)} options={opts} />
      {field === 'deliverables' || field === 'new_item' || field === 'other'
        ? <TextArea label={field === 'new_item' ? 'The item: code, name, billing and price' : 'Suggested text'} rows={4} value={value} onChange={(e) => setValue(e.target.value)} />
        : <TextField label="Suggested value" value={value} onChange={(e) => setValue(e.target.value)} />}
      <TextArea label="Reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row"><Button variant="primary" onClick={submit}>Send suggestion</Button><Button onClick={onClose}>Cancel</Button></div>
    </Dialog>
  );
}

export function SuggestionsDialog({ onClose, onOpenItem, onChanged }: { onClose: () => void; onOpenItem: (code: string) => void; onChanged: () => void }) {
  const q = useQuery({ queryKey: ['catalog-suggestions'], queryFn: () => api.get<{ items: Suggestion[] }>('/catalog/suggestions') });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [err, setErr] = useState('');
  async function decide(s: Suggestion, accept: boolean) {
    try { await api.post(`/catalog/suggestions/${s.id}/decide`, { accept, note: notes[s.id] ?? '' }); await q.refetch(); onChanged(); } catch (e) { setErr(errText(e)); }
  }
  const open = q.data?.items.filter((s) => s.status === 'open') ?? [];
  const done = q.data?.items.filter((s) => s.status !== 'open') ?? [];
  return (
    <Dialog title="Suggestions for the price list" onClose={onClose} large>
      {err && <Alert tone="danger">{err}</Alert>}
      {!q.data ? <Loading /> : (
        <div className="stack">
          {open.length === 0 && <p className="muted">No open suggestions.</p>}
          {open.map((s) => (
            <div key={s.id} className="suggestion">
              <div className="row"><strong>{s.item_code ?? 'New item'}</strong><Badge tone="navy">{s.field_label}</Badge><span className="small muted">{s.by} · {fmtDateTime(s.at)}</span></div>
              {s.suggested_value && <p className="pre">Suggested: {s.suggested_value}</p>}
              <p>{s.reason}</p>
              <TextField label="Note to the person who suggested it" value={notes[s.id] ?? ''} onChange={(e) => setNotes({ ...notes, [s.id]: e.target.value })} />
              <div className="row">
                {s.item_code && <Button size="sm" onClick={() => onOpenItem(s.item_code!)}>Open {s.item_code}</Button>}
                <Button size="sm" variant="primary" onClick={() => decide(s, true)}>Accept</Button>
                <Button size="sm" onClick={() => decide(s, false)}>Decline</Button>
              </div>
            </div>
          ))}
          {done.length > 0 && (
            <details><summary>Decided ({done.length})</summary>
              <ul>{done.map((s) => <li key={s.id}>{s.item_code ?? 'New item'} · {s.field_label}: {s.status} by {s.decided_by}{s.decision_note ? ` — ${s.decision_note}` : ''}</li>)}</ul>
            </details>
          )}
          <p className="small muted">Accepting records your decision; make the change on the grid and save it with a reason.</p>
        </div>
      )}
    </Dialog>
  );
}

export function SettingsDialog({ g, onClose, onDone }: { g: Grid; onClose: () => void; onDone: (t: string) => void }) {
  const [on, setOn] = useState(g.settings.second_check);
  const [pct, setPct] = useState(String(g.settings.second_check_pct));
  const [limit, setLimit] = useState(String(g.settings.manager_discount_limit_pct));
  const [err, setErr] = useState('');
  async function submit() {
    try {
      await api.put('/catalog/settings', { second_check: on, second_check_pct: Number(pct), manager_discount_limit_pct: Number(limit) });
      onDone('Price list settings saved.');
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <Dialog title="Price list settings" onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      <Checkbox label="Second check: the other Price List Owner confirms price changes above a chosen %" checked={on} onChange={(e) => setOn(e.target.checked)}
        help="Off by default. When on, Low, List or High changes above the limit wait for the other owner before they go live." />
      <TextField label="Second check above (%)" value={pct} onChange={(e) => setPct(e.target.value)} inputMode="decimal" disabled={!on} />
      <TextField label="Sales Manager discount limit (%)" value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="decimal"
        hint="Discounts on recurring up to this need the Sales Manager (P-2); above it, the Pricing Approver (P-3)." />
      <p className="small muted">Always on: every item must have deliverables before it can be Approved.</p>
      <div className="row"><Button variant="primary" onClick={submit}>Save settings</Button><Button onClick={onClose}>Cancel</Button></div>
    </Dialog>
  );
}

export function SecondCheckPanel({ g, onDone, onError }: { g: Grid; onDone: (t: string) => void; onError: (t: string) => void }) {
  const [note, setNote] = useState('');
  async function decide(confirm: boolean) {
    try {
      const r = await api.post<{ version: number | null }>('/catalog/checks/decide', { change_ids: g.awaiting_check.map((c) => c.id), confirm, note });
      onDone(confirm ? (r.version ? `Confirmed: the changes are live in version ${r.version}.` : 'Confirmed: the changes take effect on their date.') : 'Declined: the changes were not applied.');
    } catch (e) { onError(errText(e)); }
  }
  return (
    <section className="card second-check" aria-label="Waiting for your second check">
      <div className="card-body stack-sm">
        <strong>Waiting for a second check</strong>
        <ul>{g.awaiting_check.map((c) => <li key={c.id}>{c.code} · {c.label} {c.old_display} → {c.new_display} · {c.by}: {c.reason}</li>)}</ul>
        <TextField label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row"><Button variant="primary" size="sm" onClick={() => decide(true)}>Confirm</Button><Button size="sm" onClick={() => decide(false)}>Decline</Button></div>
        <p className="small muted">Only the other Price List Owner can confirm; the person who made the change cannot.</p>
      </div>
    </section>
  );
}
