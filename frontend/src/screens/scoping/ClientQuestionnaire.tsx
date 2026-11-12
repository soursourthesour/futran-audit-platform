import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Loading, TextField } from '@/components/ui';
import type { Draft, Question } from '@/api/scoping';
import { QuestionInput } from './QuestionInput';
import logoWhite from '@/assets/futran-logo-white.svg';
import '@/styles/scoping.css';

type View = {
  company: string; first_name: string; rep_name: string; due_on: string | null; allow_forward: boolean; submitted: boolean; questions_label: string;
  sections: { key: string; label: string; questions: (Pick<Question, 'code' | 'label' | 'help' | 'type' | 'options'>)[] }[];
  answers: Record<string, { value: unknown; confidence: Draft['confidence'] }>; footer: string; privacy: string;
};

function Shell({ children, company }: { children: React.ReactNode; company?: string }) {
  return (
    <div className="cq">
      <header className="cq-head">
        <span className="cq-brand"><img className="brand-logo" src={logoWhite} alt="Futran Solutions" /></span>
        {company && <span className="cq-for">Scoping questions for {company}</span>}
      </header>
      <main className="cq-main">{children}</main>
    </div>
  );
}

const answered = (d?: Draft) => !!d && (d.confidence === 'unknown' || (d.value !== null && d.value !== undefined && d.value !== '' && !(Array.isArray(d.value) && d.value.length === 0)));

