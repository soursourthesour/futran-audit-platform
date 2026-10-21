import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, FieldHelp, Loading, PageHeader, TextArea } from '@/components/ui';
import { scoringHelp } from '@/help/fieldwork';

type Score = {
  system: { id: string; reference_id: string; name: string; built_by: string | null; assessment_depth: string; status: string; vendor: string | null; engagement_id: string; client_id: string };
  methodology_version: string; inherent: number | null; eu_classification?: string | null;
  factors: { key: string; label: string; question: string; answer: string | null; score: number | null; weight: number; points: number | null }[];
  domains: { key: string; label: string; weight: number; proposed: number | null; final: number | null; rationale: string | null; pct_confirmed: number | null; open_findings: number }[];
  maturity: number | null; control_effectiveness?: number | null; residual: number | null; computed_rating: string | null;
  knockouts: { code: string; label: string; force: string; triggered: boolean }[]; final_rating: string | null;
  override: { rating: string; rationale: string; by: string | null } | null; locked: boolean; is_lead_auditor?: boolean; can_score?: boolean;
};

const R = (r: string | null | undefined) => (r ? r[0].toUpperCase() + r.slice(1) : '—');
const TONE: Record<string, 'danger' | 'warn' | 'navy' | 'muted'> = { critical: 'danger', high: 'danger', medium: 'warn', low: 'muted' };
const BUILT: Record<string, string> = { in_house: 'In-house', vendor: 'Vendor-supplied', open_source_customized: 'Open source (customized)', hybrid: 'Hybrid' };
const pct = (w: number) => `${Math.round(w * 100)}%`;

