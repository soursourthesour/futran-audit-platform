import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, ButtonLink, Card, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { type ActivityRow, type Contact, type OppDetail, type OppList, PIPELINE, usd } from '@/api/sales';
import { salesHelp as H } from '@/help/sales';
import '@/styles/sales.css';

type Tab = 'overview' | 'activity' | 'questionnaire' | 'proposals' | 'contacts';
const KIND_LABEL: Record<string, string> = { call: 'Call', email: 'Email', meeting: 'Meeting', note: 'Note', task: 'Task', proposal: 'Proposal', outcome: 'Outcome', created: 'Created',
  stage: 'Stage', approval_requested: 'Approval requested', approved: 'Approved', declined: 'Declined', approval_reset: 'Approval reset' };
const Q_STATUS: Record<string, string> = { draft: 'In progress', sent: 'Sent to the client', client_in_progress: 'Client answering', client_submitted: 'Client submitted', locked: 'Locked' };

/** SM-04 Opportunity record (spec §4.12): stage bar, overview with BANT, activity timeline, questionnaire, proposals,
 *  contacts and the independence panel. */
export function OpportunityRecord() {
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['opportunity', id], queryFn: () => api.get<OppDetail>(`/opportunities/${id}`) });
  const opts = useQuery({ queryKey: ['opportunities'], queryFn: () => api.get<OppList>('/opportunities') });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const tab = (params.get('tab') as Tab) || 'overview';
  const setTab = (t: Tab) => { const n = new URLSearchParams(params); n.set('tab', t); setParams(n, { replace: true }); };
  const [losing, setLosing] = useState(params.get('lose') === '1');
  const [editing, setEditing] = useState(false);
  if (q.isError) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  if (!q.data) return <div className="page"><Loading /></div>;
  const o = q.data;
  const o2 = opts.data;
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['opportunity', id] }); await qc.invalidateQueries({ queryKey: ['opportunities'] }); };
  async function run(fn: () => Promise<unknown>, done?: string) {
    setMsg(null);
    try { await fn(); await refresh(); if (done) setMsg({ tone: 'success', text: done }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const moveTo = (stage: string) => (stage === 'lost' ? setLosing(true) : run(() => api.patch(`/opportunities/${o.id}`, { stage }), `Moved to ${stageLabel(stage)}.`));
  const sub = [o.company.industry, o.company.size_band ? `${o.company.size_band} employees` : null, o.company.hq, o.owner_name ? `Owner ${o.owner_name}` : 'No owner'].filter(Boolean).join(' · ');
  const proposals = o.linked.proposals;
  return (
    <div className="page sales-page">
      <PageHeader crumbs={[{ to: '/sales/opportunities', label: 'Opportunities' }, { label: o.company.name }]}
        title={<span>{o.company.name} <Badge tone={o.company.kind === 'prospect' ? 'navy' : 'default'}>{o.company.kind === 'prospect' ? 'Prospect' : 'Client'}</Badge></span>}
        subtitle={`${o.name} · ${sub}`}
        actions={o.can_work && <>
          <ButtonLink to={`/sales/opportunities/${o.id}/scoping`}>Start scoping call</ButtonLink>
          <ButtonLink to={`/sales/opportunities/${o.id}/scoping?send=1`}>Send questionnaire</ButtonLink>
          <ButtonLink variant="primary" to={`/sales/estimate?opportunity=${o.id}`}>Build proposal</ButtonLink>
        </>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <StageBar o={o} onMove={o.can_work ? moveTo : undefined} />
      <div className="tabs" role="tablist" aria-label="Opportunity sections">
        {([['overview', 'Overview'], ['activity', `Activity (${o.activities.filter((a) => a.kind !== 'stage').length})`], ['questionnaire', 'Questionnaire'],
          ['proposals', `Proposals (${proposals.length})`], ['contacts', `Contacts (${o.contacts.length})`]] as [Tab, string][]).map(([k, l]) => (
          <button key={k} type="button" role="tab" className={tab === k ? 'active' : ''} aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      <div className="sales-record">
        <div className="stack">
          {tab === 'overview' && <Overview o={o} onEdit={() => setEditing(true)} />}
          {(tab === 'overview' || tab === 'activity') && <Timeline o={o} onDone={refresh} full={tab === 'activity'} />}
          {tab === 'questionnaire' && <QuestionnairePanel o={o} />}
          {tab === 'proposals' && <ProposalsPanel o={o} />}
          {tab === 'contacts' && <Contacts o={o} roles={o2?.contact_roles ?? []} onDone={refresh} />}
        </div>
        <aside className="stack">
          <Card title="Next step">
            <p style={{ margin: 0 }}><strong>{o.next_step ?? 'None set'}</strong>{o.next_step_due && <span className="muted"> · {fmtDate(o.next_step_due)}</span>}</p>
            <p className="small muted" style={{ margin: '6px 0 0' }}>{o.stale ? <span className="text-warn">Stale: no activity for 14 days.</span> : 'Stale after 14 days without activity.'}</p>
          </Card>
          <Card title="Questionnaire"><QuestionnaireSummary o={o} /></Card>
          <Card title="Independence">
            {o.independence_flag ? <Badge tone="warn">Flagged</Badge> : <Badge tone="success">No flag</Badge>}
            <p className="small" style={{ margin: '6px 0 0' }}>{o.independence_flag ? o.independence_reason : 'Not a current client, no engagement in the last 24 months, no open remediation.'}</p>
            {o.needs_ca_approval && <ApprovalBox o={o} run={run} />}
          </Card>
          {o.linked.order && <Card title="Order"><Link to={o.linked.order.link}>{o.linked.order.ref ?? 'Order'}</Link> · {o.linked.order.status}</Card>}
        </aside>
      </div>
      {losing && o2 && <LoseDialog o={o} reasons={o2.lost_reasons} onClose={() => { setLosing(false); if (params.get('lose')) { const n = new URLSearchParams(params); n.delete('lose'); setParams(n, { replace: true }); } }} onDone={refresh} />}
      {editing && o2 && <EditDialog o={o} opts={o2} onClose={() => setEditing(false)} onDone={async () => { setEditing(false); await refresh(); setMsg({ tone: 'success', text: 'Saved.' }); }} />}
    </div>
  );
}

function stageLabel(s: string) {
  return ({ new: 'New', qualified: 'Qualified', scoping: 'Scoping', proposal: 'Proposal', negotiation: 'Negotiation', won: 'Won', lost: 'Lost', on_hold: 'On hold', contacted: 'Contacted' } as Record<string, string>)[s] ?? s;
}

function StageBar({ o, onMove }: { o: OppDetail; onMove?: (s: string) => void }) {
  const at = PIPELINE.indexOf(o.stage === 'contacted' ? 'new' : o.stage);
  const closed = o.stage === 'won' || o.stage === 'lost';
  return (
    <ol className="sales-stagebar" aria-label="Stage">
      {PIPELINE.map((s, i) => (
        <li key={s} className={o.stage === s || (s === 'new' && o.stage === 'contacted') ? 'current' : (closed || i < at) ? 'done' : ''}>
          {onMove && !closed ? <button type="button" onClick={() => onMove(s)} aria-current={o.stage === s ? 'step' : undefined}>{stageLabel(s)}</button> : <span>{stageLabel(s)}</span>}
        </li>
      ))}
      <li className={closed ? 'current' : ''}>
        {closed ? <span>{o.stage === 'won' ? 'Won' : `Lost · ${o.lost_reason_label ?? ''}`}</span> : onMove ? (
          <span className="row"><button type="button" onClick={() => onMove('won')}>Won</button> / <button type="button" onClick={() => onMove('lost')}>Lost</button></span>
        ) : <span>Won / Lost</span>}
      </li>
      {o.stage === 'on_hold' && <li className="current"><span>On hold</span></li>}
      {onMove && o.stage !== 'on_hold' && !closed && <li className="aside"><button type="button" onClick={() => onMove('on_hold')}>Put on hold</button></li>}
      {onMove && closed && <li className="aside"><button type="button" onClick={() => onMove('negotiation')}>Reopen</button></li>}
    </ol>
  );
}

function Overview({ o, onEdit }: { o: OppDetail; onEdit: () => void }) {
  const b = o.bant;
  return (
    <Card title="Qualification (BANT)" actions={o.can_work && <Button size="sm" onClick={onEdit}>Edit</Button>}>
      <dl className="kv">
        <dt>Budget</dt><dd>{b.budget || '—'}</dd>
        <dt>Authority (signs)</dt><dd>{b.authority || '—'}</dd>
        <dt>Need</dt><dd>{b.need || '—'}</dd>
        <dt>Timeline</dt><dd>{b.timeline || '—'}</dd>
        <dt>Products of interest</dt><dd>{o.products_labels.join(', ') || '—'}</dd>
        <dt>Competitors</dt><dd>{o.competitors.join(', ') || '—'}</dd>
        <dt>Estimated value</dt><dd>{usd(o.value)}</dd>
        <dt>Expected close</dt><dd>{o.close_date ? fmtDate(o.close_date) : '—'}</dd>
        <dt>Source</dt><dd>{o.is_automatic ? `Automatic · ${o.trigger_label}` : o.source_label ?? '—'}{o.segment_label ? ` · ${o.segment_label}` : ''}</dd>
        <dt>Partner</dt><dd>{o.partner_name ?? '—'}</dd>
        <dt>Trigger</dt><dd>{o.trigger_event_label ?? o.why_now ?? '—'}</dd>
        {o.system_types.length > 0 && <><dt>AI systems</dt><dd>{o.system_types.join(', ')}</dd></>}
      </dl>
    </Card>
  );
}

function Timeline({ o, onDone, full }: { o: OppDetail; onDone: () => Promise<void>; full: boolean }) {
  const [kind, setKind] = useState<string | null>(null);
  const rows = full ? o.activities : o.activities.filter((a) => a.kind !== 'stage').slice(0, 6);
  return (
    <Card title="Activity" actions={o.can_work && (
      <div className="row">
        {[['call', 'Log call'], ['email', 'Email'], ['meeting', 'Meeting'], ['note', 'Note'], ['task', 'Task']].map(([k, l]) => <Button key={k} size="sm" onClick={() => setKind(k)}>{l}</Button>)}
      </div>
    )}>
      {rows.length === 0 ? <p className="small muted">Nothing logged yet.</p> : <ul className="sales-timeline">{rows.map((a) => <TimelineRow key={a.id} o={o} a={a} onDone={onDone} />)}</ul>}
      {kind === 'email' && <EmailDialog o={o} onClose={() => setKind(null)} onDone={onDone} />}
      {kind && kind !== 'email' && <ActivityDialog o={o} kind={kind} onClose={() => setKind(null)} onDone={onDone} />}
    </Card>
  );
}

function TimelineRow({ o, a, onDone }: { o: OppDetail; a: ActivityRow; onDone: () => Promise<void> }) {
  const [subject, ...rest] = a.kind === 'email' ? a.summary.split('\n\n') : [a.summary];
  return (
    <li>
      <span className="small muted"><strong>{KIND_LABEL[a.kind] ?? a.kind}</strong> · {fmtDateTime(a.at)} · {a.by ?? 'System'}{a.to.length ? ` · to ${a.to.join(', ')}` : ''}</span>
      <span>{a.kind === 'email' ? <><strong>{subject}</strong>{rest.length > 0 && <span className="block small clamp-3">{rest.join('\n\n')}</span>}</> : a.summary}</span>
      {a.outcome && <span className="small">Outcome: {a.outcome}</span>}
      {a.next_step && <span className="small">Next: {a.next_step}</span>}
      {a.kind === 'task' && (
        <span className="small">
          {a.due_on ? `Due ${fmtDate(a.due_on)} · ` : ''}{a.done_at ? 'Done' : 'Open'}{' '}
          {o.can_work && <button type="button" className="linklike" onClick={() => api.post(`/opportunities/${o.id}/activities/${a.id}/done`).then(onDone)}>{a.done_at ? 'Reopen' : 'Mark done'}</button>}
        </span>
      )}
      {a.replies.map((r) => <span key={r.id} className="sales-reply small"><strong>Reply from {r.from}</strong> · {fmtDateTime(r.at)}<span className="block">{r.snippet}</span></span>)}
      {a.kind === 'email' && a.replies.length === 0 && <span className="small muted">Replies will thread back here.</span>}
    </li>
  );
}

function ActivityDialog({ o, kind, onClose, onDone }: { o: OppDetail; kind: string; onClose: () => void; onDone: () => Promise<void> }) {
  const [f, setF] = useState({ summary: '', outcome: '', next_step: '', next_step_due: '', due_on: '', on: '' });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    try {
      await api.post(`/opportunities/${o.id}/activities`, { kind, summary: f.summary, outcome: f.outcome || null, next_step: f.next_step || null, next_step_due: f.next_step_due || null,
        due_on: f.due_on || null, on: f.on || null });
      await onDone(); onClose();
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={kind === 'task' ? 'Add a task' : `Log ${KIND_LABEL[kind].toLowerCase()}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label={kind === 'task' ? 'Task' : 'Summary'} rows={3} value={f.summary} onChange={set('summary')} />
        {kind === 'task' ? <TextField label="Due" type="date" value={f.due_on} onChange={set('due_on')} /> : <>
          <TextField label="When" type="date" value={f.on} onChange={set('on')} hint="Leave empty for today." />
          <TextField label="Outcome" value={f.outcome} onChange={set('outcome')} />
          <div className="grid-2"><TextField label="Next step" value={f.next_step} onChange={set('next_step')} /><TextField label="Due" type="date" value={f.next_step_due} onChange={set('next_step_due')} /></div>
        </>}
        <div className="row"><Button variant="primary" disabled={f.summary.trim().length < 2} onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function EmailDialog({ o, onClose, onDone }: { o: OppDetail; onClose: () => void; onDone: () => Promise<void> }) {
  const first = o.contacts.find((c) => c.email)?.email ?? '';
  const [to, setTo] = useState(first);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function send() {
    try { await api.post(`/opportunities/${o.id}/email`, { to: to.split(/[,;\s]+/).filter(Boolean), subject, body }); await onDone(); onClose(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Email from my mailbox" onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted">{H.email}</p>
        <TextField label="To" value={to} onChange={(e) => setTo(e.target.value)} hint={o.contacts.filter((c) => c.email).map((c) => c.email).join(', ') || undefined} />
        <TextField label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
        <TextArea label="Message" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!to || !subject || !body} onClick={send}>Send</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function QuestionnaireSummary({ o }: { o: OppDetail }) {
  const qn = o.linked.questionnaire;
  if (!qn) return <><p style={{ margin: 0 }}><strong>Not started</strong></p><p className="small muted" style={{ margin: '4px 0 0' }}>Record on the call, send to the client, or both.</p></>;
  return <p style={{ margin: 0 }}><Link to={qn.link}>Version {qn.version}</Link> · {Q_STATUS[qn.status] ?? qn.status}</p>;
}

function QuestionnairePanel({ o }: { o: OppDetail }) {
  const qn = o.linked.questionnaire;
  return (
    <Card title="Scoping questionnaire">
      <QuestionnaireSummary o={o} />
      <div className="row" style={{ marginTop: 12 }}>
        <ButtonLink to={`/sales/opportunities/${o.id}/scoping`}>{qn ? 'Open the scoping call' : 'Start scoping call'}</ButtonLink>
        {qn && <ButtonLink to={`/sales/opportunities/${o.id}/scoping/review`}>Review answers</ButtonLink>}
      </div>
    </Card>
  );
}

function ProposalsPanel({ o }: { o: OppDetail }) {
  const { proposals, estimates } = o.linked;
  return (
    <Card title="Estimates and proposals">
      {estimates.length === 0 && proposals.length === 0 && <p className="small muted">No estimate or proposal yet.</p>}
      {estimates.length > 0 && <><strong>Estimates</strong><ul>{estimates.map((e) => <li key={e.id}><Link to={e.link}>{e.name}{e.version ? ` v${e.version}` : ''}</Link></li>)}</ul></>}
      {proposals.length > 0 && <><strong>Proposals</strong><ul>{proposals.map((p) => <li key={p.id}><Link to={p.link}>{p.title} v{p.version}</Link> · {p.status.replace('_', ' ')}{p.sent_at ? ` · sent ${fmtDate(p.sent_at)}` : ''}</li>)}</ul></>}
      <div className="row">
        <ButtonLink to={`/sales/estimate?opportunity=${o.id}`}>Build an estimate</ButtonLink>
        <ButtonLink to="/sales/proposals">All proposals</ButtonLink>
        <ButtonLink to="/sales/approvals">Approvals</ButtonLink>
      </div>
    </Card>
  );
}

function Contacts({ o, roles, onDone }: { o: OppDetail; roles: { value: string; label: string }[]; onDone: () => Promise<void> }) {
  const [edit, setEdit] = useState<Contact | 'new' | null>(null);
  return (
    <Card title="Contacts" actions={o.can_work && <Button size="sm" onClick={() => setEdit('new')}>Add contact</Button>}>
      {o.contacts.length === 0 ? <p className="small muted">No contacts yet.</p> : (
        <div className="table-wrap"><table className="table"><thead><tr><th>Name</th><th>Title</th><th>Email</th><th>Phone</th><th>Role in deal</th><th /></tr></thead>
          <tbody>{o.contacts.map((c) => (
            <tr key={c.id}><td>{c.name}</td><td>{c.title ?? '—'}</td><td>{c.email ?? '—'}</td><td>{c.phone ?? '—'}</td><td>{c.contact_role_label ?? '—'}</td>
              <td>{o.can_work && <span className="row"><button type="button" className="linklike" onClick={() => setEdit(c)}>Edit</button>
                <button type="button" className="linklike" onClick={() => api.delete(`/opportunities/${o.id}/contacts/${c.id}`).then(onDone)}>Remove</button></span>}</td></tr>
          ))}</tbody></table></div>
      )}
      {edit && <ContactDialog o={o} c={edit === 'new' ? null : edit} roles={roles} onClose={() => setEdit(null)} onDone={async () => { setEdit(null); await onDone(); }} />}
    </Card>
  );
}

function ContactDialog({ o, c, roles, onClose, onDone }: { o: OppDetail; c: Contact | null; roles: { value: string; label: string }[]; onClose: () => void; onDone: () => Promise<void> }) {
  const [f, setF] = useState({ name: c?.name ?? '', title: c?.title ?? '', email: c?.email ?? '', phone: c?.phone ?? '', contact_role: c?.contact_role ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    const body = { name: f.name, title: f.title || null, email: f.email || null, phone: f.phone || null, contact_role: f.contact_role || null };
    try { await (c ? api.patch(`/opportunities/${o.id}/contacts/${c.id}`, body) : api.post(`/opportunities/${o.id}/contacts`, body)); await onDone(); } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); }
  }
  return (
    <Dialog title={c ? 'Edit contact' : 'Add contact'} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Name" value={f.name} onChange={set('name')} error={errs.name} />
        <TextField label="Title" value={f.title} onChange={set('title')} />
        <TextField label="Email" type="email" value={f.email} onChange={set('email')} error={errs.email} />
        <TextField label="Phone" value={f.phone} onChange={set('phone')} />
        <SelectField label="Role in deal" value={f.contact_role} onChange={set('contact_role')} options={roles} placeholder="Choose" />
        <div className="row"><Button variant="primary" disabled={!f.name.trim()} onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function ApprovalBox({ o, run }: { o: OppDetail; run: (fn: () => Promise<unknown>, done?: string) => Promise<void> }) {
  const [note, setNote] = useState('');
  return (
    <div className="stack-sm" style={{ marginTop: 10 }}>
      <span className="small">Chief Auditor approval: <Badge tone={o.approval === 'Approved' ? 'success' : o.approval === 'Declined' ? 'danger' : 'warn'}>{o.approval}</Badge>
        {o.ca_approved_by_name ? ` · ${o.ca_approved_by_name}` : ''}{o.ca_note ? ` · ${o.ca_note}` : ''}</span>
      {o.can_approve ? (<>
        <TextField label="Approval note" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row">
          <Button size="sm" variant="primary" onClick={() => run(() => api.post(`/opportunities/${o.id}/approve`, { decision: 'approve', note }), 'Offer approved.')}>Approve the offer</Button>
          <Button size="sm" onClick={() => run(() => api.post(`/opportunities/${o.id}/approve`, { decision: 'decline', note }), 'Offer declined.')}>Decline</Button>
        </div>
      </>) : o.can_work && !o.ca_decision && !o.approval_requested_at && (
        <Button size="sm" onClick={() => run(() => api.post(`/opportunities/${o.id}/request-approval`, { note: '' }), 'The Chief Auditors have been asked to approve.')}>Ask Chief Auditor to approve</Button>
      )}
    </div>
  );
}

function LoseDialog({ o, reasons, onClose, onDone }: { o: OppDetail; reasons: { value: string; label: string }[]; onClose: () => void; onDone: () => Promise<void> }) {
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title="Mark lost" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Reason" help={H.lostReason} value={reason} onChange={(e) => setReason(e.target.value)} options={reasons} placeholder="Choose" />
        <TextField label="Note" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!reason} onClick={() => api.patch(`/opportunities/${o.id}`, { stage: 'lost', lost_reason: reason, lost_note: note || null }).then(onDone).then(onClose).catch((e) => setErr(errorMessage(e)))}>Mark lost</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function EditDialog({ o, opts, onClose, onDone }: { o: OppDetail; opts: OppList; onClose: () => void; onDone: () => Promise<void> }) {
  const [f, setF] = useState({ name: o.name, est_value: o.value?.toString() ?? '', close_date: o.close_date ?? '', next_step: o.next_step ?? '', next_step_due: o.next_step_due ?? '',
    source: o.source ?? '', partner_id: o.partner_id ?? '', segment: o.segment ?? '', trigger_event: o.trigger_event ?? '', owner_id: o.owner_id ?? '', competitors: o.competitors.join(', ') });
  const [bant, setBant] = useState({ budget: o.bant.budget ?? '', authority: o.bant.authority ?? '', need: o.bant.need ?? '', timeline: o.bant.timeline ?? '' });
  const [products, setProducts] = useState<string[]>(o.products_of_interest);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    const body: Record<string, unknown> = { name: f.name, est_value: f.est_value ? Number(f.est_value) : null, close_date: f.close_date || null, next_step: f.next_step || null,
      next_step_due: f.next_step_due || null, source: f.source || null, partner_id: f.partner_id || null, segment: f.segment || null, trigger_event: f.trigger_event || null, bant,
      products_of_interest: products, competitors: f.competitors.split(',').map((x) => x.trim()).filter(Boolean) };
    if (o.can_reassign && f.owner_id !== (o.owner_id ?? '')) body.owner_id = f.owner_id || null;
    try { await api.patch(`/opportunities/${o.id}`, body); await onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Edit opportunity" onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Name" value={f.name} onChange={set('name')} />
        <fieldset className="grid-2"><legend>Qualification (BANT)</legend>
          <TextField label="Budget" help={H.bant} value={bant.budget} onChange={(e) => setBant({ ...bant, budget: e.target.value })} />
          <TextField label="Authority (who signs)" value={bant.authority} onChange={(e) => setBant({ ...bant, authority: e.target.value })} />
          <TextArea label="Need" rows={2} value={bant.need} onChange={(e) => setBant({ ...bant, need: e.target.value })} />
          <TextField label="Timeline" value={bant.timeline} onChange={(e) => setBant({ ...bant, timeline: e.target.value })} />
        </fieldset>
        <div className="grid-2">
          <TextField label="Estimated value ($)" type="number" min={0} value={f.est_value} onChange={set('est_value')} />
          <TextField label="Expected close" type="date" value={f.close_date} onChange={set('close_date')} />
          <TextField label="Next step" value={f.next_step} onChange={set('next_step')} />
          <TextField label="Due" type="date" value={f.next_step_due} onChange={set('next_step_due')} />
          <SelectField label="Source" value={f.source} onChange={set('source')} options={opts.sources} placeholder="Choose" />
          <SelectField label="Partner (if referred)" help={H.partner} value={f.partner_id} onChange={set('partner_id')} options={opts.partners.map((x) => ({ value: x.id, label: x.name }))} placeholder="None" />
          <SelectField label="Segment" value={f.segment} onChange={set('segment')} options={opts.segments} placeholder="Choose" />
          <SelectField label="Trigger" value={f.trigger_event} onChange={set('trigger_event')} options={opts.trigger_events} placeholder="Choose" />
          {o.can_reassign && <SelectField label="Owner" value={f.owner_id} onChange={set('owner_id')} options={opts.owners.map((x) => ({ value: x.id, label: x.name }))} placeholder="No owner" />}
          <TextField label="Competitors" hint="Separate with commas." value={f.competitors} onChange={set('competitors')} />
        </div>
        <div role="group" aria-label="Products of interest" className="sales-checks">
          {opts.products.map((x) => (
            <label key={x.value} className="checkbox"><input type="checkbox" checked={products.includes(x.value)} onChange={(e) => setProducts(e.target.checked ? [...products, x.value] : products.filter((y) => y !== x.value))} /> {x.label}</label>
          ))}
        </div>
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
