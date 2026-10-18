import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, TextField, fmtDateTime } from '@/components/ui';
import { SignPanel, type SignOffView } from '@/components/SignPanel';
import { useMe } from '@/api/auth';
import { ReportTable, type ReportRow } from '@/screens/futran/FinalReport';

type Data = {
  audit_ref: string; client: string; stage: number;
  reports: ReportRow[];
  acknowledgement: { notice: string; text: string; commitments: Record<string, string>; can_sign: boolean; signed_by: string | null; signed_at: string | null; commitment: string | null; commitment_text: string | null; disputed_refs: string[]; my_name: string };
  findings: { ref: string; title: string; severity: string }[];
  public_summary: { required: boolean; text: string | null; sign_off: SignOffView | null };
};

/** Screen 19 (client): the released report versions, the acknowledgement of the final report and the public summary. */
export function ClientReport() {
  const { data: me } = useMe();
  const clientId = me?.organization.id ?? '';
  const key = ['client-report', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/clients/${clientId}/report`), enabled: !!clientId });
  const [name, setName] = useState('');
  const [commitment, setCommitment] = useState<'plan' | 'disputes'>('plan');
  const [disputed, setDisputed] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  if (q.isLoading || !me) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const ack = d.acknowledgement;
  async function sign() {
    setErr(null); setFe({});
    try {
      await api.post(`/clients/${clientId}/report/acknowledge`, { typed_name: name, commitment, disputed_refs: commitment === 'disputes' ? disputed : [] });
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <div className="page">
      <PageHeader title="Audit report" subtitle={`${d.audit_ref}. The draft report (v1.0) comes first for your management responses; the final report (v1.1) follows.`} />
      <div className="stack" style={{ marginTop: 16 }}>
        <Card title="Report versions">
          {d.reports.length === 0 ? <EmptyState>The report has not been released yet. Futran releases the draft once its findings are approved and signed.</EmptyState> : <ReportTable rows={d.reports} />}
        </Card>
        {(ack.signed_by || ack.can_sign) && (
          <Card title="Acknowledge the final report">
            <div className="stack">
              <Alert tone="info">{ack.notice}</Alert>
              <blockquote className="statement">{ack.text}</blockquote>
              {ack.signed_by ? (
                <p style={{ margin: 0 }}><Badge tone="success">Acknowledged</Badge> by {ack.signed_by}, {fmtDateTime(ack.signed_at)}. {ack.commitment_text}</p>
              ) : (
                <>
                  {err && <Alert tone="danger">{err}</Alert>}
                  <fieldset className="stack-sm">
                    <legend>Remediation commitment</legend>
                    <label className="check"><input type="radio" name="commitment" checked={commitment === 'plan'} onChange={() => setCommitment('plan')} /><span>{ack.commitments.plan}</span></label>
                    <label className="check"><input type="radio" name="commitment" checked={commitment === 'disputes'} onChange={() => setCommitment('disputes')} /><span>We dispute one or more findings.</span></label>
                  </fieldset>
                  {commitment === 'disputes' && (
                    <fieldset className="stack-sm small">
                      <legend>Findings you dispute</legend>
                      {d.findings.map((f) => <label key={f.ref} className="check"><input type="checkbox" checked={disputed.includes(f.ref)} onChange={() => setDisputed(disputed.includes(f.ref) ? disputed.filter((x) => x !== f.ref) : [...disputed, f.ref])} /><span>{f.ref} {f.title}</span></label>)}
                      {fe.disputed_refs && <span className="error">{fe.disputed_refs}</span>}
                    </fieldset>
                  )}
                  <TextField label="Type your full name to sign" placeholder={ack.my_name} value={name} onChange={(e) => setName(e.target.value)} error={fe.typed_name} />
                  <div><Button variant="primary" disabled={!name.trim()} onClick={sign}>Sign acknowledgement</Button></div>
                </>
              )}
            </div>
          </Card>
        )}
        {d.public_summary.sign_off && (
          <Card title="Public summary · sign-off 8">
            <div className="stack">
              <p className="small muted" style={{ margin: 0 }}>Your organization publishes this summary. Approve the wording before it is released.</p>
              <SignPanel signOffId={d.public_summary.sign_off.id} hideTitle onSigned={() => qc.invalidateQueries({ queryKey: key })} agreeText="I approve this public summary for release." />
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
