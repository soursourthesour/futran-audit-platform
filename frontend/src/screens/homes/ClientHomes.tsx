import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import type { ClientAdminData, DepartmentData, DeptSection, DpoData, MyTasksData, SponsorData } from '@/api/homes';
import { Alert, Badge, ButtonLink, Card, EmptyState, Loading, PageHeader, fmtDate, fmtDateTime } from '@/components/ui';
import { RATING_LABEL, RoleNote, SEVERITY_TONE, SignOffBadge, Tile, cap, signOffStatus } from './common';

function useHome<T>(key: string) {
  return useQuery({ queryKey: ['home', key], queryFn: () => api.get<T>(`/home/${key}`) });
}

function Shell<T>({ q, children }: { q: { isLoading: boolean; data?: T; error: unknown }; children: (d: T) => JSX.Element }) {
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  return children(q.data);
}

const NO_ENGAGEMENT = 'Your organization has no audit engagement yet. This page fills in once Futran sends the initiation package.';

/** Client Admin home (spec §13.1): users, SSO, connectors and the role-change log. No audit content. */
export function ClientAdminHome() {
  return <Shell q={useHome<ClientAdminData>('client-admin')}>{(d) => (
    <div className="page">
      <PageHeader title="Client Admin home" subtitle="You manage who can sign in and how. You do not see audit content." />
      <div className="grid-tiles home-tiles">
        <Tile label="Active users" value={d.users.active} hint={`${d.users.total} on the user list`} />
        <Tile label="Invitations pending" value={d.invitations.pending} hint={d.invitations.expiring.length ? `${d.invitations.expiring.length} expire within 2 days` : 'none expire within 2 days'} />
        <Tile label="Departments without a lead" value={d.departments.without_lead.length} hint={d.departments.blocks_stage ? `blocks stage ${d.departments.blocks_stage}` : `${d.departments.total} departments`} />
        <Tile label="Email connection" value={d.email.status} text hint={d.email.done ? 'test email sent' : 'Microsoft 365 or Google Workspace'} />
      </div>
      <div className="split">
        <div className="main stack">
          <Card title="To do">
            {d.todos.length === 0 ? <EmptyState>Nothing is waiting for you.</EmptyState> : (
              <ul className="home-rows">{d.todos.map((t, i) => (
                <li key={i}><div className="what">{t.text}</div><div className="acts"><ButtonLink to={t.link}>{t.kind === 'assign_lead' ? 'Assign' : t.kind === 'resend' ? 'Resend' : 'Connect'}</ButtonLink></div></li>
              ))}</ul>
            )}
          </Card>
          <Card title="Role changes" actions={<span className="small muted">Futran is told of every change to a sign-off role</span>}>
            {d.role_changes.length === 0 ? <EmptyState>No role changes yet.</EmptyState> : (
              <ul className="home-rows">{d.role_changes.map((c, i) => (
                <li key={i}><div className="what">{c.summary}<div className="small muted">{c.by ?? 'System'} · {fmtDateTime(c.at)}</div></div>{c.sign_off_role && <Badge tone="navy">Futran notified</Badge>}</li>
              ))}</ul>
            )}
          </Card>
        </div>
        <div className="side stack">
          <Card title="Users and departments">
            <ul className="list-rows">{d.departments.items.map((x) => <li key={x.id}><span>{x.name}</span>{x.has_lead ? <Badge tone="success">Lead assigned</Badge> : <Badge tone="warn">No lead</Badge>}</li>)}</ul>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginTop: 12 }}><ButtonLink to="/people/users">Users</ButtonLink><ButtonLink to="/people/departments">Departments</ButtonLink></div>
          </Card>
          <Card title="Connectors">
            <div className="stack-sm small">
              <div><strong>Email</strong> · {d.email.status}</div>
              <div className="muted">Requests to employees and department heads go out from your own email system, and replies come back into the platform.</div>
              <div><ButtonLink to={d.email.link}>{d.email.done ? 'Email connection' : 'Set up email'}</ButtonLink></div>
            </div>
          </Card>
          <Card title="Company sign-in (SSO)">
            <div className="stack-sm small">
              <div><Badge tone="muted">Not set up</Badge></div>
              <div className="muted">People sign in with their work email, a password of 12 or more characters and a sign-in code. Ask Futran if your organization needs SAML or OIDC single sign-on.</div>
            </div>
          </Card>
        </div>
      </div>
      <RoleNote role="Client Admin" can="create departments and users, assign client roles, and set up the email connection."
        cannot="see the inventory, attestation answers, findings or reports, or approve any sign-off." />
    </div>
  )}</Shell>;
}

