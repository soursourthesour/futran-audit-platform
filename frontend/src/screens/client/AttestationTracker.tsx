import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn, type GridFilter } from '@/components/ui/DataGrid';
import { attestationLaunchHelp as H } from '@/help/client';
import { attestationAnswersHelp as AH, sendAttestationHelp as SH } from '@/help/attestation';
import './attestation.css';

type ToolItem = { label: string; kind: 'tool' | 'agent'; tool: string; account_type: string; name: string | null; has_name: boolean };
export type Answer = {
  id: string; name: string; email: string | null; department_id: string; department: string | null; uses_ai: boolean; tools: string[]; tool_items: ToolItem[]; account_types: string[];
  personal_account: boolean; purposes: string[]; purpose_other: string | null; data_entered: string[]; policy_acknowledged: boolean; submitted_at: string; source: 'link' | 'in_app';
  status: 'new' | 'reviewed'; reviewed_at: string | null; reviewed_by: string | null; edited_at: string | null; edited_by: string | null; reviewer_note: string | null;
};
type InApp = { sent_at: string | null; assigned: number; submitted: number; outstanding?: { id: string; name: string; email: string; department: string | null }[] };
type Tracker = {
  campaign: { id: string; status: string; policy_version: string; launched_at: string; closes_at: string; closed_at: string | null; link: string | null; department_ids: string[] };
  totals: { responses: number | string; use_ai: number | null; personal_accounts: number | null; headcount: number | null };
  departments: { id: string; name: string; responses: number | string; headcount: number | null }[];
  tools: { label: string; count: number | string; kind: 'tool' | 'agent' }[];
  individuals: Answer[] | null;
  in_app: InApp | null;
  permissions: { send: boolean; manage: boolean };
};
type SendOnly = { campaign: { status: string; closes_at: string; launched_at: string; policy_version: string } | null } & Partial<InApp>;
type PeopleLite = { departments: { id: string; name: string; in_scope: boolean }[] };

export function AttestationTracker() {
  const { data: me } = useMe();
  const roles = new Set(me?.roles.map((r) => r.role));
  const id = me?.organization.id ?? '';
  if (me && !['caico', 'dpo', 'dept_compliance_lead'].some((r) => roles.has(r)) && roles.has('client_admin')) return <SendOnlyView clientId={id} />;
  return <AttestationView clientId={id} canLaunch={roles.has('caico')} />;
}

