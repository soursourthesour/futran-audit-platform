import { useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextField } from '@/components/ui';

type Role = { id: string; role: string; role_label: string; department: string | null; sign_off_role: boolean };
type Person = { id: string; name: string; email: string; job_title: string | null; status: string; invite_status: string; roles: Role[] };
type Dept = { id: string; name: string; headcount: number | null; head_name: string | null; in_scope: boolean; lead: string | null };
type Holder = { user: { id: string; name: string } | null; not_appointed: boolean };
type People = { client: { id: string; name: string }; can_manage: boolean; departments: Dept[]; users: Person[]; role_holders: Record<string, Holder>; gate: { stage: number; ready: boolean; unmet: string[] } | null };
type CsvError = { row: number | null; field: string; message: string };
type Preview = { rows_ok: Record<string, string | null>[]; errors: CsvError[] };

const ROLES = [
  { value: 'dept_compliance_lead', label: 'Department Compliance Lead' },
  { value: 'contributor', label: 'Contributor' },
  { value: 'exec_sponsor', label: 'Executive Sponsor' },
  { value: 'dpo', label: 'Data Protection Officer' },
  { value: 'client_admin', label: 'Client Admin' },
  { value: 'caico', label: 'Chief AI Compliance Officer' },
];
const DEPT_ROLES = new Set(['dept_compliance_lead', 'contributor']);

