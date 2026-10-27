import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { NavLink, useParams } from 'react-router-dom';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, FieldHelp, Loading, PageHeader, SelectField, TextField, WithHelp, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { DownloadIcon } from '@/components/DownloadLinks';
import { DocReader } from '@/components/DocReader';
import { peopleHelp as H } from '@/help/client';
import '@/styles/client-people.css';

type Role = { id: string; role: string; role_label: string; department: string | null; sign_off_role: boolean };
type NoticeStatus = { status: 'acknowledged' | 'pending' | 'not_sent' | 'not_required'; at: string | null; version: number | null };
type Person = { id: string; name: string; email: string; job_title: string | null; status: string; invite_status: string; roles: Role[]; department: string | null; signed_in: boolean; notice: NoticeStatus };
type Dept = { id: string; name: string; headcount: number | null; head_name: string | null; head_email: string | null; in_scope: boolean; lead: string | null; people: number };
type Holder = { user: { id: string; name: string } | null; not_appointed: boolean };
type People = {
  client: { id: string; name: string }; can_manage: boolean; departments: Dept[]; users: Person[]; role_holders: Record<string, Holder>;
  gate: { stage: number; ready: boolean; unmet: string[] } | null; departments_confirmed: boolean; scope_locked: boolean; is_caico: boolean;
  notice: { version: number; sent_at: string } | null;
};
type CsvError = { row: number | null; field: string; message: string };
type Preview = { rows_ok: Record<string, string | null>[]; errors: CsvError[] };
type Msg = { tone: 'success' | 'danger' | 'warn'; text: string } | null;

const ROLES = [
  { value: 'dept_compliance_lead', label: 'Department Compliance Lead' },
  { value: 'contributor', label: 'Contributor' },
  { value: 'exec_sponsor', label: 'Executive Sponsor' },
  { value: 'dpo', label: 'Data Protection Officer' },
  { value: 'client_admin', label: 'Client Admin' },
  { value: 'caico', label: 'Chief AI Compliance Officer' },
];
const DEPT_ROLES = new Set(['dept_compliance_lead', 'contributor']);
const NONE = '__none';

