import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { EmptyState, Loading, PageHeader, TextField, fmtDateTime } from '@/components/ui';

type Entry = { id: string; at: string; actor_name: string | null; action: string; object_type: string; object_id: string | null; summary: string | null; ip: string | null };

export function AuditLogScreen() {
  const [action, setAction] = useState('');
  const q = useQuery({ queryKey: ['audit-log'], queryFn: () => api.get<Entry[]>('/audit-log?limit=1000') });
  const rows = (q.data ?? []).filter((e) => !action || e.action.includes(action) || (e.summary ?? '').toLowerCase().includes(action.toLowerCase()));
  return (
    <div className="page">
      <PageHeader
        title="Audit log"
        subtitle="Every create, edit, approval, send and view of sensitive records. Entries cannot be changed or deleted."
        actions={<a className="btn" href="/api/v1/audit-log?format=csv" download>Export CSV</a>}
      />
      <div style={{ maxWidth: 360 }}><TextField label="Filter by action or summary" value={action} onChange={(e) => setAction(e.target.value)} /></div>
      <section className="card">
        {q.isLoading ? <Loading /> : rows.length === 0 ? <EmptyState>No entries match.</EmptyState> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Record</th><th>Summary</th><th>IP</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td>{fmtDateTime(e.at)}</td>
                    <td>{e.actor_name ?? '—'}</td>
                    <td><code>{e.action}</code></td>
                    <td>{e.object_type}</td>
                    <td>{e.summary ?? ''}</td>
                    <td className="muted">{e.ip ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