/** Executive Sponsor home (spec §13.1): summary and signatures (sign-offs 4 and 6). */
export function SponsorHome() {
  return <Shell q={useHome<SponsorData>('sponsor')}>{(d) => {
    const e = d.engagement;
    if (!e) return <div className="page"><PageHeader title={`AI governance at ${d.organization}`} /><Card><EmptyState>{NO_ENGAGEMENT}</EmptyState></Card></div>;
    const titles: Record<string, string> = { '4': 'Sign-off 4 · Management representation: the AI inventory is complete and accurate', '6': 'Sign-off 6 · Accept the management responses and remediation plan' };
    return (
      <div className="page">
        <PageHeader title={`AI governance at ${d.organization}`} subtitle={`${e.type_label} · Futran Solutions · stage ${e.stage} of 9 · ${e.stage_name}`} />
        {d.waiting.length > 0 && (
          <Card title="Waiting for your signature" className="home-waiting">
            <ul className="home-rows">{d.waiting.map((n) => (
              <li key={n}><div className="what"><strong>{titles[String(n)]}</strong><div className="small muted">Read what you are signing on the next screen, then sign with your full name.</div></div>
                <div className="acts"><ButtonLink to={d.signoffs[String(n)].link} variant="primary">Review and sign</ButtonLink></div></li>
            ))}</ul>
          </Card>
        )}
        <div className="grid-tiles home-tiles">
          <Tile label="Overall rating" value={d.rating?.overall ? RATING_LABEL[d.rating.overall] ?? cap(d.rating.overall) : 'Not yet'} text hint={d.rating ? 'from the draft report' : 'shared with the draft report'} />
          <Tile label="Findings" value={d.findings ? d.findings.total : '—'} hint={d.findings ? ['critical', 'high', 'medium', 'low'].filter((s) => d.findings!.by_severity[s]).map((s) => `${d.findings!.by_severity[s]} ${cap(s)}`).join(' · ') || 'none' : 'shared with the draft report'} />
          <Tile label="AI systems audited" value={d.systems} hint={`${d.use_cases} use cases in the inventory`} />
        </div>
        <Card title="Your sign-offs">
          <ul className="home-rows">
            {(['4', '6'] as const).map((n) => {
              const so = d.signoffs[n]?.sign_off ?? null;
              return <li key={n}><div className="what">{titles[n]}</div><div className="acts"><SignOffBadge so={so} />{so && <ButtonLink to={d.signoffs[n].link}>Open</ButtonLink>}</div></li>;
            })}
            <li><div className="what">Final report acknowledgment (receipt, not agreement)</div><div className="acts"><Badge tone={d.final_report_released ? 'navy' : 'muted'}>{d.final_report_released ? 'Report issued' : 'After stage 8'}</Badge></div></li>
          </ul>
        </Card>
        {d.rating?.narrative && <Card title="Summary from Futran"><p className="small" style={{ margin: 0 }}>{d.rating.narrative}</p></Card>}
        <RoleNote role="Executive Sponsor" can="view summaries and reports, sign sign-offs 4 and 6, and acknowledge the final report." cannot="edit the inventory or findings." />
      </div>
    );
  }}</Shell>;
}

