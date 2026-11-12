import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { PRICE_LABEL, PRICE_TONE, SELL_LABEL, SELL_TONE, summary, type Grid, type Item } from '@/api/catalog';
import { Alert, Badge, Button, Checkbox, fmtDate, Loading } from '@/components/ui';
import { CatalogShell, useGrid } from './CatalogShell';
import { AddItemDialog, BulkDialog, ChangeLogDialog, ConfirmWarnings, DuplicateDialog, HistoryDialog, ImportDialog, RetireDialog, SecondCheckPanel, SettingsDialog, SuggestDialog, SuggestionsDialog } from './Dialogs';
import { SidePanel } from './SidePanel';

export type Dirty = Record<string, Record<string, string>>;
type Kind = 'number' | 'text' | 'select';
type ColKey = 'select' | 'code' | 'product' | 'name' | 'deliverables' | 'description' | 'pricing_unit' | 'billing' | 'basis' | 'periods_per_year' | 'low' | 'list_price' | 'high'
  | 'range' | 'status' | 'price_status' | 'sellable_status' | 'delivery_mode' | 'platform_feature_ref' | 'included_quantities' | 'engagement_type' | 'entitlement_key'
  | 'notes' | 'last_changed' | 'menu';

const PRESETS: Record<string, { label: string; cols: ColKey[] }> = {
  deliverables: { label: 'Pricing + deliverables', cols: ['select', 'code', 'name', 'billing', 'list_price', 'range', 'status', 'deliverables', 'menu'] },
  pricing: { label: 'Pricing', cols: ['select', 'code', 'name', 'billing', 'basis', 'periods_per_year', 'low', 'list_price', 'high', 'price_status', 'last_changed', 'menu'] },
  sellability: { label: 'Sellability and delivery', cols: ['select', 'code', 'name', 'sellable_status', 'delivery_mode', 'platform_feature_ref', 'engagement_type', 'entitlement_key', 'included_quantities', 'menu'] },
  all: { label: 'All', cols: ['select', 'code', 'product', 'name', 'deliverables', 'description', 'pricing_unit', 'billing', 'basis', 'periods_per_year', 'low', 'list_price', 'high',
    'price_status', 'sellable_status', 'delivery_mode', 'platform_feature_ref', 'included_quantities', 'engagement_type', 'entitlement_key', 'notes', 'last_changed', 'menu'] },
};
const HEADERS: Record<ColKey, string> = {
  select: 'Select', code: 'Code', product: 'Product', name: 'Line item', deliverables: 'Deliverables — what the client gets', description: 'Description', pricing_unit: 'Pricing unit',
  billing: 'Billing', basis: 'Basis', periods_per_year: 'Periods/yr', low: 'Low', list_price: 'List', high: 'High', range: 'Range', status: 'Status', price_status: 'Price status',
  sellable_status: 'Sellable status', delivery_mode: 'Delivery mode', platform_feature_ref: 'Platform feature', included_quantities: 'Included quantities',
  engagement_type: 'Engagement type', entitlement_key: 'Entitlement key', notes: 'Notes', last_changed: 'Last changed', menu: 'Row menu',
};
const NUMBER: string[] = ['low', 'list_price', 'high', 'periods_per_year'];

/** The value of a field as a string the editor starts from (and the dirty map compares against). */
export function rawValue(it: Item, field: string): string {
  const v = (it as unknown as Record<string, unknown>)[field];
  if (field === 'included_quantities') return it.included_text;
  if (Array.isArray(v)) return v.join(', ');
  if (v === null || v === undefined) return '';
  return String(v);
}

function same(field: string, a: string, b: string): boolean {
  if (NUMBER.includes(field)) {
    const n = (s: string) => (s.trim() === '' ? null : Number(s.replace(/[,$%]/g, '')));
    return n(a) === n(b);
  }
  return a.trim() === b.trim();
}

