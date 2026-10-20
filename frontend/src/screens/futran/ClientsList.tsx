import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, ButtonLink, Card, EmptyState, Loading, PageHeader, TextField } from '@/components/ui';

type Row = {
  id: string; name: string; industry: string | null; internal: boolean; headquarters: string; sites: number; people: number;
  engagement: { id: string; audit_ref: string | null; type_label: string; stage_label: string; status: string; status_label: string };
};
const TONE: Record<string, 'navy' | 'success' | 'warn' | 'muted'> = { draft: 'muted', pending_approval: 'warn', initiated: 'navy', in_progress: 'navy', completed: 'success', archived: 'muted' };

/** The Clients page: every client you can see, with where its current engagement stands. */
export function ClientsList() {
  const { data: me } = useMe();
  const [q, setQ] = useState('');
  const query = useQuery({ queryKey: ['clients-list', q], queryFn: () => api.get<{ clients: Row[] }>(`/clients?q=${encodeURIComponent(q)}`) });
  const canCreate = hasRole(me ?? undefined, 'auditor', 'chief_auditor', 'admin');
  const link = (r: Row) => (r.engagement.status === 'draft' ? `/clients/${r.id}/setup/company` : r.engagement.status === 'pending_approval' ? `/clients/${r.id}/setup/submit` : `/clients/${r.id}`);
  return (
    <div className="page">
      <PageHeader title="Clients" subtitle="Every client you can see. Auditors see only the clients they are assigned to." actions={canCreate ? <ButtonLink to="/audits/new" variant="primary">New client</ButtonLink> : undefined} />
      <Card>
        <div className="stack">
          <div style={{ maxWidth: 320 }}><TextField label="Search clients" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          {query.isLoading ? <Loading /> : query.isError ? <Alert tone="danger">{errorMessage(query.error)}</Alert> : !query.data?.clients.length ? <EmptyState>{q ? 'No clients match.' : 'No clients yet. Start with New client.'}</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Client</th><th>Industry</th><th>Headquarters</th><th>Sites</th><th>People</th><th>Current engagement</th><th>Stage</th><th>Status</th></tr></thead>
                <tbody>
                  {query.data.clients.map((r) => (
                    <tr key={r.id}>
                      <td><Link to={link(r)}><strong>{r.name}</strong></Link>{r.internal && <> <Badge tone="muted">Internal</Badge></>}</td>
                      <td>{r.industry ?? '—'}</td>
                      <td>{r.headquarters || '—'}</td>
                      <td>{r.sites}</td>
                      <td>{r.people}</td>
                      <td>{r.engagement.type_label}<div className="small muted">{r.engagement.audit_ref ?? 'Not yet assigned'}</div></td>
                      <td>{r.engagement.stage_label}</td>
                      <td><Badge tone={TONE[r.engagement.status] ?? 'muted'}>{r.engagement.status_label}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
