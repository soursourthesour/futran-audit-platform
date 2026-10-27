import { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useLayoutEffect, useRef, useState, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react';
import '@/styles/staff-forms.css';

export type ComboOption = { id: string; label: string; detail?: string };

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'onSelect' | 'onChange' | 'value'> & {
  value: string;
  onChange: (text: string) => void;
  options: ComboOption[];
  /** Show the list. The parent decides (after a fetch, on focus, and so on). */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (option: ComboOption) => void;
  /** Read out when the list changes, for screen readers. */
  status?: string;
  emptyText?: ReactNode;
  /** A line under the options, for example a data source credit. */
  footer?: ReactNode;
};

/**
 * A text input with a suggestion list (ARIA 1.2 combobox with a listbox popup). Arrow keys move through the options,
 * Enter picks one, Escape closes the list. The list is fixed-position so a table or card never clips it.
 */
export const ComboInput = forwardRef<HTMLInputElement, Props>(function ComboInput({ value, onChange, options, open, onOpenChange, onPick, status, emptyText, footer, className, onKeyDown, onBlur, ...rest }, ref) {
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => input.current as HTMLInputElement);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; width: number; maxHeight: number } | null>(null);
  const shown = open && (options.length > 0 || !!emptyText);

  useEffect(() => { setActive(-1); }, [options]);

  const place = useCallback(() => {
    const r = input.current?.getBoundingClientRect();
    if (!r) return;
    const vw = document.documentElement.clientWidth;
    const width = Math.min(Math.max(r.width, 280), vw - 32);
    const left = Math.max(16, Math.min(r.left, vw - 16 - width));
    const below = window.innerHeight - r.bottom - 12;
    const above = r.top - 12;
    if (below < 200 && above > below) setPos({ bottom: window.innerHeight - r.top + 4, left, width, maxHeight: Math.min(320, above) });
    else setPos({ top: r.bottom + 4, left, width, maxHeight: Math.max(120, Math.min(320, below)) });
  }, []);

  useLayoutEffect(() => { if (shown) place(); }, [shown, place, options]);
  useEffect(() => {
    if (!shown) return;
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => { window.removeEventListener('scroll', place, true); window.removeEventListener('resize', place); };
  }, [shown, place]);

  function pick(o: ComboOption) {
    onPick(o);
    onOpenChange(false);
  }

  function key(e: KeyboardEvent<HTMLInputElement>) {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) { onOpenChange(true); return; }
      setActive((a) => (options.length ? (a + 1) % options.length : -1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { onOpenChange(true); return; }
      setActive((a) => (options.length ? (a <= 0 ? options.length - 1 : a - 1) : -1));
    } else if (e.key === 'Enter' && shown && active >= 0 && options[active]) {
      e.preventDefault();
      pick(options[active]);
    } else if (e.key === 'Escape' && shown) {
      e.preventDefault();
      e.stopPropagation();
      onOpenChange(false);
    } else if (e.key === 'Tab' && shown) {
      onOpenChange(false);
    }
  }

  useEffect(() => {
    if (active < 0) return;
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [active, listId]);

  return (
    <>
      <input
        ref={input}
        className={className ?? 'input'}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={listId}
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={key}
        onBlur={(e) => { onOpenChange(false); onBlur?.(e); }}
        {...rest}
      />
      <ul id={listId} role="listbox" aria-label="Suggestions" className="combo-list" hidden={!shown}
        style={pos ? { top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width, maxHeight: pos.maxHeight } : undefined}>
        {shown && options.map((o, i) => (
          <li key={o.id} id={`${listId}-${i}`} role="option" aria-selected={i === active} className="combo-option"
            onMouseDown={(e) => e.preventDefault()} onClick={() => pick(o)} onMouseMove={() => setActive(i)}>
            <span>{o.label}</span>{o.detail && <span className="combo-detail">{o.detail}</span>}
          </li>
        ))}
        {shown && options.length === 0 && emptyText && <li className="combo-empty" role="presentation">{emptyText}</li>}
        {shown && options.length > 0 && footer && <li className="combo-footer" role="presentation" onMouseDown={(e) => e.preventDefault()}>{footer}</li>}
      </ul>
      <span className="sr-only" role="status" aria-live="polite">{status ?? ''}</span>
    </>
  );
});