export function optionsFor(g: Grid, field: string): { value: string; label: string }[] | null {
  const e = g.enums;
  const map: Record<string, Record<string, string> | string[]> = {
    product: e.products, billing: e.billing, price_status: e.price_status, sellable_status: e.sellable_status, delivery_mode: { '': 'Not set', ...e.delivery_mode }, basis: ['$', '%'],
  };
  const m = map[field];
  if (!m) return null;
  return Array.isArray(m) ? m.map((v) => ({ value: v, label: v })) : Object.entries(m).map(([value, label]) => ({ value, label }));
}

function shown(g: Grid, field: string, raw: string, basis: '$' | '%'): string {
  const opts = optionsFor(g, field);
  if (opts) return opts.find((o) => o.value === raw)?.label ?? raw;
  if (['low', 'list_price', 'high'].includes(field) && raw !== '') return basis === '%' ? `${raw}%` : Number(raw.replace(/,/g, '')).toLocaleString('en-US');
  return raw;
}

function EditCell({ g, item, field, dirty, editable, error, onCommit }: {
  g: Grid; item: Item; field: string; dirty?: string; editable: boolean; error?: string; onCommit: (v: string) => void;
}) {
  const orig = rawValue(item, field);
  const value = dirty ?? orig;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const opts = optionsFor(g, field);
  const kind: Kind = opts ? 'select' : NUMBER.includes(field) ? 'number' : 'text';
  const label = `${HEADERS[field as ColKey] ?? field} ${item.code}`;
  const changed = dirty !== undefined;
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null);
  useEffect(() => { if (editing) ref.current?.focus(); }, [editing]);
  const commit = (v: string) => { setEditing(false); onCommit(v); };
  function key(e: KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); commit(draft); }
    if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }
  }
  const cls = `cell-edit${changed ? ' cell-changed' : ''}${error ? ' cell-error' : ''}${kind === 'number' ? ' num' : ''}`;
  if (!editable) return <span className={kind === 'number' ? 'num' : ''}>{shown(g, field, value, item.basis) || <span className="muted">—</span>}</span>;
  if (!editing) {
    return (
      <span className="stack-xs">
        <button type="button" className={cls} aria-label={`${label}: ${shown(g, field, value, item.basis) || 'empty'}${changed ? ' (unsaved)' : ''}`}
          onClick={() => { setDraft(value); setEditing(true); }}>
          {shown(g, field, value, item.basis) || <span className="muted">—</span>}
        </button>
        {error && <span className="small cell-error-text">{error}</span>}
      </span>
    );
  }
  return kind === 'select' ? (
    <select ref={ref} aria-label={label} className={`${cls} cell-input`} value={draft} onChange={(e) => { setDraft(e.target.value); commit(e.target.value); }}
      onKeyDown={key} onBlur={() => setEditing(false)}>
      {opts!.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  ) : (
    <input ref={ref} aria-label={label} className={`${cls} cell-input`} value={draft} inputMode={kind === 'number' ? 'decimal' : undefined}
      onChange={(e) => setDraft(e.target.value)} onKeyDown={key} onBlur={() => commit(draft)} />
  );
}

