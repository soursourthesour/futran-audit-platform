import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { Link } from 'react-router-dom';

type BtnVariant = 'primary' | 'default' | 'danger' | 'ghost';
export function Button({ variant = 'default', size, block, className = '', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm'; block?: boolean }) {
  const cls = ['btn', variant !== 'default' && `btn-${variant}`, size === 'sm' && 'btn-sm', block && 'btn-block', className].filter(Boolean).join(' ');
  return <button type="button" className={cls} {...rest} />;
}

export function ButtonLink({ to, variant = 'default', size, children }: { to: string; variant?: BtnVariant; size?: 'sm'; children: ReactNode }) {
  const cls = ['btn', variant !== 'default' && `btn-${variant}`, size === 'sm' && 'btn-sm'].filter(Boolean).join(' ');
  return <Link className={cls} to={to}>{children}</Link>;
}

type FieldProps = { label: ReactNode; help?: ReactNode; error?: string; id?: string };

export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(function TextField({ label, help, error, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      <input ref={ref} id={fid} className="input" aria-invalid={error ? true : undefined} aria-describedby={error ? `${fid}-err` : help ? `${fid}-help` : undefined} {...rest} />
      {help && !error && <div className="help" id={`${fid}-help`}>{help}</div>}
      {error && <div className="error" id={`${fid}-err`}>{error}</div>}
    </div>
  );
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps>(function TextArea({ label, help, error, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      <textarea ref={ref} id={fid} className="textarea" aria-invalid={error ? true : undefined} {...rest} />
      {help && !error && <div className="help">{help}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
});

export const SelectField = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & FieldProps & { options: { value: string; label: string }[]; placeholder?: string }>(function SelectField({ label, help, error, id, options, placeholder, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      <select ref={ref} id={fid} className="select" aria-invalid={error ? true : undefined} {...rest}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {help && !error && <div className="help">{help}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
});

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }>(function Checkbox({ label, ...rest }, ref) {
  return (
    <label className="check">
      <input ref={ref} type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
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

/** A modal dialog. Closes on Escape and on the close button; focus moves into it when it opens. */
export function Dialog({ title, onClose, children, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }} onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <div className={`dialog ${wide ? 'dialog-wide' : ''}`} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
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
