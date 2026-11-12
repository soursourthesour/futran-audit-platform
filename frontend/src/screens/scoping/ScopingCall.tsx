import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Loading } from '@/components/ui';
import { STATUS_LABELS, usd, type Draft, type Line, type Question, type ScopingView } from '@/api/scoping';
import { QuestionInput } from './QuestionInput';
import { SendQuestionnaire } from './SendQuestionnaire';
import '@/styles/scoping.css';

const CONF: { value: Draft['confidence']; label: string }[] = [
  { value: 'confirmed', label: 'Confirmed' }, { value: 'estimate', label: 'Estimate' }, { value: 'unknown', label: 'Unknown' },
];

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s} s ago` : `${Math.round(s / 60)} min ago`;
}

/** SM-05: record answers on the scoping call. Autosaves every 5 seconds; the suggested line items update as you answer. */
export function ScopingCall() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const key = ['scoping', id];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<ScopingView>(`/scoping/opportunities/${id}`) });
  const [section, setSection] = useState<string>('A');
  const [local, setLocal] = useState<Record<string, Draft>>({});
  const dirty = useRef<Map<string, Draft>>(new Map());
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [err, setErr] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [removing, setRemoving] = useState<Line | null>(null);
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState<Record<string, boolean>>({});
  const started = useRef(false);
  const d = q.data;

  useEffect(() => {
    if (d && !d.questionnaire && d.can_work && !started.current) {
      started.current = true;
      api.post(`/scoping/opportunities/${id}/start`, { mode: 'recorded' }).then(() => qc.invalidateQueries({ queryKey: key })).catch((e) => setErr(errorMessage(e)));
    }
  }, [d, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const flush = useCallback(async () => {
    const qid = q.data?.questionnaire?.id;
    if (!qid || dirty.current.size === 0) return;
    const batch = [...dirty.current.entries()];
    dirty.current.clear();
    try {
      await api.put(`/scoping/${qid}/answers`, { answers: batch.map(([code, v]) => ({ code, value: v.confidence === 'unknown' ? null : v.value, confidence: v.confidence, note: v.note })) });
      setSavedAt(Date.now());
      setErr(null);
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) {
      for (const [code, v] of batch) if (!dirty.current.has(code)) dirty.current.set(code, v);
      setErr(errorMessage(e));
    }
  }, [q.data?.questionnaire?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setInterval(() => { setNow(Date.now()); void flush(); }, 5000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(t); clearInterval(tick); void flush(); };
  }, [flush]);

  const sections = d?.sections ?? [];
  const idx = Math.max(0, sections.findIndex((s) => s.key === section));
  const go = useCallback((k: string) => { void flush(); setSection(k); window.scrollTo({ top: 0 }); }, [flush]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void flush(); }
      if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowRight') && sections[idx + 1]) { e.preventDefault(); go(sections[idx + 1].key); }
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowLeft') && sections[idx - 1]) { e.preventDefault(); go(sections[idx - 1].key); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flush, go, idx, sections]);

  const draftOf = useMemo(() => (code: string): Draft => {
    if (local[code]) return local[code];
    const a = d?.answers?.[code];
    if (!a || a.source === 'derived') return { value: null, confidence: 'confirmed', note: '' };
    return { value: a.value, confidence: a.confidence, note: a.note ?? '' };
  }, [local, d]);

  if (q.isLoading) return <Loading />;
  if (!d) return <div className="sc-page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  if (!d.questionnaire) return <div className="sc-page">{err ? <Alert tone="danger">{err}</Alert> : <Loading label="Starting the questionnaire…" />}</div>;
  const qn = d.questionnaire;
  const locked = qn.locked || !d.can_work;

  function change(code: string, v: Draft) {
    setLocal((m) => ({ ...m, [code]: v }));
    dirty.current.set(code, v);
  }
  const cur = sections[idx];
  const answeredLocal = (s: typeof cur) => s.questions.filter((x) => {
    const v = local[x.code];
    if (v) return v.confidence === 'unknown' || (v.value !== null && v.value !== '' && !(Array.isArray(v.value) && v.value.length === 0));
    return Boolean(d.answers?.[x.code]);
  }).length;
  const lines = d.suggested ?? [];
  const live = lines.filter((l) => !l.removed_reason);
  const est = d.estimate;

  async function removeLine() {
    if (!removing) return;
    try { await api.post(`/scoping/${qn.id}/lines/remove`, { code: removing.code, reason }); setRemoving(null); setReason(''); await qc.invalidateQueries({ queryKey: key }); } catch (e) { setErr(errorMessage(e)); }
  }
  async function restore(l: Line) {
    try { await api.post(`/scoping/${qn.id}/lines/restore`, { code: l.code }); await qc.invalidateQueries({ queryKey: key }); } catch (e) { setErr(errorMessage(e)); }
  }

  function questionCard(x: Question) {
    const dr = draftOf(x.code);
    const a = d!.answers?.[x.code];
    const total = x.type === 'total';
    const derived = total && a?.source === 'derived' && !local[x.code];
    return (
      <fieldset key={x.code} className="sc-q">
        <legend><span className="sc-code">{x.code}</span> {x.label}{x.internal_only && <Badge tone="muted">Internal</Badge>}</legend>
        {x.help && <p className="small muted sc-help">{x.help}</p>}
        {derived && <p className="sc-total">Total: <strong>{a?.display}</strong> <span className="muted">(sum, can be overridden)</span></p>}
        <QuestionInput q={x} draft={dr} onChange={(v) => change(x.code, v)} label={`${x.code} ${x.label}`} disabled={locked} idp="rep" />
        {x.type !== 'text' && (
          <div className="sc-conf" role="radiogroup" aria-label={`Confidence for ${x.code}`}>
            <span className="small muted">Confidence</span>
            {CONF.map((c) => (
              <label key={c.value} className="sc-pill">
                <input type="radio" name={`conf-${x.code}`} disabled={locked} checked={dr.confidence === c.value} onChange={() => change(x.code, { ...dr, confidence: c.value, value: c.value === 'unknown' ? null : dr.value })} />
                {c.label}
              </label>
            ))}
          </div>
        )}
        {a?.client && <p className="small sc-client">Client answered: <strong>{a.client.display}</strong>{a.client.display !== a.display && <Badge tone="warn">Differs — resolve on review</Badge>}</p>}
        {notes[x.code] || dr.note ? (
          <label className="sc-note"><span className="small muted">Note</span>
            <textarea className="input" rows={2} disabled={locked} placeholder="What the customer said" value={dr.note} onChange={(e) => change(x.code, { ...dr, note: e.target.value })} />
          </label>
        ) : !locked && <button type="button" className="linklike small" onClick={() => setNotes((m) => ({ ...m, [x.code]: true }))}>Add a note</button>}
      </fieldset>
    );
  }

  return (
    <div className="sc-page">
      <header className="sc-head">
        <Link to={`/sales/opportunities/${id}`} className="sc-back">Back to opportunity</Link>
        <h1>Scoping call · {d.opportunity.company}</h1>
        <span className="sc-status">{qn.locked ? `Locked · version ${qn.version}` : `${STATUS_LABELS[qn.status] ?? qn.status} · v${qn.version} · ${savedAt ? `autosaved ${ago(now - savedAt)}` : 'autosaves every 5 s'}`}</span>
        <div className="sc-head-actions">
          {!locked && <Button onClick={async () => { await flush(); setSending(true); }}>Send rest to client</Button>}
          <Button variant="primary" onClick={async () => { await flush(); nav(`/sales/opportunities/${id}/scoping/review`); }}>Finish and review</Button>
        </div>
      </header>
      {err && <Alert tone="danger">{err}</Alert>}
      {qn.locked && <Alert tone="info">This version is locked. Open the review to unlock it; that starts version {qn.version + 1}.</Alert>}
      {d.bank?.starter && <p className="small muted sc-starter">Starter question bank — to be replaced with the Sales Collateral questionnaire.</p>}
      <div className="sc-grid">
        <nav aria-label="Sections" className="sc-nav">
          {sections.map((s) => {
            const n = answeredLocal(s);
            const label = s.key === 'RF' ? s.label : `${s.key}. ${s.label}`;
            return (
              <button key={s.key} type="button" aria-current={s.key === cur?.key ? 'step' : undefined} className={`sc-nav-item${s.key === cur?.key ? ' is-current' : ''}`} onClick={() => go(s.key)}>
                <span>{label}</span><span className={n === s.total ? 'sc-done' : ''}>{n === s.total ? 'Done' : `${n}/${s.total}`}</span>
              </button>
            );
          })}
          <p className="small muted sc-keys">Alt + ↓ / ↑ moves between sections. Ctrl + S saves now.</p>
        </nav>
        <main className="sc-main">
          {cur && (
            <>
              <h2 className="sc-h">{cur.key === 'RF' ? cur.label : `${cur.key}. ${cur.label}`}</h2>
              {cur.intro && <p className="muted">{cur.intro}</p>}
              <div className="stack">{cur.questions.map(questionCard)}</div>
              <div className="sc-pager">
                {sections[idx - 1] && <Button onClick={() => go(sections[idx - 1].key)}>Previous section</Button>}
                {sections[idx + 1] && <Button variant="primary" onClick={() => go(sections[idx + 1].key)}>Next section</Button>}
              </div>
            </>
          )}
          {(d.sends?.length ?? 0) > 0 && (
            <section className="sc-sends" aria-label="Sent to the client">
              <h2 className="sc-h">Sent to the client</h2>
              <ul>{d.sends!.map((s) => <li key={s.id}><strong>{s.contact_name}</strong> · {s.answered}/{s.question_count} answered · {STATUS_LABELS[s.status] ?? s.status}{s.forwarded ? ' · forwarded' : ''}</li>)}</ul>
            </section>
          )}
        </main>
        <aside aria-label="Suggested line items" className="sc-aside">
          <h2>Suggested line items</h2>
          <p className="small muted">Updates as you answer. Not shown to the client.</p>
          {(d.rule_errors ?? []).map((e) => <Alert key={e.rule_code} tone="warn">{e.message}</Alert>)}
          {live.length === 0 && <p className="small">Nothing suggested yet.</p>}
          <ul className="sc-lines">
            {live.map((l) => (
              <li key={l.code}>
                <div><strong>{l.code}</strong> {l.name ?? ''} × {l.qty}</div>
                <div className="small muted">{l.reason}</div>
                <div className="row" style={{ gap: 6 }}>
                  {l.sellable_status === 'manual_delivery' && <Badge tone="warn">Manual delivery</Badge>}
                  {l.in_catalog === false && <Badge tone="danger">Not in price list</Badge>}
                  {!locked && <button type="button" className="linklike small" onClick={() => { setRemoving(l); setReason(''); }}>Remove</button>}
                </div>
                {removing?.code === l.code && (
                  <div className="sc-remove">
                    <label className="small" htmlFor={`why-${l.code}`}>Why remove {l.code}?</label>
                    <input id={`why-${l.code}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
                    <div className="row" style={{ gap: 6 }}><Button size="sm" variant="primary" disabled={!reason.trim()} onClick={removeLine}>Remove line</Button><Button size="sm" onClick={() => setRemoving(null)}>Cancel</Button></div>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {lines.some((l) => l.removed_reason) && (
            <details className="small"><summary>Removed ({lines.filter((l) => l.removed_reason).length})</summary>
              <ul className="sc-lines">{lines.filter((l) => l.removed_reason).map((l) => <li key={l.code}><s>{l.code}</s> — {l.removed_reason}{!locked && <> · <button type="button" className="linklike" onClick={() => restore(l)}>Put back</button></>}</li>)}</ul>
            </details>
          )}
          {(d.not_answered_sections ?? []).map((s) => <p key={s} className="small muted">{s} not answered yet</p>)}
          <div className="sc-estimate">
            {est?.available ? (
              <>Running estimate (list): <strong>{usd(est.one_time)}</strong> one-time{est.recurring_y1 ? <> + <strong>{usd(est.recurring_y1)}</strong> recurring year 1</> : null}
                {est.missing.length > 0 && <span className="small muted block">Not priced: {est.missing.join(', ')}</span>}</>
            ) : <span className="small muted">{est?.note ?? 'No running estimate.'}</span>}
          </div>
        </aside>
      </div>
      {sending && <SendQuestionnaire qid={qn.id} onClose={() => setSending(false)} onSent={() => { setSending(false); void qc.invalidateQueries({ queryKey: key }); }} />}
    </div>
  );
}