export function FutranAttestation() {
  const { clientId = '' } = useParams();
  return <AttestationView clientId={clientId} canLaunch={false} />;
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "Send attestation": gives everyone with a login an "AI use attestation" item on their AI attestation page. */
function SendButton({ clientId, onSent }: { clientId: string; onSent: (text: string) => void }) {
  const qc = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ sent: number; total: number }>(`/clients/${clientId}/attestation/send`);
      setAsking(false);
      const already = r.total - r.sent;
      onSent(r.sent === 0 ? `Everyone with a login already has the attestation (${r.total} ${r.total === 1 ? 'person' : 'people'}). Nobody was emailed again.`
        : `Attestation sent to ${r.sent} ${r.sent === 1 ? 'person' : 'people'} with a login. They have an item on their AI attestation page and an email.${already ? ` ${already} already had it and were not emailed again.` : ''}`);
      await qc.invalidateQueries({ queryKey: ['attestation', clientId] });
      await qc.invalidateQueries({ queryKey: ['attestation-send', clientId] });
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <>
      <Button variant="primary" onClick={() => setAsking(true)}>Send attestation</Button>
      {asking && (
        <Dialog title="Send the attestation to users with a login" onClose={() => setAsking(false)}>
          <div className="stack">
            {err && <Alert tone="danger">{err}</Alert>}
            <p style={{ margin: 0 }}>{SH.send}</p>
            <p className="small muted" style={{ margin: 0 }}>Staff without a login still answer through the staff link. A person who answers both ways with the same work email is counted once.</p>
            <div className="row">
              <Button variant="primary" onClick={go} disabled={busy}>Send attestation</Button>
              <Button onClick={() => setAsking(false)}>Cancel</Button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}

function InAppCard({ inApp, open }: { inApp: InApp; open: boolean }) {
  return (
    <Card title="Users with a login">
      {!inApp.sent_at ? <EmptyState>{open ? 'Not sent yet. Use Send attestation to give everyone with a login an item on their AI attestation page.' : 'The attestation was not sent to users with a login.'}</EmptyState> : (
        <div className="stack-sm">
          <p className="small" style={{ margin: 0 }}>Sent {fmtDate(inApp.sent_at)} · <strong>{inApp.submitted} of {inApp.assigned}</strong> completed</p>
          {inApp.outstanding && (inApp.outstanding.length === 0 ? <p className="small muted" style={{ margin: 0 }}>Everyone with a login has completed it.</p> : (
            <>
              <p className="small muted" style={{ margin: 0 }}>Still to do</p>
              <table className="table"><tbody>{inApp.outstanding.map((u) => <tr key={u.id}><td>{u.name}<div className="small muted">{u.email}</div></td><td className="small">{u.department ?? '—'}</td></tr>)}</tbody></table>
            </>
          ))}
        </div>
      )}
    </Card>
  );
}

/** The Client Admin sends the line items but does not see answers or department counts. */
function SendOnlyView({ clientId }: { clientId: string }) {
  const q = useQuery({ queryKey: ['attestation-send', clientId], queryFn: () => api.get<SendOnly>(`/clients/${clientId}/attestation/in-app`), enabled: !!clientId });
  const [msg, setMsg] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const c = q.data.campaign;
  const open = c?.status === 'open';
  return (
    <div className="page">
      <PageHeader title="AI use attestation" subtitle={c ? `Policy version ${c.policy_version} · launched ${fmtDate(c.launched_at)} · ${open ? `closes ${fmtDate(c.closes_at)}` : 'closed'}` : 'Your Chief AI Compliance Officer launches the campaign.'}
        actions={open ? <SendButton clientId={clientId} onSent={setMsg} /> : undefined} />
      {msg && <Alert tone="success">{msg}</Alert>}
      {!c ? <Card><EmptyState>The campaign has not been launched yet. Once your Chief AI Compliance Officer launches it, you can send it to everyone with a login from here.</EmptyState></Card> : (
        <div style={{ maxWidth: 560 }}><InAppCard inApp={{ sent_at: q.data.sent_at ?? null, assigned: q.data.assigned ?? 0, submitted: q.data.submitted ?? 0 }} open={open} /></div>
      )}
      <p className="small muted">Answers and department totals are visible to the Chief AI Compliance Officer and the Data Protection Officer.</p>
    </div>
  );
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
        <PageHeader title="AI use attestation" subtitle="A short, anonymous-to-managers check-in that asks staff which AI tools and agents they use for work and how." />
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
  const campaignDepts = t.departments.filter((d) => t.campaign.department_ids.includes(d.id));
  return (
    <div className="page">
      <PageHeader title="AI use attestation" subtitle={`Policy version ${t.campaign.policy_version} · launched ${fmtDate(t.campaign.launched_at)} · ${open ? `closes ${fmtDate(t.campaign.closes_at)}` : `closed ${fmtDate(t.campaign.closed_at ?? t.campaign.closes_at)}`}`}
        actions={<>{open && t.permissions?.send && <SendButton clientId={clientId} onSent={(text) => setMsg({ tone: 'success', text })} />}{canLaunch && link && open && <Button onClick={copy}>Copy staff link</Button>}{canLaunch && open && <Button onClick={close}>Close campaign</Button>}</>} />
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
        </div>
        <div className="side stack">
          <Card title="Tools and agents declared">
            {t.tools.length === 0 ? <EmptyState>Shown once at least 3 people have answered.</EmptyState> : (
              <table className="table"><tbody>{t.tools.map((x) => <tr key={x.label}><td>{x.label}{x.kind === 'agent' && <> <Badge tone="muted">Agent</Badge></>}</td><td style={{ textAlign: 'right' }}>{x.count}</td></tr>)}</tbody></table>
            )}
          </Card>
          {t.in_app && <InAppCard inApp={t.in_app} open={open} />}
        </div>
      </div>
      {t.individuals && <Individuals clientId={clientId} rows={t.individuals} departments={campaignDepts.length ? campaignDepts : t.departments} canManage={!!t.permissions?.manage} onMsg={setMsg} />}
    </div>
  );
}

const DAY = 864e5;
const baseLabel = (label: string) => label.split(' · ')[0];

/** Individual answers: CAICO and DPO review, correct and remove; Futran auditors read and export. */
function Individuals({ clientId, rows, departments, canManage, onMsg }: { clientId: string; rows: Answer[]; departments: { id: string; name: string }[]; canManage: boolean; onMsg: (m: { tone: 'success' | 'danger'; text: string }) => void }) {
  const qc = useQueryClient();
  const [viewing, setViewing] = useState<Answer | null>(null);
  const [editing, setEditing] = useState<Answer | null>(null);
  const [removing, setRemoving] = useState<Answer[] | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ['attestation', clientId] });
  async function review(list: Answer[]) {
    const r = await api.post<{ reviewed: number }>(`/clients/${clientId}/attestation/answers/review`, { ids: list.map((a) => a.id) });
    onMsg({ tone: 'success', text: `${r.reviewed} ${r.reviewed === 1 ? 'answer' : 'answers'} marked as reviewed.` });
    await refresh();
  }
  async function exportCsv(list: Answer[]) {
    const blob = await api.post<Blob>(`/clients/${clientId}/attestation/answers/export`, { ids: list.map((a) => a.id) });
    download(blob, 'attestation_answers.csv');
  }
  const toolNames = Array.from(new Set(rows.flatMap((r) => r.tools.map(baseLabel)))).sort();
  const columns: GridColumn<Answer>[] = [
    { key: 'name', header: 'Name', value: (a) => a.name, render: (a) => <><strong>{a.name}</strong>{a.source === 'in_app' && <div className="small muted">In the app</div>}</> },
    { key: 'email', header: 'Email', value: (a) => a.email ?? '', render: (a) => <span className="small attest-email">{a.email ?? '—'}</span> },
    { key: 'department', header: 'Department', value: (a) => a.department ?? '' },
    { key: 'tools', header: 'Tools and agents', value: (a) => a.tools.join(', '), render: (a) => a.uses_ai ? <span className="small">{a.tool_items.map((x, i) => <span key={i}>{i > 0 && ', '}{baseLabel(x.label)}{x.kind === 'agent' && <> <Badge tone="muted">Agent</Badge></>}</span>)}</span> : <span className="small muted">Does not use AI for work</span> },
    { key: 'accounts', header: 'Account types', value: (a) => a.account_types.join(', '), render: (a) => <span className="small">{a.account_types.join(', ') || '—'}</span> },
    { key: 'purposes', header: 'Purposes', value: (a) => a.purposes.join(', '), render: (a) => <span className="small">{a.purposes.join(', ') || '—'}</span> },
    { key: 'data', header: 'Data', value: (a) => a.data_entered.join(', '), render: (a) => <span className="small">{a.data_entered.join(', ') || '—'}</span> },
    { key: 'policy', header: 'Policy read', value: (a) => (a.policy_acknowledged ? 'Yes' : 'No'), render: (a) => <span className="small">{a.policy_acknowledged ? 'Yes' : 'No'}</span> },
    { key: 'submitted', header: 'Submitted', value: (a) => a.submitted_at, render: (a) => <span className="small" title={fmtDateTime(a.submitted_at)}>{fmtDate(a.submitted_at)}</span> },
    { key: 'status', header: 'Status', value: (a) => a.status, render: (a) => (
      <div className="stack-sm">
        {a.status === 'reviewed' ? <Badge tone="success">Reviewed</Badge> : <Badge tone="warn">New</Badge>}
        {a.edited_at && <span className="small muted">Edited by {a.edited_by ?? 'a reviewer'} on {fmtDate(a.edited_at)}</span>}
      </div>
    ) },
  ];
  const filters: GridFilter<Answer>[] = [
    { key: 'department', label: 'Department', options: departments.map((d) => ({ value: d.id, label: d.name })), test: (a, v) => a.department_id === v },
    { key: 'tool', label: 'Tool or agent', options: toolNames.map((n) => ({ value: n, label: n })), test: (a, v) => a.tools.some((x) => baseLabel(x) === v) },
    { key: 'submitted', label: 'Submitted', options: [{ value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: 'older', label: 'More than 30 days ago' }],
      test: (a, v) => { const age = Date.now() - new Date(a.submitted_at).getTime(); return v === 'older' ? age > 30 * DAY : age <= Number(v) * DAY; } },
    { key: 'personal', label: 'Personal accounts', options: [{ value: 'yes', label: 'Has personal accounts' }, { value: 'no', label: 'No personal accounts' }], test: (a, v) => a.personal_account === (v === 'yes') },
  ];
  return (
    <Card title={`Individual answers · ${rows.length}`} className="attest-answers">
      <p className="small muted" style={{ marginTop: 0 }}>Select rows for bulk actions. Use the ⋯ button, or right-click a row, for one answer. Corrections never change the tools, purposes or data a person ticked, and every change is kept in the audit log.</p>
      <DataGrid<Answer> label="Individual answers" rows={rows} rowId={(a) => a.id} rowLabel={(a) => a.name} selectable columns={columns} filters={filters}
        search={{ label: 'Search', placeholder: 'Name or email', text: (a) => `${a.name} ${a.email ?? ''}` }} initialSort={{ key: 'submitted', dir: 'desc' }} emptyText="No answers yet."
        bulkActions={[
          ...(canManage ? [{ label: 'Mark reviewed', run: review, available: (l: Answer[]) => l.some((a) => a.status !== 'reviewed') }] : []),
          { label: 'Export CSV', run: exportCsv },
          ...(canManage ? [{ label: 'Remove', danger: true, run: (l: Answer[]) => setRemoving(l) }] : []),
        ]}
        rowActions={(a) => [
          { label: 'View full answer', onSelect: () => setViewing(a) },
          ...(canManage ? [
            { label: 'Edit', onSelect: () => setEditing(a) },
            { label: 'Mark reviewed', onSelect: () => { void review([a]).catch((e) => onMsg({ tone: 'danger', text: errorMessage(e) })); }, disabled: a.status === 'reviewed' },
            { label: 'Remove', danger: true, onSelect: () => setRemoving([a]) },
          ] : []),
        ]} />
      {viewing && <ViewAnswer a={viewing} onClose={() => setViewing(null)} />}
      {editing && <EditAnswer clientId={clientId} a={editing} departments={departments} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); onMsg({ tone: 'success', text: 'Answer corrected. The change is in the audit log.' }); await refresh(); }} />}
      {removing && <RemoveAnswers clientId={clientId} rows={removing} onClose={() => setRemoving(null)} onDone={async (n) => { setRemoving(null); onMsg({ tone: 'success', text: `${n} ${n === 1 ? 'answer' : 'answers'} removed. They no longer count in the totals.` }); await refresh(); }} />}
    </Card>
  );
}

