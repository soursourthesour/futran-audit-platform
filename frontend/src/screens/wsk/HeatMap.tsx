import { useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, fileUrl, fmtDate } from '@/components/ui';
import { type ControlProof, type HeatMap as Heat, type Lineage, RATING } from '@/api/wsk';
import { heatHelp } from '@/help/wsk';
import './wsk.css';

const BANDS = ['low', 'medium', 'high', 'critical'] as const;

/** Screen 35: risk heat map (F13) and lineage (F6) for a client's current engagement. */
export function HeatMap() {
  const { clientId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const qs = params.toString();
  const q = useQuery({ queryKey: ['heatmap', clientId, qs], queryFn: () => api.get<Heat>(`/clients/${clientId}/heatmap${qs ? `?${qs}` : ''}`) });
  const [findingId, setFindingId] = useState<string | null>(null);
  const [proof, setProof] = useState<{ systemId: string; code: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const set = (k: string, v: string) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p, { replace: true }); };
  const chosen = findingId ?? d.findings.find((f) => f.status === 'approved')?.id ?? d.findings[0]?.id ?? null;
  const exportQs = new URLSearchParams(params); exportQs.delete('framework');
  return (
    <div className="page">
      <PageHeader title="Risk heat map and lineage" crumbs={[{ to: `/clients/${clientId}`, label: d.client.name }, { to: `/clients/${clientId}/systems`, label: 'AI systems' }, { label: 'Heat map and lineage' }]}
        subtitle={`${d.engagement.audit_ref ?? ''} · systems placed by inherent risk and control maturity · cell colour = resulting residual band · provisional scores marked *`}
        actions={<a className="btn" href={`/api/v1/clients/${clientId}/heatmap.png${exportQs.toString() ? `?${exportQs}` : ''}`} download>Export PNG</a>} />
      <div className="row heat-filters" style={{ gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <SelectField label="Department" help={heatHelp.department} value={params.get('department') ?? ''} onChange={(e) => set('department', e.target.value)} placeholder="All departments" options={d.filters.departments.map((x) => ({ value: x.id, label: x.name }))} />
        <SelectField label="Build type" help={heatHelp.buildType} value={params.get('build_type') ?? ''} onChange={(e) => set('build_type', e.target.value)} placeholder="All build types" options={d.filters.build_types.map((x) => ({ value: x.key, label: x.label }))} />
        <SelectField label="Framework" help={heatHelp.framework} value={params.get('framework') ?? ''} onChange={(e) => set('framework', e.target.value)} placeholder="All frameworks" options={d.filters.frameworks.map((x) => ({ value: x, label: x.replace(/_/g, ' ') }))} />
      </div>
      <div className="split">
        <section className="main stack">
          <Card title="AI systems">
            <div className="heat" role="table" aria-label="Risk heat map: control maturity rows, inherent risk columns">
              {d.rows.map((row) => (
                <div className="heat-row" role="row" key={row}>
                  <div className="heat-axis" role="rowheader">Maturity {row}</div>
                  {d.grid[row].map((cell, i) => (
                    <div key={i} role="cell" className={`heat-cell band-${cell.band}`} aria-label={`Maturity ${row}, inherent ${d.columns[i].label}: ${cell.band}${cell.systems.length ? `, ${cell.systems.map((s) => s.reference_id).join(', ')}` : ''}`}>
                      {cell.systems.map((s) => <Link key={s.id} to={`/systems/${s.id}/score`} className={`chip rating-${s.final_rating ?? 'none'}`}>{s.reference_id}{s.provisional ? '*' : ''}{s.final_rating && !s.provisional ? ` · ${s.final_rating[0].toUpperCase()}${s.final_rating.slice(1)}` : ''}</Link>)}
                    </div>
                  ))}
                </div>
              ))}
              <div className="heat-row heat-cols" role="row"><div role="columnheader" />{d.columns.map((c) => <div key={c.label} role="columnheader" className="heat-axis center">Inherent {c.label}</div>)}</div>
            </div>
            <div className="heat-legend small">{BANDS.map((b) => <span key={b}><span className={`swatch band-${b}`} aria-hidden="true" /> {b[0].toUpperCase() + b.slice(1)}</span>)}<span>{d.knockout_note}</span></div>
            {d.unplaced.length > 0 && <p className="small muted" style={{ margin: 0 }}>Not placed until inherent risk and maturity are both scored: {d.unplaced.join(', ')}.</p>}
          </Card>
          <Card title="Control effect by system">
            {d.systems.length === 0 ? <EmptyState>No systems match the filters.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>System</th><th>Build</th><th className="num">Inherent</th><th className="num">Maturity</th><th>Control effect</th><th>Final rating</th></tr></thead>
                <tbody>{d.systems.map((s) => (
                  <tr key={s.id}>
                    <td><Link to={`/systems/${s.id}/score`}>{s.reference_id}</Link> {s.name}{s.department && <div className="small muted">{s.department}</div>}</td>
                    <td className="small">{s.built_by_label}</td><td className="num">{s.inherent ?? '—'}</td><td className="num">{s.maturity ?? '—'}</td>
                    <td className="small">{s.inherent !== null && s.residual !== null ? <span aria-label={`Inherent ${s.inherent} reduced to residual ${s.residual}`}>{s.inherent} <span aria-hidden="true">→</span> {s.residual}</span> : '—'}</td>
                    <td>{s.final_rating ? <Badge tone={s.final_rating === 'low' ? 'muted' : s.final_rating === 'medium' ? 'warn' : 'danger'}>{RATING[s.final_rating]}{s.provisional ? ' *' : ''}</Badge> : '—'}
                      {s.knockouts.length > 0 && <div className="small muted">Knock-out: {s.knockouts.join('; ')}</div>}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
          <Card title="Findings by severity and domain" actions={<span className="small muted">{d.findings_grid.total} finding{d.findings_grid.total === 1 ? '' : 's'}, drafts included</span>}>
            <div className="table-wrap"><table className="table findings-grid">
              <thead><tr><th>Severity</th>{d.findings_grid.domains.map((x) => <th key={x.key} className="num">{x.label}</th>)}</tr></thead>
              <tbody>{d.findings_grid.rows.map((r) => <tr key={r.severity}><th scope="row">{r.label}</th>{r.counts.map((n, i) => <td key={i} className={`num${n ? ` sev-${r.severity}` : ''}`}>{n || ''}</td>)}</tr>)}</tbody>
            </table></div>
          </Card>
        </section>
        <aside className="side stack">
          {chosen ? <LineagePanel findingId={chosen} findings={d.findings} onPick={setFindingId} onProof={setProof} /> : <Card title="Lineage"><EmptyState>No findings yet.</EmptyState></Card>}
        </aside>
      </div>
      {proof && <ProofDialog systemId={proof.systemId} code={proof.code} onClose={() => setProof(null)} />}
    </div>
  );
}

function LineagePanel({ findingId, findings, onPick, onProof }: { findingId: string; findings: Heat['findings']; onPick: (id: string) => void; onProof: (p: { systemId: string; code: string }) => void }) {
  const q = useQuery({ queryKey: ['lineage', findingId], queryFn: () => api.get<Lineage>(`/findings/${findingId}/lineage`) });
  const l = q.data;
  return (
    <Card title={l ? `Lineage: why is ${l.finding.ref} a finding?` : 'Lineage'}>
      <SelectField label="Finding" value={findingId} onChange={(e) => onPick(e.target.value)} options={findings.map((f) => ({ value: f.id, label: `${f.ref} ${f.title}${f.status !== 'approved' ? ` (${f.status})` : ''}` }))} />
      {q.isLoading && <Loading />}
      {q.error && <Alert tone="danger">{errorMessage(q.error)}</Alert>}
      {l && (
        <ol className="lineage">
          <Step k="Regulation and obligation">
            {l.obligations.length === 0 ? <span className="muted">No law in this engagement’s scope is mapped to these questions.</span> : l.obligations.map((o) => (
              <div key={o.regulation_id}><strong>{o.regulation}</strong>{o.citation ? ` · ${o.citation}` : ''}<span className="small muted"> · {o.kind === 'obligation' ? 'approved obligation' : 'law library requirement'}</span>
                <ul className="small">{o.items.map((i, n) => <li key={n}>{i.code ? `${i.code}: ` : ''}{i.text}</li>)}</ul></div>
            ))}
          </Step>
          <Step k="Control">
            <div className="small">{l.controls.map((c) => c.label).join(' · ') || '—'}</div>
            {l.checklist.length > 0 && <ul className="small">{l.checklist.map((c) => <li key={c.code}>Checklist {c.code} {c.confirmed ? '(confirmed)' : '(not confirmed)'} · <button type="button" className="linklike" onClick={() => onProof({ systemId: l.finding.system_id ?? '', code: c.code })}>What proves this control?</button></li>)}</ul>}
          </Step>
          <Step k="Response">
            {l.responses.length === 0 ? <span className="muted">Raised from fieldwork, not from an answer.</span> : l.responses.map((r) => <div key={r.code}>{r.code} {r.label}: <strong>{r.answer ?? 'Not answered'}</strong>{r.source ? ` · ${r.source}` : ''}</div>)}
          </Step>
          <Step k="Evidence">
            {l.evidence.map((e) => <div key={e.id}><a href={fileUrl(e.id)}>{e.filename}</a> <span className="small muted">({e.via})</span></div>)}
            {l.requests.map((r, i) => <div key={i}>{r.title}: <span className="danger-text">{r.status.replace('_', ' ')}</span> (document register{r.chases ? `, ${r.chases} chase${r.chases === 1 ? '' : 's'}` : ''})</div>)}
            {l.evidence_note && <span className="muted">{l.evidence_note}</span>}
          </Step>
          <Step k="Finding and remediation" emphasis>
            <div>{l.finding.ref} {RATING[l.finding.severity]} · {l.finding.title}</div>
            {l.remediation.length === 0 ? <div className="small muted">No remediation agreed yet{l.finding.proposed_owner ? ` · proposed owner ${l.finding.proposed_owner}` : ''}.</div>
              : l.remediation.map((r) => <div key={r.id} className="small">{r.action} · owner {r.owner ?? 'to be confirmed'}{r.due_date ? ` · due ${fmtDate(r.due_date)}` : ''} · {r.status.replace(/_/g, ' ')}</div>)}
          </Step>
        </ol>
      )}
    </Card>
  );
}

function Step({ k, children, emphasis }: { k: string; children: ReactNode; emphasis?: boolean }) {
  return <li className={`lineage-step${emphasis ? ' emphasis' : ''}`}><div className="k">{k}</div>{children}</li>;
}

function ProofDialog({ systemId, code, onClose }: { systemId: string; code: string; onClose: () => void }) {
  const params = useParams();
  const heat = useQuery({ queryKey: ['heatmap', params.clientId, ''], queryFn: () => api.get<Heat>(`/clients/${params.clientId}/heatmap`), enabled: !systemId });
  const [sid, setSid] = useState(systemId);
  const systems = heat.data?.systems ?? [];
  const target = sid || systems[0]?.id || '';
  const q = useQuery({ queryKey: ['proof', target, code], queryFn: () => api.get<ControlProof>(`/systems/${target}/lineage/control/${encodeURIComponent(code)}`), enabled: !!target });
  const p = q.data;
  return (
    <Dialog title={`What proves control ${code}?`} onClose={onClose} wide>
      <div className="stack">
        {systems.length > 1 && <SelectField label="System" value={target} onChange={(e) => setSid(e.target.value)} options={systems.map((s) => ({ value: s.id, label: `${s.reference_id} ${s.name}` }))} />}
        {q.isLoading && <Loading />}
        {q.error && <Alert tone="danger">{errorMessage(q.error)}</Alert>}
        {p && (
          <>
            <p style={{ margin: 0 }}><strong>{p.control.code}</strong> {p.control.text} <Badge tone={p.confirmed ? 'success' : 'muted'}>{p.confirmed ? 'Confirmed with evidence' : 'Not confirmed'}</Badge></p>
            <div><strong className="small">Evidence</strong>{p.evidence.length ? <ul className="small">{p.evidence.map((e) => <li key={e.id}><a href={fileUrl(e.id)}>{e.filename}</a> ({e.via})</li>)}</ul> : <p className="small muted" style={{ margin: 0 }}>No evidence is linked yet.</p>}</div>
            {p.answers.length > 0 && <div><strong className="small">Answers it rests on</strong><ul className="small">{p.answers.map((a) => <li key={a.code}>{a.code} {a.label}: {a.answer ?? '—'}{a.source ? ` · ${a.source}` : ''}</li>)}</ul></div>}
            <div><strong className="small">The same evidence also satisfies</strong>
              <ul className="small">{p.also_satisfies.controls.map((c) => <li key={c.ref}>{c.label}</li>)}{p.also_satisfies.requirements.map((r) => <li key={`${r.regulation}-${r.code}`}>{r.regulation} {r.code}: {r.text}{r.in_scope ? '' : ' (law not in scope)'}</li>)}</ul></div>
          </>
        )}
        <div className="row" style={{ justifyContent: 'flex-end' }}><Button onClick={onClose}>Close</Button></div>
      </div>
    </Dialog>
  );
}
