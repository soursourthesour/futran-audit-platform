import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
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

/** A modal dialog. Closes on Escape, a click on the backdrop and the close button. Focus moves into it when it opens,
 *  stays inside while it is open and returns to where it was when it closes. `large` is about 760px wide and fills
 *  the screen on a phone. */
export function Dialog({ title, onClose, children, wide, large, label }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean; large?: boolean; label?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null); // read before autoFocus moves it
  useEffect(() => {
    const back = opener.current;
    return () => { if (back && back !== document.body && document.contains(back)) back.focus(); };
  }, []);
  function trap(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') { onClose(); return; }
    if (e.key !== 'Tab' || !box.current) return;
    const f = [...box.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])')].filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  return (
    <div className={`dialog-backdrop${large ? ' has-large' : ''}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }} onKeyDown={trap}>
      <div ref={box} className={`dialog ${wide ? 'dialog-wide' : ''} ${large ? 'dialog-large' : ''}`} role="dialog" aria-modal="true" aria-label={label ?? (typeof title === 'string' ? title : undefined)}>
        <div className="card-header">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} autoFocus aria-label="Close">Close</button>
        </div>
        <div className="card-body">{children}</div>
      </div>
    </div>
  );
}

export function fileUrl(id: string): string {
  return `/api/v1/files/${id}`;
}
