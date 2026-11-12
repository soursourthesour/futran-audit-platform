import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Badge, Button, ButtonLink, Card, Loading, PageHeader, fmtDate } from '@/components/ui';
import { type SalesHome as Home, STAGE_TONE, oppLink, usd } from '@/api/sales';
import { salesHelp as H } from '@/help/sales';
import '@/styles/sales.css';

function due(d: string | null): string {
  if (!d) return '—';
  const days = Math.round((new Date(`${d}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  return days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days < 0 ? `Overdue · ${fmtDate(d)}` : fmtDate(d);
}

/** SM-01 Sales home (spec §4.12): KPIs, pipeline by stage, next steps and tasks, approvals, stale deals, new automatic
 *  opportunities and recent wins. Sales Managers and the Chief Auditor can switch to the team's pipeline. */
export function SalesHome() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const scope = params.get('scope') === 'team' ? 'team' : 'mine';
  const q = useQuery({ queryKey: ['sales-home', scope], queryFn: () => api.get<Home>(`/sales/home?scope=${scope}`) });
  const h = q.data;
  const maxStage = Math.max(1, ...(h?.by_stage.map((s) => s.value) ?? [1]));
  return (
    <div className="page sales-page">
      <PageHeader title="Sales home" subtitle={h ? (h.scope === 'team' ? "The team's pipeline" : 'My pipeline') : undefined}
        actions={<>
          {h?.can_see_team && (
            <div className="pills" role="tablist" aria-label="Pipeline">
              <button type="button" role="tab" className="pill" aria-selected={scope === 'mine'} onClick={() => setParams({}, { replace: true })}>Mine</button>
              <button type="button" role="tab" className="pill" aria-selected={scope === 'team'} onClick={() => setParams({ scope: 'team' }, { replace: true })}>Team</button>
            </div>
          )}
          <Button variant="primary" onClick={() => nav('/sales/opportunities?log=1')}>Log opportunity</Button>
          <ButtonLink to="/sales/opportunities">All opportunities</ButtonLink>
        </>} />
      {!h ? <Loading /> : (
        <>
          <div className="grid-tiles kpis">
            <div className="tile"><div className="label">Open pipeline</div><div className="value">{usd(h.kpis.open_pipeline)}</div><div className="hint">{h.kpis.open_count} {h.kpis.open_count === 1 ? 'opportunity' : 'opportunities'}</div></div>
            <div className="tile"><div className="label">Weighted by stage</div><div className="value">{usd(h.kpis.weighted)}</div><div className="hint">Stage probability × value</div></div>
            <div className="tile"><div className="label">Proposals out</div><div className="value">{h.kpis.proposals_out}</div><div className="hint">{h.kpis.proposals_expiring} expiring in 5 days</div></div>
            <div className="tile"><div className="label">Won this quarter</div><div className="value">{usd(h.kpis.won_this_quarter)}</div><div className="hint">{h.kpis.won_count} {h.kpis.won_count === 1 ? 'deal' : 'deals'}</div></div>
          </div>
          <Card title="Pipeline by stage">
            <ol className="sales-funnel" aria-label="Pipeline by stage">
              {h.by_stage.map((s) => (
                <li key={s.stage}>
                  <Link to={s.stage === 'won' ? '/sales/opportunities?stage=won' : `/sales/opportunities?stage=${s.stage}`}><strong>{s.label}</strong></Link>
                  <span className="small muted">{s.count} · {usd(s.value)}</span>
                  <span className={`sales-bar ${s.stage === 'won' ? 'won' : ''}`} style={{ width: `${Math.max(4, Math.round((s.value / maxStage) * 100))}%` }} aria-hidden />
                </li>
              ))}
            </ol>
          </Card>
          <div className="sales-home-grid">
            <Card title="My next steps">
              {h.next_steps.length === 0 && h.tasks.length === 0 ? <p className="small muted">No next steps set.</p> : (
                <div className="table-wrap"><table className="table"><thead><tr><th>Due</th><th>Opportunity</th><th>Next step</th><th>Stage</th></tr></thead>
                  <tbody>
                    {h.next_steps.map((s) => (
                      <tr key={s.id}><td className="nowrap">{due(s.next_step_due)}</td><td><Link to={oppLink(s.id)}>{s.company}</Link></td><td>{s.next_step}</td><td><Badge tone={STAGE_TONE[s.stage]}>{s.stage_label}</Badge></td></tr>
                    ))}
                    {h.tasks.map((t) => (
                      <tr key={t.id}><td className="nowrap">{due(t.due_on)}</td><td><Link to={oppLink(t.opportunity_id)}>{t.company}</Link></td><td>Task: {t.summary}</td><td /></tr>
                    ))}
                  </tbody></table></div>
              )}
            </Card>
            <div className="stack">
              <Card title="Waiting on approval">
                {h.approvals.length === 0 ? <p className="small muted">Nothing waiting.</p> : (
                  <ul className="sales-list">{h.approvals.map((a, i) => (
                    <li key={`${a.opportunity_id}-${i}`}><Link to={a.link}>{a.label}</Link> <span className="small muted">({a.rule} · {a.kind === 'to_decide' ? 'you decide' : `waiting on ${a.approver.replace('_', ' ')}`})</span></li>
                  ))}</ul>
                )}
                <ButtonLink size="sm" to="/sales/approvals">Open approvals</ButtonLink>
              </Card>
              <Card title="Stale deals" actions={<span className="small muted" title={H.stale}>No activity for 14 days</span>}>
                {h.stale.length === 0 ? <p className="small muted">None. Every open opportunity has had activity in the last 14 days.</p> : (
                  <ul className="sales-list">{h.stale.map((s) => <li key={s.id}><Link to={oppLink(s.id)}>{s.company}</Link> · {s.name} <Badge tone="danger">{`Stale ${s.days} d`}</Badge></li>)}</ul>
                )}
              </Card>
            </div>
          </div>
          <div className="sales-home-grid">
            <Card title="New automatic opportunities this week">
              {h.new_automatic.length === 0 ? <p className="small muted">None this week.</p> : (
                <ul className="sales-list">{h.new_automatic.map((a) => <li key={a.id}><Link to={oppLink(a.id)}>{a.trigger_label}</Link> · {a.company}{a.why_now ? ` — ${a.why_now}` : ''}</li>)}</ul>
              )}
            </Card>
            <Card title="Recent wins">
              {h.recent_wins.length === 0 ? <p className="small muted">No wins this quarter yet.</p> : (
                <ul className="sales-list">{h.recent_wins.map((w) => <li key={w.id}><Link to={oppLink(w.id)}>{w.company}</Link> · {w.name} · {usd(w.value)} <span className="small muted">{fmtDate(w.closed_at)}</span></li>)}</ul>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
