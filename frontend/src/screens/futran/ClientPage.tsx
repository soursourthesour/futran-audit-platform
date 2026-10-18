import { Fragment, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, fileUrl, fmtDateTime } from '@/components/ui';
import { StageTracker } from '@/components/StageTracker';
import { SignPanel } from '@/components/SignPanel';
import { DocPreview } from '@/components/DocPreview';

type Page = {
  client: { id: string; name: string; legal_name: string | null; client_ref: string; industry: string | null; employee_band: string | null; hq: string; status: string };
  engagement: { id: string; audit_ref: string; name: string; type_label: string; status: string; status_label: string; stage: number; stage_label: string; returned_comment: string | null };
  gate: { ready: boolean; unmet: string[] };
  sites: { site_name: string; city: string | null; jurisdictions: string[] }[];
  laws: { label: string; jurisdiction: string | null; type: string | null }[];
  contacts: { role: string; role_label: string; name: string | null; email: string | null; not_appointed: boolean; invite_status: string | null }[];
  team: { name: string; role_label: string }[];
  package: { id: string; status: string; documents: { id: string; item: number; title: string; pdf_file_id: string | null; docx_file_id: string | null; csv_file_id: string | null; completed_at: string | null }[] } | null;
  sign_off_1: { id: string; status: string } | null;
  activity: { at: string; actor: string | null; summary: string | null }[];
};

