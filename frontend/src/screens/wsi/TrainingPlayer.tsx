import { useState } from 'react';
import { api, errorMessage } from '@/api/client';
import type { Answered, FinishResult, PlayerState } from '@/api/wsi';
import { Alert, Button } from '@/components/ui';
import './wsi.css';

/** The employee's module player (screen 33, EmployeeTraining): pages, then a short quiz with feedback after each answer.
 *  `base` is `/learn/{id}` for a signed-in person or `/public/training/{token}` for the email link. */
export function TrainingPlayer({ state, base, organization }: { state: PlayerState; base: string; organization: string }) {
  const m = state.module;
  const total = m.pages.length + m.quiz.length;
  const [pos, setPos] = useState(0);
  const [answered, setAnswered] = useState<Record<string, Answered>>(state.answered ?? {});
  const [picked, setPicked] = useState<string | null>(null);
  const [result, setResult] = useState<FinishResult | null>(state.status === 'completed' ? { passed: true, score: state.score ?? 0, attempts: state.attempts, status: 'completed', certificate_no: null } : null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pct = Math.round((100 * Math.min(pos, total)) / Math.max(total, 1));
  const header = (
    <div style={{ background: 'var(--navy)', color: '#fff', padding: '16px 18px', borderRadius: 8 }}>
      <div className="small" style={{ color: '#c9d6ea' }}>{organization} · AI training · {m.minutes} min</div>
      <h1 style={{ fontSize: 19, margin: '2px 0 10px', color: '#fff' }}>{m.title}</h1>
      <div className="wsi-meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${pct}% through module`} style={{ background: 'rgba(255,255,255,0.3)' }}><span style={{ width: `${pct}%` }} /></div>
    </div>
  );
  if (result) {
    return (
      <div className="stack">
        {header}
        {result.passed ? (
          <>
            <Alert tone="success">Completed with {result.score}%. Thank you.</Alert>
            <a className="btn btn-primary btn-block" href={`/api/v1${base}/certificate`}>Download your certificate</a>
          </>
        ) : (
          <>
            <Alert tone="warn">You scored {result.score}%. The pass mark is {result.pass_mark ?? m.pass_mark}%. Read the module again and retry the questions.</Alert>
            <Button variant="primary" block onClick={() => { setResult(null); setAnswered({}); setPos(0); setPicked(null); }}>Start again</Button>
          </>
        )}
      </div>
    );
  }
  async function check(qid: string, option: string) {
    setBusy(true); setErr(null);
    try { const r = await api.post<Answered & { question_id: string }>(`${base}/check`, { question_id: qid, option_id: option }); setAnswered({ ...answered, [qid]: r }); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function finish() {
    setBusy(true); setErr(null);
    try { setResult(await api.post<FinishResult>(`${base}/finish`)); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const onPage = pos < m.pages.length;
  const page = onPage ? m.pages[pos] : null;
  const q = !onPage ? m.quiz[pos - m.pages.length] : null;
  const a = q ? answered[q.id] : undefined;
  const last = pos === total - 1;
  return (
    <div className="stack">
      {header}
      {err && <Alert tone="danger">{err}</Alert>}
      {page && (
        <section className="stack-sm" aria-labelledby="tp-page-h">
          <h2 id="tp-page-h" style={{ fontSize: 17, margin: 0 }}>{page.title}</h2>
          {(page.paragraphs ?? []).map((t, i) => <p key={i} style={{ margin: 0, lineHeight: 1.55 }} className={i === 0 ? 'wsi-note' : undefined}>{t}</p>)}
          {page.points && <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6 }}>{page.points.map((t, i) => <li key={i}>{t}</li>)}</ul>}
        </section>
      )}
      {q && (
        <fieldset style={{ border: 'none', margin: 0, padding: 0 }} className="stack-sm">
          <legend style={{ fontWeight: 600, fontSize: 15.5, marginBottom: 8 }}>Quick check {pos - m.pages.length + 1} of {m.quiz.length}: {q.question}</legend>
          {q.options.map((o) => {
            const cls = a ? (o.id === a.correct_option ? 'right' : o.id === a.option_id ? 'wrong' : '') : '';
            return (
              <label key={o.id} className={`wsi-opt ${cls}`}>
                <input type="radio" name={q.id} value={o.id} checked={(a?.option_id ?? picked) === o.id} disabled={Boolean(a) || busy} onChange={() => setPicked(o.id)} />
                <span>{o.text}</span>
              </label>
            );
          })}
          {a ? <p role="status" style={{ margin: 0, fontWeight: 600, color: a.correct ? 'var(--success)' : 'var(--danger)' }}>{a.correct ? 'Correct.' : 'Not quite.'} <span style={{ fontWeight: 400, color: 'var(--ink)' }}>{a.explanation}</span></p>
            : <Button variant="primary" disabled={!picked || busy} onClick={() => picked && check(q.id, picked)}>Check my answer</Button>}
        </fieldset>
      )}
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <Button block disabled={pos === 0 || busy} onClick={() => { setPos(pos - 1); setPicked(null); }}>Back</Button>
        {last ? <Button variant="primary" block disabled={busy || Object.keys(answered).length < m.quiz.length} onClick={finish}>Finish</Button>
          : <Button variant="primary" block disabled={busy || (Boolean(q) && !a)} onClick={() => { setPos(pos + 1); setPicked(null); }}>Next</Button>}
      </div>
    </div>
  );
}
