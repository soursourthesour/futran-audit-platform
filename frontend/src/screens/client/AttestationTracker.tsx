import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, EmptyState, FieldGroup, Loading, PageHeader, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { attestationLaunchHelp as H } from '@/help/client';

type Tracker = {
  campaign: { id: string; status: string; policy_version: string; launched_at: string; closes_at: string; closed_at: string | null; link: string | null };
  totals: { responses: number | string; use_ai: number | null; personal_accounts: number | null; headcount: number | null };
  departments: { id: string; name: string; responses: number | string; headcount: number | null }[];
  tools: { label: string; count: number }[];
  individuals: { id: string; name: string; email: string | null; department: string; uses_ai: boolean; tools: string[]; purposes: string[]; data_entered: string[]; submitted_at: string }[] | null;
};
type PeopleLite = { departments: { id: string; name: string; in_scope: boolean }[] };

export function AttestationTracker() {
  const { data: me } = useMe();
  return <AttestationView clientId={me?.organization.id ?? ''} canLaunch={!!me?.roles.some((r) => r.role === 'caico')} />;
}

export function FutranAttestation() {
  const { clientId = '' } = useParams();
  return <AttestationView clientId={clientId} canLaunch={false} />;
}

function AttestationView({ clientId, canLaunch }: { clientId: string; canLaunch: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['attestation', clientId], queryFn: () => api.get<Tracker>(`/clients/${clientId}/attestation`), enabled: !!clientId, retry: false });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  const none = q.error instanceof ApiError && q.error.status === 404;
  if (none) {
    return (
      <div className="page">
        <PageHeader title="AI use attestation" subtitle="A short, anonymous-to-managers check-in that asks staff which AI tools they use for work and how." />
        {canLaunch ? <Launch clientId={clientId} onDone={() => qc.invalidateQueries({ queryKey: ['attestation', clientId] })} /> : <Card><EmptyState>The client has not launched the attestation campaign yet.</EmptyState></Card>}
      </div>
    );
  }
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const t = q.data;
  const link = t.campaign.link ? `${window.location.origin}${t.campaign.link}` : null;
  async function copy() {
    if (!link) return;
    try { await navigator.clipboard.writeText(link); setMsg({ tone: 'success', text: 'Staff link copied. Send it to everyone in the departments in scope.' }); } catch { setMsg({ tone: 'success', text: link }); }
  }
  async function close() {
    try { await api.post(`/clients/${clientId}/attestation/close`); await qc.invalidateQueries(); setMsg({ tone: 'success', text: 'Campaign closed. The link no longer accepts answers.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const open = t.campaign.status === 'open';
  return (
    <div className="page">
      <PageHeader title="AI use attestation" subtitle={`Policy version ${t.campaign.policy_version} · launched ${fmtDate(t.campaign.launched_at)} · ${open ? `closes ${fmtDate(t.campaign.closes_at)}` : `closed ${fmtDate(t.campaign.closed_at ?? t.campaign.closes_at)}`}`}
        actions={canLaunch ? <>{link && open && <Button onClick={copy}>Copy staff link</Button>}{open && <Button onClick={close}>Close campaign</Button>}</> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Responses</div><div className="value">{t.totals.responses}</div><div className="hint">{t.totals.headcount ? `of ${t.totals.headcount} staff` : 'staff'}</div></div>
        <div className="tile"><div className="label">Use AI at work</div><div className="value">{t.totals.use_ai ?? '—'}</div><div className="hint">respondents</div></div>
        <div className="tile"><div className="label">On personal accounts</div><div className="value">{t.totals.personal_accounts ?? '—'}</div><div className="hint">respondents</div></div>
        <div className="tile"><div className="label">Status</div><div className="value" style={{ fontSize: 24 }}>{open ? <Badge tone="navy">Open</Badge> : <Badge tone="success">Closed</Badge>}</div></div>
      </div>
      <div className="split">
        <div className="main stack">
          <Card title="Responses by department">
            <p className="small muted" style={{ marginTop: 0 }}>Totals only. Counts under 3 are hidden so nobody can be identified. Individual answers are visible to the Chief AI Compliance Officer, the DPO and the Futran auditors, not to department leads.</p>
            <table className="table"><tbody>
              {t.departments.map((d) => <tr key={d.id}><td>{d.name}</td><td style={{ textAlign: 'right' }}>{d.responses}{d.headcount && typeof d.responses === 'number' ? ` / ${d.headcount}` : ''}</td></tr>)}
            </tbody></table>
          </Card>
          {t.individuals && (
            <Card title={`Individual answers · ${t.individuals.length}`}>
              {t.individuals.length === 0 ? <EmptyState>No answers yet.</EmptyState> : (
                <div className="table-wrap"><table className="table">
                  <thead><tr><th>Name</th><th>Department</th><th>Tools</th><th>Data entered</th><th>Submitted</th></tr></thead>
                  <tbody>{t.individuals.map((a) => (
                    <tr key={a.id}><td>{a.name}<div className="small muted">{a.email}</div></td><td>{a.department}</td><td className="small">{a.uses_ai ? a.tools.join(', ') : 'Does not use AI for work'}</td><td className="small">{a.data_entered.join(', ') || '—'}</td><td className="small">{fmtDateTime(a.submitted_at)}</td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Card>
          )}
        </div>
        <div className="side">
          <Card title="Tools declared">
            {t.tools.length === 0 ? <EmptyState>Shown once at least 3 people have answered.</EmptyState> : (
              <table className="table"><tbody>{t.tools.map((x) => <tr key={x.label}><td>{x.label}</td><td style={{ textAlign: 'right' }}>{x.count}</td></tr>)}</tbody></table>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Launch({ clientId, onDone }: { clientId: string; onDone: () => void }) {
  const people = useQuery({ queryKey: ['people', clientId], queryFn: () => api.get<PeopleLite>(`/clients/${clientId}/people`) });
  const inScope = (people.data?.departments ?? []).filter((d) => d.in_scope);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [closes, setCloses] = useState(new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10));
  const [version, setVersion] = useState('1.0');
  const [err, setErr] = useState<string | null>(null);
  const ids = chosen ?? inScope.map((d) => d.id);
  async function go() {
    setErr(null);
    try {
      await api.post(`/clients/${clientId}/attestation/campaigns`, { department_ids: ids, closes_at: `${closes}T23:59:00`, policy_version: version });
      onDone();
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card title="Launch the campaign">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>You get one link to send to all staff in the departments below. Nobody needs an account. Acknowledge the employee data notice on the Getting started page first.</p>
        <FieldGroup legend="Departments" help={H.departments}>
          <div className="grid-2">{inScope.map((d) => <Checkbox key={d.id} label={d.name} checked={ids.includes(d.id)} onChange={(e) => setChosen(e.target.checked ? [...ids, d.id] : ids.filter((x) => x !== d.id))} />)}</div>
        </FieldGroup>
        <div className="grid-2">
          <TextField type="date" label="Closes on" help={H.closesOn} value={closes} onChange={(e) => setCloses(e.target.value)} />
          <TextField label="AI use policy version" help={H.policyVersion} value={version} onChange={(e) => setVersion(e.target.value)} />
        </div>
        <div><Button variant="primary" onClick={go} disabled={!ids.length}>Launch and get the staff link</Button></div>
      </div>
    </Card>
  );
}
