import { Children, isValidElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from 'react';

/* Only one help popover is open at a time across the page. */
let openId: string | null = null;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
const current = () => openId;
function setOpen(id: string | null) {
  if (openId === id) return;
  openId = id;
  listeners.forEach((fn) => fn());
}

/** Plain text of a label, for the button's accessible name. Drops a trailing "*" (required marker). */
export function plainText(node: ReactNode): string {
  const walk = (n: ReactNode): string => {
    if (n === null || n === undefined || typeof n === 'boolean') return '';
    if (typeof n === 'string' || typeof n === 'number') return String(n);
    if (Array.isArray(n)) return n.map(walk).join('');
    if (isValidElement<{ children?: ReactNode }>(n)) return Children.toArray(n.props.children).map(walk).join('');
    return '';
  };
  return walk(node).replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim();
}

type Pos = { top: number; left: number; width: number; arrow: number; above: boolean };
const GUTTER = 16;
const GAP = 8;

/**
 * A small circled "i" after a field label. Hover or keyboard focus shows the help; a click or tap pins it open.
 * Escape, a tap outside or opening another one closes it. The popover is fixed-position and kept inside the viewport.
 */
export function FieldHelp({ label, children }: { label: ReactNode; children: ReactNode }) {
  const id = useId();
  const tipId = `${id}-help`;
  const open = useSyncExternalStore(subscribe, current, current) === id;
  const pinned = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const btn = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Pos | null>(null);
  const name = `About ${plainText(label) || 'this field'}`;

  const show = (pin: boolean) => {
    window.clearTimeout(timer.current);
    pinned.current = pin;
    setOpen(id);
  };
  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    pinned.current = false;
    if (current() === id) setOpen(null);
  }, [id]);
  const hideSoon = () => {
    if (pinned.current) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(hide, 150);
  };

  const place = useCallback(() => {
    const b = btn.current?.getBoundingClientRect();
    const t = tip.current;
    if (!b || !t) return;
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const width = Math.min(320, vw - GUTTER * 2);
    t.style.width = `${width}px`;
    const h = t.offsetHeight;
    const centre = b.left + b.width / 2;
    const left = Math.max(GUTTER, Math.min(centre - width / 2, vw - GUTTER - width));
    const roomBelow = vh - b.bottom - GAP;
    const above = h > roomBelow && b.top - GAP - h > 0;
    setPos({ top: above ? b.top - GAP - h : b.bottom + GAP, left, width, arrow: Math.max(12, Math.min(centre - left, width - 12)), above });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
    else setPos(null);
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!btn.current?.contains(t) && !tip.current?.contains(t)) hide();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide(); };
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, hide, place]);

  useEffect(() => () => { window.clearTimeout(timer.current); if (current() === id) setOpen(null); }, [id]);

  return (
    <span className="field-help">
      <button
        ref={btn}
        type="button"
        className="field-help-btn"
        aria-label={name}
        aria-expanded={open}
        aria-controls={open ? tipId : undefined}
        aria-describedby={open ? tipId : undefined}
        onMouseDown={(e) => e.preventDefault()}
        onPointerEnter={(e) => { if (e.pointerType === 'mouse' && !open) show(false); else if (e.pointerType === 'mouse') window.clearTimeout(timer.current); }}
        onPointerLeave={(e) => { if (e.pointerType === 'mouse') hideSoon(); }}
        onFocus={(e) => { if (!open && e.currentTarget.matches(':focus-visible')) show(false); }}
        onBlur={hide}
        onClick={() => { if (open && pinned.current) hide(); else show(true); }}
        onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); hide(); } }}
      >
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="7.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="8" cy="4.9" r="1" fill="currentColor" />
          <path d="M8 7.2v4.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div
          ref={tip}
          id={tipId}
          role="tooltip"
          className={`field-help-pop${pos?.above ? ' above' : ''}`}
          style={pos ? { top: pos.top, left: pos.left, width: pos.width, ['--arrow-x' as string]: `${pos.arrow}px` } : { top: 0, left: 0, visibility: 'hidden' }}
          onPointerEnter={(e) => { if (e.pointerType === 'mouse') window.clearTimeout(timer.current); }}
          onPointerLeave={(e) => { if (e.pointerType === 'mouse') hideSoon(); }}
        >
          {children}
        </div>
      )}
    </span>
  );
}

/** A fieldset whose legend carries a help icon. The group is named by the legend text alone. */
export function FieldGroup({ legend, help, className, legendClassName, style, children }: { legend: ReactNode; help?: ReactNode; className?: string; legendClassName?: string; style?: CSSProperties; children: ReactNode }) {
  const id = useId();
  return (
    <fieldset className={className} style={style} aria-labelledby={`${id}-legend`}>
      <legend className={legendClassName}>
        <span className="label-row"><span id={`${id}-legend`}>{legend}</span>{help && <FieldHelp label={legend}>{help}</FieldHelp>}</span>
      </legend>
      {children}
    </fieldset>
  );
}

/** Heading or other inline text followed by a help icon. */
export function WithHelp({ children, help, label }: { children: ReactNode; help?: ReactNode; label?: ReactNode }) {
  if (!help) return <>{children}</>;
  return <span className="label-row">{children}<FieldHelp label={label ?? children}>{help}</FieldHelp></span>;
}
