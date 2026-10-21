import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, ButtonLink, Card, EmptyState, Loading, PageHeader, TextArea, TextField } from '@/components/ui';
import { SignPanel, type SignOffView } from '@/components/SignPanel';
import { FindingForm, SEV_TONE, type FindingRow } from '@/screens/futran/FieldworkUseCase';
import { findingHelp } from '@/help/fieldwork';

type Data = { findings: (FindingRow & { review_role?: string | null; origin?: string })[]; stage: number; audit_ref: string; client: string; control_options: string[]; sign_off_5: SignOffView | null; approved: number; total: number; can_approve_as: string[]; me: string };

const STATUS: Record<string, string> = { draft: 'Draft', submitted: 'Awaiting approval', approved: 'Approved', returned: 'Returned' };

/** Screen 17: findings for approval (Chief Auditor, or QA Reviewer for the Chief Auditor's own findings) and sign-off 5. */
export function FindingsQA() {
  const { clientId = '' } = useParams();
  const key = ['findings', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/clients/${clientId}/findings`) });
  const [sel, setSel] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [reason, setReason] = useState('');
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const f = d.findings.find((x) => x.id === sel) ?? d.findings.find((x) => x.status === 'submitted') ?? d.findings[0];
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const run = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); setComment(''); setReason(''); await refresh(); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } };
  const mine = (x: FindingRow) => x.author_id === d.me;
  const canReview = (x: Data['findings'][number]) => x.status === 'submitted' && !mine(x) && d.can_approve_as.includes(x.review_role ?? 'chief_auditor');
  const statusText = (x: Data['findings'][number]) => x.status === 'submitted' ? (canReview(x) ? 'Awaiting you' : x.review_role === 'qa_reviewer' ? 'With QA Reviewer' : 'With Chief Auditor') : STATUS[x.status] ?? x.status;
  const so5 = d.sign_off_5;
  return (
    <div className="page">
      <PageHeader title="Findings" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client} · ${d.audit_ref}` }, { label: 'Findings' }]}
        subtitle={`Stage ${d.stage} · ${d.approved} of ${d.total} approved. The draft report can be issued once all are approved and sign-off 5 is signed.`}
        actions={<><Button onClick={() => setAdding(true)}>New finding</Button><ButtonLink to={`/clients/${clientId}/report`} variant={so5?.status === 'approved' ? 'primary' : 'default'}>Report</ButtonLink></>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {adding && <FindingForm clientId={clientId} controls={d.control_options} initial={{}} prefill={null} onDone={(t) => { setAdding(false); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      <div className="split" style={{ marginTop: 16 }}>
        <div className="main stack">
          <Card>
            {d.findings.length === 0 ? <EmptyState>No findings yet. Draft them from a use case's fieldwork page or a system assessment.</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Finding</th><th>Severity</th><th>Author</th><th>Status</th></tr></thead>
                <tbody>{d.findings.map((x) => (
                  <tr key={x.id} className={`clickable${x.id === f?.id ? ' selected' : ''}`} onClick={() => setSel(x.id)}>
                    <td><span className="small muted">{x.ref}</span> <strong>{x.title}</strong>{x.null_compliance_flag && <> <Badge tone="warn">Null-compliance</Badge></>}</td>
                    <td><Badge tone={SEV_TONE[x.severity]}>{x.severity[0].toUpperCase() + x.severity.slice(1)}</Badge></td>
                    <td>{mine(x) ? 'You' : x.author ?? '—'}</td>
                    <td>{statusText(x)}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
          <Card title="Sign-off 5 · Final risk tiers and findings">
            <div className="stack">
              <p className="small muted" style={{ margin: 0 }}>Prepared by the auditor once every finding is approved. When the Chief Auditor signs, the findings, final tiers and every system score are locked.</p>
              {so5 ? <SignPanel signOffId={so5.id} hideTitle onSigned={refresh} agreeText="I approve the final risk tiers and findings." /> : (
                <div><Button disabled={d.approved !== d.total || d.total === 0} onClick={() => run(() => api.post(`/clients/${clientId}/signoffs/5/submit`, {}), 'Sign-off 5 sent to the Chief Auditor.')}>Send sign-off 5 to the Chief Auditor</Button></div>
              )}
            </div>
          </Card>
        </div>
        <div className="side">
          {f && (
            <div className="card selected-panel">
              <div className="small muted">Selected finding · {f.severity[0].toUpperCase() + f.severity.slice(1)} · {f.ref}</div>
              <h3 style={{ margin: '4px 0 10px' }}>{f.title}</h3>
              <dl className="kv-stacked">
                {f.control_refs.length > 0 && <><dt>Control</dt><dd>{f.control_refs.join(' · ')}</dd></>}
                {f.use_cases.length > 0 && <><dt>Use case</dt><dd>{f.use_cases.map((u, i) => <span key={u}>{i > 0 && ', '}<Link to={`/clients/${clientId}/fieldwork/${f.use_case_ids[i]}`}>{u}</Link></span>)}</dd></>}
                {f.system && <><dt>System</dt><dd><Link to={`/systems/${f.ai_system_id}/assess`}>{f.system}</Link></dd></>}
              </dl>
              {f.description && <div className="statement small" style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}>{f.description}{f.recommended_remediation && `\n\nRecommended action: ${f.recommended_remediation}`}</div>}
              {f.review_comment && <p className="small" style={{ marginBottom: 0 }}>Review comment: {f.review_comment}</p>}
              {canReview(f) && (
                <div className="stack-sm" style={{ marginTop: 12 }}>
                  <TextArea label="Review comment" help={findingHelp.reviewComment} placeholder="Required if returning to the author" value={comment} onChange={(e) => setComment(e.target.value)} />
                  <div className="row" style={{ gap: 8 }}>
                    <Button variant="primary" onClick={() => run(() => api.post(`/findings/${f.id}/approve`, { comment }), `${f.ref} approved.`)}>Approve</Button>
                    <Button onClick={() => run(() => api.post(`/findings/${f.id}/return`, { comment }), `${f.ref} returned to its author.`)}>Return to author</Button>
                  </div>
                </div>
              )}
              {(f.status === 'draft' || f.status === 'returned') && (
                <div className="stack-sm" style={{ marginTop: 12 }}>
                  <div className="row" style={{ gap: 8 }}><Button variant="primary" onClick={() => run(() => api.post(`/findings/${f.id}/submit`), `${f.ref} submitted for approval.`)}>Submit for approval</Button></div>
                  <TextField label="Reason to dismiss" help={findingHelp.dismissReason} value={reason} onChange={(e) => setReason(e.target.value)} />
                  <div><Button variant="ghost" size="sm" onClick={() => run(() => api.post(`/findings/${f.id}/dismiss`, { reason }), `${f.ref} dismissed.`)}>Dismiss finding</Button></div>
                </div>
              )}
              <p className="small muted" style={{ marginBottom: 0, marginTop: 12 }}>Findings you wrote go to the QA Reviewer automatically; you cannot approve your own.</p>
            </div>
          )}
          {f && (f.status === 'draft' || f.status === 'returned') && <div style={{ marginTop: 16 }}><FindingForm key={f.id} clientId={clientId} controls={d.control_options} initial={{}} prefill={null} existing={f} onDone={(t) => { setMsg({ tone: 'success', text: t }); refresh(); }} /></div>}
        </div>
      </div>
    </div>
  );
}