/** SM-07: the client's scoping questions on a phone, behind a personal no-login link. */
export function ClientQuestionnaire() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['client-q', token], queryFn: () => api.get<View>(`/public/q/${token}`), retry: false, refetchOnWindowFocus: false });
  const [step, setStep] = useState(0);
  const [vals, setVals] = useState<Record<string, Draft>>({});
  const dirty = useRef<Set<string>>(new Set());
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [fwdOpen, setFwdOpen] = useState(false);
  const [fwd, setFwd] = useState({ name: '', email: '' });
  const [fwdMsg, setFwdMsg] = useState<string | null>(null);
  const [fwdErr, setFwdErr] = useState<Record<string, string>>({});
  const v = q.data;
  useEffect(() => {
    if (!v) return;
    const init: Record<string, Draft> = {};
    for (const [code, a] of Object.entries(v.answers)) init[code] = { value: a.value, confidence: a.confidence, note: '' };
    setVals(init);
  }, [v]);

  async function save(): Promise<boolean> {
    if (dirty.current.size === 0) return true;
    const codes = [...dirty.current];
    dirty.current.clear();
    try {
      await api.put(`/public/q/${token}/answers`, { answers: codes.map((c) => ({ code: c, value: vals[c]?.confidence === 'unknown' ? null : vals[c]?.value ?? null, confidence: vals[c]?.confidence ?? 'confirmed' })) });
      setSaved('Saved'); setErr(null);
      return true;
    } catch (e) { codes.forEach((c) => dirty.current.add(c)); setErr(errorMessage(e)); return false; }
  }
  useEffect(() => { const t = setInterval(() => { void save(); }, 4000); return () => clearInterval(t); }); // saved as you go

  if (q.isLoading) return <Shell><Loading /></Shell>;
  if (!v) return <Shell><h1 className="cq-h1">These questions are not available</h1><Alert tone="danger">{errorMessage(q.error)}</Alert></Shell>;
  if (done || v.submitted) {
    return <Shell company={v.company}><h1 className="cq-h1">Thank you</h1><p>Your answers have been sent to {v.rep_name} at Futran Solutions.</p><p className="small muted">{v.footer}</p></Shell>;
  }
  const secs = v.sections;
  const s = secs[step];
  const all = secs.flatMap((x) => x.questions);
  const pct = all.length ? Math.round((all.filter((x) => answered(vals[x.code])).length / all.length) * 100) : 0;
  const last = step === secs.length - 1;
  function set(code: string, d: Draft) { setVals((m) => ({ ...m, [code]: d })); dirty.current.add(code); setSaved(null); }

  async function next() {
    if (!(await save())) return;
    if (last) {
      try { await api.post(`/public/q/${token}/submit`); setDone(true); } catch (e) { setErr(errorMessage(e)); }
    } else { setStep(step + 1); window.scrollTo({ top: 0 }); }
  }
  async function forward() {
    setFwdErr({}); setFwdMsg(null);
    try { await save(); const r = await api.post<{ sent_to: string }>(`/public/q/${token}/forward`, fwd); setFwdMsg(`Sent to ${r.sent_to}. They get their own link.`); setFwd({ name: '', email: '' }); setFwdOpen(false); }
    catch (e) { setFwdErr({ ...fieldErrors(e), _: errorMessage(e) }); }
  }

  return (
    <Shell company={v.company}>
      <div className="cq-progress">
        <span>Step {step + 1} of {secs.length} · {s.label}</span><span>{pct}% done</span>
        <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Answered so far"><span style={{ width: `${pct}%` }} /></div>
      </div>
      {step === 0 && <p className="cq-intro">Hello {v.first_name}. {v.questions_label}. "Not sure" is a fine answer.{v.due_on ? ` Please answer by ${new Date(v.due_on + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })}.` : ''}</p>}
      {err && <Alert tone="danger">{err}</Alert>}
      {fwdMsg && <Alert tone="success">{fwdMsg}</Alert>}
      <form className="cq-form" onSubmit={(e) => { e.preventDefault(); void next(); }}>
        {s.questions.map((x) => {
          const d = vals[x.code] ?? { value: null, confidence: 'confirmed' as const, note: '' };
          const unsure = d.confidence === 'unknown';
          return (
            <fieldset key={x.code} className="cq-q">
              <legend>{x.label}</legend>
              {x.help && <p className="small muted">{x.help}</p>}
              <QuestionInput q={{ ...x, client_label: null, section: s.key, section_label: s.label, sum_of: [], client_visible: true, internal_only: false, unknown_assumption: null, order: 0, active: true }}
                draft={d} onChange={(nd) => set(x.code, nd)} label={x.label} idp="client" />
              <label className="sc-option cq-unsure">
                <input type={x.type === 'single' || x.type === 'yes_no' ? 'radio' : 'checkbox'} name={x.type === 'single' || x.type === 'yes_no' ? `client-${x.code}` : undefined}
                  checked={unsure} onChange={(e) => set(x.code, { value: null, confidence: (e.target as HTMLInputElement).checked ? 'unknown' : 'confirmed', note: '' })} />
                <span>Not sure</span>
              </label>
            </fieldset>
          );
        })}
        {v.allow_forward && (
          fwdOpen ? (
            <fieldset className="cq-q">
              <legend>Forward these questions to a colleague</legend>
              <p className="small muted">They get their own link. Your answers so far are kept.</p>
              {fwdErr._ && <Alert tone="danger">{fwdErr._}</Alert>}
              <TextField label="Their name" value={fwd.name} onChange={(e) => setFwd({ ...fwd, name: e.target.value })} error={fwdErr.contact} />
              <TextField label="Their work email" type="email" value={fwd.email} onChange={(e) => setFwd({ ...fwd, email: e.target.value })} error={fwdErr.email} />
              <div className="row" style={{ gap: 8 }}><Button type="button" variant="primary" onClick={forward} disabled={!fwd.name || !fwd.email}>Send to colleague</Button><Button type="button" onClick={() => setFwdOpen(false)}>Cancel</Button></div>
            </fieldset>
          ) : <button type="button" className="linklike cq-forward" onClick={() => setFwdOpen(true)}>Forward these questions to a colleague</button>
        )}
        <div className="cq-actions">
          <Button type="button" disabled={step === 0} onClick={async () => { await save(); setStep(step - 1); }}>Back</Button>
          <Button type="submit" variant="primary">{last ? 'Submit answers' : 'Save and continue'}</Button>
        </div>
        {saved && <p className="small muted" role="status">{saved}</p>}
      </form>
      <footer className="cq-foot">
        <p>Saved as you go. Used only to prepare Futran's proposal. {v.footer.split('. ')[0]}.</p>
        <p>{v.privacy}</p>
      </footer>
    </Shell>
  );
}
