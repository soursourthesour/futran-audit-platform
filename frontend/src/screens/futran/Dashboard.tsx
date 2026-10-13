import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, ButtonLink, Card, EmptyState, Loading, PageHeader, TextField, fmtDate, fmtDateTime } from '@/components/ui';

type Row = { engagement_id: string; client_id: string; client_name: string; audit_ref: string; type_label: string; stage: number; stage_label: string; status: string; status_label: string; chief_auditor: string | null; target_date: string | null };
type Data = { kpis: Record<string, number>; counts: Record<string, number>; rows: Row[] };
type Activity = { at: string; actor: string | null; client: string | null; client_id: string; summary: string | null };

const TONE: Record<string, 'navy' | 'success' | 'warn' | 'muted'> = { draft: 'muted', pending_approval: 'warn', initiated: 'navy', in_progress: 'navy', completed: 'success', archived: 'muted' };
const FILTERS = [{ key: 'all', label: 'All' }, { key: 'in_progress', label: 'In progress' }, { key: 'completed', label: 'Completed' }, { key: 'drafts', label: 'Drafts' }];

export function Dashboard() {
  const { data: me } = useMe();
  const flash = (useLocation().state as { flash?: string } | null)?.flash;
  const canCreate = hasRole(me ?? undefined, 'auditor', 'chief_auditor', 'admin');
  const isChief = hasRole(me ?? undefined, 'chief_auditor');
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const data = useQuery({ queryKey: ['engagements', filter, q], queryFn: () => api.get<Data>(`/engagements?filter=${filter}&q=${encodeURIComponent(q)}`) });
  const act = useQuery({ queryKey: ['engagements', 'activity'], queryFn: () => api.get<Activity[]>('/engagements/activity') });
  const k = data.data?.kpis;
  const link = (r: Row) => (r.status === 'draft' ? `/clients/${r.client_id}/setup/company` : r.status === 'pending_approval' ? `/clients/${r.client_id}/setup/submit` : `/clients/${r.client_id}`);
  return (
    <div className="page">
      <PageHeader title="Audits" subtitle="All clients and engagements you can see. Auditors see only assigned clients and their own drafts." actions={canCreate ? <ButtonLink to="/audits/new" variant="primary">New client</ButtonLink> : undefined} />
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">In progress</div><div className="value">{k?.in_progress ?? '–'}</div><div className="hint">engagements</div></div>
        <div className="tile"><div className="label">Completed</div><div className="value">{k?.completed ?? '–'}</div><div className="hint">final report signed</div></div>
        <div className="tile"><div className="label">{isChief ? 'Awaiting your approval' : 'Awaiting approval'}</div><div className="value">{k?.awaiting_approval ?? '–'}</div><div className="hint">drafts ready to send</div></div>
        <div className="tile"><div className="label">Awaiting client</div><div className="value">{k?.awaiting_client ?? '–'}</div><div className="hint">engagement letter not yet signed</div></div>
      </div>
      <div className="split">
        <div className="main">
          <Card>
            <div className="stack">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <div className="pills" role="tablist" aria-label="Filter engagements">
                  {FILTERS.map((f) => <button key={f.key} type="button" role="tab" className="pill" aria-selected={filter === f.key} onClick={() => setFilter(f.key)}>{f.label} · {data.data?.counts[f.key] ?? 0}</button>)}
                </div>
                <div style={{ minWidth: 240 }}><TextField label="Search clients" value={q} onChange={(e) => setQ(e.target.value)} /></div>
              </div>
              {data.isLoading ? <Loading /> : !data.data?.rows.length ? <EmptyState>{q || filter !== 'all' ? 'No engagements match.' : 'No engagements yet. Start with New client.'}</EmptyState> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Client</th><th>Engagement</th><th>Stage</th><th>Chief Auditor</th><th>Target date</th><th>Status</th></tr></thead>
                    <tbody>
                      {data.data.rows.map((r) => (
                        <tr key={r.engagement_id}>
                          <td><Link to={link(r)}><strong>{r.client_name}</strong></Link><div className="small muted">{r.audit_ref}</div></td>
                          <td>{r.type_label}</td>
                          <td>{r.stage_label}</td>
                          <td>{r.chief_auditor ?? '—'}</td>
                          <td>{fmtDate(r.target_date)}</td>
                          <td><Badge tone={TONE[r.status] ?? 'muted'}>{r.status_label}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </Card>
        </div>
        <div className="side">
          <Card title="Recent activity">
            {act.isLoading ? <Loading /> : !act.data?.length ? <EmptyState>Nothing yet.</EmptyState> : (
              <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {act.data.map((a, i) => (
                  <li key={i} style={{ padding: '10px 0', borderTop: i ? '1px solid var(--line-soft)' : undefined }}>
                    <Link to={`/clients/${a.client_id}`}><strong>{a.client}</strong></Link> {a.summary}
                    <div className="muted">{a.actor ?? 'System'} · {fmtDateTime(a.at)}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
