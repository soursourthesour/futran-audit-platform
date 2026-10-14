import { useState } from 'react';
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

  return (
    <div className="page">
      <PageHeader crumbs={[{ to: '/audits', label: 'Audits' }, { label: p.client.name }]} title={p.client.name} subtitle={`${e.type_label}${places ? ` · ${places}` : ''} · ${e.audit_ref}`}
        actions={e.status === 'pending_approval' ? <Link className="btn btn-primary" to={`/clients/${clientId}/setup/submit`}>Review initiation package</Link> : e.status === 'draft' ? <Link className="btn" to={`/clients/${clientId}/setup/company`}>Continue the draft</Link> : undefined} />
      {flash && !msg && <Alert tone="success">{flash}</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="stack">
        <Card title="Engagement progress" actions={<Badge tone="navy">{e.status_label}</Badge>}>
          <div className="stack">
            <StageTracker stage={e.stage} status={e.status} />
            {e.status !== 'draft' && e.status !== 'pending_approval' && (
              p.gate.ready ? <p className="small">Stage {e.stage} is complete.</p> : (
                <div><strong className="small">What's left in this stage</strong><ul className="small" style={{ margin: '4px 0 0', paddingLeft: 18 }}>{p.gate.unmet.map((u) => <li key={u}>{u}</li>)}</ul></div>
              )
            )}
          </div>
        </Card>
        <div className="split">
          <div className="main stack">
            {p.sign_off_1 && p.sign_off_1.status !== 'approved' && (
              <Card title="Sign-off 1: engagement letter and scope"><SignPanel signOffId={p.sign_off_1.id} /></Card>
            )}
            <Card title="Client details">
              <dl className="kv">
                <dt>Legal name</dt><dd>{p.client.legal_name ?? '—'} · {p.client.client_ref}</dd>
                <dt>Industry</dt><dd>{p.client.industry ?? '—'}</dd>
                <dt>Employees</dt><dd>{p.client.employee_band ?? '—'}</dd>
                <dt>Headquarters</dt><dd>{p.client.hq || '—'}</dd>
                <dt>Sites in scope</dt><dd>{p.sites.map((s) => s.site_name).join(' · ') || '—'}</dd>
                <dt>Laws in scope</dt><dd>{p.laws.map((l) => l.label + (l.type === 'voluntary' ? ' (framework)' : '')).join(' · ') || '—'}</dd>
              </dl>
            </Card>
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
            </Card>
            <Card title="Activity">
              {p.activity.length === 0 ? <EmptyState>Nothing yet.</EmptyState> : (
                <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {p.activity.map((a, i) => <li key={i} style={{ padding: '8px 0', borderTop: i ? '1px solid var(--line-soft)' : undefined }}>{a.summary}<div className="muted">{a.actor ?? 'System'} · {fmtDateTime(a.at)}</div></li>)}
                </ul>
              )}
            </Card>
          </div>
          <div className="side stack">
            <Card title="Client contacts">
              <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {p.contacts.map((c) => (
                  <li key={c.role} style={{ padding: '8px 0' }}>
                    <strong>{c.role_label}</strong>
                    <div>{c.not_appointed ? 'Not appointed' : c.name}{c.invite_status ? <span className="muted"> · {c.invite_status}</span> : null}</div>
                    {c.invite_status && c.invite_status !== 'Active' && c.invite_status !== 'Not invited yet' && <Button size="sm" variant="ghost" onClick={() => resend(c.role)}>Resend invitation</Button>}
                  </li>
                ))}
              </ul>
            </Card>
            {e.status !== 'draft' && e.status !== 'pending_approval' && (
              <Card title="AI governance structure"><Link to={`/clients/${clientId}/governance`}>Open the governance request</Link></Card>
            )}
            <Card title="Futran team">
              <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {p.team.map((m, i) => <li key={i} style={{ padding: '6px 0' }}><strong>{m.name}</strong><div className="muted">{m.role_label}</div></li>)}
              </ul>
            </Card>
          </div>
        </div>
      </div>
      {preview && <DocPreview docId={preview.id} title={preview.title} onClose={() => setPreview(null)} />}
    </div>
  );
}
