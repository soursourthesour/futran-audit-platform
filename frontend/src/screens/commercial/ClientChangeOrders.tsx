import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { money, type ChangeOrder } from '@/api/commercial';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, TextArea, fmtDate } from '@/components/ui';
import './commercial.css';

/** Client app: the CAICO approves or rejects change orders. The scope changes only when the CAICO approves. */
export function ClientChangeOrders() {
  const q = useQuery({ queryKey: ['client-change-orders'], queryFn: () => api.get<ChangeOrder[]>('/change-orders') });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const decide = async (co: ChangeOrder, approve: boolean) => {
    setMsg(null);
    try {
      await api.post(`/change-orders/${co.id}/decide`, { approve, note: notes[co.id] || null });
      setMsg({ tone: 'success', text: approve ? `${co.ref} approved. Futran will add it to the audit scope.` : `${co.ref} rejected.` });
      await q.refetch();
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  };
  return (
    <div className="page commercial">
      <PageHeader title="Change orders" subtitle="Futran asks before the audit scope grows. Nothing changes until you approve." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {q.data.length === 0 ? <EmptyState>No change orders.</EmptyState> : q.data.map((co) => (
        <Card key={co.id} title={`${co.ref} · ${co.kind_label ?? 'Change order'}`} actions={<Badge tone={co.status === 'approved' ? 'success' : co.status === 'rejected' ? 'danger' : 'navy'}>{co.status_label}</Badge>}>
          <div className="stack">
            <p className="small muted" style={{ margin: 0 }}>{co.engagement_name} · raised {fmtDate(co.raised_at)}</p>
            <p style={{ margin: 0 }}>{co.reason}</p>
            <ul className="plain">{co.lines.map((l, i) => <li key={i}>{l.qty} × {l.description ?? l.code} at {money(l.unit_price)} = <strong>{money(l.value)}</strong></li>)}</ul>
            {co.status === 'awaiting_client' && <>
              <TextArea label="Note (needed if you reject)" rows={2} value={notes[co.id] ?? ''} onChange={(e) => setNotes({ ...notes, [co.id]: e.target.value })} />
              <div className="row"><Button variant="primary" onClick={() => decide(co, true)}>Approve</Button><Button onClick={() => decide(co, false)}>Reject</Button></div>
            </>}
            {co.decided_note && co.status !== 'awaiting_client' && <p className="small" style={{ margin: 0 }}>Note: {co.decided_note}</p>}
          </div>
        </Card>
      ))}
    </div>
  );
}