export function PriceList() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [showRetired, setShowRetired] = useState(false);
  const q = useGrid(showRetired);
  const g = q.data;
  const [dirty, setDirty] = useState<Dirty>({});
  const [reason, setReason] = useState('');
  const [effMode, setEffMode] = useState<'now' | 'date'>('now');
  const [effDate, setEffDate] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'warn'; text: string } | null>(null);
  const [warnings, setWarnings] = useState<{ message: string }[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [product, setProduct] = useState('');
  const [priceStatus, setPriceStatus] = useState('');
  const [sellable, setSellable] = useState('');
  const [billing, setBilling] = useState('');
  const [recent, setRecent] = useState(false);
  const [preset, setPreset] = useState<keyof typeof PRESETS>('deliverables');
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ kind: string; code?: string } | null>(null);
  const panel = params.get('item');
  const sidePanelOpen = params.get('panel');
  const refresh = () => qc.invalidateQueries({ queryKey: ['catalog'] });

  useEffect(() => {
    if (sidePanelOpen === 'suggestions') setDialog({ kind: 'suggestions' });
  }, [sidePanelOpen]);

  const nChanges = Object.values(dirty).reduce((n, f) => n + Object.keys(f).length, 0);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (nChanges) { e.preventDefault(); } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [nChanges]);

  const items = useMemo(() => {
    if (!g) return [];
    const needle = search.trim().toLowerCase();
    const cutoff = Date.now() - 30 * 86400_000;
    return g.items.filter((it) => (!product || it.product === product) && (!priceStatus || it.price_status === priceStatus) && (!sellable || it.sellable_status === sellable)
      && (!billing || it.billing === billing)
      && (!recent || it.pending.length > 0 || (it.last_changed_at && new Date(`${it.last_changed_at}Z`).getTime() >= cutoff && !it.is_starter))
      && (!needle || `${it.code} ${it.name} ${it.deliverables ?? ''} ${it.description ?? ''} ${it.notes ?? ''}`.toLowerCase().includes(needle)));
  }, [g, search, product, priceStatus, sellable, billing, recent]);

  if (!g) return <CatalogShell tab="prices"><Loading /></CatalogShell>;

  function setCell(code: string, field: string, v: string) {
    const it = g!.items.find((i) => i.code === code);
    if (!it) return;
    setDirty((d) => {
      const row = { ...(d[code] ?? {}) };
      if (same(field, v, rawValue(it, field))) delete row[field]; else row[field] = v;
      const next = { ...d, [code]: row };
      if (!Object.keys(row).length) delete next[code];
      return next;
    });
    setErrors((e) => { const n = { ...e }; delete n[`${code}:${field}`]; delete n[`${code}:row`]; return n; });
  }

  async function save(confirm = false) {
    if (!reason.trim()) { setMsg({ tone: 'danger', text: 'Give one reason for this batch of changes.' }); return; }
    if (effMode === 'date' && !effDate) { setMsg({ tone: 'danger', text: 'Choose the date the changes take effect.' }); return; }
    const changes = Object.entries(dirty).flatMap(([code, f]) => Object.entries(f).map(([field, value]) => ({ code, field, value })));
    try {
      const v = await api.post<{ version: number; change_count: number }>('/catalog/save', {
        changes, reason, effective_from: effMode === 'date' ? effDate : null, base_version: g!.version, confirm_warnings: confirm,
      });
      setDirty({}); setReason(''); setErrors({}); setWarnings(null); setEffMode('now'); setEffDate('');
      setMsg({ tone: 'success', text: effMode === 'date' ? `Saved as version ${v.version}: ${v.change_count} change(s) take effect on ${fmtDate(effDate)}.` : `Saved as version ${v.version}: ${v.change_count} change(s).` });
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.errors.length && e.errors.every((x) => (x as { kind?: string }).kind === 'warning')) { setWarnings(e.errors); return; }
      if (e instanceof ApiError && e.errors.length) {
        const map: Record<string, string> = {};
        for (const x of e.errors as { code?: string; field: string; message: string }[]) map[`${x.code ?? ''}:${x.field}`] = x.message;
        setErrors(map);
      }
      setMsg({ tone: 'danger', text: e instanceof ApiError && e.errors.length ? `${errorMessage(e)} ${e.errors.map((x) => x.message).join(' ')}` : errorMessage(e) });
    }
  }

  const cols = PRESETS[preset].cols.filter((c) => c !== 'select' || g.can_edit);
  const allShownSelected = items.length > 0 && items.every((i) => selected.has(i.code));
  const toggle = (code: string) => setSelected((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code); return n; });
  const panelItem = g.items.find((i) => i.code === panel);

  function cell(it: Item, c: ColKey) {
    const editable = g!.can_edit && it.status === 'active';
    const common = { g: g!, item: it, editable, onCommit: (v: string) => setCell(it.code, c, v) };
    switch (c) {
      case 'select':
        return <input type="checkbox" aria-label={`Select ${it.code}`} checked={selected.has(it.code)} onChange={() => toggle(it.code)} />;
      case 'code':
        return <span className="nowrap"><strong>{it.code}</strong>{it.status === 'retired' && <span className="block"><Badge tone="muted">Retired</Badge></span>}</span>;
      case 'name':
      case 'product': case 'description': case 'pricing_unit': case 'billing': case 'basis': case 'periods_per_year': case 'low': case 'list_price': case 'high':
      case 'price_status': case 'sellable_status': case 'delivery_mode': case 'platform_feature_ref': case 'included_quantities': case 'engagement_type': case 'entitlement_key': case 'notes': {
        const field = c;
        const node = <EditCell {...common} field={field} dirty={dirty[it.code]?.[field]} error={errors[`${it.code}:${field}`]} />;
        if (c === 'billing' && preset === 'deliverables') return <span>{node}{it.pricing_unit && <span className="small muted block">{it.pricing_unit}</span>}</span>;
        return node;
      }
      case 'range':
        return <span className="nowrap">{it.range || '—'}</span>;
      case 'status':
        return <span className="stack-xs"><Badge tone={PRICE_TONE[it.price_status]}>{PRICE_LABEL[it.price_status]}</Badge><Badge tone={SELL_TONE[it.sellable_status]}>{SELL_LABEL[it.sellable_status]}</Badge></span>;
      case 'deliverables': {
        const edited = dirty[it.code]?.deliverables !== undefined;
        return (
          <span className="deliv-cell">
            {it.deliverables ? summary(dirty[it.code]?.deliverables ?? it.deliverables) : <span className="muted">No deliverables yet{it.price_status !== 'approved' ? ' — needed before it can be Approved' : ''}.</span>}
            {edited && <span className="small cell-changed-text"> Edited — see side panel.</span>}{' '}
            <button type="button" className="linklike" onClick={() => setParams({ item: it.code, focus: 'deliverables' })} aria-label={`Read all deliverables for ${it.code}`}>Read all</button>
          </span>
        );
      }
      case 'last_changed':
        return <span className="small">{it.last_changed_by ?? '—'}<span className="block muted">{fmtDate(it.last_changed_at)}</span></span>;
      case 'menu':
        return <RowMenu it={it} g={g!} open={menuFor === it.code} setOpen={(o) => setMenuFor(o ? it.code : null)} act={(kind) => {
          setMenuFor(null);
          if (kind === 'edit' || kind === 'view') setParams({ item: it.code });
          else setDialog({ kind, code: it.code });
        }} />;
    }
  }

  return (
    <CatalogShell tab="prices" actions={<>
      {g.can_edit && <Button variant="primary" onClick={() => setDialog({ kind: 'add' })}>Add item</Button>}
      {g.can_edit && <Button onClick={() => setDialog({ kind: 'import' })}>Import Excel</Button>}
      <a className="btn" href="/api/v1/catalog/export.xlsx" download>Export Excel</a>
      <Button onClick={() => setDialog({ kind: 'log' })}>Change log</Button>
      {g.can_edit && <Button onClick={() => setDialog({ kind: 'suggestions' })}>Suggestions{g.open_suggestions ? ` (${g.open_suggestions})` : ''}</Button>}
      {g.can_edit && <Button onClick={() => setDialog({ kind: 'settings' })}>Settings</Button>}
      {!g.can_edit && g.can_suggest && <Button onClick={() => setDialog({ kind: 'suggest' })}>Suggest a new item</Button>}
    </>}>
      {g.starter && <Alert tone="info">These are starter items from the screen designs (demo data), not the full price list. A Price List Owner loads the master price list workbook with Import Excel; you see every add, change and retirement before it is saved.</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {g.rule_flags.length > 0 && (
        <Alert tone="warn">{g.rule_flags.length} mapping rule{g.rule_flags.length === 1 ? ' points' : 's point'} to an item that is retired or not on the price list: {g.rule_flags.map((f) => `${f.rule_code} → ${f.line_code} (${f.problem.toLowerCase()})`).join('; ')}. Repair them on the Mapping rules tab.</Alert>
      )}
      {g.can_edit && g.awaiting_check.length > 0 && <SecondCheckPanel g={g} onDone={(t) => { setMsg({ tone: 'success', text: t }); refresh(); }} onError={(t) => setMsg({ tone: 'danger', text: t })} />}

      <div className="catalog-filters" role="search">
        <label className="field-inline">Search<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Code, name or deliverable" aria-label="Search the price list" /></label>
        <label className="field-inline">Product<select value={product} onChange={(e) => setProduct(e.target.value)}><option value="">All</option>{g.enums.products.map((p) => <option key={p}>{p}</option>)}</select></label>
        <label className="field-inline">Billing<select value={billing} onChange={(e) => setBilling(e.target.value)}><option value="">All</option>{Object.entries(g.enums.billing).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field-inline">Price status<select value={priceStatus} onChange={(e) => setPriceStatus(e.target.value)}><option value="">All</option>{Object.entries(g.enums.price_status).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field-inline">Sellable<select value={sellable} onChange={(e) => setSellable(e.target.value)}><option value="">All</option>{Object.entries(g.enums.sellable_status).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field-inline">Columns<select value={preset} onChange={(e) => setPreset(e.target.value as keyof typeof PRESETS)}>{Object.entries(PRESETS).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}</select></label>
        <Checkbox label="Changed in last 30 days" checked={recent} onChange={(e) => setRecent(e.target.checked)} />
        <Checkbox label="Show retired" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
      </div>

      {nChanges > 0 && (
        <div className="save-bar" role="region" aria-label="Unsaved changes">
          <strong>{nChanges} unsaved change{nChanges === 1 ? '' : 's'}</strong>
          <label className="field-inline grow">Reason<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="One reason for this batch, e.g. Q1 2027 price review" aria-label="Reason for these changes" /></label>
          <label className="field-inline">Effective<select value={effMode} onChange={(e) => setEffMode(e.target.value as 'now' | 'date')} aria-label="When the changes take effect"><option value="now">Now</option><option value="date">From a date…</option></select></label>
          {effMode === 'date' && <label className="field-inline">Date<input type="date" value={effDate} onChange={(e) => setEffDate(e.target.value)} aria-label="Effective date" /></label>}
          <Button onClick={() => { setDirty({}); setErrors({}); setMsg(null); }}>Discard</Button>
          <Button variant="primary" onClick={() => save(false)}>Save changes</Button>
        </div>
      )}
      {g.can_edit && selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected rows">
          <strong>{selected.size} selected</strong>
          <Button onClick={() => setDialog({ kind: 'bulk' })}>Bulk edit</Button>
          <Button variant="ghost" onClick={() => setSelected(new Set())}>Clear selection</Button>
        </div>
      )}

      <div className="catalog-grid-wrap">
        <table className="catalog-grid" aria-label="Master price list">
          <thead>
            <tr>{cols.map((c) => <th key={c} scope="col" className={`col-${c}`}>{c === 'select'
              ? <input type="checkbox" aria-label="Select all shown rows" checked={allShownSelected} onChange={() => setSelected(allShownSelected ? new Set() : new Set(items.map((i) => i.code)))} />
              : c === 'menu' ? <span className="sr-only">{HEADERS[c]}</span> : HEADERS[c]}</th>)}</tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.code} className={`${it.status === 'retired' ? 'row-retired' : ''}${dirty[it.code] ? ' row-dirty' : ''}`}>
                {cols.map((c) => <td key={c} className={`col-${c}`}>{cell(it, c)}{c === 'name' && <RowNotes it={it} rowError={errors[`${it.code}:row`]} />}</td>)}
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={cols.length}><span className="muted">No items match these filters.</span></td></tr>}
          </tbody>
        </table>
      </div>
      <p className="small muted">Row menu: {g.can_edit ? 'Edit all fields · Duplicate · View history · Retire.' : 'View details · View history · Suggest a change.'} Deliverables appear in the Estimator, the proposal's "What we'll do" section and the client acceptance page.</p>

      {panelItem && <SidePanel g={g} item={panelItem} dirty={dirty[panelItem.code] ?? {}} setCell={setCell} focus={params.get('focus')}
        onClose={() => setParams({})} onHistory={() => setDialog({ kind: 'history', code: panelItem.code })} onSuggest={() => setDialog({ kind: 'suggest', code: panelItem.code })} />}
      {warnings && <ConfirmWarnings warnings={warnings} onCancel={() => setWarnings(null)} onConfirm={() => save(true)} />}
      {dialog?.kind === 'history' && dialog.code && <HistoryDialog code={dialog.code} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'log' && <ChangeLogDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === 'add' && <AddItemDialog g={g} onClose={() => setDialog(null)} onDone={(t, code) => { setDialog(null); setMsg({ tone: 'success', text: t }); refresh(); setParams({ item: code }); }} />}
      {dialog?.kind === 'duplicate' && dialog.code && <DuplicateDialog code={dialog.code} onClose={() => setDialog(null)} onDone={(t, code) => { setDialog(null); setMsg({ tone: 'success', text: t }); refresh(); setParams({ item: code }); }} />}
      {(dialog?.kind === 'retire' || dialog?.kind === 'restore') && dialog.code && <RetireDialog g={g} code={dialog.code} restore={dialog.kind === 'restore'} onClose={() => setDialog(null)} onDone={(t) => { setDialog(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {dialog?.kind === 'bulk' && <BulkDialog g={g} codes={[...selected]} onClose={() => setDialog(null)} onDone={(t) => { setDialog(null); setSelected(new Set()); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {dialog?.kind === 'import' && <ImportDialog onClose={() => setDialog(null)} onDone={(t) => { setDialog(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {dialog?.kind === 'suggest' && <SuggestDialog g={g} code={dialog.code} onClose={() => setDialog(null)} onDone={(t) => { setDialog(null); setMsg({ tone: 'success', text: t }); }} />}
      {dialog?.kind === 'suggestions' && <SuggestionsDialog onClose={() => { setDialog(null); if (sidePanelOpen) setParams({}); }} onOpenItem={(code) => { setDialog(null); setParams({ item: code }); }} onChanged={refresh} />}
      {dialog?.kind === 'settings' && <SettingsDialog g={g} onClose={() => setDialog(null)} onDone={(t) => { setDialog(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
    </CatalogShell>
  );
}

function RowNotes({ it, rowError }: { it: Item; rowError?: string }) {
  return (
    <>
      {it.pending.map((p) => (
        <span key={p.id} className="small pending-note block">
          {p.status === 'awaiting_check' ? 'Waiting for second check' : `Pending from ${fmtDate(p.effective_from)}`}: {p.label} {p.old_display || '—'} → {p.new_display || '—'}
        </span>
      ))}
      {rowError && <span className="small cell-error-text block">{rowError}</span>}
    </>
  );
}

function RowMenu({ it, g, open, setOpen, act }: { it: Item; g: Grid; open: boolean; setOpen: (o: boolean) => void; act: (kind: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    ref.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    return () => document.removeEventListener('mousedown', close);
  }, [open, setOpen]);
  const entries: [string, string][] = g.can_edit
    ? [['edit', 'Edit all fields'], ['duplicate', 'Duplicate'], ['history', 'View history'], it.status === 'retired' ? ['restore', 'Restore'] : ['retire', 'Retire']]
    : [['view', 'View details'], ['history', 'View history'], ...(g.can_suggest ? [['suggest', 'Suggest a change'] as [string, string]] : [])];
  function keys(e: KeyboardEvent<HTMLDivElement>) {
    const list = [...(ref.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])];
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'Escape') { setOpen(false); ref.current?.querySelector<HTMLButtonElement>('button')?.focus(); }
    if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length]?.focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length]?.focus(); }
  }
  return (
    <div className="row-menu" ref={ref} onKeyDown={keys}>
      <button type="button" className="btn btn-ghost btn-sm" aria-haspopup="menu" aria-expanded={open} aria-label={`Actions for ${it.code}`} onClick={() => setOpen(!open)}>⋯</button>
      {open && (
        <div role="menu" className="row-menu-list" aria-label={`${it.code} actions`}>
          {entries.map(([k, label]) => <button key={k} type="button" role="menuitem" onClick={() => act(k)}>{label}</button>)}
        </div>
      )}
    </div>
  );
}

