import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import type { AgentRow, AgentsPage, Sample } from '@/api/wsl';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { agentHelp as H } from '@/help/wsl';
import { Trend } from './AgentTab';
import '@/styles/wsl.css';

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;
const VTONE: Record<string, 'success' | 'danger' | 'warn'> = { appropriate: 'success', inappropriate: 'danger', needs_follow_up: 'warn' };

/** Agent oversight `/clients/:clientId/agents` (spec §21 F14), for the audit team: each agent's registration, its
 *  override-rate trend, and random samples of its decisions with a verdict on each. */
export function AgentOversight() {
  const { clientId = '' } = useParams();
  const key = ['client-agents', clientId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<AgentsPage>(`/clients/${clientId}/agents`) });
  const qc = useQueryClient();
  const [drawing, setDrawing] = useState<AgentRow | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  return (
    <div className="page">
      <PageHeader title="Agent oversight" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client}${d.engagement ? ` · ${d.engagement}` : ''}` }, { label: 'Agent oversight' }]}
        subtitle="The client's AI agents: what each may do, how often it hands decisions to a person, and samples of its decisions for your review. The decision log comes from the client (import, GuardRail or the public API)." />
      {d.agents.length === 0 && <EmptyState>This client has no agents in its register.</EmptyState>}
      {d.agents.map((a) => (
        <Card key={a.id} title={<h2>{a.reference} {a.name} {a.department && <span className="small muted">· {a.department}</span>}</h2>}
          actions={<Button variant="primary" onClick={() => setDrawing(a)} disabled={a.decisions === 0}>Sample decisions</Button>}>
          <div className="stack">
            {!a.registration && <Alert tone="warn">The client has not registered this agent's tools and permissions.</Alert>}
            {a.registration && <p className="small" style={{ margin: 0 }}><strong>{a.registration.autonomy_label}</strong> · {plural(a.registration.tools.length, 'tool')} ({a.registration.tools.filter((t) => t.access === 'act').length} that act{a.registration.tools.filter((t) => t.access === 'act').length === 1 ? 's' : ''}) · {plural(a.registration.approval_points.length, 'approval point')} · kill switch {a.registration.kill_switch ? 'recorded' : 'not recorded'}</p>}
            {a.unregistered_tools.length > 0 && <Alert tone="warn">Used but not registered: {a.unregistered_tools.join(', ')}.</Alert>}
            {a.flags.map((f) => <Alert key={f} tone="warn">{f}</Alert>)}
            <p className="small muted" style={{ margin: 0 }}>{a.decisions} decisions on record.</p>
            <Trend months={a.trend} />
            {a.samples.length > 0 && (
              <DataGrid label={`Samples for ${a.name}`} rows={a.samples} rowId={(s) => s.id}
                columns={[
                  { key: 'at', header: 'Drawn', value: (s) => s.drawn_at, render: (s) => <>{fmtDateTime(s.drawn_at)}<div className="small muted">{s.drawn_by}</div></> },
                  { key: 'size', header: 'Sample', value: (s) => s.size, render: (s) => `${s.size} of ${s.population}` },
                  { key: 'seed', header: 'Seed', value: (s) => s.seed },
                  { key: 'status', header: 'Status', value: (s) => s.status, render: (s) => <Badge tone={s.status === 'complete' ? 'success' : 'navy'}>{s.status === 'complete' ? 'Complete' : 'In review'}</Badge> },
                  { key: 'res', header: 'Verdicts', value: (s) => s.summary.inappropriate ?? 0, render: (s) => `${s.summary.appropriate ?? 0} appropriate · ${s.summary.inappropriate ?? 0} inappropriate · ${s.summary.needs_follow_up ?? 0} follow up` },
                ]}
                rowActions={(s) => [{ label: s.status === 'complete' ? 'View' : 'Review', onSelect: () => setOpen(s.id) }]}
              />
            )}
          </div>
        </Card>
      ))}
      {drawing && <DrawDialog clientId={clientId} agent={drawing} onClose={() => setDrawing(null)} onDrawn={async (s) => { setDrawing(null); await refresh(); setOpen(s.id); }} />}
      {open && <SampleDialog sampleId={open} verdicts={d.verdicts} onClose={() => { setOpen(null); void refresh(); }} />}
    </div>
  );
}

function DrawDialog({ clientId, agent, onClose, onDrawn }: { clientId: string; agent: AgentRow; onClose: () => void; onDrawn: (s: Sample) => void }) {
  const [size, setSize] = useState('25');
  const [days, setDays] = useState('90');
  const [seed, setSeed] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function draw() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    try { onDrawn(await api.post<Sample>(`/clients/${clientId}/agents/${agent.id}/samples`, { size: Number(size), period_days: Number(days), seed: seed.trim() === '' ? null : Number(seed) })); }
    catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Dialog title={`Sample decisions: ${agent.name}`} onClose={onClose}>
      <div className="stack">
        <TextField label="Number of decisions" help={H.sampleSize} type="number" min={1} max={200} value={size} onChange={(e) => setSize(e.target.value)} error={fe.size} />
        <TextField label="Period in days" help={H.period} type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} error={fe.period_days} />
        <TextField label="Seed (optional)" help={H.seed} type="number" min={0} value={seed} onChange={(e) => setSeed(e.target.value)} error={fe.seed} />
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy} onClick={draw}>{busy ? 'Drawing…' : 'Draw sample'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function SampleDialog({ sampleId, verdicts, onClose }: { sampleId: string; verdicts: { value: string; label: string }[]; onClose: () => void }) {
  const key = ['agent-sample', sampleId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Sample>(`/agent-samples/${sampleId}`) });
  const qc = useQueryClient();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [conclusion, setConclusion] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const s = q.data;
  async function judge(traceId: string, verdict: string) {
    if (busy) return;
    setBusy(traceId); setErr(null);
    try { const out = await api.post<Sample>(`/agent-samples/${sampleId}/reviews`, { trace_id: traceId, verdict, note: notes[traceId] ?? '' }); qc.setQueryData(key, out); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function complete() {
    if (busy) return;
    setBusy('complete'); setErr(null);
    try { const out = await api.post<Sample>(`/agent-samples/${sampleId}/complete`, { conclusion }); qc.setQueryData(key, out); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  return (
    <Dialog title="Decision sample" onClose={onClose} large>
      {!s ? (q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />) : (
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>{s.method}{s.engagement ? ` For ${s.engagement}.` : ''}</p>
          {err && <Alert tone="danger">{err}</Alert>}
          <ol className="stack" style={{ paddingLeft: 18, margin: 0 }}>
            {s.decisions.map((x) => (
              <li key={x.id} className="stack-sm">
                <div><strong>{x.action}</strong> <Badge tone={x.decision === 'blocked' ? 'danger' : x.decision === 'escalated' ? 'warn' : 'success'}>{x.decision_label}</Badge></div>
                <div className="small muted">{fmtDateTime(x.at)}{x.tool ? ` · ${x.tool}` : ''}{x.policy_ref ? ` · ${x.policy_ref}` : ''}{x.approver ? ` · ${x.approver}` : ''}</div>
                {x.verdict ? (
                  <div className="small"><Badge tone={VTONE[x.verdict]}>{x.verdict_label}</Badge> {x.note} <span className="muted">· {x.reviewer}</span></div>
                ) : null}
                {s.status === 'open' && (
                  <div className="stack-sm">
                    <TextField label="Note" help={H.note} value={notes[x.id] ?? x.note ?? ''} onChange={(e) => setNotes({ ...notes, [x.id]: e.target.value })} />
                    <div className="wsl-verdict" role="group" aria-label="Verdict">
                      {verdicts.map((v) => <Button key={v.value} size="sm" variant={x.verdict === v.value ? 'primary' : 'default'} disabled={busy !== null} onClick={() => judge(x.id, v.value)}>{v.label}</Button>)}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {s.status === 'open' ? (
            <div className="stack-sm">
              <TextArea label="Conclusion" help={H.conclusion} value={conclusion} onChange={(e) => setConclusion(e.target.value)} />
              <div><Button variant="primary" disabled={busy !== null} onClick={complete}>Complete the review</Button></div>
            </div>
          ) : (
            <Alert tone="success">Completed by {s.completed_by} on {fmtDateTime(s.completed_at)}: {s.summary.appropriate ?? 0} appropriate, {s.summary.inappropriate ?? 0} inappropriate, {s.summary.needs_follow_up ?? 0} to follow up.{s.conclusion ? ` ${s.conclusion}` : ''}</Alert>
          )}
        </div>
      )}
    </Dialog>
  );
}

