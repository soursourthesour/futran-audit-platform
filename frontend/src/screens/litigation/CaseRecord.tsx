import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Loading, PageHeader, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { CaseForm } from './CaseForm';
import { AssignDialog, TalkingPoints, stageBadge } from './Litigation';
import { TYPE_LABELS, lines, type CaseDetail, type Match } from './types';
import '@/styles/monitoring.css';

export function CaseRecord() {
  const { caseId = '' } = useParams();
  const { data: me } = useMe();
  const { hash } = useLocation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['case', caseId], queryFn: () => api.get<CaseDetail>(`/litigation/${caseId}`) });
  const laws = useQuery({ queryKey: ['case-laws', caseId, q.data?.regulation_ids], enabled: !!q.data?.regulation_ids.length,
    queryFn: () => Promise.all((q.data?.regulation_ids ?? []).map((id) => api.get<{ id: string; short_name: string; jurisdiction_name: string }>(`/laws/${id}`).catch(() => null))) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [assign, setAssign] = useState<string[] | null>(null);
  const canSell = hasRole(me ?? undefined, 'sales_team', 'chief_auditor');
  useEffect(() => { if (hash === '#clients' && q.data) document.getElementById('clients')?.scrollIntoView(); }, [hash, q.data]);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <div className="page"><Alert tone="danger">This case was not found.</Alert></div>;
  const c = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['case', caseId] });
  async function follow() {
    try { await api.post(`/litigation/${c.id}/${c.following ? 'unfollow' : 'follow'}`); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function briefing(orgs?: string[]) {
    try {
      const out = await api.post<{ queued: number }>(`/litigation/${c.id}/briefing`, { organization_ids: orgs ?? null });
      setMsg({ tone: 'success', text: `${out.queued} client ${out.queued === 1 ? 'briefing waits' : 'briefings wait'} for the Chief Auditor in Client alerts.` });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const columns: GridColumn<Match>[] = [
    { key: 'client', header: 'Client', value: (m) => m.organization_name, render: (m) => <strong>{m.organization_name}</strong> },
    { key: 'systems', header: 'AI system', value: (m) => m.systems.map((s) => s.name ?? s.type_label).join(', '),
      render: (m) => <span>{m.systems.map((s, i) => <span key={s.id ?? `${s.type}-${i}`} className="block">{s.name ? <>{s.name} <span className="small muted">({s.type_label})</span></> : s.type_label}</span>)}</span> },
    { key: 'why', header: 'Why it matches', value: (m) => m.match_reason },
  ];
  return (
    <div className="page">
      <PageHeader title={c.name} crumbs={[{ to: '/litigation', label: 'Litigation tracker' }, { label: c.name }]}
        subtitle={<span className="row wrap" style={{ gap: 6 }}>{c.geography && <Badge>{c.geography}</Badge>}{c.court && <Badge tone="muted">{c.court}</Badge>}{c.docket_ref && <Badge tone="muted">{c.docket_ref}</Badge>}<Badge tone="muted">{c.area}</Badge>{stageBadge(c)}</span>}
        actions={<>{c.can_edit && <Button onClick={() => setEditing(true)}>Edit</Button>}<Button onClick={follow}>{c.following ? 'Stop following' : 'Follow updates'}</Button><Button variant="primary" onClick={() => briefing()}>Send client briefing</Button></>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <Card title="Where the case is">
            <ol className="timeline">
              {c.timeline.map((t, i) => <li key={i} className={i === c.timeline.length - 1 ? 'current' : ''}><span className="when">{t.on}</span><span>{t.label}{i === c.timeline.length - 1 && <Badge tone="navy">Current stage</Badge>}</span></li>)}
            </ol>
            <p className="small muted">Dates and stages from the last approved refresh or edit; check the court docket before quoting them.</p>
          </Card>
          <Card title="What it is about"><p style={{ margin: 0 }}>{c.description}</p></Card>
          <Card title="Why it matters to our clients"><ul className="tight">{lines(c.why_matters).map((l, i) => <li key={i}>{l}</li>)}</ul></Card>
          <Card title="Talking points"><TalkingPoints c={c} /></Card>
          <div id="clients">
            <Card title={`Clients using similar AI (${c.matches.length})`}>
              <p className="small muted" style={{ marginTop: 0 }}>Matched from client registers{c.match_rule.types?.length ? `: ${c.match_rule.types.map((t) => TYPE_LABELS[t] ?? t).join(', ')}` : ''}{c.match_rule.uses?.length ? `; use words ${c.match_rule.uses.join(', ')}` : ''}{c.match_rule.decision_impact?.length ? '; consequential decisions' : ''}.</p>
              <DataGrid label="Clients using similar AI" rows={c.matches} rowId={(m) => m.organization_id} rowLabel={(m) => m.organization_name} columns={columns} selectable
                bulkActions={[
                  { label: 'Send client briefing', run: (rows) => briefing(rows.map((r) => r.organization_id)) },
                  ...(canSell ? [{ label: 'Create opportunities', run: async (rows: Match[]) => setAssign(rows.map((r) => r.organization_id)) }] : []),
                ]}
                rowActions={(m) => [
                  { label: 'Send client briefing', onSelect: () => briefing([m.organization_id]) },
                  ...(canSell ? [{ label: 'Create opportunity', onSelect: () => setAssign([m.organization_id]) }] : []),
                ]}
                emptyText="No client register holds AI like this yet." />
              <p className="small muted">Sales sees the client and system type, not audit evidence. For a current audit client, the Chief Auditor approves any offer before it is sent.</p>
            </Card>
          </div>
        </div>
        <div className="side stack">
          <Card title="Sources"><ul className="tight">{c.sources.map((s, i) => <li key={i}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a></li>)}</ul></Card>
          <Card title="Laws it interprets">
            {!c.regulation_ids.length ? <p className="small muted" style={{ margin: 0 }}>None linked.</p> : (
              <ul className="tight">{(laws.data ?? []).filter(Boolean).map((l) => <li key={l!.id}>{can(me, 'view_reg_master') ? <Link to={`/reg/${l!.id}`}>{l!.short_name}</Link> : <span>{l!.short_name}</span>} <span className="small muted">{l!.jurisdiction_name}</span></li>)}</ul>
            )}
          </Card>
          <Card title="Record"><p className="small muted" style={{ margin: 0 }}>Version {c.version} · last checked {fmtDate(c.last_update_on)} · {c.origin === 'claude' ? 'added from a Claude refresh' : c.origin === 'seed' ? 'starter case' : 'added by hand'}</p></Card>
        </div>
      </div>
      {editing && <CaseForm initial={c} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); refresh(); }} />}
      {assign && <AssignDialog onClose={() => setAssign(null)} onAssign={async (owner) => {
        const out = await api.post<{ created: number }>(`/litigation/${c.id}/opportunities`, { organization_ids: assign, owner_id: owner });
        setAssign(null);
        await Promise.all([refresh(), qc.invalidateQueries({ queryKey: ['opportunities'] }), qc.invalidateQueries({ queryKey: ['litigation'] })]);
        setMsg({ tone: 'success', text: `${out.created} ${out.created === 1 ? 'opportunity' : 'opportunities'} created.` });
      }} />}
    </div>
  );
}