export function UsersDepartments() {
  const { data: me } = useMe();
  const cid = me?.organization.id ?? '';
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['people', cid], queryFn: () => api.get<People>(`/clients/${cid}/people`), enabled: !!cid });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'warn'; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [upload, setUpload] = useState<{ kind: 'users' | 'departments'; text: string; preview: Preview } | null>(null);
  const [newDept, setNewDept] = useState('');
  const userFile = useRef<HTMLInputElement>(null);
  const deptFile = useRef<HTMLInputElement>(null);
  const refresh = () => qc.invalidateQueries();

  if (q.isLoading || !q.data) return <div className="page"><Loading /></div>;
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
      setMsg({ tone: r.errors.length ? 'warn' : 'success', text: `Imported ${r.imported} ${upload.kind === 'users' ? (r.imported === 1 ? 'user' : 'users') : (r.imported === 1 ? 'department' : 'departments')}.${r.errors.length ? ` ${new Set(r.errors.map((x) => x.row)).size === 1 ? '1 row was' : `${new Set(r.errors.map((x) => x.row)).size} rows were`} not imported; fix and upload again.` : ''}${upload.kind === 'users' && r.imported ? ' Invitations have been sent.' : ''}` });
      setUpload(null);
      await refresh();
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function addDept(e: FormEvent) {
    e.preventDefault();
    try { await api.post(`/clients/${cid}/departments`, { name: newDept }); setNewDept(''); await refresh(); } catch (ex) { setMsg({ tone: 'danger', text: errorMessage(ex) }); }
  }
  async function toggleScope(d: Dept) {
    await api.patch(`/clients/${cid}/departments/${d.id}`, { in_scope: !d.in_scope });
    await refresh();
  }
  async function confirm() {
    try { await api.post(`/clients/${cid}/departments/confirm`); setMsg({ tone: 'success', text: 'Department list confirmed. Futran has been notified.' }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function removeRole(u: Person, r: Role) {
    try { await api.delete(`/clients/${cid}/users/${u.id}/roles/${r.id}`); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function notAppointed(role: string, value: boolean) {
    await api.put(`/clients/${cid}/role-holders/${role}`, { not_appointed: value });
    await refresh();
  }

  return (
    <div className="page">
      <PageHeader title="Departments and users" subtitle="Only people who need a login. All other staff take part later through the attestation link."
        actions={p.can_manage ? <>
          <a className="btn" href={`/api/v1/clients/${cid}/departments/template.csv`}>Department template</a>
          <Button onClick={() => userFile.current?.click()}>Upload user CSV</Button>
          <Button variant="primary" onClick={() => setAdding(true)}>Add user</Button>
        </> : undefined} />
      <input ref={userFile} type="file" accept=".csv,text/csv" hidden aria-label="User list CSV" onChange={(e) => { void pick('users', e.target.files?.[0]); e.target.value = ''; }} />
      <input ref={deptFile} type="file" accept=".csv,text/csv" hidden aria-label="Department list CSV" onChange={(e) => { void pick('departments', e.target.files?.[0]); e.target.value = ''; }} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {p.gate && p.gate.stage === 2 && !p.gate.ready && (
        <Alert tone="info"><strong>To finish setup:</strong> {p.gate.unmet.join(' ')}</Alert>
      )}
      {upload && (
        <Card title={`${upload.kind === 'users' ? 'User' : 'Department'} CSV: ${upload.preview.rows_ok.length} rows ready${upload.preview.errors.length ? `, ${new Set(upload.preview.errors.map((e) => e.row)).size} need fixing before import` : ''}`}
          actions={<><Button variant="primary" onClick={runImport} disabled={!upload.preview.rows_ok.length}>Import {upload.preview.rows_ok.length} ready rows</Button><Button onClick={() => setUpload(null)}>Cancel</Button></>}>
          {upload.preview.errors.length === 0 ? <p className="small">Every row is ready.</p> : (
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {upload.preview.errors.map((e, i) => <li key={i}>{e.row ? `Row ${e.row}: ` : ''}{e.message}</li>)}
            </ul>
          )}
        </Card>
      )}
      <div className="split" style={{ marginTop: 16 }}>
        <div className="side stack">
          <Card title="Departments" actions={p.can_manage ? <Button size="sm" onClick={() => deptFile.current?.click()}>Upload CSV</Button> : undefined}>
            <div className="stack">
              {p.departments.length === 0 ? <EmptyState>No departments yet. Download the template (pre-filled from the scope), or add them here.</EmptyState> : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {p.departments.map((d) => (
                    <li key={d.id} className="row" style={{ justifyContent: 'space-between', padding: '8px 0', borderTop: '1px solid var(--line-soft)' }}>
                      <span><strong style={{ opacity: d.in_scope ? 1 : 0.5 }}>{d.name}</strong>{d.headcount ? <span className="small muted"> · {d.headcount} staff</span> : null}</span>
                      <span className="row" style={{ gap: 6 }}>
                        {!d.in_scope ? <Badge tone="muted">Out of scope</Badge> : d.lead ? <Badge tone="success">Lead: {d.lead}</Badge> : <Badge tone="warn">No lead yet</Badge>}
                        {p.can_manage && <button type="button" className="link-btn small" onClick={() => toggleScope(d)}>{d.in_scope ? 'Exclude' : 'Include'}</button>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {p.can_manage && (
                <>
                  <form className="row" onSubmit={addDept}><input className="input" style={{ flex: 1 }} aria-label="New department" placeholder="Department name" value={newDept} onChange={(e) => setNewDept(e.target.value)} /><Button type="submit" size="sm">Add</Button></form>
                  <Button onClick={confirm} disabled={!p.departments.length}>Confirm the department list</Button>
                </>
              )}
            </div>
          </Card>
          <Card title="Sign-off roles">
            <div className="stack small">
              {(['caico', 'exec_sponsor', 'dpo'] as const).map((r) => {
                const h = p.role_holders[r];
                const label = ROLES.find((x) => x.value === r)!.label;
                return (
                  <div key={r}>
                    <strong>{label}</strong>
                    <div>{h.user ? h.user.name : h.not_appointed ? 'Not appointed: the Chief AI Compliance Officer covers this role' : 'Not named yet'}</div>
                    {r !== 'caico' && !h.user && p.can_manage && <Checkbox label="Not appointed" checked={h.not_appointed} onChange={(e) => notAppointed(r, e.target.checked)} />}
                  </div>
                );
              })}
              <p className="muted" style={{ margin: 0 }}>Assigning or removing a sign-off role notifies Futran and is recorded in the audit log.</p>
            </div>
          </Card>
        </div>
        <div className="main">
          <Card title={`Users · ${p.users.length}`}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Name</th><th>Role</th><th>Department</th><th>Invitation</th></tr></thead>
                <tbody>
                  {p.users.map((u) => (
                    <tr key={u.id}>
                      <td><strong>{u.name}</strong><div className="small muted">{u.email}{u.job_title ? ` · ${u.job_title}` : ''}</div></td>
                      <td>
                        {u.roles.map((r) => (
                          <div key={r.id} className="small">
                            {r.role_label}{r.sign_off_role && <span className="muted"> · sign-off role</span>}
                            {p.can_manage && <> <button type="button" className="link-btn small" aria-label={`Remove ${r.role_label} from ${u.name}`} onClick={() => removeRole(u, r)}>Remove</button></>}
                          </div>
                        ))}
                      </td>
                      <td className="small">{u.roles.map((r) => r.department).filter(Boolean).join(', ') || '—'}</td>
                      <td className="small">{u.invite_status === 'Active' ? <Badge tone="success">Active</Badge> : u.invite_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>
      {adding && <AddUser cid={cid} departments={p.departments.filter((d) => d.in_scope)} onClose={() => setAdding(false)} onDone={async (name) => { setAdding(false); setMsg({ tone: 'success', text: `${name} was added and invited.` }); await refresh(); }} />}
    </div>
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
          <TextField label="First name" value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} error={fe.first_name} />
          <TextField label="Last name" value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} error={fe.last_name} />
        </div>
        <TextField label="Work email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} error={fe.email} />
        <TextField label="Job title" value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} />
        <SelectField label="Role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={ROLES} />
        {needsDept && <SelectField label="Department" value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} options={departments.map((d) => ({ value: d.name, label: d.name }))} error={fe.department} />}
        <div className="row"><Button type="submit" variant="primary">Add and send invitation</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}