/** Data Protection Officer home (spec §13.1): data review (sign-off 3) and attestation privacy. */
export function DPOHome() {
  return <Shell q={useHome<DpoData>('dpo')}>{(d) => {
    if (!d.engagement) return <div className="page"><PageHeader title="Data review" /><Card><EmptyState>{NO_ENGAGEMENT}</EmptyState></Card></div>;
    const so = d.signoff3?.sign_off ?? null;
    return (
      <div className="page">
        <PageHeader title="Data review" subtitle="Sign-off 3: the data categories of Tier 2 and Tier 3 use cases." actions={<ButtonLink to="/review" variant={so?.can_sign ? 'primary' : 'default'}>{so?.can_sign ? 'Review and sign' : 'Open review'}</ButtonLink>} />
        <div className="grid-tiles home-tiles">
          <Tile label="Sign-off 3" value={signOffStatus(so).label} text hint={d.signoff3?.unmet?.length ? d.signoff3.unmet[0] : 'data categories for Tier 2 and 3'} />
          <Tile label="Use cases to review" value={d.use_cases.length} hint={`${d.use_cases.filter((u) => u.tier === 3).length} Tier 3 · ${d.use_cases.filter((u) => u.tier === 2).length} Tier 2`} />
          <Tile label="On a personal account" value={d.use_cases.filter((u) => u.personal_account).length} hint="data may leave company control" />
        </div>
        <Card title="Tier 2 and Tier 3 use cases">
          {d.use_cases.length === 0 ? <EmptyState>No Tier 2 or Tier 3 use cases have been submitted.</EmptyState> : (
            <div className="table-wrap"><table className="table stacked-table">
              <thead><tr><th>Use case</th><th>Tier</th><th>Data</th><th>Account</th><th>Status</th></tr></thead>
              <tbody>{d.use_cases.map((u) => (
                <tr key={u.id}>
                  <td data-label="Use case"><Link to={u.link}><strong>{u.name}</strong></Link><div className="small muted">{u.department}</div></td>
                  <td data-label="Tier">{u.tier ?? '—'}</td>
                  <td data-label="Data">{u.data_labels.join(', ') || '—'}</td>
                  <td data-label="Account">{u.accounts.join(', ') || '—'}{u.personal_account && <> <Badge tone="warn">Personal</Badge></>}</td>
                  <td data-label="Status">{u.status_label}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>
        <div className="home-grid" style={{ marginTop: 16 }}>
          <Card title="Attestation privacy">
            <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
              <li>Department Compliance Leads see department totals only.</li>
              <li>A count below {d.privacy.min_group} is not shown, so no one can be identified from it.</li>
              <li>Individual answers are visible to: {d.privacy.individuals_visible_to.join(', ')}.</li>
              <li>Employee data notice: {d.privacy.notice_acknowledged ? 'sent and acknowledged' : 'not yet acknowledged by everyone'}.</li>
            </ul>
          </Card>
          <Card title="Attestation campaign" actions={<ButtonLink to="/attestation">Attestation tracker</ButtonLink>}>
            {d.campaign ? <div className="small">{d.campaign.responses} responses · {d.campaign.status === 'open' ? `open until ${fmtDate(d.campaign.closes_at)}` : 'closed'}</div> : <EmptyState>No campaign has been launched.</EmptyState>}
          </Card>
        </div>
        <RoleNote role="Data Protection Officer" can="review data categories and approve or return them (sign-off 3), review new AI projects and view attestations."
          cannot="sign the management representation or edit findings. If no DPO is appointed, the Chief AI Compliance Officer does this." />
      </div>
    );
  }}</Shell>;
}

function DepartmentSection({ s, shared }: { s: DeptSection; shared: boolean }) {
  const so = s.signoff2.sign_off;
  const resp = s.attestation.responses;
  const open = (s.findings ?? []).filter((f) => f.response_status === 'needed' || f.response_status === 'inadequate');
  return (
    <section className="stack" aria-label={s.name}>
      <div className="grid-tiles home-tiles">
        <Tile label="Use cases" value={s.use_cases.length} hint={`${s.tiers['3'] ?? 0} Tier 3 · ${s.tiers['2'] ?? 0} Tier 2 · ${s.tiers['1'] ?? 0} Tier 1`} />
        <Tile label="Awaiting your approval" value={s.awaiting_approval} hint={`Sign-off 2: ${signOffStatus(so).label}`} />
        <Tile label="Attestation" value={resp == null ? '—' : typeof resp === 'string' ? cap(resp) : `${resp}${s.attestation.headcount ? ` / ${s.attestation.headcount}` : ''}`} text={typeof resp === 'string'}
          hint={typeof resp === 'string' ? `counts below ${s.attestation.min_group} are hidden` : 'totals only'} />
        <Tile label="Findings to respond to" value={shared ? open.length : '—'} hint={shared ? `${(s.findings ?? []).length} for your department` : 'shared with the draft report'} />
      </div>
      <div className="split">
        <div className="main stack">
          <Card title="Sign-off 2 · Department inventory" actions={<ButtonLink to="/review" variant={so?.can_sign ? 'primary' : 'default'}>{so?.can_sign ? 'Review and sign' : 'Open review'}</ButtonLink>}>
            {s.use_cases.length === 0 ? <EmptyState>No use cases for this department yet.</EmptyState> : (
              <ul className="home-rows">{s.use_cases.map((u) => (
                <li key={u.id}><div className="what"><Link to={u.link}><strong>{u.name}</strong></Link><div className="small muted">{u.by ? `By ${u.by}` : ''}{u.tier ? ` · Tier ${u.tier}` : ''}</div></div>
                  <div className="acts">{u.status === 'submitted' ? <ButtonLink to={u.link} variant="primary">Review</ButtonLink> : <Badge tone={u.status === 'dept_approved' ? 'success' : u.status === 'returned' ? 'warn' : 'muted'}>{u.status_label}</Badge>}</div></li>
              ))}</ul>
            )}
          </Card>
          {shared && (
            <Card title="Findings for your department" actions={<ButtonLink to="/responses">Responses</ButtonLink>}>
              {(s.findings ?? []).length === 0 ? <EmptyState>No findings for this department.</EmptyState> : (
                <ul className="home-rows">{(s.findings ?? []).map((f) => (
                  <li key={f.id}><div className="what"><strong>{f.ref} {f.title}</strong><div className="small muted">{cap(f.severity)}{f.due_date ? ` · due ${fmtDate(f.due_date)}` : ''}</div></div>
                    <div className="acts"><Badge tone={SEVERITY_TONE[f.severity] ?? 'muted'}>{cap(f.severity)}</Badge><Badge tone={f.response_status === 'needed' ? 'warn' : 'navy'}>{f.response_status === 'needed' ? 'Response needed' : cap(f.response_status)}</Badge></div></li>
                ))}</ul>
              )}
            </Card>
          )}
        </div>
        <div className="side">
          <Card title="AI system register" actions={<ButtonLink to="/register">Open register</ButtonLink>}>
            {s.register.total === 0 ? <EmptyState>No AI systems recorded for this department.</EmptyState> : (
              <>
                <div className="small muted" style={{ marginBottom: 8 }}>{s.register.total} systems · {s.register.live} live</div>
                <ul className="home-rows">{s.register.items.map((r) => <li key={r.id}><div className="what"><Link to={r.link}>{r.reference} {r.name}</Link></div><Badge tone={r.stage === 'live' ? 'success' : 'muted'}>{cap(r.stage.replace(/_/g, ' '))}</Badge></li>)}</ul>
              </>
            )}
          </Card>
        </div>
      </div>
    </section>
  );
}

/** Department Compliance Lead home (spec §13.1): approvals, attestation totals, findings and the department's register. */
export function DepartmentHome() {
  return <Shell q={useHome<DepartmentData>('department')}>{(d) => (
    <div className="page">
      {d.departments.length === 0 ? <><PageHeader title="My department" /><Card><EmptyState>You are not the lead for a department yet. Ask your Client Admin.</EmptyState></Card></> :
        d.departments.map((s, i) => (
          <div key={s.id} style={i ? { marginTop: 32 } : undefined}>
            <PageHeader title={s.name} subtitle={i === 0 ? 'Everything here is limited to your department.' : undefined} />
            {!d.engagement ? <Card><EmptyState>{NO_ENGAGEMENT}</EmptyState></Card> : <DepartmentSection s={s} shared={d.findings_shared} />}
          </div>
        ))}
      <RoleNote role="Department Compliance Lead" can="review and approve the department's tools and use cases, keep its AI systems in the register, draft responses to its findings, and see attestation totals."
        cannot="see individual attestations, other departments' data, or sign the management representation." />
    </div>
  )}</Shell>;
}

/** Contributor home (spec §13.1): returned items, evidence requests and drafts. */
export function MyTasks() {
  return <Shell q={useHome<MyTasksData>('my-tasks')}>{(d) => {
    const n = d.returned.length + d.evidence.length + d.documents.length + d.drafts.length;
    return (
      <div className="page">
        <PageHeader title="My tasks" subtitle="Help your department describe how it uses AI." actions={d.engagement && d.inventory_open !== false ? <ButtonLink to="/inventory/new" variant="primary">Add a use case</ButtonLink> : undefined} />
        {!d.engagement ? <Card><EmptyState>{NO_ENGAGEMENT}</EmptyState></Card> : (
          <div className="split" style={{ marginTop: 16 }}>
            <div className="main">
              <Card title={`Needs your attention · ${n}`}>
                {n === 0 ? <EmptyState>Nothing is waiting for you.</EmptyState> : (
                  <ul className="home-rows">
                    {d.returned.map((u) => <li key={u.id}><div className="what"><strong>Returned by your Department Lead</strong><div className="small muted">{u.name}{u.comment ? ` · “${u.comment}”` : ''}</div></div><div className="acts"><ButtonLink to={u.link} variant="primary">Fix</ButtonLink></div></li>)}
                    {d.evidence.map((r) => <li key={r.id}><div className="what"><strong>Evidence requested by Futran</strong>{r.overdue && <> <Badge tone="danger">Overdue</Badge></>}<div className="small muted">{r.ref} · {r.description} · due {fmtDate(r.due_date)}</div></div><div className="acts"><ButtonLink to="/documents">Upload</ButtonLink></div></li>)}
                    {d.documents.map((r) => <li key={r.id}><div className="what"><strong>Document requested by Futran</strong><div className="small muted">{r.title}{r.system ? ` · ${r.system}` : ''}{r.due_at ? ` · due ${fmtDate(r.due_at)}` : ''}</div></div><div className="acts"><ButtonLink to="/documents">Upload</ButtonLink></div></li>)}
                    {d.drafts.map((u) => <li key={u.id}><div className="what"><strong>{u.from_attestation ? 'Draft from the attestation' : 'Draft not yet submitted'}</strong><div className="small muted">{u.name}</div></div><div className="acts"><ButtonLink to={u.link}>Complete</ButtonLink></div></li>)}
                  </ul>
                )}
              </Card>
            </div>
            <div className="side">
              <Card title="My entries">
                {d.entries.length === 0 ? <EmptyState>You have not added a use case yet.</EmptyState> : (
                  <ul className="home-rows">{d.entries.map((u) => <li key={u.id}><div className="what"><Link to={u.link}>{u.name}</Link></div><Badge tone={u.status === 'dept_approved' ? 'success' : u.status === 'returned' ? 'warn' : 'muted'}>{u.status_label}</Badge></li>)}</ul>
                )}
              </Card>
            </div>
          </div>
        )}
        <RoleNote role="Contributor" can="add and edit tools and use cases for their department, upload evidence, and see what they submitted."
          cannot="approve anything, or see attestation answers, findings or reports." />
      </div>
    );
  }}</Shell>;
}
