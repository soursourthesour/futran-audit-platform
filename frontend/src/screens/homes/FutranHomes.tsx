import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, useMe } from '@/api/auth';
import type { AdminHomeData, MyWorkData, QaData, QaFinding, QaOverride } from '@/api/homes';
import { Alert, Badge, Button, ButtonLink, Card, EmptyState, Loading, PageHeader, Progress, TextArea, fmtDate, fmtDateTime } from '@/components/ui';
import { qaHelp } from '@/help/homes';
import { RATING_LABEL, RoleNote, SEVERITY_TONE, Tile, cap } from './common';

const FUTRAN_ROLE_ORDER: [string, string][] = [['chief_auditor', 'Chief Auditors'], ['auditor', 'Auditors'], ['qa_reviewer', 'QA Reviewers'], ['engagement_manager', 'Engagement Managers'],
  ['legal_reviewer', 'Legal reviewers'], ['sales_team', 'Sales Team'], ['admin', 'Admins']];

function useHome<T>(key: string) {
  return useQuery({ queryKey: ['home', key], queryFn: () => api.get<T>(`/home/${key}`) });
}

/** Futran Admin console (spec §13.1): users, templates, law-matrix import. */
export function AdminHome() {
  const q = useHome<AdminHomeData>('admin');
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="Admin console" subtitle="Platform setup: Futran users, client organizations, templates and reference data." actions={<ButtonLink to="/audits/new" variant="primary">New client</ButtonLink>} />
      <div className="grid-tiles home-tiles">
        <Tile label="Futran users" value={d.users.total} hint={`${d.users.mfa} of ${d.users.active} active users have MFA${d.users.invited ? ` · ${d.users.invited} invited` : ''}`} />
        <Tile label="Client organizations" value={d.clients.total} hint={`${d.clients.drafts} in draft · ${d.clients.in_progress} in progress`} />
        <Tile label="Law matrix" value={d.law_matrix.status_date ? fmtDate(d.law_matrix.status_date) : d.law_matrix.published_at ? fmtDate(d.law_matrix.published_at) : 'Not imported'} text hint={`${d.law_matrix.laws} laws in force`} />
        <Tile label="Templates" value={d.templates} hint="active document templates" />
      </div>
      <div className="home-grid">
        <Card title="Futran users" actions={<ButtonLink to="/admin/users">Manage users</ButtonLink>}>
          <ul className="list-rows">
            {FUTRAN_ROLE_ORDER.filter(([r]) => d.users.by_role[r]).map(([r, label]) => <li key={r}><span>{label}</span><strong>{d.users.by_role[r]}</strong></li>)}
          </ul>
        </Card>
        <Card title="Reference data" actions={<ButtonLink to="/admin/reference">Open reference data</ButtonLink>}>
          <div className="stack-sm small">
            <div><strong>{d.law_matrix.label ?? 'No law matrix published yet'}</strong></div>
            {d.law_matrix.published_at && <div className="muted">Published {fmtDateTime(d.law_matrix.published_at)}</div>}
            <div>{d.pending_proposals === 0 ? 'No regulatory changes are waiting for the Chief Auditor.' : `${d.pending_proposals} regulatory change${d.pending_proposals === 1 ? '' : 's'} waiting for the Chief Auditor.`}</div>
            <div><Link className="home-link" to="/reg/refresh">Open refresh and review</Link></div>
          </div>
        </Card>
      </div>
      <RoleNote role="Admin" can="create clients and engagements, manage Futran and client users, templates, the question bank and the law matrix, platform settings, and view the audit log."
        cannot="record, edit or approve findings, risk tiers, scores or sign-offs (separation of duties)." />
    </div>
  );
}

