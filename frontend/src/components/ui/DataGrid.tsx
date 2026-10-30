/**
 * DataGrid: a table for lists people work through, with sorting, filters, search, multi-select bulk actions,
 * a "⋯" menu on each row (also opened by right-clicking the row) and inline editing.
 *
 * Usage:
 *   <DataGrid
 *     label="Departments"                       // accessible name of the table
 *     rows={depts} rowId={(d) => d.id} rowLabel={(d) => d.name}
 *     columns={[
 *       { key: 'name', header: 'Department', value: (d) => d.name, edit: { onSave: (d, v) => rename(d, v) } },
 *       { key: 'scope', header: 'Scope', value: (d) => (d.in_scope ? 'In scope' : 'Out of scope'), render: (d) => <Badge>…</Badge> },
 *     ]}
 *     filters={[{ key: 'scope', label: 'Scope', options: [...], test: (d, v) => … }]}
 *     search={{ label: 'Search departments', text: (d) => d.name }}
 *     bulkActions={[{ label: 'Delete', danger: true, confirm: (rows) => `Delete ${rows.length} departments?`, run: (rows) => … }]}
 *     rowActions={(d) => [{ label: 'Edit', onSelect: () => … }, { label: 'Delete', danger: true, onSelect: () => … }]}
 *   />
 *
 * - Sorting: every column with `value` sorts (click the header); `sortable: false` turns it off.
 * - Inline edit: columns with `edit` are editable. Double-click or Enter opens the editor; Enter or leaving the field
 *   saves, Escape cancels. A rejected save keeps the editor open and shows the error under it.
 * - Row menu: the "⋯" button (aria-haspopup="menu") opens the menu; right-clicking the row opens it at the pointer.
 *   Arrow keys, Home and End move between items, Escape closes and returns focus to the button.
 * - Bulk actions show when at least one row is selected. Actions with `confirm` ask first.
 * - On narrow screens the table scrolls sideways inside its own container, never the page.
 */
import { Fragment, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Alert, Button, Dialog } from './index';
import './DataGrid.css';

export type GridOption = { value: string; label: string };

export type GridColumn<T> = {
  key: string;
  header: ReactNode;
  /** Plain value for sorting, searching and the editor's starting value. */
  value?: (row: T) => string | number | null | undefined;
  /** Cell content; defaults to `value`. */
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  /** Inline editing. `onSave` may throw (or reject) with a message to show under the editor. */
  edit?: {
    type?: 'text' | 'number' | 'select';
    options?: GridOption[] | ((row: T) => GridOption[]);
    canEdit?: (row: T) => boolean;
    /** Accessible name of the editor, for example "Department name for Finance". */
    label?: (row: T) => string;
    onSave: (row: T, value: string) => Promise<unknown> | unknown;
  };
  className?: string;
  width?: string;
};

export type GridRowAction = { label: string; onSelect: () => void; danger?: boolean; disabled?: boolean };

export type GridBulkAction<T> = {
  label: string;
  run: (rows: T[]) => Promise<unknown> | unknown;
  danger?: boolean;
  /** Ask before running. The text is the question; the confirm button repeats `label`. */
  confirm?: string | ((rows: T[]) => string);
  /** Hide the action unless every selected row passes. */
  available?: (rows: T[]) => boolean;
};

export type GridFilter<T> = { key: string; label: string; options: GridOption[]; test: (row: T, value: string) => boolean };

export type DataGridProps<T> = {
  label: string;
  rows: T[];
  columns: GridColumn<T>[];
  rowId: (row: T) => string;
  /** Short name of the row for screen readers, for example the person's name. */
  rowLabel?: (row: T) => string;
  selectable?: boolean;
  bulkActions?: GridBulkAction<T>[];
  rowActions?: (row: T) => GridRowAction[];
  filters?: GridFilter<T>[];
  search?: { label: string; placeholder?: string; text: (row: T) => string };
  initialSort?: { key: string; dir: 'asc' | 'desc' };
  emptyText?: ReactNode;
  /** Shown when filters or search hide every row. */
  noMatchText?: ReactNode;
  rowClassName?: (row: T) => string | undefined;
  /** Filter values to start with, by filter key (for example from the page address). */
  initialFilters?: Record<string, string>;
};

type Sort = { key: string; dir: 'asc' | 'desc' } | null;

const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

function compare(a: unknown, b: unknown): number {
  const ea = a === null || a === undefined || a === '';
  const eb = b === null || b === undefined || b === '';
  if (ea || eb) return ea === eb ? 0 : ea ? 1 : -1; // blanks last
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return collator.compare(String(a), String(b));
}

