import { useState } from 'react';
import { api, errorMessage } from '@/api/client';
import { Alert, Button } from '@/components/ui';
import './copilot.css';

type Explanation = { code: string; explanation: string; terms: { term: string; meaning: string }[] };

/** Client Q&A helper (spec §21 F1): explains what a question means. It never suggests an answer. */
export function ExplainQuestion({ base, code }: { base: string; code: string }) {
  const [x, setX] = useState<Explanation | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function explain() {
    if (x) { setOpen(!open); return; }
    if (busy) return;
    setBusy(true); setErr(null);
    try { setX(await api.post<Explanation>(`${base}/questions/${code}/explain`)); setOpen(true); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="ai-explain">
      <Button size="sm" onClick={explain} disabled={busy} aria-expanded={open}>{busy ? 'Explaining…' : open ? 'Hide the explanation' : 'Explain this question'}</Button>
      {err && <Alert tone="danger">{err}</Alert>}
      {open && x && (
        <div className="cp-card" role="note" style={{ marginTop: 6 }}>
          <p style={{ margin: 0 }}>{x.explanation}</p>
          {x.terms.length > 0 && <dl className="small" style={{ margin: 0 }}>{x.terms.map((t) => <div key={t.term}><dt style={{ display: 'inline', fontWeight: 600 }}>{t.term}: </dt><dd style={{ display: 'inline', margin: 0 }}>{t.meaning}</dd></div>)}</dl>}
          <p className="small muted" style={{ margin: 0 }}>Written by AI from the question's guidance and glossary. It explains the question only; the answer must come from your team.</p>
        </div>
      )}
    </div>
  );
}
