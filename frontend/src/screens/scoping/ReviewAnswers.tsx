import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Loading } from '@/components/ui';
import { SOURCE_LABELS, type AnswerOut, type Line, type ScopingView } from '@/api/scoping';
import '@/styles/scoping.css';

type Review = {
  questionnaire: ScopingView['questionnaire'] & object; company: string; opportunity_id: string; summary: string;
  counts: { answered: number; total: number; conflicts: number; unknown: number; lines: number };
  conflicts: { code: string; label: string; rep: AnswerOut; client: AnswerOut; effect: string }[];
  unknowns: { code: string; label: string; effect: string; assumption: string | null }[];
  answers: { code: string; label: string; section: string; internal_only: boolean; rep: AnswerOut | null; client: AnswerOut | null; used: AnswerOut | null }[];
  suggested: Line[]; rule_errors: { rule_code: string; message: string }[]; assumptions: { code: string; text: string }[]; can_work: boolean; can_build_proposal: boolean; build_note: string | null;
  versions: { id: string; version: number; status: string }[];
};

const show = (a: AnswerOut | null) => (a ? `${a.display}${a.confidence === 'estimate' ? ' (estimate)' : ''}` : '—');

/** SM-08: rep and client answers side by side, conflicts to settle, unknowns and their effect, then lock. */
export function ReviewAnswers() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const base = useQuery({ queryKey: ['scoping', id], queryFn: () => api.get<ScopingView>(`/scoping/opportunities/${id}`) });
  const qid = base.data?.questionnaire?.id;
  const r = useQuery({ queryKey: ['scoping-review', qid], queryFn: () => api.get<Review>(`/scoping/${qid}/review`), enabled: !!qid });
  const [keep, setKeep] = useState<Record<string, { keep: string; value: string }>>({});
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['scoping-review'] }); await qc.invalidateQueries({ queryKey: ['scoping', id] }); };

  if (base.isLoading || (qid && r.isLoading)) return <Loading />;
  if (!base.data) return <div className="sc-page"><Alert tone="danger">{errorMessage(base.error)}</Alert></div>;
  if (!qid) return <div className="sc-page"><Alert tone="info">No questionnaire yet. <Link to={`/sales/opportunities/${id}/scoping`}>Start the scoping call</Link>.</Alert></div>;
  const d = r.data;
  if (!d) return <div className="sc-page"><Alert tone="danger">{errorMessage(r.error)}</Alert></div>;
  const q = d.questionnaire;
  const editable = d.can_work && !q.locked;

  async function resolve(code: string) {
    const k = keep[code];
    if (!k) return;
    try {
      await api.post(`/scoping/${qid}/resolve`, { code, keep: k.keep, value: k.keep === 'other' ? (k.value.trim() === '' || Number.isNaN(Number(k.value)) ? k.value : Number(k.value)) : null });
      setMsg({ tone: 'success', text: `${code} settled.` }); await refresh();
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function lock(build: boolean) {
    setBusy(true);
    try {
      const out = await api.post<{ version: number; proposal_id: string | null }>(`/scoping/${qid}/lock`, { build_proposal: build });
      await refresh();
      if (out.proposal_id) nav(`/sales/proposals/${out.proposal_id}`);
      else setMsg({ tone: 'success', text: `Version ${out.version} locked.` });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  async function unlock() {
    try { const out = await api.post<{ version: number }>(`/scoping/${qid}/unlock`); await refresh(); setMsg({ tone: 'success', text: `Version ${out.version} started. Edit the answers on the scoping call.` }); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }

  return (
    <div className="sc-page">
      <nav className="breadcrumb" aria-label="Breadcrumb"><Link to={`/sales/opportunities/${id}`}>{d.company}</Link> / <Link to={`/sales/opportunities/${id}/scoping`}>Scoping call</Link> / Review</nav>
      <div className="sc-review-head">
        <div>
          <h1>Review answers</h1>
          <p className="muted">{d.summary}{q.locked && <> · <Badge tone="navy">Locked</Badge> by {q.locked_by_name}</>}</p>
        </div>
        {d.versions.length > 1 && <p className="small muted">Versions: {d.versions.map((v) => `v${v.version} ${v.status === 'locked' ? '(locked)' : ''}`).join(' · ')}</p>}
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="sc-kpis">
        <div><span>Answered</span><strong>{d.counts.answered} / {d.counts.total}</strong></div>
        <div className={d.counts.conflicts ? 'is-warn' : ''}><span>Conflicts to resolve</span><strong>{d.counts.conflicts}</strong></div>
        <div><span>Unknown</span><strong>{d.counts.unknown}</strong></div>
        <div><span>Proposed line items</span><strong>{d.counts.lines}</strong></div>
      </div>

      <section className="card sc-card" aria-labelledby="sc-conflicts">
        <h2 id="sc-conflicts">Conflicts</h2>
        {d.conflicts.length === 0 ? <p className="muted">No conflicts. Client answers match the rep's, or have been settled.</p> : (
          <div className="sc-table-wrap"><table className="sc-table">
            <thead><tr><th>Question</th><th>Rep (on call)</th><th>Client (link)</th><th>Effect on price</th><th>Keep</th></tr></thead>
            <tbody>{d.conflicts.map((c) => (
              <tr key={c.code}>
                <td><strong>{c.code}</strong> {c.label}</td><td>{show(c.rep)}</td><td>{show(c.client)}</td><td>{c.effect}</td>
                <td>
                  <fieldset className="sc-keep"><legend className="sr-only">Keep for {c.code}</legend>
                    {(['rep', 'client', 'other'] as const).map((k) => (
                      <label key={k} className="sc-pill"><input type="radio" name={`keep-${c.code}`} disabled={!editable} checked={keep[c.code]?.keep === k} onChange={() => setKeep({ ...keep, [c.code]: { keep: k, value: keep[c.code]?.value ?? '' } })} />{k === 'rep' ? 'Rep' : k === 'client' ? 'Client' : 'Other'}</label>
                    ))}
                    {keep[c.code]?.keep === 'other' && <input className="input sc-num" aria-label={`Other value for ${c.code}`} value={keep[c.code].value} onChange={(e) => setKeep({ ...keep, [c.code]: { keep: 'other', value: e.target.value } })} />}
                    {editable && <Button size="sm" disabled={!keep[c.code]} onClick={() => resolve(c.code)}>Settle</Button>}
                  </fieldset>
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      <section className="card sc-card" aria-labelledby="sc-unknown">
        <h2 id="sc-unknown">Unknown answers</h2>
        {d.unknowns.length === 0 ? <p className="muted">No unknown answers.</p> : (
          <div className="sc-table-wrap"><table className="sc-table">
            <thead><tr><th>Question</th><th>Effect</th><th>Proposal assumption added</th></tr></thead>
            <tbody>{d.unknowns.map((u) => <tr key={u.code}><td><strong>{u.code}</strong> {u.label}</td><td>{u.effect}</td><td>{u.assumption ? `"${u.assumption}"` : '—'}</td></tr>)}</tbody>
          </table></div>
        )}
      </section>

      <section className="card sc-card" aria-labelledby="sc-lines">
        <h2 id="sc-lines">Proposed line items</h2>
        {d.rule_errors.map((e) => <Alert key={e.rule_code} tone="warn">{e.message}</Alert>)}
        <ul className="sc-lines">{d.suggested.map((l) => <li key={l.code}>{l.removed_reason ? <><s>{l.code} × {l.qty}</s> — removed: {l.removed_reason}</> : <><strong>{l.code}</strong> × {l.qty} <span className="small muted">— {l.reason}</span></>}</li>)}</ul>
      </section>

      <details className="card sc-card">
        <summary><h2 className="sc-inline">All answers, rep and client side by side</h2></summary>
        <div className="sc-table-wrap"><table className="sc-table">
          <thead><tr><th>Question</th><th>Rep</th><th>Client</th><th>Used</th></tr></thead>
          <tbody>{d.answers.map((a) => <tr key={a.code}><td><strong>{a.code}</strong> {a.label}{a.internal_only && <> <Badge tone="muted">Internal</Badge></>}</td><td>{show(a.rep)}</td><td>{show(a.client)}</td><td>{show(a.used)} <span className="small muted">{a.used ? SOURCE_LABELS[a.used.source] ?? a.used.source : ''}</span></td></tr>)}</tbody>
        </table></div>
      </details>

      <div className="sc-review-foot">
        <p className="small muted">{q.locked ? `Version ${q.version} is locked. Unlocking starts version ${q.version + 1}; this one stays as it is.` : `Locking creates version ${q.version}. Edits after that create version ${q.version + 1}.`}</p>
        {d.build_note && !q.locked && <p className="small">{d.build_note}</p>}
        <div className="row" style={{ gap: 8 }}>
          {q.locked ? (d.can_work && <Button onClick={unlock}>Unlock for edits</Button>) : <Link className="btn" to={`/sales/opportunities/${id}/scoping`}>Edit answers</Link>}
          {editable && !d.can_build_proposal && <Button variant="primary" disabled={busy || d.counts.conflicts > 0} onClick={() => lock(false)}>Lock questionnaire</Button>}
          {editable && <Button variant={d.can_build_proposal ? 'primary' : 'default'} disabled={busy || d.counts.conflicts > 0 || !d.can_build_proposal} onClick={() => lock(true)} title={d.build_note ?? undefined}>Lock and build proposal</Button>}
        </div>
      </div>
    </div>
  );
}
