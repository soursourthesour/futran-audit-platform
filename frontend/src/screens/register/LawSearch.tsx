import { useEffect, useId, useState } from 'react';
import { api } from '@/api/client';
import { FieldHelp } from '@/components/ui';

type LawGroup = { jurisdiction: { code: string; name: string }; laws: { id: string; short_name: string }[] };

/** Search the law library and pick one law. */
export function LawSearch({ label, help, onPick, exclude = [] }: { label: string; help?: string; onPick: (law: { id: string; name: string }) => void; exclude?: string[] }) {
  const id = useId();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{ id: string; name: string; place: string }[]>([]);
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const groups = await api.get<LawGroup[]>(`/laws?q=${encodeURIComponent(term)}`);
        setResults(groups.flatMap((g) => g.laws.map((l) => ({ id: l.id, name: l.short_name, place: g.jurisdiction.name }))).filter((l) => !exclude.includes(l.id)).slice(0, 12));
      } catch { setResults([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [q, exclude.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="field reg-lawsearch">
      <div className="field-label"><label htmlFor={id}>{label}</label>{help && <FieldHelp label={label}>{help}</FieldHelp>}</div>
      <input id={id} className="input" type="search" placeholder="Search the law library" value={q} onChange={(e) => setQ(e.target.value)} aria-controls={`${id}-list`} />
      {results.length > 0 && (
        <ul id={`${id}-list`} className="reg-lawlist" aria-label="Matching laws">
          {results.map((l) => (
            <li key={l.id}><button type="button" onClick={() => { onPick({ id: l.id, name: l.name }); setQ(''); setResults([]); }}>{l.name} <span className="muted small">· {l.place}</span></button></li>
          ))}
        </ul>
      )}
      {q.trim().length >= 2 && results.length === 0 && <div className="help">No matching law. Try another word.</div>}
    </div>
  );
}