/** Auditor home (spec §13.1): assigned engagements and today's tasks. */
export function MyWork() {
  const { data: me } = useMe();
  const q = useHome<MyWorkData>('my-work');
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="My work" subtitle="Engagements you are assigned to or drafted. You see no others."
        actions={can(me, 'create_client_engagement') ? <ButtonLink to="/audits/new" variant="primary">Draft a new client</ButtonLink> : undefined} />
      {d.engagements.length === 0 ? <Card><EmptyState>You are not assigned to an engagement yet.</EmptyState></Card> : (
        <div className="home-grid" style={{ margin: '16px 0 24px' }}>
          {d.engagements.map((e) => (
            <Card key={e.id}>
              <Link to={e.link} className="home-eng">
                <strong>{e.client}</strong>
                <span className="small muted">{e.audit_ref} · {e.type_label}</span>
                <span className="small">Stage {e.stage_label}{e.my_role ? ` · ${e.my_role}` : ''}</span>
              </Link>
              {e.systems > 0 && <div className="stack-sm" style={{ marginTop: 8 }}><Progress value={(e.systems_assessed / e.systems) * 100} label={`${e.client}: systems scored`} /><span className="small muted">{e.systems_assessed} of {e.systems} AI systems scored</span></div>}
            </Card>
          ))}
        </div>
      )}
      <Card title={`Today · ${d.tasks.length} task${d.tasks.length === 1 ? '' : 's'}`}>
        {d.tasks.length === 0 ? <EmptyState>Nothing is waiting for you.</EmptyState> : (
          <ul className="home-rows">
            {d.tasks.map((t, i) => (
              <li key={i}>
                <div className="what"><strong>{t.title}</strong>{t.overdue && <> <Badge tone="danger">Overdue</Badge></>}<div className="small muted">{t.client} · {t.detail}</div></div>
                <div className="acts"><ButtonLink to={t.link}>Open</ButtonLink></div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <RoleNote role="Auditor" can="draft clients, assess systems, set final tiers, request evidence, write findings and verify remediation."
        cannot="approve findings, sign reports, close remediation, send initiation packages, or see engagements they are not assigned to." />
    </div>
  );
}

type QaItem = { kind: 'finding'; f: QaFinding } | { kind: 'override'; o: QaOverride };
const itemKey = (x: QaItem) => (x.kind === 'finding' ? `f:${x.f.id}` : `o:${x.o.system_id}`);

/** QA Reviewer home (spec §13.1): findings and rating overrides by a Chief Auditor; approve or return only. */
export function QAQueue() {
  const q = useHome<QaData>('qa');
  const qc = useQueryClient();
  const [tab, setTab] = useState<'queue' | 'reviewed'>('queue');
  const [sel, setSel] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const items: QaItem[] = [...d.findings.map((f) => ({ kind: 'finding' as const, f })), ...d.overrides.map((o) => ({ kind: 'override' as const, o }))];
  const cur = items.find((x) => itemKey(x) === sel) ?? items[0];

  async function decide(decision: 'approve' | 'return') {
    if (!cur) return;
    setMsg(null); setBusy(true);
    try {
      if (cur.kind === 'finding') await api.post(`/findings/${cur.f.id}/${decision}`, { comment: comment || null });
      else await api.post(`/systems/${cur.o.system_id}/score/override/review`, { decision, comment: comment || null });
      const what = cur.kind === 'finding' ? `Finding ${cur.f.ref}` : `The rating override for ${cur.o.reference_id}`;
      setMsg({ tone: 'success', text: `${what} was ${decision === 'approve' ? 'approved' : 'returned to the Chief Auditor'}.` });
      setComment(''); setSel(null);
      await qc.invalidateQueries({ queryKey: ['home', 'qa'] });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }

  return (
    <div className="page">
      <PageHeader title="QA review queue" subtitle="Findings and rating overrides written by a Chief Auditor come to you, so no one approves their own work." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="pills" role="tablist" aria-label="QA queue" style={{ margin: '16px 0' }}>
        <button type="button" role="tab" className="pill" aria-selected={tab === 'queue'} onClick={() => setTab('queue')}>Waiting · {items.length}</button>
        <button type="button" role="tab" className="pill" aria-selected={tab === 'reviewed'} onClick={() => setTab('reviewed')}>Reviewed · {d.reviewed.length}</button>
      </div>
      {tab === 'reviewed' ? (
        <Card>{d.reviewed.length === 0 ? <EmptyState>You have not reviewed anything yet.</EmptyState> : (
          <ul className="home-rows">{d.reviewed.map((r, i) => <li key={i}><div className="what">{r.summary}<div className="small muted">{fmtDateTime(r.at)}</div></div><Badge tone={r.decision === 'approved' ? 'success' : 'warn'}>{r.decision === 'approved' ? 'Approved' : 'Returned'}</Badge></li>)}</ul>
        )}</Card>
      ) : items.length === 0 ? <Card><EmptyState>Nothing is waiting for your review.</EmptyState></Card> : (
        <div className="split">
          <div className="main">
            <Card>
              <div className="table-wrap"><table className="table qa-table stacked-table" aria-label="Waiting for review">
                <thead><tr><th>Item</th><th>Client</th><th>Author</th><th>Type</th><th>Waiting</th></tr></thead>
                <tbody>{items.map((x) => {
                  const k = itemKey(x);
                  const waiting = x.kind === 'finding' ? x.f.waiting_days : x.o.waiting_days;
                  return (
                    <tr key={k} className={`clickable${cur && itemKey(cur) === k ? ' selected' : ''}`} onClick={() => { setSel(k); setComment(''); }}>
                      <td data-label="Item"><button type="button" className="link-btn" onClick={(e) => { e.stopPropagation(); setSel(k); setComment(''); }}>
                        {x.kind === 'finding' ? `${x.f.ref} ${x.f.title}` : `${x.o.reference_id} ${x.o.system}: rating set to ${RATING_LABEL[x.o.rating] ?? x.o.rating}`}</button></td>
                      <td data-label="Client">{x.kind === 'finding' ? x.f.client : x.o.client}</td>
                      <td data-label="Author">{(x.kind === 'finding' ? x.f.author : x.o.by) ?? '—'}</td>
                      <td data-label="Type">{x.kind === 'finding' ? <Badge tone={SEVERITY_TONE[x.f.severity] ?? 'muted'}>{cap(x.f.severity)}</Badge> : <Badge tone="navy">Rating override</Badge>}</td>
                      <td data-label="Waiting">{waiting == null ? '—' : waiting === 0 ? 'today' : `${waiting} day${waiting === 1 ? '' : 's'}`}</td>
                    </tr>
                  );
                })}</tbody>
              </table></div>
            </Card>
          </div>
          {cur && (
            <div className="side">
              <Card className="qa-detail" title={cur.kind === 'finding' ? `${cur.f.client} · ${cur.f.ref}` : `${cur.o.client} · ${cur.o.reference_id}`}>
                <div className="stack">
                  {cur.kind === 'finding' ? (
                    <>
                      <h3 style={{ margin: 0 }}>{cur.f.title}</h3>
                      {cur.f.description && <p className="small" style={{ margin: 0 }}>{cur.f.description}</p>}
                      <dl className="kv"><dt>Severity</dt><dd>{cap(cur.f.severity)}</dd><dt>Controls</dt><dd>{cur.f.control_refs.join('; ') || '—'}</dd><dt>Engagement</dt><dd>{cur.f.audit_ref}</dd></dl>
                      <Link className="home-link small" to={cur.f.link}>Open the findings page</Link>
                    </>
                  ) : (
                    <>
                      <h3 style={{ margin: 0 }}>{cur.o.system}</h3>
                      <dl className="kv"><dt>Computed rating</dt><dd>{RATING_LABEL[cur.o.computed_rating ?? ''] ?? 'Not computed'}</dd><dt>Override</dt><dd><strong>{RATING_LABEL[cur.o.rating] ?? cur.o.rating}</strong></dd>
                        <dt>Rationale</dt><dd>{cur.o.rationale}</dd><dt>Set by</dt><dd>{cur.o.by ?? '—'}{cur.o.at ? ` · ${fmtDateTime(cur.o.at)}` : ''}</dd></dl>
                      <Link className="home-link small" to={cur.o.link}>Open the risk score</Link>
                    </>
                  )}
                  <div className="small">
                    <div className="muted">Before you approve, check that:</div>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                      {cur.kind === 'finding'
                        ? <><li>the finding is supported by linked evidence;</li><li>the severity matches the classification guide (§18.6);</li><li>it reads plainly for a senior executive.</li></>
                        : <><li>the rationale explains why the computed rating does not reflect the risk;</li><li>it rests on evidence on file, not on judgment alone.</li></>}
                    </ul>
                  </div>
                  {(cur.kind === 'finding' ? cur.f.can_review : cur.o.can_review) ? (
                    <>
                      <TextArea label="QA comment" help={qaHelp.comment} value={comment} onChange={(e) => setComment(e.target.value)} rows={3} />
                      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                        <Button variant="primary" disabled={busy} onClick={() => decide('approve')}>Approve</Button>
                        <Button disabled={busy || !comment.trim()} onClick={() => decide('return')}>Return to Chief Auditor</Button>
                      </div>
                    </>
                  ) : <Alert tone="warn">You wrote or edited this item, so another reviewer must decide it.</Alert>}
                </div>
              </Card>
            </div>
          )}
        </div>
      )}
      <RoleNote role="QA Reviewer" can="view assigned engagements, and approve or return findings and rating overrides written by a Chief Auditor."
        cannot="write findings, edit client data, sign reports, or review their own work." />
    </div>
  );
}