function ViewAnswer({ a, onClose }: { a: Answer; onClose: () => void }) {
  const row = (k: string, v: React.ReactNode) => <tr><th scope="row" style={{ width: '34%' }}>{k}</th><td>{v}</td></tr>;
  return (
    <Dialog title={`Answer from ${a.name}`} onClose={onClose} wide>
      <table className="table"><tbody>
        {row('Name', a.name)}
        {row('Email', a.email ?? 'Not given')}
        {row('Department', a.department ?? '—')}
        {row('Uses AI for work', a.uses_ai ? 'Yes' : 'No')}
        {row('Tools and agents', a.tool_items.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{a.tool_items.map((x, i) => <li key={i}>{x.label}{x.kind === 'agent' ? ' (agent)' : ''}</li>)}</ul> : '—')}
        {row('Purposes', a.purposes.join(', ') || '—')}
        {row('Information entered', a.data_entered.join(', ') || '—')}
        {row('AI use policy', a.policy_acknowledged ? 'Acknowledged' : 'Not acknowledged')}
        {row('Submitted', `${fmtDateTime(a.submitted_at)} · ${a.source === 'in_app' ? 'in the app' : 'through the staff link'}`)}
        {row('Status', a.status === 'reviewed' ? `Reviewed by ${a.reviewed_by ?? 'a reviewer'} on ${fmtDate(a.reviewed_at)}` : 'Not reviewed yet')}
        {a.edited_at && row('Corrected', `Edited by ${a.edited_by ?? 'a reviewer'} on ${fmtDate(a.edited_at)}`)}
        {row('Reviewer note', a.reviewer_note ?? '—')}
      </tbody></table>
    </Dialog>
  );
}

