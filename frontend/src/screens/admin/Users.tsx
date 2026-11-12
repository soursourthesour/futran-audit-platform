import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { ROLE_LABELS, can, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, Loading, PageHeader, SelectField, TextField } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import '@/styles/futran-screens.css';

type U = { id: string; name: string; email: string; job_title: string | null; department_id: string | null; department: string | null; status: string; mfa_enabled: boolean; roles: string[]; role_labels: string[] };
type Dept = { id: string; name: string; people: number };
const FUTRAN_ROLES = ['chief_auditor', 'admin', 'auditor', 'qa_reviewer', 'engagement_manager', 'legal_reviewer', 'sales_team', 'sales_manager', 'pricing_approver', 'price_list_owner'];
const STATUS_LABEL: Record<string, string> = { active: 'Active', invited: 'Invited', disabled: 'Disabled' };

function RolePicker({ roles, setRoles, error }: { roles: string[]; setRoles: (r: string[]) => void; error?: string }) {
  return (
    <fieldset>
      <legend>Roles</legend>
      <div className="grid-2">
        {FUTRAN_ROLES.map((r) => (
          <Checkbox key={r} label={ROLE_LABELS[r]} checked={roles.includes(r)} onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))} />
        ))}
      </div>
      {error && <div className="error small">{error}</div>}
    </fieldset>
  );
}

const deptOptions = (depts: Dept[]) => depts.map((d) => ({ value: d.id, label: d.name }));

function AddUser({ depts, onDone }: { depts: Dept[]; onDone: () => void }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');
  const [dept, setDept] = useState('');
  const [roles, setRoles] = useState<string[]>(['auditor']);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const qc = useQueryClient();
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setFe({});
    try {
      await api.post('/admin/users', { name, email, job_title: title || null, department_id: dept || null, roles });
      await qc.invalidateQueries({ queryKey: ['admin-users'] });
      await qc.invalidateQueries({ queryKey: ['futran-departments'] });
      onDone();
    } catch (ex) {
      setErr(errorMessage(ex));
      setFe(fieldErrors(ex));
    }
  }
  return (
    <form onSubmit={submit} className="stack" noValidate>
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="grid-2">
        <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={fe.name} />
        <TextField label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={fe.email} />
        <TextField label="Job title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <SelectField label="Department" value={dept} onChange={(e) => setDept(e.target.value)} options={deptOptions(depts)} placeholder="No department" error={fe.department_id}
          hint={depts.length ? undefined : 'Add Futran departments in the Departments section below.'} />
      </div>
      <RolePicker roles={roles} setRoles={setRoles} error={fe.roles} />
      <p className="small muted">Admins manage users, templates and reference data. They cannot record findings, set risk tiers or approve audit work.</p>
      <div className="row"><Button type="submit" variant="primary">Add and send invitation</Button><Button onClick={onDone}>Cancel</Button></div>
    </form>
  );
}

