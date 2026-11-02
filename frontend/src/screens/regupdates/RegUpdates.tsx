import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useLaws, useLawJurisdictions } from '@/api/laws';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { updateHelp as H } from '@/help/regupdates';
import '@/styles/monitoring.css';
import '@/styles/regupdates.css';

type Opt = { value: string; label: string };
export type Update = {
  kind: 'update' | 'law_library'; id: string; reference: string | null; change_type: string; change_label: string; jurisdiction_id?: string | null; jurisdiction_name: string | null;
  regulation_id?: string | null; law_name: string | null; title: string; summary: string; todo_text?: string | null; effective_on: string | null; source_url: string | null;
  source_name?: string | null; source_quote?: string | null; affected_features?: string[]; feature_labels: string[]; watch: boolean; verify_note?: string | null; status: string;
  status_label: string; author_name?: string | null; reviewed_by_name: string | null; review_note?: string | null; published_at: string | null; client_count: number;
  clients: { id: string; name: string }[]; read_only: boolean; can_edit: boolean; can_review: boolean; can_act: boolean; can_submit?: boolean;
  can_propose_law_change?: boolean; can_withdraw?: boolean; proposed_change_id?: string | null;
};
type Data = { rows: Update[]; counts: { all: number; awaiting_review: number; published: number }; can_add: boolean; can_manage_digest: boolean; clients: { id: string; name: string }[];
  features: Opt[]; change_types: Opt[] };
type Impact = { organization_id: string; client_name: string; match_reason: string | null; systems: { id: string; reference: string; name: string; risk_tier: number | null; stage: string; department: string | null }[];
  findings: { id: string; ref: string; title: string; severity: string; engagement: string; system_reference: string; remediation_due: string | null; remediation_status: string }[];
  todos: { code: string; text: string }[]; alert_status?: string | null; opportunity_id?: string | null };
type Msg = { tone: 'success' | 'danger'; text: string } | null;

const TONE: Record<string, 'navy' | 'danger' | 'warn' | 'muted' | 'success'> = {
  effective_date: 'navy', new_law: 'navy', amendment: 'navy', enforcement_action: 'danger', enforcement: 'danger', guidance: 'success', court_ruling: 'warn', pending_bill: 'muted',
  new_rule: 'navy', repeal: 'muted', role_mapping: 'navy',
};
const TIER: Record<number, string> = { 1: 'Tier 1 · Baseline', 2: 'Tier 2 · Elevated', 3: 'Tier 3 · High' };
const TABS = [{ key: 'all', label: 'All' }, { key: 'awaiting_review', label: 'Awaiting review' }, { key: 'published', label: 'Published' }] as const;
const KINDS: Opt[] = [{ value: 'advisory', label: 'Advisory' }, { value: 'readiness', label: 'Readiness review' }, { value: 'bias_audit', label: 'Bias audit' },
  { value: 'training', label: 'Training' }, { value: 'remediation', label: 'Remediation support' }];
const FIELDS: Opt[] = [{ value: 'law.effective_on', label: 'Effective date' }, { value: 'law.compliance_on', label: 'Compliance date' }, { value: 'law.status', label: 'Status' },
  { value: 'law.enforcer', label: 'Enforcer' }, { value: 'law.penalty_text', label: 'Penalty' }, { value: 'law.litigation_text', label: 'Litigation and enforcement' },
  { value: 'law.scope_text', label: 'Scope' }];