function EditAnswer({ clientId, a, departments, onClose, onSaved }: { clientId: string; a: Answer; departments: { id: string; name: string }[]; onClose: () => void; onSaved: () => void }) {
  const [dept, setDept] = useState(a.department_id);
  const [name, setName] = useState(a.name);
  const [other, setOther] = useState(a.purpose_other ?? '');
  const [names, setNames] = useState<Record<string, string>>(Object.fromEntries(a.tool_items.map((x, i) => [String(i), x.name ?? ''])));
  const [note, setNote] = useState(a.reviewer_note ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const hasOther = a.purpose_other !== null || a.purposes.some((p) => p.startsWith('Something else'));
  async function save() {
    setErr(null); setFe({});
    const body: Record<string, unknown> = { department_id: dept, respondent_name: name, reviewer_note: note };
    if (hasOther) body.purpose_other = other;
    const named = a.tool_items.map((x, i) => [String(i), x] as const).filter(([, x]) => x.has_name);
    if (named.length) body.tool_names = Object.fromEntries(named.map(([i]) => [i, names[i] ?? '']));
    try { await api.patch(`/clients/${clientId}/attestation/answers/${a.id}`, body); onSaved(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={`Correct the answer from ${a.name}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Department" help={AH.department} value={dept} onChange={(e) => setDept(e.target.value)} options={departments.map((d) => ({ value: d.id, label: d.name }))} error={fe.department_id} />
        <TextField label="Name" help={AH.name} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} error={fe.respondent_name} />
        {hasOther && <TextField label="What else (under Something else)" help={AH.purposeOther} value={other} onChange={(e) => setOther(e.target.value)} maxLength={200} error={fe.purpose_other} />}
        {a.tool_items.map((x, i) => x.has_name ? <TextField key={i} label={`Name typed for ${baseLabel(x.label)}`} help={AH.toolName} value={names[String(i)] ?? ''} onChange={(e) => setNames({ ...names, [String(i)]: e.target.value })} maxLength={80} error={fe.tool_names} /> : null)}
        <TextArea label="Reviewer note" help={AH.reviewerNote} value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000} />
        <p className="small muted" style={{ margin: 0 }}>The tools, purposes and data the person ticked are not changed here.</p>
        <div className="row"><Button variant="primary" onClick={save}>Save correction</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function RemoveAnswers({ clientId, rows, onClose, onDone }: { clientId: string; rows: Answer[]; onClose: () => void; onDone: (n: number) => void }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setErr(null);
    try { const r = await api.post<{ removed: number }>(`/clients/${clientId}/attestation/answers/remove`, { ids: rows.map((a) => a.id), reason }); onDone(r.removed); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={rows.length === 1 ? `Remove the answer from ${rows[0].name}` : `Remove ${rows.length} answers`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p style={{ margin: 0 }}>Use this for duplicates and test answers. Removed answers stop counting in totals and in the AI inventory; they stay in the audit log.</p>
        <TextArea label="Reason" help={AH.removeReason} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={300} required />
        <div className="row"><Button variant="danger" onClick={go} disabled={!reason.trim()}>Remove</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
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
        <p className="small muted" style={{ margin: 0 }}>You get one link to send to all staff in the departments below. Nobody needs an account. Once it is running you can also send it to everyone with a login, so it appears on their AI attestation page. Send the employee data notice from the Getting started page first.</p>
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