/** Turn a failed request into the message to show: the field's own message when there is one. */
function failure(ex: unknown, field?: string): Error {
  const fe = fieldErrors(ex);
  return new Error((field && fe[field]) || Object.values(fe)[0] || errorMessage(ex));
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** People: departments and users, as two tabs (getting-started items 4 and 5). */
export function UsersDepartments({ tab }: { tab: 'departments' | 'users' }) {
  const { data: me } = useMe();
  const { clientId } = useParams();
  const cid = clientId ?? me?.organization.id ?? '';
  const base = clientId ? `/clients/${clientId}/people` : '/people';
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['people', cid], queryFn: () => api.get<People>(`/clients/${cid}/people`), enabled: !!cid });
  const [msg, setMsg] = useState<Msg>(null);
  const [upload, setUpload] = useState<{ kind: 'users' | 'departments'; text: string; preview: Preview } | null>(null);
  const refresh = () => qc.invalidateQueries();

  if (q.isLoading || !q.data) return <div className="page">{q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />}</div>;
  const p = q.data;

  async function pick(kind: 'users' | 'departments', file?: File) {
    if (!file) return;
    setMsg(null);
    const text = await file.text();
    try {
      const preview = await api.post<Preview>(`/clients/${cid}/${kind}/import/preview`, { csv_text: text });
      setUpload({ kind, text, preview });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function runImport() {
    if (!upload) return;
    try {
      const r = await api.post<{ imported: number; errors: CsvError[] }>(`/clients/${cid}/${upload.kind}/import`, { csv_text: upload.text });
      const bad = new Set(r.errors.map((x) => x.row)).size;
      setMsg({ tone: r.errors.length ? 'warn' : 'success', text: `Imported ${plural(r.imported, upload.kind === 'users' ? 'user' : 'department')}.${r.errors.length ? ` ${bad === 1 ? '1 row was' : `${bad} rows were`} not imported; fix and upload again.` : ''}${upload.kind === 'users' && r.imported ? ' Invitations have been sent.' : ''}` });
      setUpload(null);
      await refresh();
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }

  const shared = { p, cid, setMsg, refresh, pick };
  return (
    <div className="page">
      <PageHeader title="People" subtitle="Departments in scope and the people who need a login. All other staff take part later through the attestation link." />
      <nav className="subnav" aria-label="People sections">
        <NavLink to={`${base}/departments`}>Departments · {p.departments.length}</NavLink>
        <NavLink to={`${base}/users`}>Users · {p.users.filter((u) => u.status !== 'disabled').length}</NavLink>
      </nav>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {p.gate && p.gate.stage === 2 && !p.gate.ready && <Alert tone="info"><strong>To finish setup:</strong> {p.gate.unmet.join(' ')}</Alert>}
      {upload && upload.kind === (tab === 'users' ? 'users' : 'departments') && (
        <Card title={`${upload.kind === 'users' ? 'User' : 'Department'} CSV: ${upload.preview.rows_ok.length} rows ready${upload.preview.errors.length ? `, ${new Set(upload.preview.errors.map((e) => e.row)).size} need fixing before import` : ''}`}
          actions={<><Button variant="primary" onClick={runImport} disabled={!upload.preview.rows_ok.length}>Import {upload.preview.rows_ok.length} ready rows</Button><Button onClick={() => setUpload(null)}>Cancel</Button></>}>
          {upload.preview.errors.length === 0 ? <p className="small">Every row is ready.</p> : (
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {upload.preview.errors.map((e, i) => <li key={i}>{e.row ? `Row ${e.row}: ` : ''}{e.message}</li>)}
            </ul>
          )}
        </Card>
      )}
      {tab === 'departments' ? <DepartmentsTab {...shared} /> : <UsersTab {...shared} meId={me?.user.id ?? ''} isClient={!clientId} />}
    </div>
  );
}

type TabProps = { p: People; cid: string; setMsg: (m: Msg) => void; refresh: () => Promise<unknown>; pick: (kind: 'users' | 'departments', f?: File) => Promise<void> };

function CsvButtons({ kind, pick, templateHref }: { kind: 'users' | 'departments'; pick: TabProps['pick']; templateHref: string }) {
  const file = useRef<HTMLInputElement>(null);
  const noun = kind === 'users' ? 'user' : 'department';
  return (
    <>
      <a className="btn" href={templateHref} download><DownloadIcon />Download template</a>
      <Button onClick={() => file.current?.click()}>Upload {noun} CSV</Button>
      <input ref={file} type="file" accept=".csv,text/csv" hidden aria-label={kind === 'users' ? 'User list CSV' : 'Department list CSV'}
        onChange={(e) => { void pick(kind, e.target.files?.[0]); e.target.value = ''; }} />
    </>
  );
}

// ---------------------------------------------------------------- Departments
function DepartmentsTab({ p, cid, setMsg, refresh, pick }: TabProps) {
  const [newDept, setNewDept] = useState('');
  const [editing, setEditing] = useState<Dept | null>(null);
  const [deleting, setDeleting] = useState<Dept | null>(null);
  const manage = p.can_manage;
  const locked = p.scope_locked;

  async function addDept(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    try { await api.post(`/clients/${cid}/departments`, { name: newDept }); setNewDept(''); await refresh(); } catch (ex) { setMsg({ tone: 'danger', text: errorMessage(ex) }); }
  }
  async function confirm() {
    try { await api.post(`/clients/${cid}/departments/confirm`); setMsg({ tone: 'success', text: 'Department list confirmed. Futran has been notified.' }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function patch(d: Dept, body: Record<string, unknown>, field?: string) {
    try { await api.patch(`/clients/${cid}/departments/${d.id}`, body); await refresh(); } catch (ex) { throw failure(ex, field); }
  }
  async function setScope(list: Dept[], in_scope: boolean) {
    const todo = list.filter((d) => d.in_scope !== in_scope);
    const failed: string[] = [];
    for (const d of todo) {
      try { await api.patch(`/clients/${cid}/departments/${d.id}`, { in_scope }); } catch (ex) { failed.push(`${d.name}: ${errorMessage(ex)}`); }
    }
    await refresh();
    const done = todo.length - failed.length;
    setMsg(failed.length ? { tone: 'danger', text: `${done ? `${plural(done, 'department')} ${in_scope ? 'included' : 'excluded'}. ` : ''}${failed.join(' ')}` }
      : { tone: 'success', text: `${plural(done, 'department')} ${in_scope ? 'included in' : 'excluded from'} scope. Confirm the list again when you have finished.` });
  }
  async function remove(list: Dept[]) {
    const failed: string[] = [];
    for (const d of list) {
      try { await api.delete(`/clients/${cid}/departments/${d.id}`); } catch (ex) { failed.push(errorMessage(ex)); }
    }
    await refresh();
    const done = list.length - failed.length;
    setMsg(failed.length ? { tone: 'danger', text: `${done ? `${plural(done, 'department')} deleted. ` : ''}${failed.join(' ')}` } : { tone: 'success', text: `${plural(done, 'department')} deleted.` });
  }

  const columns: GridColumn<Dept>[] = [
    { key: 'name', header: 'Department', value: (d) => d.name, render: (d) => <strong style={{ opacity: d.in_scope ? 1 : 0.6 }}>{d.name}</strong>,
      edit: manage ? { label: (d) => `Department name for ${d.name}`, onSave: (d, v) => patch(d, { name: v }, 'name') } : undefined },
    { key: 'head', header: 'Head of department', value: (d) => d.head_name ?? '', render: (d) => d.head_name || <span className="muted">Not given</span>,
      edit: manage ? { label: (d) => `Head of ${d.name}`, onSave: (d, v) => patch(d, { head_name: v }, 'head_name') } : undefined },
    { key: 'headcount', header: 'Headcount', value: (d) => d.headcount, render: (d) => d.headcount ?? '—',
      edit: manage ? { type: 'number', label: (d) => `Headcount for ${d.name}`, onSave: (d, v) => patch(d, { headcount: v }, 'headcount') } : undefined },
    { key: 'people', header: 'Users', value: (d) => d.people },
    { key: 'lead', header: 'Compliance lead', value: (d) => d.lead ?? '', render: (d) => (!d.in_scope ? <span className="muted">—</span> : d.lead ? d.lead : <Badge tone="warn">No lead yet</Badge>) },
    { key: 'scope', header: 'Scope', value: (d) => (d.in_scope ? 'In scope' : 'Out of scope'), render: (d) => (d.in_scope ? <Badge tone="success">In scope</Badge> : <Badge tone="muted">Out of scope</Badge>) },
  ];
  const rowActions = manage ? (d: Dept): GridRowAction[] => [
    { label: 'Edit', onSelect: () => setEditing(d) },
    ...(locked ? [] : [d.in_scope ? { label: 'Exclude from scope', onSelect: () => void setScope([d], false) } : { label: 'Include in scope', onSelect: () => void setScope([d], true) }]),
    ...(locked ? [] : [{ label: 'Delete', danger: true, onSelect: () => setDeleting(d) }]),
  ] : undefined;

  return (
    <>
      {manage && (
        <div className="people-actions">
          <CsvButtons kind="departments" pick={pick} templateHref={`/api/v1/clients/${cid}/departments/template.csv`} />
        </div>
      )}
      <Card title={<h2><WithHelp help={H.departments}>Departments</WithHelp></h2>}
        actions={p.departments_confirmed ? <Badge tone="success">List confirmed</Badge> : p.departments.length ? <Badge tone="warn">Not confirmed yet</Badge> : undefined}>
        <div className="stack">
          {locked && <p className="small muted" style={{ margin: 0 }}>Setup has finished, so departments can no longer be added to or taken out of scope. You can still correct names, heads and headcounts.</p>}
          {manage && !locked && (
            <form className="inline-add" onSubmit={addDept}>
              <input className="input" aria-label="New department" placeholder="Department name" value={newDept} onChange={(e) => setNewDept(e.target.value)} />
              <FieldHelp label="New department">{H.newDepartment}</FieldHelp>
              <Button type="submit">Add</Button>
            </form>
          )}
          <DataGrid label="Departments" rows={p.departments} rowId={(d) => d.id} rowLabel={(d) => d.name} columns={columns}
            selectable={manage && !locked}
            bulkActions={[
              { label: 'Include in scope', run: (rows) => setScope(rows, true) },
              { label: 'Exclude from scope', run: (rows) => setScope(rows, false) },
              { label: 'Delete', danger: true, confirm: (rows) => `Delete ${rows.length === 1 ? rows[0].name : `these ${rows.length} departments`}? A department that still has people in it is kept; move or remove the people first.`, run: remove },
            ]}
            rowActions={rowActions}
            filters={[
              { key: 'scope', label: 'Scope', options: [{ value: 'in', label: 'In scope' }, { value: 'out', label: 'Out of scope' }], test: (d, v) => (v === 'in') === d.in_scope },
              { key: 'lead', label: 'Compliance lead', options: [{ value: 'yes', label: 'Has a lead' }, { value: 'no', label: 'No lead yet' }], test: (d, v) => (v === 'yes') === !!d.lead },
            ]}
            search={{ label: 'Search departments', text: (d) => `${d.name} ${d.head_name ?? ''}` }}
            initialSort={{ key: 'name', dir: 'asc' }}
            rowClassName={(d) => (d.in_scope ? undefined : 'dg-muted')}
            emptyText="No departments yet. Download the template (pre-filled from the scope), or add them above." />
          {manage && (
            <div className="row">
              <Button variant={p.departments_confirmed ? 'default' : 'primary'} onClick={confirm} disabled={!p.departments.length}>Confirm the department list</Button>
              <span className="small muted">Confirming tells Futran the list is right. Any later change during setup needs confirming again.</span>
            </div>
          )}
        </div>
      </Card>
      {editing && <EditDept cid={cid} d={editing} onClose={() => setEditing(null)} onDone={async () => { setEditing(null); await refresh(); }} />}
      {deleting && (
        <Dialog title="Delete department" onClose={() => setDeleting(null)}>
          <div className="stack">
            <p>Delete {deleting.name}? This is recorded in the audit log. If anyone is still in the department, it is kept and you are told who.</p>
            <div className="row"><Button variant="danger" onClick={async () => { const d = deleting; setDeleting(null); await remove([d]); }}>Delete</Button><Button onClick={() => setDeleting(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </>
  );
}

function EditDept({ cid, d, onClose, onDone }: { cid: string; d: Dept; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ name: d.name, head_name: d.head_name ?? '', head_email: d.head_email ?? '', headcount: d.headcount?.toString() ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null); setFe({});
    try { await api.patch(`/clients/${cid}/departments/${d.id}`, f); onDone(); } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title={`Edit ${d.name}`} onClose={onClose}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Department name" help={H.departmentName} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={fe.name} />
        <div className="grid-2">
          <TextField label="Head of department" help={H.headName} value={f.head_name} onChange={(e) => setF({ ...f, head_name: e.target.value })} error={fe.head_name} />
          <TextField label="Head's email" help={H.headEmail} type="email" value={f.head_email} onChange={(e) => setF({ ...f, head_email: e.target.value })} error={fe.head_email} />
        </div>
        <TextField label="Headcount" help={H.headcount} inputMode="numeric" value={f.headcount} onChange={(e) => setF({ ...f, headcount: e.target.value })} error={fe.headcount} />
        <div className="row"><Button type="submit" variant="primary">Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Users
const NOTICE_LABEL: Record<string, string> = { acknowledged: 'Acknowledged', pending: 'Pending', not_sent: 'Not sent yet', not_required: '—' };

function inviteBadge(u: Person): ReactNode {
  if (u.invite_status === 'Active') return <Badge tone="success">Active</Badge>;
  if (u.invite_status === 'Disabled') return <Badge tone="muted">Deactivated</Badge>;
  if (u.invite_status === 'Invitation expired') return <Badge tone="danger">Invitation expired</Badge>;
  return <span className="small">{u.invite_status}</span>;
}

function UsersTab({ p, cid, setMsg, refresh, pick, meId, isClient }: TabProps & { meId: string; isClient: boolean }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [rolesFor, setRolesFor] = useState<Person | null>(null);
  const [moving, setMoving] = useState<Person[] | null>(null);
  const [removing, setRemoving] = useState<Person[] | null>(null);
  const manage = p.can_manage;
  const inScope = p.departments.filter((d) => d.in_scope);
  const deptOptions = p.departments.map((d) => ({ value: d.name, label: d.name }));
  const roleOptions = ROLES.filter((r) => p.users.some((u) => u.roles.some((x) => x.role === r.value)));
  const inviteOptions = [...new Set(p.users.map((u) => u.invite_status))].sort().map((s) => ({ value: s, label: s === 'Disabled' ? 'Deactivated' : s }));
  const canResend = (u: Person) => !u.signed_in && u.status !== 'disabled';
  const initiation = useQuery({ queryKey: ['my-initiation'], queryFn: () => api.get<{ items: { key: string; document: { id: string } | null }[] }>('/me/initiation'), enabled: isClient, retry: false });
  const rolesNote = initiation.data?.items.find((i) => i.key === 'nominate')?.document ?? null;

  async function patch(u: Person, body: Record<string, unknown>, field?: string) {
    try { await api.patch(`/clients/${cid}/users/${u.id}`, body); await refresh(); } catch (ex) { throw failure(ex, field); }
  }
  async function resend(list: Person[]) {
    const failed: string[] = [];
    for (const u of list) { try { await api.post(`/invitations/${u.id}/resend`); } catch (ex) { failed.push(`${u.name}: ${errorMessage(ex)}`); } }
    await refresh();
    const done = list.length - failed.length;
    setMsg(failed.length ? { tone: 'danger', text: `${done ? `Invitation sent again to ${plural(done, 'person', 'people')}. ` : ''}${failed.join(' ')}` } : { tone: 'success', text: `Invitation sent again to ${list.length === 1 ? list[0].name : plural(done, 'person', 'people')}.` });
  }
  async function moveTo(list: Person[], department: string) {
    const failed: string[] = [];
    for (const u of list) { try { await api.patch(`/clients/${cid}/users/${u.id}`, { department }); } catch (ex) { failed.push(`${u.name}: ${failure(ex, 'department').message}`); } }
    await refresh();
    const done = list.length - failed.length;
    setMsg(failed.length ? { tone: 'danger', text: `${done ? `${plural(done, 'person', 'people')} moved to ${department}. ` : ''}${failed.join(' ')}` } : { tone: 'success', text: `${plural(done, 'person', 'people')} moved to ${department}.` });
  }
  async function remove(list: Person[]) {
    const failed: string[] = [];
    let removed = 0, deactivated = 0;
    for (const u of list) {
      try { const r = await api.delete<{ result: string }>(`/clients/${cid}/users/${u.id}`); if (r.result === 'removed') removed++; else deactivated++; } catch (ex) { failed.push(`${u.name}: ${errorMessage(ex)}`); }
    }
    await refresh();
    const parts = [removed && `${plural(removed, 'person', 'people')} removed.`, deactivated && `${plural(deactivated, 'person', 'people')} deactivated; they have signed or recorded work in this audit, so their name stays on it.`, ...failed].filter(Boolean);
    setMsg({ tone: failed.length ? 'danger' : 'success', text: parts.join(' ') });
  }

  const columns: GridColumn<Person>[] = [
    { key: 'name', header: 'Name', value: (u) => u.name, render: (u) => <strong>{u.name}</strong>,
      edit: manage ? { label: (u) => `Name of ${u.name}`, onSave: (u, v) => patch(u, { name: v }, 'name') } : undefined },
    { key: 'email', header: 'Email', value: (u) => u.email, render: (u) => <span className="small">{u.email}</span>,
      edit: manage ? { label: (u) => `Email of ${u.name}`, canEdit: (u) => !u.signed_in, onSave: (u, v) => patch(u, { email: v }, 'email') } : undefined },
    { key: 'job_title', header: 'Job title', value: (u) => u.job_title ?? '', render: (u) => u.job_title || <span className="muted">—</span>,
      edit: manage ? { label: (u) => `Job title of ${u.name}`, onSave: (u, v) => patch(u, { job_title: v }, 'job_title') } : undefined },
    { key: 'department', header: 'Department', value: (u) => u.department ?? '', render: (u) => u.department ?? <span className="muted">—</span>,
      edit: manage ? { type: 'select', label: (u) => `Department of ${u.name}`, options: (u) => [...(u.roles.some((r) => DEPT_ROLES.has(r.role)) ? [] : [{ value: '', label: 'No department' }]), ...deptOptions], onSave: (u, v) => patch(u, { department: v }, 'department') } : undefined },
    { key: 'roles', header: 'Roles', value: (u) => u.roles.map((r) => r.role_label).join(', '),
      render: (u) => <div className="stack-sm" style={{ gap: 2 }}>{u.roles.map((r) => <span key={r.id} className="small">{r.role_label}{r.sign_off_role && <span className="muted"> · sign-off</span>}</span>)}</div> },
    { key: 'invite', header: 'Invitation', value: (u) => u.invite_status, render: inviteBadge },
  ];
  if (p.notice) {
    columns.push({ key: 'notice', header: 'Data notice', value: (u) => (u.notice.status === 'acknowledged' ? `Acknowledged ${u.notice.at}` : NOTICE_LABEL[u.notice.status]),
      render: (u) => (u.notice.status === 'acknowledged' ? <Badge tone="success">Acknowledged {fmtDate(u.notice.at)}</Badge> : u.notice.status === 'pending' ? <Badge tone="warn">Pending</Badge> : <span className="muted">{NOTICE_LABEL[u.notice.status]}</span>) });
  }
  const rowActions = manage ? (u: Person): GridRowAction[] => [
    { label: 'Edit', onSelect: () => setEditing(u) },
    ...(canResend(u) ? [{ label: 'Resend invitation', onSelect: () => void resend([u]) }] : []),
    { label: 'Change role', onSelect: () => setRolesFor(u) },
    ...(u.status === 'disabled' ? [] : [{ label: u.id === meId ? 'Remove (not yourself)' : 'Remove', danger: true, disabled: u.id === meId, onSelect: () => setRemoving([u]) }]),
  ] : undefined;
  const filters = [
    { key: 'department', label: 'Department', options: [...deptOptions, { value: NONE, label: 'No department' }], test: (u: Person, v: string) => (v === NONE ? !u.department : u.department === v) },
    { key: 'role', label: 'Role', options: roleOptions, test: (u: Person, v: string) => u.roles.some((r) => r.role === v) },
    { key: 'invite', label: 'Invitation', options: inviteOptions, test: (u: Person, v: string) => u.invite_status === v },
    ...(p.notice ? [{ key: 'notice', label: 'Data notice', options: [{ value: 'acknowledged', label: 'Acknowledged' }, { value: 'pending', label: 'Pending' }], test: (u: Person, v: string) => u.notice.status === v }] : []),
  ];

  return (
    <>
      {manage && (
        <div className="people-actions">
          <CsvButtons kind="users" pick={pick} templateHref={`/api/v1/clients/${cid}/users/template.csv`} />
          <Button variant="primary" onClick={() => setAdding(true)}>Add user</Button>
        </div>
      )}
      <Card title={<h2><WithHelp help={H.signOffRoles}>Sign-off roles</WithHelp></h2>}>
        <div className="stack">
          <div className="grid-3 small">
            {(['caico', 'exec_sponsor', 'dpo'] as const).map((r) => {
              const h = p.role_holders[r];
              const label = ROLES.find((x) => x.value === r)!.label;
              return (
                <div key={r}>
                  <strong>{label}</strong>
                  <div>{h.user ? h.user.name : h.not_appointed ? 'Not appointed: the Chief AI Compliance Officer covers this role' : 'Not named yet'}</div>
                  {r !== 'caico' && !h.user && manage && <Checkbox label="Not appointed" help={H.notAppointed} checked={h.not_appointed} onChange={async (e) => { await api.put(`/clients/${cid}/role-holders/${r}`, { not_appointed: e.target.checked }); await refresh(); }} />}
                </div>
              );
            })}
          </div>
          <p className="small muted" style={{ margin: 0 }}>To name someone, add them as a user with that role, or use Change role on their row. Each in-scope department also needs a Department Compliance Lead. Assigning or removing a sign-off role notifies Futran and is recorded in the audit log.</p>
          {rolesNote && (
            <details className="roles-note">
              <summary>What each role does <FieldHelp label="What each role does">{H.rolesNote}</FieldHelp></summary>
              <DocReader docId={rolesNote.id} label="Roles note" maxHeight="50vh" />
            </details>
          )}
        </div>
      </Card>
      <Card title={<h2><WithHelp help={H.users} label="Users">Users</WithHelp></h2>}>
        <DataGrid label="Users" rows={p.users} rowId={(u) => u.id} rowLabel={(u) => u.name} columns={columns}
          selectable={manage}
          bulkActions={[
            { label: 'Resend invitation', available: (rows) => rows.every(canResend), run: resend },
            { label: 'Change department', run: async (rows) => setMoving(rows) },
            { label: 'Remove', danger: true, available: (rows) => rows.every((u) => u.id !== meId && u.status !== 'disabled'), run: async (rows) => setRemoving(rows) },
          ]}
          rowActions={rowActions}
          filters={filters}
          search={{ label: 'Search by name or email', placeholder: 'Name or email', text: (u) => `${u.name} ${u.email}` }}
          initialSort={{ key: 'name', dir: 'asc' }}
          rowClassName={(u) => (u.status === 'disabled' ? 'dg-muted' : undefined)}
          emptyText="No users yet. Upload the user CSV or add people one at a time." />
      </Card>
      {adding && <AddUser cid={cid} departments={inScope} onClose={() => setAdding(false)} onDone={async (name) => { setAdding(false); setMsg({ tone: 'success', text: `${name} was added and invited.` }); await refresh(); }} />}
      {editing && <EditUser cid={cid} u={editing} departments={p.departments} onClose={() => setEditing(null)} onDone={async () => { setEditing(null); await refresh(); }} />}
      {rolesFor && <ChangeRoles cid={cid} u={p.users.find((x) => x.id === rolesFor.id) ?? rolesFor} departments={inScope} onClose={() => setRolesFor(null)} refresh={refresh} />}
      {moving && <MoveDialog people={moving} departments={inScope} onClose={() => setMoving(null)} onMove={async (d) => { const list = moving; setMoving(null); await moveTo(list, d); }} />}
      {removing && (
        <Dialog title={removing.length === 1 ? `Remove ${removing[0].name}` : `Remove ${removing.length} people`} onClose={() => setRemoving(null)}>
          <div className="stack">
            <p>{removing.length === 1 ? `${removing[0].name} loses access straight away.` : 'They lose access straight away.'} Anyone who has signed a sign-off or recorded work in this audit is deactivated instead of deleted, so their name stays on what they did. Pending invitations stop working.</p>
            <div className="row"><Button variant="danger" onClick={async () => { const list = removing; setRemoving(null); await remove(list); }}>Remove</Button><Button onClick={() => setRemoving(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </>
  );
}

function MoveDialog({ people, departments, onClose, onMove }: { people: Person[]; departments: Dept[]; onClose: () => void; onMove: (department: string) => void }) {
  const [d, setD] = useState(departments[0]?.name ?? '');
  return (
    <Dialog title="Change department" onClose={onClose}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>{people.length === 1 ? people[0].name : `${people.length} people`}: {people.slice(0, 5).map((u) => u.name).join(', ')}{people.length > 5 ? ' and others' : ''}.</p>
        <SelectField label="Move to" help={H.changeDepartment} value={d} onChange={(e) => setD(e.target.value)} options={departments.map((x) => ({ value: x.name, label: x.name }))} />
        <div className="row"><Button variant="primary" disabled={!d} onClick={() => onMove(d)}>Move</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function EditUser({ cid, u, departments, onClose, onDone }: { cid: string; u: Person; departments: Dept[]; onClose: () => void; onDone: () => void }) {
  const needsDept = u.roles.some((r) => DEPT_ROLES.has(r.role));
  const [f, setF] = useState({ name: u.name, email: u.email, job_title: u.job_title ?? '', department: u.department ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null); setFe({});
    const body: Record<string, string> = { name: f.name, job_title: f.job_title, department: f.department };
    if (!u.signed_in) body.email = f.email;
    try { await api.patch(`/clients/${cid}/users/${u.id}`, body); onDone(); } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title={`Edit ${u.name}`} onClose={onClose}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Full name" help={H.firstName} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={fe.name} />
        <TextField label="Work email" help={H.email} type="email" value={f.email} disabled={u.signed_in} hint={u.signed_in ? 'This person has signed in, so their email stays as it is.' : undefined} onChange={(e) => setF({ ...f, email: e.target.value })} error={fe.email} />
        <TextField label="Job title" help={H.jobTitle} value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} error={fe.job_title} />
        <SelectField label="Department" help={H.department} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} error={fe.department}
          options={[...(needsDept ? [] : [{ value: '', label: 'No department' }]), ...departments.map((d) => ({ value: d.name, label: d.name }))]} />
        <div className="row"><Button type="submit" variant="primary">Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

function ChangeRoles({ cid, u, departments, onClose, refresh }: { cid: string; u: Person; departments: Dept[]; onClose: () => void; refresh: () => Promise<unknown> }) {
  const [role, setRole] = useState('contributor');
  const [dept, setDept] = useState(u.department && departments.some((d) => d.name === u.department) ? u.department : departments[0]?.name ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const needsDept = DEPT_ROLES.has(role);
  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null); setFe({});
    try { await api.post(`/clients/${cid}/users/${u.id}/roles`, { role, department: needsDept ? dept : '' }); await refresh(); } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  async function drop(r: Role) {
    setErr(null);
    try { await api.delete(`/clients/${cid}/users/${u.id}/roles/${r.id}`); await refresh(); } catch (ex) { setErr(errorMessage(ex)); }
  }
  return (
    <Dialog title={`Roles for ${u.name}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {u.roles.length === 0 ? <p className="small muted" style={{ margin: 0 }}>No roles. Add one below so this person can work in the audit.</p> : (
          <ul className="list-rows">
            {u.roles.map((r) => (
              <li key={r.id}>
                <span>{r.role_label}{r.department ? ` · ${r.department}` : ''}{r.sign_off_role && <span className="muted"> · sign-off role</span>}</span>
                <button type="button" className="link-btn small" aria-label={`Remove ${r.role_label} from ${u.name}`} onClick={() => drop(r)}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <form className="stack-sm" onSubmit={add} noValidate>
          <SelectField label="Add a role" help={H.addRole} value={role} onChange={(e) => setRole(e.target.value)} options={ROLES} error={fe.role} />
          {needsDept && <SelectField label="Department" help={H.department} value={dept} onChange={(e) => setDept(e.target.value)} options={departments.map((d) => ({ value: d.name, label: d.name }))} error={fe.department} />}
          <div className="row"><Button type="submit" variant="primary">Add role</Button><Button onClick={onClose}>Done</Button></div>
        </form>
      </div>
    </Dialog>
  );
}

function AddUser({ cid, departments, onClose, onDone }: { cid: string; departments: Dept[]; onClose: () => void; onDone: (name: string) => void }) {
  const [f, setF] = useState({ first_name: '', last_name: '', email: '', job_title: '', role: 'contributor', department: departments[0]?.name ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const needsDept = DEPT_ROLES.has(f.role);
  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null); setFe({});
    try {
      await api.post(`/clients/${cid}/users`, { ...f, department: needsDept ? f.department : '' });
      onDone(`${f.first_name} ${f.last_name}`);
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title="Add user" onClose={onClose}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="First name" help={H.firstName} value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} error={fe.first_name} />
          <TextField label="Last name" help={H.lastName} value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} error={fe.last_name} />
        </div>
        <TextField label="Work email" help={H.email} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} error={fe.email} />
        <TextField label="Job title" help={H.jobTitle} value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} />
        <SelectField label="Role" help={H.role} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={ROLES} />
        {needsDept && <SelectField label="Department" help={H.department} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} options={departments.map((d) => ({ value: d.name, label: d.name }))} error={fe.department} />}
        <div className="row"><Button type="submit" variant="primary">Add and send invitation</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}