export function RegUpdates() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get('tab') ?? 'all') as (typeof TABS)[number]['key'];
  const q = useQuery({ queryKey: ['reg-updates'], queryFn: () => api.get<Data>('/reg/updates') });
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ['reg-updates'] });
  const [msg, setMsg] = useState<Msg>(null);
  const [editing, setEditing] = useState<Update | 'new' | null>(null);
  const [reviewing, setReviewing] = useState<Update | null>(null);
  const [lawChange, setLawChange] = useState<Update | null>(null);
  const [opp, setOpp] = useState<{ u: Update; org: string } | null>(null);
  const [digest, setDigest] = useState(false);
  const [withdrawing, setWithdrawing] = useState<Update | null>(null);
  const [focus, setFocus] = useState<{ id: string; org: string } | null>(null);
  const d = q.data;
  const rows = useMemo(() => (d ? d.rows.filter((r) => tab === 'all' || r.status === tab) : []), [d, tab]);
  const focused = d?.rows.find((r) => r.id === focus?.id) ?? null;
  useEffect(() => {
    if (d && !focus) {
      const first = d.rows.find((r) => r.status === 'published' && r.client_count > 0);
      if (first) setFocus({ id: first.id, org: first.clients[0].id });
    }
  }, [d, focus]);

  async function run(fn: () => Promise<unknown>, done: string) {
    try { await fn(); await refresh(); setMsg({ tone: 'success', text: done }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const sendAlert = (u: Update, orgs: string[]) => run(() => api.post(`/reg/updates/${u.id}/alerts`, { organization_ids: orgs }),
    `${orgs.length === 1 ? 'The alert waits' : `${orgs.length} alerts wait`} for the Chief Auditor's approval in Client alerts.`);
  const columns: GridColumn<Update>[] = [
    { key: 'type', header: 'Change', value: (u) => u.change_label, width: '150px',
      render: (u) => <span className="stack-xs"><Badge tone={u.status === 'awaiting_review' ? 'warn' : TONE[u.change_type] ?? 'navy'}>{u.status === 'awaiting_review' ? 'Awaiting review' : u.change_label}</Badge><span className="small muted">{u.jurisdiction_name}</span></span> },
    { key: 'update', header: 'Update', value: (u) => u.title, render: (u) => (
      <span className="ru-item">
        <strong>{u.law_name && !u.title.includes(u.law_name) ? `${u.law_name}: ` : ''}{u.title}</strong>
        <span className="clamp-3">{u.summary}</span>
        <span className="small muted">
          {u.kind === 'law_library' ? 'From the law library · ' : ''}
          {u.feature_labels.length > 0 && `Feature: ${u.feature_labels.join(', ')} · `}
          {u.effective_on && `From ${fmtDate(u.effective_on)} · `}
          {u.status === 'awaiting_review' || u.status === 'draft' ? `Drafted by ${u.author_name ?? '—'}${u.status === 'awaiting_review' ? ' · needs second reviewer' : ''}` : u.reviewed_by_name ? `Reviewed by ${u.reviewed_by_name}` : ''}
          {u.source_url && <> · <a href={u.source_url} target="_blank" rel="noreferrer">source</a></>}
        </span>
        {u.verify_note && <span className="small"><Badge tone="warn">To confirm</Badge> {u.verify_note}</span>}
      </span>) },
    { key: 'clients', header: 'Clients', value: (u) => (u.watch ? -1 : u.client_count), width: '130px', render: (u) => (
      u.watch ? <strong>Watch</strong> : u.status !== 'published' ? <span className="muted">{u.status_label}</span> :
        <span className="stack-xs"><strong>{u.client_count} {u.client_count === 1 ? 'client' : 'clients'}</strong>
          {u.client_count > 0 && <button type="button" className="linklike left" onClick={() => setFocus({ id: u.id, org: u.clients[0].id })}>See impact</button>}</span>) },
  ];
  const rowActions = (u: Update): GridRowAction[] => [
    ...(u.client_count > 0 ? [{ label: 'See impact', onSelect: () => setFocus({ id: u.id, org: u.clients[0].id }) }] : []),
    ...(u.can_edit ? [{ label: 'Edit', onSelect: () => setEditing(u) }] : []),
    ...(u.can_submit ? [{ label: 'Send for review', onSelect: () => run(() => api.post(`/reg/updates/${u.id}/submit`), `${u.reference} waits for a second reviewer.`) }] : []),
    ...(u.can_review ? [{ label: 'Review', onSelect: () => setReviewing(u) }] : []),
    ...(u.can_act && u.client_count > 0 ? [{ label: 'Send alert to every matched client', onSelect: () => sendAlert(u, u.clients.map((c) => c.id)) }] : []),
    ...(u.can_propose_law_change ? [{ label: 'Propose the law change', onSelect: () => setLawChange(u) }] : []),
    ...(u.can_withdraw ? [{ label: 'Withdraw', danger: true, onSelect: () => setWithdrawing(u) }] : []),
  ];
  return (
    <div className="page">
      <PageHeader title="Regulatory change alerts" subtitle="Curated by Futran Research · a second reviewer checks every update before any client is alerted · approved law-library changes appear here too"
        actions={d && <span className="row">{d.can_manage_digest && <Button onClick={() => setDigest(true)}>Weekly digest</Button>}{d.can_add && <Button variant="primary" onClick={() => setEditing('new')}>Add update</Button>}</span>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!d ? <Loading /> : (
        <div className="ru-layout">
          <section className="ru-main">
            <Card>
              <div className="pills" role="tablist" aria-label="Show">
                {TABS.map((t) => (
                  <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={`pill${tab === t.key ? ' active' : ''}`} onClick={() => setParams(t.key === 'all' ? {} : { tab: t.key })}>
                    {t.label} · {d.counts[t.key]}
                  </button>))}
              </div>
              <DataGrid label="Regulatory updates" rows={rows} rowId={(u) => u.id} rowLabel={(u) => u.title} columns={columns} selectable rowActions={rowActions}
                bulkActions={[{ label: 'Export for thought leadership', run: (sel) => exportCsv(sel) }]}
                filters={[{ key: 'type', label: 'Change', options: d.change_types, test: (u, v) => u.change_type === v },
                  { key: 'source', label: 'Source', options: [{ value: 'update', label: 'Futran Research' }, { value: 'law_library', label: 'Law library' }], test: (u, v) => u.kind === v }]}
                search={{ label: 'Search updates', text: (u) => `${u.law_name ?? ''} ${u.title} ${u.summary} ${u.jurisdiction_name ?? ''}` }}
                emptyText={tab === 'awaiting_review' ? 'Nothing is waiting for review.' : 'No updates yet. Add one, or approve a change in Refresh and review.'} />
            </Card>
          </section>
          <aside className="ru-aside">
            {focused ? <ImpactCard u={focused} org={focus!.org} onOrg={(org) => setFocus({ id: focused.id, org })} onAlert={(org) => sendAlert(focused, [org])} onOpp={(org) => setOpp({ u: focused, org })} />
              : <Card title="Impact for a client"><EmptyState>Choose "See impact" on a published update.</EmptyState></Card>}
            <UpcomingDates clients={d.clients} />
            <Card><p className="small" style={{ margin: 0 }}>A published update that changes a law's facts goes to Refresh and review as a proposed change, so approved updates create a new law version. The weekly digest goes to client Chief AI Compliance Officers who have it turned on; selected items can be exported for the thought leadership pipeline.</p></Card>
          </aside>
        </div>
      )}
      {editing && d && <UpdateForm d={d} u={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onDone={(t) => { setEditing(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {reviewing && <ReviewDialog u={reviewing} onClose={() => setReviewing(null)} onDone={(t) => { setReviewing(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {lawChange && <LawChangeDialog u={lawChange} onClose={() => setLawChange(null)} onDone={(t) => { setLawChange(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {opp && <OpportunityDialog u={opp.u} org={opp.org} onClose={() => setOpp(null)} onDone={(t) => { setOpp(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {digest && <DigestDialog onClose={() => setDigest(false)} />}
      {withdrawing && <WithdrawDialog u={withdrawing} onClose={() => setWithdrawing(null)} onDone={(t) => { setWithdrawing(null); setMsg({ tone: 'success', text: t }); refresh(); }} />}
    </div>
  );
}

function exportCsv(rows: Update[]) {
  const esc = (v: string | null | undefined) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [['Change', 'Jurisdiction', 'Law', 'Headline', 'Summary', 'Effective', 'Source'].join(',')]
    .concat(rows.map((u) => [u.change_label, u.jurisdiction_name, u.law_name, u.title, u.summary, u.effective_on, u.source_url].map(esc).join(',')));
  const url = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'regulatory-updates.csv';
  a.click();
  URL.revokeObjectURL(url);
}

function ImpactCard({ u, org, onOrg, onAlert, onOpp }: { u: Update; org: string; onOrg: (o: string) => void; onAlert: (o: string) => Promise<void>; onOpp: (o: string) => void }) {
  const path = u.kind === 'law_library' ? `/reg/updates/law-library/${u.id}/impact/${org}` : `/reg/updates/${u.id}/impact/${org}`;
  const q = useQuery({ queryKey: ['reg-impact', path], queryFn: () => api.get<Impact>(path) });
  const [busy, setBusy] = useState(false);
  const i = q.data;
  return (
    <section className="card ru-impact" aria-label="Impact for a client">
      <div className="card-body stack-sm">
        {u.clients.length > 1 ? <SelectField label="Impact for" value={org} onChange={(e) => onOrg(e.target.value)} options={u.clients.map((c) => ({ value: c.id, label: c.name }))} />
          : <div className="small muted"><strong>Impact for {u.clients[0]?.name}</strong></div>}
        <h2 className="ru-impact-title">{u.title}</h2>
        {!i ? <Loading /> : (
          <>
            {i.match_reason && <p className="small muted" style={{ margin: 0 }}>{i.match_reason}</p>}
            <ul className="ru-list">
              {i.systems.map((s) => <li key={s.id}>Affects <strong>{s.reference} {s.name}</strong>{s.risk_tier ? ` (${TIER[s.risk_tier]})` : ''}{s.department ? `, ${s.department}` : ''}</li>)}
              {i.systems.length === 0 && <li>No register system is linked; the client operates where the change applies.</li>}
              {i.findings.map((f) => <li key={f.id}>Open finding {f.ref}: {f.title.toLowerCase()} ({f.engagement})</li>)}
              {i.findings.map((f) => f.remediation_due && <li key={`${f.id}-due`}>Remediation due {fmtDate(f.remediation_due)}{f.remediation_status === 'Overdue' ? ' (overdue)' : ''}</li>)}
            </ul>
            {i.alert_status && <p className="small" style={{ margin: 0 }}><Badge tone={i.alert_status === 'sent' ? 'success' : 'warn'}>{i.alert_status === 'sent' ? 'Alert sent' : 'Alert waiting for approval'}</Badge></p>}
            {u.can_act && (
              <div className="row wrap">
                <Button variant="primary" disabled={busy || !!i.alert_status} onClick={async () => { setBusy(true); await onAlert(org); await q.refetch(); setBusy(false); }}>Send alert to client</Button>
                <Button disabled={busy || !!i.opportunity_id} onClick={() => onOpp(org)}>{i.opportunity_id ? 'Opportunity created' : 'Create advisory opportunity'}</Button>
              </div>)}
            {u.read_only && <p className="small muted" style={{ margin: 0 }}>Client alerts for law-library changes are queued when the change is approved in <Link to="/reg/refresh">Refresh and review</Link>.</p>}
          </>)}
      </div>
    </section>
  );
}

function UpcomingDates({ clients }: { clients: { id: string; name: string }[] }) {
  const [org, setOrg] = useState('');
  const q = useQuery({ queryKey: ['reg-calendar', org], queryFn: () => api.get<{ rows: { law: string; date: string; what: string; clients: { id: string; name: string }[] }[] }>(`/reg/updates/calendar${org ? `?organization_id=${org}` : ''}`) });
  return (
    <Card title="Upcoming dates for your clients">
      <SelectField label="Client" help={H.calendarClient} value={org} onChange={(e) => setOrg(e.target.value)} options={clients.map((c) => ({ value: c.id, label: c.name }))} placeholder="All clients" />
      {!q.data ? <Loading /> : q.data.rows.length === 0 ? <EmptyState>No dates in the next two years.</EmptyState> : (
        <ul className="ru-dates">
          {q.data.rows.slice(0, 12).map((r) => (
            <li key={`${r.law}-${r.date}-${r.what}`}><span>{r.law}<span className="small muted block">{r.what}{!org ? ` · ${r.clients.map((c) => c.name).join(', ')}` : ''}</span></span><strong className="nowrap">{fmtDate(r.date)}</strong></li>))}
        </ul>)}
    </Card>
  );
}

type Form = { change_type: string; jurisdiction_id: string; regulation_id: string; law_name: string; title: string; summary: string; todo_text: string; effective_on: string; source_url: string;
  source_name: string; source_quote: string; affected_features: string[]; watch: boolean; verify_note: string };

function UpdateForm({ d, u, onClose, onDone }: { d: Data; u: Update | null; onClose: () => void; onDone: (t: string) => void }) {
  const [f, setF] = useState<Form>({
    change_type: u?.change_type ?? 'guidance', jurisdiction_id: u?.jurisdiction_id ?? '', regulation_id: u?.regulation_id ?? '', law_name: u?.law_name ?? '', title: u?.title ?? '',
    summary: u?.summary ?? '', todo_text: u?.todo_text ?? '', effective_on: u?.effective_on ?? '', source_url: u?.source_url ?? '', source_name: u?.source_name ?? '',
    source_quote: u?.source_quote ?? '', affected_features: u?.affected_features ?? [], watch: u?.watch ?? false, verify_note: u?.verify_note ?? '',
  });
  const [lawQ, setLawQ] = useState('');
  const jur = useLawJurisdictions();
  const laws = useLaws('all', '', lawQ);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Form, v: Form[keyof Form]) => setF((x) => ({ ...x, [k]: v }));
  const lawOptions = (laws.data ?? []).flatMap((g) => g.laws.map((l) => ({ value: l.id, label: `${l.short_name} (${g.jurisdiction.name})` }))).slice(0, 60);
  if (f.regulation_id && u?.regulation_id === f.regulation_id && !lawOptions.some((o) => o.value === f.regulation_id)) lawOptions.unshift({ value: f.regulation_id, label: u?.law_name ?? 'Linked law' });
  async function save(submit: boolean) {
    setBusy(true); setErr(null); setErrs({});
    const body = { ...f, jurisdiction_id: f.jurisdiction_id || null, regulation_id: f.regulation_id || null, effective_on: f.effective_on || null };
    try {
      const saved = u ? await api.patch<Update>(`/reg/updates/${u.id}`, body) : await api.post<Update>('/reg/updates', body);
      if (submit) await api.post(`/reg/updates/${saved.id}/submit`);
      onDone(submit ? `${saved.reference} waits for a second reviewer.` : `${saved.reference} saved as a draft.`);
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={u ? `Edit ${u.reference}` : 'Add update'} onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <SelectField label="Type of change *" help={H.changeType} value={f.change_type} onChange={(e) => { set('change_type', e.target.value); if (e.target.value === 'pending_bill') set('watch', true); }} options={d.change_types} error={errs.change_type} />
          <SelectField label="Jurisdiction *" help={H.jurisdiction} value={f.jurisdiction_id} onChange={(e) => set('jurisdiction_id', e.target.value)} placeholder="Choose"
            options={(jur.data ?? []).map((j) => ({ value: j.id, label: j.name }))} error={errs.jurisdiction_id} />
        </div>
        <div className="grid-2">
          <TextField label="Find a law in the law library" help={H.law} value={lawQ} onChange={(e) => setLawQ(e.target.value)} placeholder="Type part of the name" />
          <SelectField label="Law" help={H.law} value={f.regulation_id} onChange={(e) => set('regulation_id', e.target.value)} options={lawOptions} placeholder="Not in the law library" error={errs.regulation_id} />
        </div>
        <TextField label="Law, bill or rule as shown" help={H.lawName} value={f.law_name} onChange={(e) => set('law_name', e.target.value)} />
        <TextField label="Headline *" help={H.title} value={f.title} onChange={(e) => set('title', e.target.value)} error={errs.title} />
        <TextArea label="Summary *" help={H.summary} rows={3} value={f.summary} onChange={(e) => set('summary', e.target.value)} error={errs.summary} />
        <TextArea label="What clients should do" help={H.todos} rows={3} value={f.todo_text} onChange={(e) => set('todo_text', e.target.value)} />
        <div className="grid-2">
          <TextField label="Effective date" type="date" help={H.effectiveOn} value={f.effective_on} onChange={(e) => set('effective_on', e.target.value)} error={errs.effective_on} />
          <TextField label="Source name" help={H.sourceName} value={f.source_name} onChange={(e) => set('source_name', e.target.value)} />
        </div>
        <TextField label="Source link *" help={H.sourceUrl} type="url" value={f.source_url} onChange={(e) => set('source_url', e.target.value)} error={errs.source_url} hint="Needed before the update can be sent for review." />
        <TextArea label="Quoted passage" help={H.sourceQuote} rows={2} value={f.source_quote} onChange={(e) => set('source_quote', e.target.value)} />
        <FieldGroup legend="Kinds of AI it concerns" help={H.features}>
          <div className="ru-checks">{d.features.filter((x) => x.value !== 'government_other').map((x) => (
            <Checkbox key={x.value} label={x.label} checked={f.affected_features.includes(x.value)}
              onChange={(e) => set('affected_features', e.target.checked ? [...f.affected_features, x.value] : f.affected_features.filter((v) => v !== x.value))} />))}</div>
        </FieldGroup>
        <Checkbox label="Watch item: no client action" help={H.watch} checked={f.watch} onChange={(e) => set('watch', e.target.checked)} />
        <TextField label="Still to confirm" help={H.verifyNote} value={f.verify_note} onChange={(e) => set('verify_note', e.target.value)} />
        <div className="row wrap">
          <Button variant="primary" disabled={busy} onClick={() => save(true)}>Save and send for review</Button>
          <Button disabled={busy} onClick={() => save(false)}>Save draft</Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Dialog>
  );
}

function ReviewDialog({ u, onClose, onDone }: { u: Update; onClose: () => void; onDone: (t: string) => void }) {
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function decide(approve: boolean) {
    setBusy(true); setErr(null);
    try { await api.post(`/reg/updates/${u.id}/review`, { approve, note, clear_verify_note: approve && confirmed }); onDone(approve ? `${u.reference} published and matched to clients.` : `${u.reference} sent back to ${u.author_name ?? 'its author'}.`); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Review ${u.reference}`} onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <dl className="kv">
          <dt>Change</dt><dd>{u.change_label} · {u.jurisdiction_name}</dd>
          <dt>Headline</dt><dd>{u.law_name ? `${u.law_name}: ` : ''}{u.title}</dd>
          <dt>Summary</dt><dd>{u.summary}</dd>
          {u.todo_text && <><dt>To-dos</dt><dd style={{ whiteSpace: 'pre-line' }}>{u.todo_text}</dd></>}
          <dt>Effective</dt><dd>{u.effective_on ? fmtDate(u.effective_on) : 'No date'}</dd>
          <dt>Source</dt><dd>{u.source_url ? <a href={u.source_url} target="_blank" rel="noreferrer">{u.source_name || u.source_url}</a> : '—'}</dd>
          {u.source_quote && <><dt>Quoted</dt><dd>“{u.source_quote}”</dd></>}
          {u.verify_note && <><dt>To confirm</dt><dd>{u.verify_note}</dd></>}
          <dt>Drafted by</dt><dd>{u.author_name}</dd>
        </dl>
        <TextArea label="Note" help={H.reviewNote} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        {u.verify_note && <Checkbox label="I confirmed the point above; clear it and publish" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />}
        <div className="row wrap">
          <Button variant="primary" disabled={busy || (!!u.verify_note && !confirmed)} onClick={() => decide(true)}>Publish</Button>
          <Button disabled={busy} onClick={() => decide(false)}>Send back</Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Dialog>
  );
}

function LawChangeDialog({ u, onClose, onDone }: { u: Update; onClose: () => void; onDone: (t: string) => void }) {
  const [field, setField] = useState(u.change_type === 'effective_date' ? 'law.effective_on' : 'law.litigation_text');
  const [value, setValue] = useState(u.change_type === 'effective_date' ? u.effective_on ?? '' : u.summary);
  const [summary, setSummary] = useState(u.title);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/reg/updates/${u.id}/law-change`, { field_path: field, new_value: value, summary }); onDone('The change waits for approval in Refresh and review.'); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Propose the law change: ${u.law_name ?? ''}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="What changes" help={H.fieldPath} value={field} onChange={(e) => setField(e.target.value)} options={FIELDS} />
        {field.endsWith('_on') ? <TextField label="New value" type="date" help={H.newValue} value={value} onChange={(e) => setValue(e.target.value)} />
          : <TextArea label="New value" help={H.newValue} rows={3} value={value} onChange={(e) => setValue(e.target.value)} />}
        <TextField label="Summary for the review queue" help={H.changeSummary} value={summary} onChange={(e) => setSummary(e.target.value)} />
        <p className="small muted">The source link and quoted passage of {u.reference} go with the proposal. Nothing changes in the law library until the Chief Auditor approves it.</p>
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Propose</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function OpportunityDialog({ u, org, onClose, onDone }: { u: Update; org: string; onClose: () => void; onDone: (t: string) => void }) {
  const [kind, setKind] = useState('advisory');
  const [service, setService] = useState(`${u.law_name ? `${u.law_name} ` : ''}advisory`);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const client = u.clients.find((c) => c.id === org)?.name ?? '';
  async function save() {
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ needs_ca_approval: boolean }>(`/reg/updates/${u.id}/opportunity`, { organization_id: org, service_kind: kind, service });
      onDone(`Opportunity for ${client} created in Opportunities.${r.needs_ca_approval ? ' It needs the Chief Auditor\'s approval before an offer goes out.' : ''}`);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Create advisory opportunity: ${client}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Kind of service" help={H.serviceKind} value={kind} onChange={(e) => setKind(e.target.value)} options={KINDS} />
        <TextField label="Service" help={H.service} value={service} onChange={(e) => setService(e.target.value)} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Create</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function WithdrawDialog({ u, onClose, onDone }: { u: Update; onClose: () => void; onDone: (t: string) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/reg/updates/${u.id}/withdraw`, { reason }); onDone(`${u.reference} withdrawn. Clients no longer see it.`); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Withdraw ${u.reference}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="Why is it withdrawn? *" help={H.withdrawReason} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="row wrap"><Button variant="danger" disabled={busy} onClick={save}>Withdraw</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DigestDialog({ onClose }: { onClose: () => void }) {
  const q = useQuery({ queryKey: ['reg-digest'], queryFn: () => api.get<{ rows: { organization_id: string; name: string; enabled: boolean; last_sent_at: string | null }[] }>('/reg/updates/digest') });
  const [busy, setBusy] = useState<string | null>(null);
  return (
    <Dialog title="Weekly digest" onClose={onClose}>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>{H.digest}</p>
        {!q.data ? <Loading /> : q.data.rows.map((r) => (
          <Checkbox key={r.organization_id} help={H.digest} disabled={busy === r.organization_id} label={<>{r.name}{r.last_sent_at && <span className="small muted"> · last sent {fmtDate(r.last_sent_at)}</span>}</>} checked={r.enabled}
            onChange={async (e) => { setBusy(r.organization_id); await api.put(`/reg/updates/digest/${r.organization_id}`, { enabled: e.target.checked }); await q.refetch(); setBusy(null); }} />))}
        <div className="row"><Button onClick={onClose}>Done</Button></div>
      </div>
    </Dialog>
  );
}
