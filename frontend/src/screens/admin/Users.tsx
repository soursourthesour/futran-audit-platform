import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { ROLE_LABELS, hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Loading, PageHeader, TextField } from '@/components/ui';

type U = { id: string; name: string; email: string; job_title: string | null; status: string; mfa_enabled: boolean; roles: string[]; role_labels: string[] };
const FUTRAN_ROLES = ['chief_auditor', 'admin', 'auditor', 'qa_reviewer', 'engagement_manager', 'legal_reviewer', 'sales_team'];

function AddUser({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');
  const [roles, setRoles] = useState<string[]>(['auditor']);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const qc = useQueryClient();
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setFe({});
    try {
      await api.post('/admin/users', { name, email, job_title: title || null, roles });
      await qc.invalidateQueries({ queryKey: ['admin-users'] });
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
      </div>
      <fieldset>
        <legend>Roles</legend>
        <div className="grid-2">
          {FUTRAN_ROLES.map((r) => (
            <Checkbox key={r} label={ROLE_LABELS[r]} checked={roles.includes(r)} onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))} />
          ))}
        </div>
        {fe.roles && <div className="error small">{fe.roles}</div>}
      </fieldset>
      <p className="small muted">Admins manage users, templates and reference data. They cannot record findings, set risk tiers or approve audit work.</p>
      <div className="row"><Button type="submit" variant="primary">Add and send invitation</Button><Button onClick={onDone}>Cancel</Button></div>
    </form>
  );
}

export function UsersAdmin() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const q = useQuery({ queryKey: ['admin-users'], queryFn: () => api.get<U[]>('/admin/users') });
  const canManage = hasRole(me ?? undefined, 'admin');
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
  return (
    <div className="page">
      <PageHeader title="Futran users" subtitle="People at Futran who can sign in, and what they can do." actions={canManage && !adding ? <Button variant="primary" onClick={() => setAdding(true)}>Add user</Button> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {adding && <Card title="Add a Futran user"><AddUser onDone={() => setAdding(false)} /></Card>}
      <section className="card">
        {q.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="table stack-table">
              <thead><tr><th>Name</th><th>Email</th><th>Roles</th><th>Status</th><th>Sign-in codes</th>{canManage && <th><span className="sr-only">Actions</span></th>}</tr></thead>
              <tbody>
                {q.data?.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.name}</strong>{u.job_title && <div className="small muted">{u.job_title}</div>}</td>
                    <td data-label="Email" className="break">{u.email}</td>
                    <td data-label="Roles">{u.role_labels.join(', ')}</td>
                    <td data-label="Status">{u.status === 'active' ? <Badge tone="success">Active</Badge> : u.status === 'invited' ? <Badge tone="warn">Invited</Badge> : <Badge tone="muted">Disabled</Badge>}</td>
                    <td data-label="Sign-in codes">{u.mfa_enabled ? 'On' : 'Not set up'}</td>
                    {canManage && (
                      <td>
                        <div className="row">
                          {u.status === 'invited' && <Button size="sm" onClick={() => resend(u)}>Resend invitation</Button>}
                          {u.status === 'active' && u.id !== me?.user.id && <Button size="sm" variant="danger" onClick={() => patch.mutate({ id: u.id, body: { status: 'disabled' } })}>Disable</Button>}
                          {u.status === 'disabled' && <Button size="sm" onClick={() => patch.mutate({ id: u.id, body: { status: 'active' } })}>Enable</Button>}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
