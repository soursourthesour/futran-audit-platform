import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useLawJurisdictions, type Law } from '@/api/laws';
import { Alert, Badge, Button, Card, EmptyState, Loading, fmtDateTime } from '@/components/ui';

type Proposal = {
  id: string;
  change_type: 'add' | 'update' | 'retire';
  status: 'pending' | 'accepted' | 'rejected';
  jurisdiction: string;
  proposed: Record<string, string>;
  rationale: string;
  sources: { title: string; url: string }[];
  current: Law | null;
};
type Run = { id: string; status: string; error: string | null; warnings: string[]; jurisdictions: string[]; created_at: string; counts: Record<string, number>; proposals?: Proposal[] };
type Settings = { law_refresh_enabled: boolean; claude_model: string };

const FIELD_LABELS: Record<string, string> = {
  short_name: 'Short name', feature: 'AI feature', type: 'Type', enforcer: 'Enforcer', trigger_text: 'When it reaches AI', obligations_text: 'Obligations',
  developments_text: 'Developments', most_affected: 'Most affected', full_text: 'Text', applies_to: 'Applies to', verify_flag: 'Verify', status_text: 'Status', effective_date_text: 'Effective date',
};

export function LawUpdates() {
  const settings = useQuery({ queryKey: ['admin-settings'], queryFn: () => api.get<Settings>('/admin/settings') });
  const juris = useLawJurisdictions();
  const runs = useQuery({ queryKey: ['refresh-runs'], queryFn: () => api.get<Run[]>('/admin/laws/refresh'), refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 4000 : false) });
  const [picked, setPicked] = useState<string[]>([]);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const qc = useQueryClient();

  async function start() {
    setMsg(null);
    try {
      const run = await api.post<Run>('/admin/laws/refresh', { jurisdiction_codes: picked });
      setOpenRun(run.id);
      setPicked([]);
      await qc.invalidateQueries({ queryKey: ['refresh-runs'] });
    } catch (e) {
      setMsg({ tone: 'danger', text: errorMessage(e) });
    }
  }

  const enabled = settings.data?.law_refresh_enabled;
  return (
    <div className="split">
      <div className="main stack">
        <Card title="Check for law updates">
          <div className="stack">
            <p className="small muted">Claude researches each jurisdiction you choose, using web search and primary sources, and proposes additions, changes and retirements with sources. Nothing changes until you accept a proposal. Accepted proposals publish as a new version of the matrix.</p>
            {!enabled && <Alert tone="warn">Law updates are switched off. Add an Anthropic API key (ANTHROPIC_API_KEY) to the server's .env file and restart.</Alert>}
            {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
            <fieldset>
              <legend>Jurisdictions (up to 10 per run)</legend>
              <div className="row" style={{ gap: 6 }}>
                {(juris.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)).map((j) => {
                  const on = picked.includes(j.code);
                  return (
                    <button key={j.code} type="button" className="pill" aria-pressed={on} onClick={() => setPicked(on ? picked.filter((c) => c !== j.code) : picked.length < 10 ? [...picked, j.code] : picked)}>{j.name}</button>
                  );
                })}
              </div>
            </fieldset>
            <div><Button variant="primary" disabled={!enabled || !picked.length} onClick={start}>Check {picked.length || ''} {picked.length === 1 ? 'jurisdiction' : 'jurisdictions'}</Button></div>
          </div>
        </Card>
        {openRun && <RunDetail runId={openRun} />}
      </div>
      <div className="side">
        <Card title="Recent runs">
          {runs.isLoading ? <Loading /> : !runs.data?.length ? <EmptyState>No runs yet.</EmptyState> : (
            <div className="stack-sm">
              {runs.data.map((r) => (
                <button key={r.id} type="button" className="btn btn-block" style={{ justifyContent: 'space-between', fontWeight: 400 }} onClick={() => setOpenRun(r.id)} aria-pressed={openRun === r.id}>
                  <span style={{ textAlign: 'left' }}>{r.jurisdictions.join(', ')}<br /><span className="small muted">{fmtDateTime(r.created_at)}</span></span>
                  {r.status === 'running' ? <Badge>Running</Badge> : r.status === 'failed' ? <Badge tone="danger">Failed</Badge> : r.counts.pending ? <Badge tone="warn">{r.counts.pending} to review</Badge> : <Badge tone="success">Reviewed</Badge>}
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const q = useQuery({ queryKey: ['refresh-run', runId], queryFn: () => api.get<Run>(`/admin/laws/refresh/${runId}`), refetchInterval: (qq) => (qq.state.data?.status === 'running' ? 4000 : false) });
  const [decision, setDecision] = useState<Record<string, 'accept' | 'reject'>>({});
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const qc = useQueryClient();
  useEffect(() => setDecision({}), [runId]);
  if (q.isLoading || !q.data) return <Loading />;
  const run = q.data;
  const pending = (run.proposals ?? []).filter((p) => p.status === 'pending');
  async function submit() {
    const accept = Object.entries(decision).filter(([, d]) => d === 'accept').map(([id]) => id);
    const reject = Object.entries(decision).filter(([, d]) => d === 'reject').map(([id]) => id);
    try {
      const out = await api.post<{ version_id: string | null }>('/admin/laws/proposals/decide', { accept, reject });
      setMsg({ tone: 'success', text: out.version_id ? `${accept.length} accepted and published as a new version. ${reject.length} rejected.` : `${reject.length} rejected. Nothing was published.` });
      setDecision({});
      await qc.invalidateQueries();
    } catch (e) {
      setMsg({ tone: 'danger', text: errorMessage(e) });
    }
  }
  return (
    <Card title={`Proposals — ${run.jurisdictions.join(', ')}`} actions={pending.length ? <Button variant="primary" disabled={!Object.keys(decision).length} onClick={submit}>Apply decisions</Button> : undefined}>
      <div className="stack">
        {run.status === 'running' && <Alert>Claude is researching. This usually takes one to three minutes per jurisdiction; this page updates by itself.</Alert>}
        {run.status === 'failed' && <Alert tone="danger">The run failed: {run.error}</Alert>}
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        {run.warnings.length > 0 && <Alert tone="warn">{run.warnings.join(' ')}</Alert>}
        {run.status === 'completed' && !run.proposals?.length && <EmptyState>No changes found.</EmptyState>}
        {run.proposals?.map((p) => (
          <div key={p.id} className="card" style={{ padding: 16 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="row">
                <Badge tone={p.change_type === 'add' ? 'success' : p.change_type === 'retire' ? 'danger' : 'navy'}>{p.change_type === 'add' ? 'New law' : p.change_type === 'retire' ? 'Retire' : 'Change'}</Badge>
                <strong>{p.change_type === 'add' ? p.proposed.short_name : p.current?.short_name}</strong>
                <span className="small muted">{p.jurisdiction}</span>
              </div>
              {p.status === 'pending' ? (
                <div className="radio-group" role="radiogroup" aria-label="Decision">
                  <label className="radio-pill"><input type="radio" name={p.id} checked={decision[p.id] === 'accept'} onChange={() => setDecision({ ...decision, [p.id]: 'accept' })} />Accept</label>
                  <label className="radio-pill"><input type="radio" name={p.id} checked={decision[p.id] === 'reject'} onChange={() => setDecision({ ...decision, [p.id]: 'reject' })} />Reject</label>
                </div>
              ) : <Badge tone={p.status === 'accepted' ? 'success' : 'muted'}>{p.status === 'accepted' ? 'Accepted' : 'Rejected'}</Badge>}
            </div>
            <p style={{ marginTop: 8 }}>{p.rationale}</p>
            {p.change_type !== 'retire' && (
              <table className="table" style={{ marginTop: 8 }}>
                <thead><tr><th>Field</th>{p.current && <th>Now</th>}<th>Proposed</th></tr></thead>
                <tbody>
                  {Object.entries(p.proposed).map(([k, v]) => (
                    <tr key={k}><td className="small">{FIELD_LABELS[k] ?? k}</td>{p.current && <td className="small muted" style={{ whiteSpace: 'normal' }}>{String((p.current as unknown as Record<string, unknown>)[k] ?? '—')}</td>}<td className="small" style={{ whiteSpace: 'normal' }}>{String(v)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="small" style={{ marginTop: 8 }}>Sources: {p.sources.map((s, i) => <span key={i}>{i ? ' · ' : ''}<a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a></span>)}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}