function EditUser({ user, depts, self, onClose, onSaved }: { user: U; depts: Dept[]; self: boolean; onClose: () => void; onSaved: (m: string) => void }) {
  const [name, setName] = useState(user.name);
  const [title, setTitle] = useState(user.job_title ?? '');
  const [dept, setDept] = useState(user.department_id ?? '');
  const [roles, setRoles] = useState<string[]>(user.roles);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  async function save() {
    setErr(null); setFe({}); setBusy(true);
    try {
      await api.patch(`/admin/users/${user.id}`, { name, job_title: title || null, department_id: dept || null, roles });
      await qc.invalidateQueries({ queryKey: ['admin-users'] });
      await qc.invalidateQueries({ queryKey: ['futran-departments'] });
      onSaved(`Saved ${name}.`);
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={`Edit ${user.name}`} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={fe.name} />
          <TextField label="Job title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <SelectField label="Department" value={dept} onChange={(e) => setDept(e.target.value)} options={deptOptions(depts)} placeholder="No department" error={fe.department_id} />
        </div>
        <RolePicker roles={roles} setRoles={setRoles} error={fe.roles} />
        {self && <p className="small muted">You cannot remove your own Admin role.</p>}
        <div className="row"><Button variant="primary" disabled={busy} onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** Futran's own department list (feedback 10 Nov F1). Only the Futran Admin changes it; every change is in the audit log. */
function Departments({ depts, canManage }: { depts: Dept[]; canManage: boolean }) {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['futran-departments'] }); await qc.invalidateQueries({ queryKey: ['admin-users'] }); };
  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); await refresh(); setMsg({ tone: 'success', text: ok }); return true; } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); return false; }
  }
  return (
    <Card title="Departments">
      <p className="small muted" style={{ marginTop: 0 }}>Futran's own departments. Clients never see them.{canManage ? '' : ' Only a Futran Admin changes this list.'}</p>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {depts.length === 0 ? <p className="small">No departments yet.</p> : (
        <ul className="fx-dept-list" aria-label="Futran departments">
          {depts.map((d) => (
            <li key={d.id}>
              {renaming?.id === d.id ? (
                <form className="fx-dept-row" onSubmit={async (e) => { e.preventDefault(); if (await run(() => api.patch(`/admin/departments/${d.id}`, { name: renaming.name }), `Renamed ${d.name} to ${renaming.name}.`)) setRenaming(null); }}>
                  <TextField label={`New name for ${d.name}`} value={renaming.name} onChange={(e) => setRenaming({ id: d.id, name: e.target.value })} autoFocus />
                  <div className="row"><Button type="submit" size="sm" variant="primary">Save</Button><Button size="sm" onClick={() => setRenaming(null)}>Cancel</Button></div>
                </form>
              ) : (
                <div className="fx-dept-row">
                  <span><strong>{d.name}</strong> <span className="small muted">· {d.people} {d.people === 1 ? 'person' : 'people'}</span></span>
                  {canManage && (
                    <div className="row">
                      <Button size="sm" onClick={() => setRenaming({ id: d.id, name: d.name })} aria-label={`Rename ${d.name}`}>Rename</Button>
                      <Button size="sm" variant="danger" disabled={d.people > 0} title={d.people > 0 ? 'Move its people to another department first' : undefined}
                        onClick={() => run(() => api.delete(`/admin/departments/${d.id}`), `Removed ${d.name}.`)} aria-label={`Remove ${d.name}`}>Remove</Button>
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form className="fx-dept-add" onSubmit={async (e) => { e.preventDefault(); if (await run(() => api.post('/admin/departments', { name }), `Added ${name.trim()}.`)) setName(''); }}>
          <TextField label="New department" value={name} onChange={(e) => setName(e.target.value)} placeholder="For example, Audit delivery" />
          <Button type="submit" disabled={!name.trim()}>Add department</Button>
        </form>
      )}
    </Card>
  );
}

export function UsersAdmin() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<U | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const q = useQuery({ queryKey: ['admin-users'], queryFn: () => api.get<U[]>('/admin/users') });
  const dq = useQuery({ queryKey: ['futran-departments'], queryFn: () => api.get<Dept[]>('/admin/departments') });
  const canManage = can(me, 'manage_futran_users');
  const depts = dq.data ?? [];
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/admin/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e) => setMsg({ tone: 'danger', text: errorMessage(e) }),
  });
  async function resend(u: U) {
    try {
      await api.post(`/invitations/${u.id}/resend`);
      setMsg({ tone: 'success', text: `A new invitation was sent to ${u.email}. The previous link no longer works.` });
    } catch (e) {
      setMsg({ tone: 'danger', text: errorMessage(e) });
    }
  }
  const users = q.data ?? [];
  const roleKeys = FUTRAN_ROLES.filter((r) => users.some((u) => u.roles.includes(r)));
  return (
    <div className="page">
      <PageHeader title="Futran users" subtitle="People at Futran who can sign in, their department and what they can do. Adding a user sends them an invitation to set a password." actions={canManage && !adding ? <Button variant="primary" onClick={() => setAdding(true)}>Add user</Button> : undefined} />
      {!canManage && <p className="small muted">Only a Futran Admin adds users and changes their roles.</p>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {adding && <Card title="Add a Futran user"><AddUser depts={depts} onDone={() => setAdding(false)} /></Card>}
      <section className="card"><div className="card-body">
        {q.isLoading ? <Loading /> : (
          <DataGrid label="Futran users" rows={users} rowId={(u) => u.id} rowLabel={(u) => u.name} initialSort={{ key: 'name', dir: 'asc' }}
            search={{ label: 'Search', placeholder: 'Name or email', text: (u) => `${u.name} ${u.email} ${u.job_title ?? ''}` }}
            filters={[
              { key: 'dept', label: 'Department', options: [...depts.map((d) => ({ value: d.id, label: d.name })), { value: '__none', label: 'No department' }], test: (u, v) => (v === '__none' ? !u.department_id : u.department_id === v) },
              { key: 'role', label: 'Role', options: roleKeys.map((r) => ({ value: r, label: ROLE_LABELS[r] })), test: (u, v) => u.roles.includes(v) },
              { key: 'status', label: 'Status', options: Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label })), test: (u, v) => u.status === v },
            ]}
            columns={[
              { key: 'name', header: 'Name', value: (u) => u.name, render: (u) => <><strong>{u.name}</strong>{u.job_title && <div className="small muted">{u.job_title}</div>}</> },
              { key: 'email', header: 'Email', value: (u) => u.email, render: (u) => <span className="break">{u.email}</span> },
              { key: 'dept', header: 'Department', value: (u) => u.department ?? '', render: (u) => u.department ?? <span className="muted">None</span> },
              { key: 'roles', header: 'Roles', value: (u) => u.role_labels.join(', ') },
              { key: 'status', header: 'Status', value: (u) => STATUS_LABEL[u.status] ?? u.status, render: (u) => u.status === 'active' ? <Badge tone="success">Active</Badge> : u.status === 'invited' ? <Badge tone="warn">Invited</Badge> : <Badge tone="muted">Disabled</Badge> },
              { key: 'mfa', header: 'Sign-in codes', value: (u) => (u.mfa_enabled ? 'On' : 'Not set up') },
            ]}
            rowActions={canManage ? (u) => [
              { label: 'Edit', onSelect: () => setEditing(u) },
              ...(u.status === 'invited' ? [{ label: 'Resend invitation', onSelect: () => resend(u) }] : []),
              ...(u.status === 'active' && u.id !== me?.user.id ? [{ label: 'Disable', danger: true, onSelect: () => patch.mutate({ id: u.id, body: { status: 'disabled' } }) }] : []),
              ...(u.status === 'disabled' ? [{ label: 'Enable', onSelect: () => patch.mutate({ id: u.id, body: { status: 'active' } }) }] : []),
            ] : undefined} />
        )}
      </div></section>
      <Departments depts={depts} canManage={canManage} />
      {editing && <EditUser user={editing} depts={depts} self={editing.id === me?.user.id} onClose={() => setEditing(null)} onSaved={(m) => { setEditing(null); setMsg({ tone: 'success', text: m }); }} />}
    </div>
  );
}
