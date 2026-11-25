import { forwardRef, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { Link } from 'react-router-dom';
import { FieldHelp } from './FieldHelp';

export { FieldGroup, FieldHelp, WithHelp } from './FieldHelp';

type BtnVariant = 'primary' | 'default' | 'danger' | 'ghost';
export function Button({ variant = 'default', size, block, className = '', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm'; block?: boolean }) {
  const cls = ['btn', variant !== 'default' && `btn-${variant}`, size === 'sm' && 'btn-sm', block && 'btn-block', className].filter(Boolean).join(' ');
  return <button type="button" className={cls} {...rest} />;
}

export function ButtonLink({ to, variant = 'default', size, children }: { to: string; variant?: BtnVariant; size?: 'sm'; children: ReactNode }) {
  const cls = ['btn', variant !== 'default' && `btn-${variant}`, size === 'sm' && 'btn-sm'].filter(Boolean).join(' ');
  return <Link className={cls} to={to}>{children}</Link>;
}

/* Field help: `help` puts a circled "i" after the label with the text in a popover. `hint` stays visible under the
   field; keep it for short text the user must see without asking (password rules, for example). */
type FieldProps = { label: ReactNode; help?: ReactNode; hint?: ReactNode; error?: string; id?: string };

function FieldLabel({ htmlFor, label, help }: { htmlFor: string; label: ReactNode; help?: ReactNode }) {
  if (!help) return <label htmlFor={htmlFor}>{label}</label>;
  return <div className="field-label"><label htmlFor={htmlFor}>{label}</label><FieldHelp label={label}>{help}</FieldHelp></div>;
}

function describedBy(fid: string, error?: string, hint?: ReactNode) {
  return error ? `${fid}-err` : hint ? `${fid}-hint` : undefined;
}

export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(function TextField({ label, help, hint, error, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <FieldLabel htmlFor={fid} label={label} help={help} />
      <input ref={ref} id={fid} className="input" aria-invalid={error ? true : undefined} aria-describedby={describedBy(fid, error, hint)} {...rest} />
      {hint && !error && <div className="help" id={`${fid}-hint`}>{hint}</div>}
      {error && <div className="error" id={`${fid}-err`}>{error}</div>}
    </div>
  );
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps>(function TextArea({ label, help, hint, error, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <FieldLabel htmlFor={fid} label={label} help={help} />
      <textarea ref={ref} id={fid} className="textarea" aria-invalid={error ? true : undefined} aria-describedby={describedBy(fid, error, hint)} {...rest} />
      {hint && !error && <div className="help" id={`${fid}-hint`}>{hint}</div>}
      {error && <div className="error" id={`${fid}-err`}>{error}</div>}
    </div>
  );
});

export const SelectField = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & FieldProps & { options: { value: string; label: string }[]; placeholder?: string }>(function SelectField({ label, help, hint, error, id, options, placeholder, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <FieldLabel htmlFor={fid} label={label} help={help} />
      <select ref={ref} id={fid} className="select" aria-invalid={error ? true : undefined} aria-describedby={describedBy(fid, error, hint)} {...rest}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {hint && !error && <div className="help" id={`${fid}-hint`}>{hint}</div>}
      {error && <div className="error" id={`${fid}-err`}>{error}</div>}
    </div>
  );
});

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; help?: ReactNode }>(function Checkbox({ label, help, ...rest }, ref) {
  const box = (
    <label className="check">
      <input ref={ref} type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
  if (!help) return box;
  return <div className="check-row">{box}<FieldHelp label={label}>{help}</FieldHelp></div>;
});

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-header">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Badge({ tone = 'default', children }: { tone?: 'default' | 'navy' | 'success' | 'warn' | 'danger' | 'muted'; children: ReactNode }) {
  return <span className={`badge ${tone !== 'default' ? `badge-${tone}` : ''}`}>{children}</span>;
}

export function Alert({ tone = 'info', children, role }: { tone?: 'info' | 'danger' | 'success' | 'warn'; children: ReactNode; role?: string }) {
  return <div role={role ?? (tone === 'danger' ? 'alert' : 'status')} className={`alert ${tone !== 'info' ? `alert-${tone}` : ''}`}>{children}</div>;
}

export function PageHeader({ title, subtitle, crumbs, actions }: { title: ReactNode; subtitle?: ReactNode; crumbs?: { to?: string; label: string }[]; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        {crumbs && crumbs.length > 0 && (
          <nav className="breadcrumb" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i}>{c.to ? <Link to={c.to}>{c.label}</Link> : c.label}{i < crumbs.length - 1 ? ' / ' : ''}</span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

/** The wrapper for a table that may scroll sideways (`.table-wrap`). While the table is wider than the wrapper, the
 *  wrapper is a named region and a Tab stop, so a keyboard user can reach it and scroll with the arrow keys (WCAG 2.1.1,
 *  BUG-G02). The name is `label`, or else the table's caption or aria-label. When the table fits, it is a plain wrapper
 *  and adds no Tab stop. */
export function TableWrap({ label, className, style, children }: { label?: string; className?: string; style?: CSSProperties; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);
  const [name, setName] = useState(label);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1);
    check();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(check) : null;
    ro?.observe(el);
    const table = el.querySelector('table');
    if (table) ro?.observe(table);
    return () => ro?.disconnect();
  });
  useLayoutEffect(() => {
    if (label) { setName(label); return; }
    const t = ref.current?.querySelector('table');
    setName(t?.getAttribute('aria-label') || t?.querySelector('caption')?.textContent?.trim() || 'Table');
  }, [label]);
  return (
    <div ref={ref} className={['table-wrap', className].filter(Boolean).join(' ')} style={style}
      {...(scrolls ? { tabIndex: 0, role: 'region', 'aria-label': name } : {})}>
      {children}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Progress({ value, label }: { value: number; label?: string }) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="progress" role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? 'Progress'}>
      <span style={{ width: `${v}%` }} />
    </div>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="empty" role="status">{label}</div>;
}

export function fmtDate(v?: string | null): string {
  if (!v) return '—';
  const d = new Date(v.length === 10 ? v + 'T00:00:00' : v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function fmtDateTime(v?: string | null): string {
  if (!v) return '—';
  const d = new Date(v.endsWith('Z') || v.includes('+') ? v : v + 'Z');
  return d.toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/* The last few elements that had focus, newest last. A dialog opened from a menu item mounts after the item is gone,
   so the dialog returns focus to the newest of these still on the page (the menu's button) instead (BUG-14). */
const focusTrail: HTMLElement[] = [];
if (typeof document !== 'undefined') {
  document.addEventListener('focusin', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t === document.body) return;
    const i = focusTrail.indexOf(t);
    if (i >= 0) focusTrail.splice(i, 1);
    focusTrail.push(t);
    if (focusTrail.length > 20) focusTrail.shift();
  }, true);
}

function focusable(el: HTMLElement | null): el is HTMLElement {
  return !!el && el !== document.body && document.contains(el);
}

function lastFocused(): HTMLElement | null {
  for (let i = focusTrail.length - 1; i >= 0; i--) if (focusable(focusTrail[i])) return focusTrail[i];
  return null;
}

/* Open dialogs, newest last. Keys go to the newest one only, so a dialog opened from a dialog closes first. */
const openDialogs: HTMLElement[] = [];
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])';

function tabStops(box: HTMLElement): HTMLElement[] {
  return [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('data-focus-guard') && (el.offsetParent !== null || el === document.activeElement));
}

/** A modal dialog. Closes on Escape, a click on the backdrop and the close button. Focus moves into it when it opens,
 *  stays inside while it is open and returns to the control that opened it when it closes. When that control is gone
 *  (a menu item, for example), focus returns to the last control still on the page (the menu's button). `large` is
 *  about 760px wide and fills the screen on a phone.
 *
 *  Keys are read on the document, not on the dialog, and two focus guards sit before and after the content. A key press
 *  inside an embedded frame (an email preview) never reaches the page, so Tab out of the frame lands on a guard, which
 *  sends focus back into the dialog, and Escape works again as soon as focus is back on the page (BUG-G07). */
export function Dialog({ title, onClose, children, wide, large, label }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean; large?: boolean; label?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const opener = useRef<HTMLElement | null | undefined>(undefined);
  if (opener.current === undefined && typeof document !== 'undefined') { // read before autoFocus moves it
    const active = document.activeElement as HTMLElement | null;
    opener.current = focusable(active) ? active : lastFocused();
  }
  useEffect(() => {
    const back = opener.current;
    const el = box.current;
    if (el) openDialogs.push(el);
    function onKey(e: globalThis.KeyboardEvent) {
      if (!el || openDialogs[openDialogs.length - 1] !== el || e.defaultPrevented) return;
      if (e.key === 'Escape') { e.preventDefault(); close.current(); return; }
      if (e.key !== 'Tab') return;
      const f = tabStops(el);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1], at = document.activeElement;
      if (!at || !el.contains(at)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
      else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      const i = el ? openDialogs.indexOf(el) : -1;
      if (i >= 0) openDialogs.splice(i, 1);
      const to = focusable(back ?? null) ? back! : lastFocused(); // the dialog's own controls are off the page by now
      to?.focus();
    };
  }, []);
  function guard(end: 'start' | 'end') {
    const f = box.current ? tabStops(box.current) : [];
    (end === 'start' ? f[f.length - 1] : f[0])?.focus();
  }
  return (
    <div className={`dialog-backdrop${large ? ' has-large' : ''}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={box} className={`dialog ${wide ? 'dialog-wide' : ''} ${large ? 'dialog-large' : ''}`} role="dialog" aria-modal="true" aria-label={label ?? (typeof title === 'string' ? title : undefined)}>
        <span tabIndex={0} data-focus-guard="" className="focus-guard" onFocus={() => guard('start')} />
        <div className="card-header">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} autoFocus aria-label="Close">Close</button>
        </div>
        <div className="card-body">{children}</div>
        <span tabIndex={0} data-focus-guard="" className="focus-guard" onFocus={() => guard('end')} />
      </div>
    </div>
  );
}

export function fileUrl(id: string): string {
  return `/api/v1/files/${id}`;
}