export function DataGrid<T>(props: DataGridProps<T>) {
  const { label, rows, columns, rowId, rowLabel, selectable, bulkActions = [], rowActions, filters = [], search, initialSort, emptyText, noMatchText, rowClassName, initialFilters } = props;
  const [sort, setSort] = useState<Sort>(initialSort ?? null);
  const [filterValues, setFilterValues] = useState<Record<string, string>>(initialFilters ?? {});
  const [text, setText] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [menu, setMenu] = useState<{ id: string; x?: number; y?: number; anchor?: HTMLElement | null } | null>(null);
  const [confirming, setConfirming] = useState<{ action: GridBulkAction<T>; rows: T[] } | null>(null);
  const [bulkErr, setBulkErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uid = useId();

  const visible = useMemo(() => {
    let out = rows.filter((r) => filters.every((f) => !filterValues[f.key] || f.test(r, filterValues[f.key])));
    const q = text.trim().toLowerCase();
    if (q && search) out = out.filter((r) => search.text(r).toLowerCase().includes(q));
    const col = sort && columns.find((c) => c.key === sort.key);
    if (sort && col?.value) {
      const get = col.value;
      out = [...out].sort((a, b) => compare(get(a), get(b)) * (sort.dir === 'asc' ? 1 : -1));
    }
    return out;
  }, [rows, filters, filterValues, text, search, sort, columns]);

  // Drop selections for rows that no longer exist (deleted, or the list reloaded).
  useEffect(() => {
    const ids = new Set(rows.map(rowId));
    setSelected((s) => {
      const next = new Set([...s].filter((id) => ids.has(id)));
      return next.size === s.size ? s : next;
    });
  }, [rows, rowId]);

  const selectedRows = rows.filter((r) => selected.has(rowId(r)));
  const visibleIds = visible.map(rowId);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const someVisibleSelected = visibleIds.some((id) => selected.has(id));
  const hasMenu = !!rowActions;
  const name = (r: T) => (rowLabel ? rowLabel(r) : rowId(r));

  function toggleSort(key: string) {
    setSort((s) => (s?.key === key ? (s.dir === 'asc' ? { key, dir: 'desc' } : null) : { key, dir: 'asc' }));
  }
  function toggleRow(id: string) {
    setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  function toggleAll() {
    setSelected((s) => {
      const n = new Set(s);
      if (allVisibleSelected) visibleIds.forEach((id) => n.delete(id)); else visibleIds.forEach((id) => n.add(id));
      return n;
    });
  }
  async function runBulk(action: GridBulkAction<T>, list: T[]) {
    setBulkErr(null); setBusy(true);
    try { await action.run(list); setSelected(new Set()); } catch (e) { setBulkErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); setConfirming(null); }
  }
  function startBulk(action: GridBulkAction<T>) {
    if (action.confirm) setConfirming({ action, rows: selectedRows }); else void runBulk(action, selectedRows);
  }

  const filtered = filters.some((f) => filterValues[f.key]) || !!text.trim();
  const colCount = columns.length + (selectable ? 1 : 0) + (hasMenu ? 1 : 0);
  const openRow = menu ? rows.find((r) => rowId(r) === menu.id) : undefined;

  return (
    <div className="dg">
      {(filters.length > 0 || search) && (
        <div className="dg-tools" role="search" aria-label={`Filter ${label.toLowerCase()}`}>
          {search && (
            <div className="dg-filter dg-search">
              <label htmlFor={`${uid}-q`}>{search.label}</label>
              <input id={`${uid}-q`} className="input" type="search" value={text} placeholder={search.placeholder} onChange={(e) => setText(e.target.value)} />
            </div>
          )}
          {filters.map((f) => (
            <div key={f.key} className="dg-filter">
              <label htmlFor={`${uid}-${f.key}`}>{f.label}</label>
              <select id={`${uid}-${f.key}`} className="select" value={filterValues[f.key] ?? ''} onChange={(e) => setFilterValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                <option value="">All</option>
                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          ))}
          {filtered && <Button size="sm" variant="ghost" onClick={() => { setFilterValues({}); setText(''); }}>Clear filters</Button>}
        </div>
      )}
      {selectable && selectedRows.length > 0 && (
        <div className="dg-bulk" role="region" aria-label="Actions for selected rows">
          <strong>{selectedRows.length} selected</strong>
          {bulkActions.filter((a) => !a.available || a.available(selectedRows)).map((a) => (
            <Button key={a.label} size="sm" variant={a.danger ? 'danger' : 'default'} disabled={busy} onClick={() => startBulk(a)}>{a.label}</Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear selection</Button>
        </div>
      )}
      {bulkErr && <Alert tone="danger">{bulkErr}</Alert>}
      <div className="dg-scroll">
        <table className="table dg-table" aria-label={label}>
          <thead>
            <tr>
              {selectable && (
                <th className="dg-check">
                  <input type="checkbox" aria-label={`Select all ${label.toLowerCase()} shown`} checked={allVisibleSelected} ref={(el) => { if (el) el.indeterminate = !allVisibleSelected && someVisibleSelected; }} onChange={toggleAll} disabled={!visible.length} />
                </th>
              )}
              {columns.map((c) => {
                const canSort = c.sortable !== false && !!c.value;
                const dir = sort?.key === c.key ? sort.dir : null;
                return (
                  <th key={c.key} style={c.width ? { width: c.width } : undefined} aria-sort={dir ? (dir === 'asc' ? 'ascending' : 'descending') : canSort ? 'none' : undefined}>
                    {canSort ? (
                      <button type="button" className="dg-sort" onClick={() => toggleSort(c.key)}>
                        {c.header}<span className="dg-sort-ind" aria-hidden="true">{dir === 'asc' ? '▲' : dir === 'desc' ? '▼' : '↕'}</span>
                      </button>
                    ) : c.header}
                  </th>
                );
              })}
              {hasMenu && <th className="dg-menu-col"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr><td colSpan={colCount} className="dg-empty">{rows.length === 0 ? (emptyText ?? 'Nothing here yet.') : (noMatchText ?? 'No rows match these filters.')}</td></tr>
            ) : visible.map((r) => {
              const id = rowId(r);
              const isSel = selected.has(id);
              return (
                <tr key={id} className={[isSel ? 'selected' : '', rowClassName?.(r) ?? ''].filter(Boolean).join(' ') || undefined}
                  onContextMenu={hasMenu ? (e: ReactMouseEvent) => {
                    if ((e.target as HTMLElement).closest('input, select, textarea')) return;
                    e.preventDefault();
                    setMenu({ id, x: e.clientX, y: e.clientY, anchor: (e.currentTarget as HTMLElement).querySelector<HTMLElement>('.dg-menu-btn') });
                  } : undefined}>
                  {selectable && <td className="dg-check"><input type="checkbox" aria-label={`Select ${name(r)}`} checked={isSel} onChange={() => toggleRow(id)} /></td>}
                  {columns.map((c) => <Cell key={c.key} col={c} row={r} />)}
                  {hasMenu && (
                    <td className="dg-menu-col">
                      <button type="button" className="dg-menu-btn" aria-haspopup="menu" aria-expanded={menu?.id === id} aria-label={`Actions for ${name(r)}`}
                        onClick={(e) => setMenu(menu?.id === id ? null : { id, anchor: e.currentTarget })}>
                        <span aria-hidden="true">⋯</span>
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {menu && openRow && rowActions && (
        <RowMenu label={`Actions for ${name(openRow)}`} items={rowActions(openRow)} x={menu.x} y={menu.y} anchor={menu.anchor ?? null} onClose={(refocus) => { const a = menu.anchor; setMenu(null); if (refocus) a?.focus(); }} />
      )}
      {confirming && (
        <Dialog title={confirming.action.label} onClose={() => setConfirming(null)}>
          <div className="stack">
            <p>{typeof confirming.action.confirm === 'function' ? confirming.action.confirm(confirming.rows) : confirming.action.confirm}</p>
            <div className="row">
              <Button variant={confirming.action.danger ? 'danger' : 'primary'} disabled={busy} onClick={() => runBulk(confirming.action, confirming.rows)}>{confirming.action.label}</Button>
              <Button onClick={() => setConfirming(null)}>Cancel</Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function Cell<T>({ col, row }: { col: GridColumn<T>; row: T }) {
  const editable = !!col.edit && (!col.edit.canEdit || col.edit.canEdit(row));
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const cellRef = useRef<HTMLTableCellElement>(null);
  const done = useRef(false);
  const refocus = useRef(false); // closed from the keyboard: put focus back on the cell (not after a click elsewhere)
  useEffect(() => {
    if (editing || !refocus.current) return;
    refocus.current = false;
    const active = document.activeElement;
    if (!active || active === document.body || cellRef.current?.contains(active)) cellRef.current?.focus(); // unless the user has moved on
  }, [editing]);
  const content = col.render ? col.render(row) : (col.value?.(row) ?? '—');

  function open() {
    if (!editable) return;
    const v = col.value?.(row);
    setDraft(v === null || v === undefined ? '' : String(v));
    setErr(null);
    done.current = false;
    setEditing(true);
  }
  function cancel() {
    done.current = true;
    setEditing(false);
    setErr(null);
  }
  async function save(value = draft) {
    if (done.current || saving) return;
    const before = col.value?.(row);
    if (String(before ?? '') === value) { cancel(); return; }
    setSaving(true);
    try {
      await col.edit!.onSave(row, value);
      done.current = true;
      setEditing(false);
      setErr(null);
    } catch (e) {
      refocus.current = false;
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  function onKey(e: ReactKeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); refocus.current = true; void save(); }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); refocus.current = true; cancel(); }
  }

  if (!editable) return <td className={col.className}>{content}</td>;
  const editLabel = col.edit!.label ? col.edit!.label(row) : `Edit ${typeof col.header === 'string' ? col.header.toLowerCase() : col.key}`;
  if (editing) {
    const opts = typeof col.edit!.options === 'function' ? col.edit!.options(row) : col.edit!.options ?? [];
    const errId = `dg-err-${col.key}-${Math.abs(hash(editLabel))}`;
    return (
      <td className={`${col.className ?? ''} dg-editing`}>
        {col.edit!.type === 'select' ? (
          <select className="select dg-editor" autoFocus aria-label={editLabel} aria-invalid={err ? true : undefined} aria-describedby={err ? errId : undefined} value={draft} disabled={saving}
            onChange={(e) => { setDraft(e.target.value); void save(e.target.value); }} onBlur={() => void save()} onKeyDown={onKey}>
            {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ) : (
          <input className="input dg-editor" autoFocus aria-label={editLabel} aria-invalid={err ? true : undefined} aria-describedby={err ? errId : undefined} value={draft} disabled={saving}
            inputMode={col.edit!.type === 'number' ? 'numeric' : undefined} onChange={(e) => setDraft(e.target.value)} onBlur={() => void save()} onKeyDown={onKey} />
        )}
        {err && <div className="error" id={errId} role="alert">{err}</div>}
      </td>
    );
  }
  return (
    <td ref={cellRef} className={`${col.className ?? ''} dg-editable`} tabIndex={0} title="Double-click or press Enter to edit"
      onDoubleClick={open} onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); open(); } }}>
      <span>{content}</span><span className="sr-only"> (press Enter to edit)</span>
    </td>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

/** A menu of actions for one row, positioned at the pointer (right-click) or under its button. */
export function RowMenu({ label, items, x, y, anchor, onClose }: { label: string; items: GridRowAction[]; x?: number; y?: number; anchor: HTMLElement | null; onClose: (refocus: boolean) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number }>({ left: -9999, top: -9999 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let left = x ?? 0, top = y ?? 0;
    if (x === undefined && anchor) {
      const b = anchor.getBoundingClientRect();
      left = b.right - w; top = b.bottom + 4;
      if (top + h > vh - 8) top = b.top - h - 4;
    }
    left = Math.max(8, Math.min(left, vw - w - 8));
    top = Math.max(8, Math.min(top, vh - h - 8));
    setPos({ left, top });
    el.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus();
  }, [x, y, anchor]);

  useEffect(() => {
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node) && !(anchor && anchor.contains(e.target as Node))) onClose(false); };
    const away = (e: Event) => { if (!(ref.current && ref.current.contains(e.target as Node))) onClose(false); };
    document.addEventListener('mousedown', down);
    window.addEventListener('resize', away);
    window.addEventListener('scroll', away, true);
    return () => { document.removeEventListener('mousedown', down); window.removeEventListener('resize', away); window.removeEventListener('scroll', away, true); };
  }, [anchor, onClose]);

  function onKey(e: ReactKeyboardEvent) {
    const list = [...(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])];
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); list[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); list[list.length - 1]?.focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose(true); }
    else if (e.key === 'Tab') { onClose(true); }
  }

  return createPortal(
    <div ref={ref} className="dg-menu" role="menu" aria-label={label} style={{ left: pos.left, top: pos.top }} onKeyDown={onKey}>
      {items.map((it, i) => (
        <Fragment key={it.label + i}>
          <button type="button" role="menuitem" tabIndex={-1} className={it.danger ? 'danger' : undefined} aria-disabled={it.disabled ? true : undefined}
            onClick={() => { if (it.disabled) return; onClose(false); it.onSelect(); }}>{it.label}</button>
        </Fragment>
      ))}
    </div>,
    document.body,
  );
}
