import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { api } from '@/api/client';
import { ComboInput, type ComboOption } from './ComboInput';
import { FieldHelp } from './FieldHelp';

export type AddressSuggestion = {
  id: string; label: string; street: string | null; city: string | null; state: string | null; state_code: string | null;
  postal_code: string | null; country_code: string | null; needs_details: boolean;
};
type SuggestResult = { available: boolean; provider: string; suggestions: AddressSuggestion[] };

const DEBOUNCE_MS = 300;
const MIN_CHARS = 3;

function newSession(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

/**
 * A text field that suggests full addresses as the user types (three characters, then a short pause). Picking one
 * hands the parts to `onPick`. Typing by hand always works: when suggestions are off or fail, a short note says so.
 * With `label` it renders as a form field; without, pass `aria-label` (for a table cell).
 */
export function AddressField({ label, help, value, onChange, onPick, error, placeholder, disabled, 'aria-label': ariaLabel, compact }: {
  label?: ReactNode; help?: ReactNode; value: string; onChange: (text: string) => void; onPick: (s: AddressSuggestion) => void;
  error?: string; placeholder?: string; disabled?: boolean; 'aria-label'?: string; compact?: boolean;
}) {
  const fid = useId();
  const [items, setItems] = useState<AddressSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [status, setStatus] = useState('');
  const [source, setSource] = useState('');
  const typed = useRef(false);
  const focused = useRef(false);
  const session = useRef<string>(newSession());
  const timer = useRef<number | undefined>(undefined);
  const req = useRef(0);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!typed.current) return;
    const q = value.trim();
    if (q.length < MIN_CHARS) { setItems([]); setOpen(false); return; }
    timer.current = window.setTimeout(async () => {
      const n = ++req.current;
      try {
        const r = await api.get<SuggestResult>(`/geo/suggest?${new URLSearchParams({ q, session: session.current })}`);
        if (n !== req.current) return;
        setUnavailable(!r.available);
        setSource(r.provider);
        setItems(r.suggestions);
        setOpen(focused.current && r.suggestions.length > 0);
        setStatus(r.suggestions.length ? `${r.suggestions.length} address${r.suggestions.length === 1 ? '' : 'es'} found. Use the up and down arrows to choose one.` : '');
      } catch {
        if (n !== req.current) return;
        setUnavailable(true);
        setItems([]);
        setOpen(false);
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer.current);
  }, [value]);

  async function pick(o: ComboOption) {
    let s = items.find((x) => x.id === o.id);
    if (!s) return;
    typed.current = false;
    if (s.needs_details) {
      try {
        s = await api.get<AddressSuggestion>(`/geo/place?${new URLSearchParams({ id: s.id, session: session.current })}`);
      } catch {
        setUnavailable(true);
        return;
      }
    }
    session.current = newSession();
    setItems([]);
    setStatus(`Address filled in: ${s.label}`);
    onPick(s);
  }

  const options: ComboOption[] = items.map((s) => ({ id: s.id, label: s.label }));
  const noteId = `${fid}-note`;
  const describedBy = [error ? `${fid}-err` : null, unavailable ? noteId : null].filter(Boolean).join(' ') || undefined;
  const input = (
    <ComboInput
      id={fid}
      value={value}
      onChange={(t) => { typed.current = true; onChange(t); }}
      options={options}
      open={open}
      onOpenChange={setOpen}
      onPick={pick}
      status={status}
      footer={source === 'photon' ? 'Address data © OpenStreetMap contributors' : source === 'google' ? 'Suggestions from Google' : undefined}
      placeholder={placeholder}
      disabled={disabled}
      aria-label={label ? undefined : ariaLabel}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy}
      onFocus={() => { focused.current = true; if (items.length && typed.current) setOpen(true); }}
      onBlur={() => { focused.current = false; }}
    />
  );
  const note = unavailable && <div className="field-note" id={noteId}>Suggestions unavailable. Type the address.</div>;
  if (!label) return <>{input}{note}{error && <div className="small" id={`${fid}-err`} style={{ color: 'var(--danger)' }}>{error}</div>}</>;
  return (
    <div className={`field${compact ? ' field-compact' : ''}`}>
      {help ? <div className="field-label"><label htmlFor={fid}>{label}</label><FieldHelp label={label}>{help}</FieldHelp></div> : <label htmlFor={fid}>{label}</label>}
      {input}
      {note}
      {error && <div className="error" id={`${fid}-err`}>{error}</div>}
    </div>
  );
}
