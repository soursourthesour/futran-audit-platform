import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Loading, PageHeader } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import '@/styles/futran-screens.css';

type Row = { id: string; name: string; email: string; client_id: string; client: string; department: string | null; job_title: string | null; role_keys: string[]; roles: string[]; status: string };
type Data = { users: Row[]; clients: { id: string; name: string }[]; departments: string[]; roles: { value: string; label: string }[] };
const STATUS_LABEL: Record<string, string> = { active: 'Active', invited: 'Invited', disabled: 'Disabled' };

/** Administration › Client users (feedback 10 Nov F1): every client organisation's people, read-only. Futran Admin and Chief
 *  Auditor only; each time the list is opened it is recorded in the audit log. Changes are made on each client's People page. */
export function ClientUsers() {
  const q = useQuery({ queryKey: ['admin-client-users'], queryFn: () => api.get<Data>('/admin/client-users'), staleTime: 60_000 });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const count = (id: string) => d.users.filter((u) => u.client_id === id).length;
  return (
    <div className="page">
      <PageHeader title="Client users"
        subtitle="Every client organisation's people, with their department, job title, AI compliance roles and status. Read-only: people are added and changed on each client's People page. Opening this list is recorded in the audit log." />
      <section className="card"><div className="card-body">
        <p className="small muted" style={{ marginTop: 0 }}>{d.users.length} people across {d.clients.length} {d.clients.length === 1 ? 'client' : 'clients'}.</p>
        <DataGrid label="Client users" rows={d.users} rowId={(u) => u.id} rowLabel={(u) => `${u.name}, ${u.client}`} initialSort={{ key: 'client', dir: 'asc' }}
          emptyText="No client has any users yet."
          search={{ label: 'Search', placeholder: 'Name, email or job title', text: (u) => `${u.name} ${u.email} ${u.job_title ?? ''}` }}
          filters={[
            { key: 'client', label: 'Client', options: d.clients.map((c) => ({ value: c.id, label: `${c.name} (${count(c.id)})` })), test: (u, v) => u.client_id === v },
            { key: 'dept', label: 'Department', options: [...d.departments.map((x) => ({ value: x, label: x })), { value: '__none', label: 'No department' }], test: (u, v) => (v === '__none' ? !u.department : u.department === v) },
            { key: 'role', label: 'AI compliance role', options: [...d.roles, { value: '__none', label: 'No role' }], test: (u, v) => (v === '__none' ? u.role_keys.length === 0 : u.role_keys.includes(v)) },
            { key: 'status', label: 'Status', options: Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label })), test: (u, v) => u.status === v },
          ]}
          columns={[
            { key: 'name', header: 'Name', value: (u) => u.name, render: (u) => <><strong>{u.name}</strong><div className="small muted break">{u.email}</div></> },
            { key: 'client', header: 'Client', value: (u) => u.client },
            { key: 'dept', header: 'Department', value: (u) => u.department ?? '', render: (u) => u.department ?? <span className="muted">None</span> },
            { key: 'title', header: 'Job title', value: (u) => u.job_title ?? '' },
            { key: 'roles', header: 'AI compliance roles', value: (u) => u.roles.join(', '), render: (u) => (u.roles.length ? u.roles.join(', ') : <span className="muted">None</span>) },
            { key: 'status', header: 'Status', value: (u) => STATUS_LABEL[u.status] ?? u.status, render: (u) => <Badge tone={u.status === 'active' ? 'success' : u.status === 'invited' ? 'warn' : 'muted'}>{STATUS_LABEL[u.status] ?? u.status}</Badge> },
          ]} />
      </div></section>
    </div>
  );
}