export function ClientPage() {
  const { clientId = '' } = useParams();
  const qc = useQueryClient();
  const flash = (useLocation().state as { flash?: string } | null)?.flash;
  const q = useQuery({ queryKey: ['client-page', clientId], queryFn: () => api.get<Page>(`/clients/${clientId}`) });
  const [preview, setPreview] = useState<{ id: string; title: string } | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [tab, setTab] = useState<string>('overview');
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const p = q.data;
  const e = p.engagement;
  const places = [...new Set(p.sites.map((s) => s.city).filter(Boolean))].join(' and ');

  async function resend(role: string) {
    setMsg(null);
    try {
      const r = await api.post<{ sent_to: string }>(`/clients/${clientId}/contacts/${role}/resend`);
      setMsg({ tone: 'success', text: `A new invitation was sent to ${r.sent_to}. The earlier link no longer works.` });
      await qc.invalidateQueries({ queryKey: ['client-page', clientId] });
    } catch (ex) {
      setMsg({ tone: 'danger', text: errorMessage(ex) });
    }
  }

  const live = e.status !== 'draft' && e.status !== 'pending_approval';
  const tabs = [['overview', 'Overview'], ['engagements', 'Engagements'], ['laws', 'Locations and laws'], ['contacts', 'Contacts and users'], ['documents', 'Documents'], ['activity', 'Activity']] as const;
  const contacts = (
    <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {p.contacts.map((c) => (
        <li key={c.role} style={{ padding: '8px 0' }}>
          <strong>{c.role_label}</strong>
          <div>{c.not_appointed ? 'Not appointed' : c.name}{c.email && !c.not_appointed ? <span className="muted"> · {c.email}</span> : null}{c.invite_status ? <span className="muted"> · {c.invite_status}</span> : null}</div>
          {c.invite_status && c.invite_status !== 'Active' && c.invite_status !== 'Not invited yet' && <Button size="sm" variant="ghost" onClick={() => resend(c.role)}>Resend invitation</Button>}
        </li>
      ))}
    </ul>
  );
  const activity = (limit?: number) => p.activity.length === 0 ? <EmptyState>Nothing yet.</EmptyState> : (
    <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {p.activity.slice(0, limit).map((a, i) => <li key={i} style={{ padding: '8px 0', borderTop: i ? '1px solid var(--line-soft)' : undefined }}>{a.summary}<div className="muted">{a.actor ?? 'System'} · {fmtDateTime(a.at)}</div></li>)}
    </ul>
  );
  const resendable = p.contacts.find((c) => c.invite_status && c.invite_status !== 'Active' && c.invite_status !== 'Not invited yet');

  return (
    <div className="page">
      <PageHeader crumbs={[{ to: '/audits', label: 'Audits' }, { label: p.client.name }]} title={p.client.name} subtitle={`${e.type_label}${places ? ` · ${places}` : ''} · ${e.audit_ref}`}
        actions={e.status === 'pending_approval' ? <Link className="btn btn-primary" to={`/clients/${clientId}/setup/submit`}>Review initiation package</Link> : e.status === 'draft' ? <Link className="btn" to={`/clients/${clientId}/setup/company`}>Continue the draft</Link> : resendable ? <Button onClick={() => resend(resendable.role)}>Resend invitation</Button> : undefined} />
      {flash && !msg && <Alert tone="success">{flash}</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="tabs" role="tablist" aria-label="Client sections">
        {tabs.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      {tab === 'overview' && (
        <div className="stack">
          <Card title="Engagement progress" actions={<Badge tone="navy">{e.status_label}</Badge>}>
            <div className="stack">
              <StageTracker stage={e.stage} status={e.status} />
              {live && (
                p.gate.ready ? <p className="small">Stage {e.stage} is complete.</p> : (
                  <div><strong className="small">What's left in this stage</strong><ul className="small" style={{ margin: '4px 0 0', paddingLeft: 18 }}>{p.gate.unmet.map((u) => <li key={u}>{u}</li>)}</ul></div>
                )
              )}
            </div>
          </Card>
          {p.sign_off_1 && p.sign_off_1.status !== 'approved' && (
            <Card title="Sign-off 1: engagement letter and scope"><SignPanel signOffId={p.sign_off_1.id} /></Card>
          )}
          <div className="grid-3">
            <Card title="Client details">
              <dl className="kv-stacked">
                <dt>Industry</dt><dd>{p.client.industry ?? '—'}</dd>
                <dt>Employees</dt><dd>{p.client.employee_band ?? '—'}</dd>
                <dt>Headquarters</dt><dd>{p.client.hq || '—'}</dd>
                <dt>Laws in scope</dt><dd>{p.laws.map((l) => l.label + (l.type === 'voluntary' ? ' (framework)' : '')).join(' · ') || '—'}</dd>
                {p.contacts.filter((c) => c.role === 'caico' || c.role === 'client_admin').map((c) => <Fragment key={c.role}><dt>{c.role_label}</dt><dd>{c.not_appointed ? 'Not appointed' : c.name}{c.invite_status ? ` · ${c.invite_status.toLowerCase()}` : ''}</dd></Fragment>)}
              </dl>
            </Card>
            <Card title="Futran team">
              <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {p.team.map((m, i) => <li key={i} className="row" style={{ justifyContent: 'space-between', padding: '6px 0' }}><span>{m.name}</span><span className="muted">{m.role_label}</span></li>)}
              </ul>
            </Card>
            <Card title="Activity">
              {activity(5)}
              <p className="small" style={{ marginBottom: 0 }}><button type="button" className="linklike" onClick={() => setTab('activity')}>View all activity</button></p>
            </Card>
          </div>
          {live && <Card title="Work areas"><WorkAreas clientId={clientId} /></Card>}
        </div>
      )}
      {tab === 'engagements' && (
        <Card>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Engagement</th><th>Reference</th><th>Stage</th><th>Status</th></tr></thead>
            <tbody><tr><td>{e.type_label}</td><td>{e.audit_ref}</td><td>{e.stage} · {e.stage_label}</td><td><Badge tone="navy">{e.status_label}</Badge></td></tr></tbody>
          </table></div>
          {live && <div style={{ marginTop: 16 }}><WorkAreas clientId={clientId} /></div>}
        </Card>
      )}
      {tab === 'laws' && (
        <div className="stack">
          <Card title="Sites in scope">
            {p.sites.length === 0 ? <EmptyState>No sites yet.</EmptyState> : (
              <div className="table-wrap"><table className="table"><thead><tr><th>Site</th><th>City</th><th>Laws from</th></tr></thead>
                <tbody>{p.sites.map((x, i) => <tr key={i}><td>{x.site_name}</td><td>{x.city ?? '—'}</td><td className="small">{x.jurisdictions.join(', ') || '—'}</td></tr>)}</tbody></table></div>
            )}
          </Card>
          <Card title="Laws and frameworks in scope">
            {p.laws.length === 0 ? <EmptyState>None yet.</EmptyState> : (
              <div className="table-wrap"><table className="table"><thead><tr><th>Law or framework</th><th>Geography</th><th>Type</th></tr></thead>
                <tbody>{p.laws.map((l, i) => <tr key={i}><td>{l.label}</td><td>{l.jurisdiction ?? '—'}</td><td>{l.type === 'voluntary' ? 'Framework' : l.type ?? '—'}</td></tr>)}</tbody></table></div>
            )}
          </Card>
        </div>
      )}
      {tab === 'contacts' && (
        <div className="split">
          <div className="main"><Card title="Client contacts">{contacts}</Card></div>
          <div className="side"><Card title="Client users">{live ? <p className="small" style={{ margin: 0 }}>Departments, users and role holders are managed by the client. <Link to={`/clients/${clientId}/people`}>View them</Link>.</p> : <p className="small muted" style={{ margin: 0 }}>Available once the initiation package is sent.</p>}</Card></div>
        </div>
      )}
      {tab === 'documents' && (
        <Card title="Initiation package">
          {!p.package ? <EmptyState>Generated when the draft is submitted for approval.</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Document</th><th>Files</th><th>Client</th></tr></thead>
                <tbody>
                  {p.package.documents.map((d) => (
                    <tr key={d.id}>
                      <td>{d.item} · {d.title}</td>
                      <td className="small">
                        <button type="button" className="link-btn" onClick={() => setPreview({ id: d.id, title: d.title })}>Preview</button>
                        {d.pdf_file_id && <> · <a href={fileUrl(d.pdf_file_id)}>PDF</a></>}
                        {d.docx_file_id && <> · <a href={fileUrl(d.docx_file_id)}>Word</a></>}
                        {d.csv_file_id && <> · <a href={fileUrl(d.csv_file_id)}>CSV</a></>}
                      </td>
                      <td>{d.completed_at ? <Badge tone="success">Done</Badge> : <span className="small muted">Open</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {live && <p className="small" style={{ marginBottom: 0 }}><Link to={`/clients/${clientId}/documents`}>Document request register</Link></p>}
        </Card>
      )}
      {tab === 'activity' && <Card title="Activity">{activity()}<p className="small" style={{ marginBottom: 0 }}><Link to={`/admin/audit-log?org=${clientId}`}>View full audit log</Link></p></Card>}
      {preview && <DocPreview docId={preview.id} title={preview.title} onClose={() => setPreview(null)} />}
    </div>
  );
}

export const WORK_AREAS = [
  ['governance', 'AI governance structure'], ['attestation', 'Employee attestation'], ['inventory', 'AI inventory and tiers'], ['systems', 'AI systems in scope'],
  ['documents', 'Document requests'], ['findings', 'Findings'], ['report', 'Report'], ['remediation', 'Remediation'],
] as const;

function WorkAreas({ clientId }: { clientId: string }) {
  return <div className="work-areas">{WORK_AREAS.map(([path, label]) => <Link key={path} to={`/clients/${clientId}/${path}`}>{label}</Link>)}</div>;
}
