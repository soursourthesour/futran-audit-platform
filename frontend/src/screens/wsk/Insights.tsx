import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, useMe } from '@/api/auth';
import { Alert, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextField } from '@/components/ui';
import type { Comparison, Practice } from '@/api/wsk';
import { insightHelp } from '@/help/wsk';
import './wsk.css';

/** Screen 34: anonymized peer comparison (Chief Auditor) and the practice view (Chief Auditor and Sales Team). */
export function Insights() {
  const { data: me } = useMe();
  const chief = can(me, 'view_benchmarks');
  const clients = useQuery({ queryKey: ['insight-clients'], queryFn: () => api.get<{ clients: { id: string; name: string; consent: boolean | null }[]; min_peers: number }>('/insights/clients'), enabled: chief });
  const practice = useQuery({ queryKey: ['insight-practice'], queryFn: () => api.get<Practice>('/insights/practice') });
  const [clientId, setClientId] = useState<string>('');
  const picked = clientId || clients.data?.clients.find((c) => c.consent)?.id || clients.data?.clients[0]?.id || '';
  return (
    <div className="page">
      <PageHeader title="Benchmarking and practice insights" subtitle="Anonymized. A figure is shown only when its peer group has at least 5 consenting clients." />
      <div className="split">
        {chief && (
          <section className="main stack">
            {clients.isLoading ? <Loading /> : clients.data && clients.data.clients.length === 0 ? <Card><EmptyState>No signed reports yet. Figures appear after a final report is signed.</EmptyState></Card> : clients.data && (
              <>
                <div style={{ maxWidth: 420 }}><SelectField label="Client" help={insightHelp.client} value={picked} onChange={(e) => setClientId(e.target.value)} options={clients.data.clients.map((c) => ({ value: c.id, label: `${c.name}${c.consent ? '' : ' (no consent)'}` }))} /></div>
                {picked && <ComparisonCard clientId={picked} />}
              </>
            )}
          </section>
        )}
        <aside className={chief ? 'side stack' : 'main stack'}>
          <Card title={chief ? 'Practice view: most common findings' : 'Practice view: most common findings across clients'}>
            {practice.isLoading ? <Loading /> : practice.error ? <Alert tone="danger">{errorMessage(practice.error)}</Alert> : practice.data && (
              practice.data.themes.length === 0 ? <EmptyState>{practice.data.note ?? 'No findings to show yet.'}</EmptyState> : (
                <ul className="data-list">{practice.data.themes.map((t) => (
                  <li key={t.code}><div><strong>{t.label}</strong><div className="small muted">Service: {t.service}</div></div><span className="small">{t.clients} of {practice.data!.clients} clients</span></li>
                ))}</ul>
              )
            )}
            <p className="small muted" style={{ margin: 0 }}>Counts only clients who consented to benchmarking. Client names and scores are never shown in this view.</p>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function ComparisonCard({ clientId }: { clientId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['insight', clientId], queryFn: () => api.get<Comparison>(`/insights/clients/${clientId}`) });
  const [consent, setConsent] = useState(false);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const title = d.group ? `${d.client.name} vs. peers: ${d.group.label} (n = ${d.group.n})` : `${d.client.name}: no peer figure yet`;
  return (
    <Card title={title} actions={<div className="row" style={{ gap: 8 }}><Button size="sm" onClick={() => setConsent(true)}>Benchmark consent</Button>{d.group && <a className="btn btn-sm" href={`/api/v1/insights/clients/${clientId}/page.pdf`}>Share as a report page</a>}</div>}>
      {d.note && <Alert tone="info">{d.note}</Alert>}
      <div className="bench-legend small"><span><span className="dot" aria-hidden="true" /> {d.client.name}</span><span><span className="peer" aria-hidden="true" /> peer median</span><span>scale 1–5</span></div>
      <div className="bench">
        {d.domains.map((x) => (
          <div className="bench-row" key={x.key}>
            <span>{x.label}</span>
            <div className="track" role="img" aria-label={`${d.client.name} ${x.client ?? 'not scored'}, peers ${x.peer_median ?? 'not shown'}`}>
              {x.peer_median !== null && <div className="peer" style={{ left: `${((x.peer_median - 1) / 4) * 100}%` }} />}
              {x.client !== null && <div className={`dot${x.below_peers ? ' below' : ''}`} style={{ left: `${((x.client - 1) / 4) * 100}%` }} />}
            </div>
            <span className={`num${x.below_peers ? ' danger-text' : ''}`}>{x.client ?? '—'} vs {x.peer_median ?? '—'}</span>
          </div>
        ))}
      </div>
      <p className="small muted" style={{ margin: 0 }}>Overall maturity {d.overall.client ?? '—'} against a peer median of {d.overall.peer_median ?? '—'}. Groups tried: {d.groups_considered.map((g) => `${g.label} (${g.n})`).join(', ') || 'none'}.</p>
      {consent && <ConsentDialog clientId={clientId} current={!!d.client.consent} onClose={() => setConsent(false)} onDone={() => { setConsent(false); void qc.invalidateQueries({ queryKey: ['insight', clientId] }); void qc.invalidateQueries({ queryKey: ['insight-clients'] }); }} />}
    </Card>
  );
}

function ConsentDialog({ clientId, current, onClose, onDone }: { clientId: string; current: boolean; onClose: () => void; onDone: () => void }) {
  const [on, setOn] = useState(current);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    if (busy) return;
    setBusy(true);
    try { await api.put(`/insights/clients/${clientId}/consent`, { consent: on, note }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Benchmark consent" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <Checkbox label="The client consented to anonymous benchmarking in its engagement letter" help={insightHelp.consent} checked={on} onChange={(e) => setOn(e.target.checked)} />
        <TextField label="Where it is recorded" help={insightHelp.consentNote} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={save}>Save</Button></div>
      </div>
    </Dialog>
  );
}
