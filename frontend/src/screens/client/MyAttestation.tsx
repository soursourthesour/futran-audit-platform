import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import { AttestationSteps, type AttestInfo, type Identity } from '@/screens/phone/AttestationForm';

type Mine = {
  line_item: { title: string; status: 'to_do' | 'submitted' | 'closed'; sent_at: string; closes_at: string; submitted_at: string | null; via: 'link' | 'in_app' | null } | null;
  prefill: Identity;
  form: AttestInfo | null;
};

/** Every signed-in client user's own AI use attestation: the line item, and the same form as the staff link. */
export function MyAttestation() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['my-attestation'], queryFn: () => api.get<Mine>('/me/attestation') });
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const { line_item: item, prefill, form } = q.data;
  const status = item?.status === 'submitted'
    ? <Badge tone="success">Submitted on {fmtDate(item.submitted_at)}</Badge>
    : item?.status === 'closed' ? <Badge tone="muted">Closed</Badge> : <Badge tone="warn">To do</Badge>;

  return (
    <div className="page">
      <PageHeader title="AI attestation" subtitle="Your own answers about the AI tools and agents you use for work. Individual answers are seen only by the Chief AI Compliance Officer, the Data Protection Officer and the Futran auditors." />
      {msg && <Alert tone="success">{msg}</Alert>}
      <Card title="To complete">
        {!item ? <EmptyState>Nothing to complete. When your organization sends the AI use attestation, it appears here and you get an email.</EmptyState> : (
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div className="stack-sm" style={{ minWidth: 0 }}>
              <div><strong>{item.title}</strong> {status}</div>
              <div className="small muted">Sent {fmtDate(item.sent_at)} · closes {fmtDate(item.closes_at)}{item.via === 'link' ? ' · answered through the staff link with your work email' : ''}</div>
            </div>
            {item.status === 'to_do' && !open && <Button variant="primary" onClick={() => setOpen(true)}>Complete attestation</Button>}
          </div>
        )}
      </Card>
      {open && item?.status === 'to_do' && form && (
        <div style={{ maxWidth: 560, marginTop: 24 }}>
          <Card title="AI use attestation">
            <AttestationSteps info={form} identity={prefill} headingLevel={2} onSubmit={async (payload) => {
              await api.post('/me/attestation', payload);
              setOpen(false);
              setMsg('Thank you. Your attestation has been recorded.');
              await qc.invalidateQueries({ queryKey: ['my-attestation'] });
            }} />
          </Card>
        </div>
      )}
    </div>
  );
}