export function SystemScore() {
  const { systemId = '' } = useParams();
  const key = ['score', systemId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Score>(`/systems/${systemId}/score`) });
  const [edit, setEdit] = useState<Score['domains'][number] | null>(null);
  const [rating, setRating] = useState<string | null>(null);
  const [rationale, setRationale] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const s = d.system;
  const editable = !d.locked && !!d.is_lead_auditor;
  const chosen = rating ?? d.override?.rating ?? d.final_rating ?? d.computed_rating ?? '';
  const triggered = d.knockouts.filter((k) => k.triggered);
  async function saveOverride(clear = false) {
    setMsg(null);
    if (!clear && !d.override && chosen === d.final_rating) { setMsg({ tone: 'success', text: 'No change: that is already the final rating.' }); return; }
    try {
      await api.put(`/systems/${systemId}/score/override`, clear ? { rating: null } : { rating: chosen, rationale: rationale || d.override?.rationale || '' });
      await qc.invalidateQueries({ queryKey: key }); setRating(null); setRationale('');
      setMsg({ tone: 'success', text: clear ? 'Override cleared. The final rating follows the score and knock-outs again.' : 'Final rating saved.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const changed = d.domains.filter((x) => x.final !== null && x.proposed !== null && x.final !== x.proposed);
  return (
    <div className="page">
      <PageHeader title={`Risk score: ${s.name}`}
        crumbs={[{ to: `/clients/${s.client_id}/systems`, label: 'AI systems' }, { to: `/systems/${s.id}/assess`, label: `${s.reference_id} ${s.name}` }, { label: 'Risk score' }]}
        subtitle={`${s.built_by ? BUILT[s.built_by] : 'Build type not set'} · ${s.assessment_depth} assessment · methodology v${d.methodology_version} · ${d.locked ? 'locked' : 'recalculates on every answer change until locked'}`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Inherent risk</div><div className="value">{d.inherent ?? '—'}<span className="small muted"> / 100</span></div><div className="hint">{d.inherent === null ? `needs ${d.factors.filter((f) => f.score === null).map((f) => f.question).join(', ')}` : 'impact before controls'}</div></div>
        <div className="tile"><div className="label">Control maturity</div><div className="value">{d.maturity ?? '—'}<span className="small muted"> / 5</span></div><div className="hint">{d.maturity !== null ? `${s.built_by === 'vendor' ? 'vendor' : 'in-house'} weights · effectiveness ${Math.round((d.control_effectiveness ?? 0) * 100)}%` : 'set every domain score below'}</div></div>
        <div className="tile"><div className="label">Residual risk</div><div className="value">{d.residual ?? '—'}</div><div className="hint">{d.residual !== null ? `${d.inherent} × (1 − 0.75 × ${(d.control_effectiveness ?? 0).toFixed(2)})` : ' '}</div></div>
        <div className="tile"><div className="label">Final rating</div><div className="value">{d.maturity !== null || d.override ? R(d.final_rating) : triggered.length ? `≥ ${R(d.final_rating)}` : '—'}</div><div className="hint">{d.computed_rating ? `score band ${R(d.computed_rating)}` : 'score band pending'}{triggered.length ? ` · ${triggered.length} knock-out${triggered.length === 1 ? '' : 's'}` : ''}{d.override ? ' · Lead Auditor override' : ''}</div></div>
      </div>
      <div className="split">
        <div className="main stack">
          <Card title="Inherent risk factors" actions={<span className="small muted">From §3.1–3.3 and §5.1 answers</span>}>
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Factor</th><th>Answer</th><th>Score</th><th>Weight</th><th>Points</th></tr></thead>
              <tbody>
                {d.factors.map((f) => <tr key={f.key}><td>{f.label}<div className="small muted">{f.question}</div></td><td className="small">{f.answer ?? (f.score === null ? <span className="muted">Not answered</span> : '—')}</td><td>{f.score ?? '—'}</td><td>{pct(f.weight)}</td><td>{f.points ?? '—'}</td></tr>)}
                <tr><th colSpan={4}>Inherent risk{d.eu_classification === 'high' ? ' (EU AI Act high-risk floor 70)' : ''}</th><th>{d.inherent ?? '—'}</th></tr>
              </tbody>
            </table></div>
          </Card>
          <Card title="Control maturity by domain (§11)" actions={<span className="small muted">Proposed from evidence-confirmed checklist items; the auditor sets the final score</span>}>
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Domain</th><th>Weight</th><th>Evidence</th><th>Proposed</th><th>Final</th><th /></tr></thead>
              <tbody>{d.domains.map((x) => (
                <tr key={x.key}>
                  <td>{x.label}{x.rationale && <div className="small muted">“{x.rationale}”</div>}</td><td>{pct(x.weight)}</td>
                  <td className="small">{x.pct_confirmed === null ? 'no checklist items' : `${x.pct_confirmed}% confirmed`}{x.open_findings ? ` · ${x.open_findings} High/Critical finding${x.open_findings === 1 ? '' : 's'}` : ''}</td>
                  <td>{x.proposed ?? '—'}</td><td><strong>{x.final ?? '—'}</strong></td>
                  <td>{editable && <Button size="sm" variant="ghost" onClick={() => setEdit(x)}>Set</Button>}</td>
                </tr>
              ))}</tbody>
            </table></div>
            {changed.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>{changed.map((x) => `${x.label} set to ${x.final} (proposed ${x.proposed})`).join('; ')}.</p>}
          </Card>
        </div>
        <div className="side stack">
          <Card title="Knock-out rules">
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }} className="small">
              {d.knockouts.map((k) => <li key={k.code} style={{ padding: '8px 0', borderTop: '1px solid var(--line-soft)' }}>{k.label}<div>{k.triggered ? <Badge tone="danger">Triggered · at least {R(k.force)}</Badge> : <span className="muted">Not triggered</span>}</div></li>)}
            </ul>
            <p className="small muted" style={{ marginBottom: 0 }}>Bands: Critical ≥ 75 · High 50–74.9 · Medium 25–49.9 · Low under 25</p>
          </Card>
          <Card title="Lead Auditor rating">
            {d.override && <p className="small" style={{ marginTop: 0 }}>Set to <Badge tone={TONE[d.override.rating]}>{R(d.override.rating)}</Badge> by {d.override.by}: “{d.override.rationale}”</p>}
            {d.is_lead_auditor && !d.locked ? (
              <div className="stack-sm">
                <div className="label-row"><strong className="small">Final rating</strong><FieldHelp label="Final rating">{scoringHelp.rating}</FieldHelp></div>
                <div className="stack-sm" role="radiogroup" aria-label="Final rating">
                  {['critical', 'high', 'medium', 'low'].map((r) => (
                    <label key={r} className="radio-pill"><input type="radio" name="rating" checked={chosen === r} onChange={() => setRating(r)} />{R(r)}{r === d.computed_rating ? ' (as computed)' : ''}</label>
                  ))}
                </div>
                <TextArea label="Rationale (required if changed)" help={scoringHelp.ratingRationale} value={rationale} onChange={(e) => setRationale(e.target.value)} />
                <div className="row" style={{ gap: 8 }}>
                  <Button variant="primary" onClick={() => saveOverride()}>Save final rating</Button>
                  {d.override && <Button onClick={() => saveOverride(true)}>Clear override</Button>}
                </div>
              </div>
            ) : <p className="small muted" style={{ margin: 0 }}>{d.locked ? 'Locked at sign-off 5.' : 'Only the engagement’s Lead Auditor sets domain scores and the final rating.'}</p>}
            <p className="small muted" style={{ marginBottom: 0 }}>Locking is part of sign-off 5. The engagement rating takes the highest final system rating. <Link to={`/systems/${s.id}/assess`}>Back to the assessment</Link></p>
          </Card>
        </div>
      </div>
      {edit && <DomainDialog systemId={systemId} domain={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); qc.invalidateQueries({ queryKey: key }); }} />}
    </div>
  );
}

function DomainDialog({ systemId, domain, onClose, onDone }: { systemId: string; domain: Score['domains'][number]; onClose: () => void; onDone: () => void }) {
  const [score, setScore] = useState<number>(domain.final ?? domain.proposed ?? 3);
  const [rationale, setRationale] = useState(domain.rationale ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const needs = domain.proposed === null || Math.abs(score - domain.proposed) > 1;
  async function save() {
    try { await api.put(`/systems/${systemId}/score/domains/${domain.key}`, { score, rationale }); onDone(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={domain.label} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small" style={{ margin: 0 }}>Proposed from evidence: <strong>{domain.proposed ?? 'none'}</strong>{domain.pct_confirmed !== null ? ` (${domain.pct_confirmed}% of checklist items confirmed${domain.open_findings ? `, less ${domain.open_findings} for open High/Critical findings` : ''})` : ''}.</p>
        <div className="label-row"><strong className="small">Final score</strong><FieldHelp label="Final score">{scoringHelp.domainScore}</FieldHelp></div>
        <div className="row" role="radiogroup" aria-label="Final score" style={{ gap: 6 }}>
          {[1, 2, 3, 4, 5].map((n) => <label key={n} className="radio-pill"><input type="radio" checked={score === n} onChange={() => setScore(n)} />{n}</label>)}
        </div>
        <TextArea label={needs ? 'Rationale (required: more than 1 from the proposed score)' : 'Rationale (optional)'} help={scoringHelp.domainRationale} value={rationale} onChange={(e) => setRationale(e.target.value)} error={fe.rationale} />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
