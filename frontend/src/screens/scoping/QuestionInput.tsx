import type { Draft, Question } from '@/api/scoping';

/** One answer control by question type. Shared by SM-05 (rep) and SM-07 (client). `idp` keeps ids unique on the page. */
export function QuestionInput({ q, draft, onChange, label, disabled, idp = 'q' }: { q: Question; draft: Draft; onChange: (d: Draft) => void; label: string; disabled?: boolean; idp?: string }) {
  const unknown = draft.confidence === 'unknown';
  const id = `${idp}-${q.code}`;
  const set = (value: unknown) => onChange({ ...draft, value, confidence: draft.confidence === 'unknown' ? 'confirmed' : draft.confidence });
  if (q.type === 'count' || q.type === 'total') {
    return (
      <input id={id} className="input sc-num" type="number" inputMode="numeric" min={0} step={1} aria-label={label} disabled={disabled || unknown}
        value={unknown || draft.value === null || draft.value === undefined ? '' : String(draft.value)} placeholder={unknown ? 'Unknown' : 'Enter a number'}
        onChange={(e) => set(e.target.value === '' ? null : Number(e.target.value))} />
    );
  }
  if (q.type === 'text') {
    return <textarea id={id} className="input sc-text" rows={2} aria-label={label} disabled={disabled || unknown} value={unknown ? '' : String(draft.value ?? '')} onChange={(e) => set(e.target.value)} />;
  }
  if (q.type === 'multi') {
    const cur = Array.isArray(draft.value) ? (draft.value as string[]) : [];
    return (
      <div className="sc-options" role="group" aria-label={label}>
        {q.options.map((o) => (
          <label key={o.value} className="sc-option">
            <input type="checkbox" disabled={disabled || unknown} checked={cur.includes(o.value)} onChange={(e) => set(e.target.checked ? [...cur, o.value] : cur.filter((v) => v !== o.value))} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    );
  }
  return (
    <div className="sc-options" role="radiogroup" aria-label={label}>
      {q.options.map((o) => (
        <label key={o.value} className="sc-option">
          <input type="radio" name={id} disabled={disabled} checked={!unknown && draft.value === o.value} onChange={() => onChange({ ...draft, value: o.value, confidence: unknown ? 'confirmed' : draft.confidence })} />
          <span>{o.label}</span>
        </label>
      ))}
    </div>
  );
}
