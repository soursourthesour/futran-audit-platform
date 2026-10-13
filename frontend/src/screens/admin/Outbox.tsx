import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Badge, EmptyState, Loading, PageHeader, fmtDateTime } from '@/components/ui';

type Msg = { id: string; to: string[]; cc: string[] | null; subject: string; body_html: string; template_key: string; status: string; error: string | null; created_at: string };

export function OutboxScreen() {
  const q = useQuery({ queryKey: ['outbox'], queryFn: () => api.get<Msg[]>('/admin/outbox') });
  const [open, setOpen] = useState<string | null>(null);
  const selected = q.data?.find((m) => m.id === open);
  return (
    <div className="page">
      <PageHeader title="Outbox" subtitle="Every email the platform has sent or would send. In test mode nothing leaves the platform; open a message to read it." />
      <div className="split">
        <section className="card main">
          {q.isLoading ? <Loading /> : !q.data?.length ? <EmptyState>No emails yet.</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>When</th><th>To</th><th>Subject</th><th>Status</th></tr></thead>
                <tbody>
                  {q.data.map((m) => (
                    <tr key={m.id} className="clickable" onClick={() => setOpen(m.id)} aria-selected={open === m.id}>
                      <td>{fmtDateTime(m.created_at)}</td>
                      <td>{m.to.join(', ')}</td>
                      <td><button className="link-btn" onClick={() => setOpen(m.id)}>{m.subject}</button></td>
                      <td>{m.status === 'sent' ? <Badge tone="success">Sent</Badge> : m.status === 'failed' ? <Badge tone="danger">Failed</Badge> : <Badge>Queued</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card side" aria-live="polite">
          {selected ? (
            <div className="card-body stack">
              <h2 style={{ fontSize: 16 }}>{selected.subject}</h2>
              <div className="small muted">To {selected.to.join(', ')}{selected.cc?.length ? ` · CC ${selected.cc.join(', ')}` : ''}</div>
              {selected.error && <div className="alert alert-danger">{selected.error}</div>}
              <iframe title="Email preview" sandbox="" srcDoc={selected.body_html} style={{ width: '100%', minHeight: 520, border: '1px solid var(--line)', borderRadius: 6 }} />
            </div>
          ) : <EmptyState>Select a message to preview it.</EmptyState>}
        </section>
      </div>
    </div>
  );
}
