import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { Alert, Loading } from '@/components/ui';
import { PhoneShell } from '@/shells/Shells';
import { AttestationSteps, type AttestInfo } from './AttestationForm';

/** The no-login staff check-in (schematic D13, mockup Attestation): four short steps on a phone. */
export function PhoneAttestation() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['attest', token], queryFn: () => api.get<AttestInfo>(`/public/attest/${token}`), retry: false });
  const [done, setDone] = useState(false);

  if (q.isLoading) return <PhoneShell title="AI use check-in"><Loading /></PhoneShell>;
  if (q.error instanceof ApiError || !q.data) return <PhoneShell title="AI use check-in"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const info = q.data;
  if (!info.open) return <PhoneShell title={`${info.client_name} · AI use check-in`}><Alert tone="info">This check-in has closed. Thank you; nothing more is needed.</Alert></PhoneShell>;
  if (done) return <PhoneShell title={`${info.client_name} · AI use check-in`}><div className="stack"><h1 style={{ fontSize: 22 }}>Thank you</h1><p>Your answers have been recorded. If something changes, you can open the same link and answer again with the same email; your new answers replace the old ones.</p></div></PhoneShell>;

  return (
    <PhoneShell title={`${info.client_name} · AI use check-in`}>
      <AttestationSteps info={info} onSubmit={async (payload) => { await api.post(`/public/attest/${token}`, payload); setDone(true); }} />
    </PhoneShell>
  );
}
