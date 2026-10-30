import { Link, useParams } from 'react-router-dom';
import { useMe } from '@/api/auth';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Card, fmtDateTime } from '@/components/ui';
import { type Connection } from '@/api/mail';
import { StatusBadge } from './common';

type Status = { status: Connection['status']; provider: string | null; provider_label: string | null; mailbox_address: string | null; sender_mode: string | null; people: number | null; last_sync_at: string | null; test_sent_at: string | null };

/** Wizard step 6 (client contacts) and the client page: whether the client has connected its email (spec §26.1). */
export function ClientEmailStatus({ clientId: given }: { clientId?: string }) {
  const params = useParams();
  const { data: me } = useMe();
  const clientId = given ?? params.clientId ?? '';
  const q = useQuery({ queryKey: ['client-mail-status', clientId], queryFn: () => api.get<Status>(`/mail/clients/${clientId}/status`), enabled: !!clientId, retry: false });
  if (!q.data) return null;
  const s = q.data;
  return (
    <Card title="Client email">
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <StatusBadge status={s.status} />
        <span className="small">
          {s.status === 'connected'
            ? `${s.provider_label ?? ''}${s.mailbox_address ? ` · sends from ${s.mailbox_address}` : ''}${s.sender_mode === 'futran_on_behalf' ? ' · Futran sends on the client\'s behalf' : ''}${s.people !== null ? ` · ${s.people.toLocaleString()} people synced` : ''}${s.last_sync_at ? ` · last sync ${fmtDateTime(s.last_sync_at)}` : ''}`
            : s.status === 'consent_requested' ? 'The client has asked its IT administrator to approve access.'
            : 'The Client Admin connects Microsoft 365 or Google Workspace during onboarding ("Connect your email" in Getting started). Until then emails come from Futran on the client\'s behalf.'}
        </span>
        {me?.organization.type === 'futran' && !given && <Link className="btn btn-sm" to={`/clients/${clientId}/groups`}>Email groups</Link>}
      </div>
    </Card>
  );
}
