import { useEffect, useId, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { useCountries, useSubdivisions } from '@/api/clients';
import { useLaws } from '@/api/laws';
import type { LawSuggestion, Place } from '@/api/register';
import { Button, EmptyState, FieldGroup, FieldHelp, Loading, SelectField, TextField } from '@/components/ui';
import { placeHelp as H } from '@/help/register';

/* 11-03 C14: where a system runs, where the people whose data it uses are, the laws suggested from those places and
   the system's features (the law library's own logic, no AI), and a law library dropdown. */

export function PlaceFields({ value, onChange, legend, help, disabled, onRemove }: { value: Place; onChange: (p: Place) => void; legend: string; help?: string; disabled?: boolean; onRemove?: () => void }) {
  const countries = useCountries();
  const subs = useSubdivisions(value.country || null);
  const regions = (subs.data ?? []).filter((x) => x.level === 'state').slice().sort((a, b) => a.name.localeCompare(b.name));
  return (
    <FieldGroup legend={legend} help={help}>
      <div className="reg-place">
        <SelectField label="Country" value={value.country} placeholder="Choose" disabled={disabled}
          onChange={(e) => onChange({ country: e.target.value, region: null, city: value.city ?? null })}
          options={(countries.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)).map((c) => ({ value: c.code, label: c.name }))} />
        <SelectField label="State or region" value={value.region ?? ''} placeholder={regions.length ? 'All of the country' : 'None listed'} disabled={disabled || !value.country || !regions.length}
          onChange={(e) => onChange({ ...value, region: e.target.value || null })} options={regions.map((r) => ({ value: r.code, label: r.name }))} />
        <TextField label="City" value={value.city ?? ''} disabled={disabled || !value.country} onChange={(e) => onChange({ ...value, city: e.target.value || null })} />
        {onRemove && <div className="reg-place-x"><Button size="sm" variant="ghost" onClick={onRemove} disabled={disabled} aria-label={`Remove ${legend}`}>Remove</Button></div>}
      </div>
    </FieldGroup>
  );
}

export function Places({ run, data, onRun, onData, disabled }: { run: Place | null; data: Place[]; onRun: (p: Place | null) => void; onData: (p: Place[]) => void; disabled?: boolean }) {
  return (
    <div className="stack">
      <PlaceFields legend="Where it runs" help={H.run} value={run ?? { country: '' }} disabled={disabled} onChange={(p) => onRun(p.country ? p : null)} />
      <div className="stack-sm">
        <div className="field-label"><strong>Where the people whose data it uses are</strong><FieldHelp label="Where the people whose data it uses are">{H.data}</FieldHelp></div>
        {data.length === 0 && <p className="small muted" style={{ margin: 0 }}>No place added. Add each country, state or city where the candidates, patients, customers or employees are.</p>}
        {data.map((p, i) => (
          <PlaceFields key={i} legend={`Place ${i + 1}`} value={p} disabled={disabled} onChange={(x) => onData(data.map((y, j) => (j === i ? x : y)))} onRemove={() => onData(data.filter((_, j) => j !== i))} />
        ))}
        <div className="row">
          <Button size="sm" disabled={disabled} onClick={() => onData([...data, { country: run?.country ?? '' }])}>Add a place</Button>
          {run?.country && <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onData([...data, { ...run }])}>Add where it runs</Button>}
        </div>
      </div>
    </div>
  );
}

export type Draft = Record<string, unknown>;

/** Laws suggested for a draft system. Suggestions are worked out on the server from the places and features; nothing is saved. */
export function useLawSuggestions(draft: Draft, exclude: string[], enabled: boolean) {
  const [rows, setRows] = useState<LawSuggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify([draft, exclude]);
  useEffect(() => {
    if (!enabled) { setRows(null); return; }
    let live = true;
    setBusy(true);
    const t = setTimeout(async () => {
      try { const r = await api.post<LawSuggestion[]>('/register/law-suggestions', { ...draft, exclude }); if (live) setRows(r); } catch { if (live) setRows([]); } finally { if (live) setBusy(false); }
    }, 350);
    return () => { live = false; clearTimeout(t); };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return { rows, busy };
}

export function SuggestionList({ rows, busy, onAccept, onRemove, disabled, empty }: { rows: LawSuggestion[] | null; busy?: boolean; onAccept: (s: LawSuggestion) => void; onRemove: (s: LawSuggestion) => void; disabled?: boolean; empty: string }) {
  if (rows === null && busy) return <Loading label="Looking for laws…" />;
  if (!rows?.length) return <p className="small muted" style={{ margin: 0 }}>{empty}</p>;
  return (
    <ul className="reg-suggest" aria-label="Suggested laws">
      {rows.map((s) => (
        <li key={s.regulation_id}>
          <div className="reg-suggest-text">
            <strong>{s.short_name}</strong>{s.jurisdiction && <span className="small muted"> · {s.jurisdiction}</span>}
            {s.reason && <div className="small">Why: {s.reason}</div>}
          </div>
          {!disabled && <div className="row reg-suggest-act">
            <Button size="sm" variant="primary" onClick={() => onAccept(s)} aria-label={`Accept ${s.short_name}`}>Accept</Button>
            <Button size="sm" variant="ghost" onClick={() => onRemove(s)} aria-label={`Remove suggestion ${s.short_name}`}>Remove</Button>
          </div>}
        </li>
      ))}
    </ul>
  );
}

/** Any law from the law library, grouped by jurisdiction. */
export function LawSelect({ onPick, exclude = [], disabled }: { onPick: (law: { id: string; name: string }) => void; exclude?: string[]; disabled?: boolean }) {
  const id = useId();
  const laws = useLaws('all', '', '');
  const groups = useMemo(() => (laws.data ?? []).map((g) => ({ name: g.jurisdiction.name, laws: g.laws.filter((l) => !exclude.includes(l.id)) })).filter((g) => g.laws.length), [laws.data, exclude.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="field">
      <div className="field-label"><label htmlFor={id}>Law library</label><FieldHelp label="Law library">{H.library}</FieldHelp></div>
      {laws.isLoading ? <EmptyState>Loading the law library…</EmptyState> : (
        <select id={id} className="select" value="" disabled={disabled} onChange={(e) => {
          const law = groups.flatMap((g) => g.laws).find((l) => l.id === e.target.value);
          if (law) onPick({ id: law.id, name: law.short_name });
        }}>
          <option value="">Choose a law to add</option>
          {groups.map((g) => <optgroup key={g.name} label={g.name}>{g.laws.map((l) => <option key={l.id} value={l.id}>{l.short_name}</option>)}</optgroup>)}
        </select>
      )}
    </div>
  );
}
