import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ClientEmailStatus } from './ClientEmailStatus';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { type GroupDetail, type Group, type GroupsList, type Person, downloadBlob } from '@/api/mail';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { emailHelp as H } from '@/help/email';
import './email.css';

const ROLE_OPTIONS = [
  { value: 'caico', label: 'Chief AI Compliance Officer' }, { value: 'client_admin', label: 'Client Admin' }, { value: 'exec_sponsor', label: 'Executive Sponsor' },
  { value: 'dpo', label: 'Data Protection Officer' }, { value: 'dept_compliance_lead', label: 'Department Compliance Lead' }, { value: 'contributor', label: 'Contributor' },
];
const FUTRAN_ROLES = [
  { value: 'chief_auditor', label: 'Chief Auditor' }, { value: 'auditor', label: 'Auditor' }, { value: 'qa_reviewer', label: 'QA Reviewer' }, { value: 'admin', label: 'Futran Admin' },
  { value: 'engagement_manager', label: 'Engagement Manager' }, { value: 'legal_reviewer', label: 'Legal/Compliance Reviewer' },
];

function sourceTone(s: Group['source']): 'default' | 'warn' | 'navy' {
  return s === 'rule' ? 'warn' : s === 'directory' ? 'navy' : 'default';
}

function qs(owner?: 'futran', clientId?: string) {
  if (owner === 'futran') return '?owner=futran';
  return clientId ? `?client_id=${clientId}` : '';
}

/** E3 Email groups (client) and the Futran groups grid on E1. */
export function GroupsScreen() {
  return (
    <div className="page">
      <PageHeader title="Email groups" subtitle="Groups you send AI governance emails to. They live only in the Futran Audit Platform and are expanded to people at the moment an email is sent. Your Microsoft 365 or Google groups are not changed." />
      <GroupsManager />
    </div>
  );
}

export function GroupsManager({ owner, clientId, title }: { owner?: 'futran'; clientId?: string; title?: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const key = ['mail-groups', owner ?? clientId ?? 'own'];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<GroupsList>(`/mail/groups${qs(owner, clientId)}`) });
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [bulkEdit, setBulkEdit] = useState<Group[] | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const isFutran = d.organization.type === 'futran';

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ tone: 'success', text: ok }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function exportMembers(groups: Group[]) {
    for (const g of groups) downloadBlob(await api.get<Blob>(`/mail/groups/${g.id}/export`), `${g.name.replace(/[^A-Za-z0-9]+/g, '_')}_members.csv`);
  }
  const sync = (ids: string[]) => act(() => api.post(`/mail/groups/sync${qs(owner, clientId)}`, { group_ids: ids }), d.directory_connected ? 'Directory synced. Members are up to date.' : 'Groups refreshed. Rule groups update themselves; connect your directory to sync directory groups.');
  const sendTo = (ids: string[]) => nav(`/send?groups=${ids.join(',')}${clientId ? `&client=${clientId}` : ''}`);

  const columns: GridColumn<Group>[] = [
    { key: 'name', header: 'Group', value: (g) => g.name, render: (g) => <span className="group-name"><strong>{g.name}</strong>{g.purpose && <span className="small muted">{g.purpose}</span>}</span> },
    { key: 'source', header: 'Source', value: (g) => g.source_label, render: (g) => <span className="group-name"><Badge tone={sourceTone(g.source)}>{g.source_label}</Badge>{g.source !== 'manual' && <span className="small muted">{g.rule_text.replace(/^Rule: /, '')}</span>}</span> },
    { key: 'members', header: 'Members', value: (g) => g.member_count, render: (g) => <span className="num">{g.member_count.toLocaleString()}</span> },
    { key: 'synced', header: 'Last synced', value: (g) => g.last_synced_at ?? '', render: (g) => (g.source === 'manual' ? '—' : g.last_synced_at ? fmtDateTime(g.last_synced_at) : g.source === 'rule' ? 'Live' : '—') },
    { key: 'used', header: 'Used by', value: (g) => g.used_by ?? '', render: (g) => g.used_by ?? '—' },
  ];
  return (
    <div className="stack">
      {title && <h2 style={{ margin: 0 }}>{title}</h2>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        {!isFutran && d.directory_groups.length > 0 && d.can_create && <Button onClick={() => setImporting(true)}>Import from directory</Button>}
        {d.can_create && <Button variant="primary" onClick={() => setEditing('new')}>Add group</Button>}
      </div>
      <div className={`groups-layout ${editing ? '' : 'single'}`}>
        <Card>
          <DataGrid<Group>
            label={isFutran ? 'Futran groups' : 'Email groups'}
            rows={d.groups}
            rowId={(g) => g.id}
            rowLabel={(g) => g.name}
            columns={columns}
            selectable
            search={{ label: 'Search', placeholder: 'Group name or purpose', text: (g) => `${g.name} ${g.purpose ?? ''} ${g.rule_text}` }}
            filters={[
              { key: 'source', label: 'Source', options: [{ value: 'manual', label: 'Manual list' }, { value: 'rule', label: 'Rule' }, { value: 'directory', label: 'Directory group' }], test: (g, v) => g.source === v },
              { key: 'used', label: 'Used by', options: [...new Set(d.groups.map((g) => g.used_by).filter(Boolean) as string[])].map((u) => ({ value: u, label: u })), test: (g, v) => g.used_by === v },
            ]}
            bulkActions={[
              ...(d.can_create ? [{ label: 'Edit selected', run: (rows: Group[]) => setBulkEdit(rows) }] : []),
              ...(!isFutran ? [{ label: 'Send email to selected', run: (rows: Group[]) => sendTo(rows.map((r) => r.id)) }] : []),
              ...(d.can_create ? [{ label: 'Sync now', run: (rows: Group[]) => sync(rows.map((r) => r.id)) }] : []),
              { label: 'Export', run: (rows: Group[]) => exportMembers(rows) },
            ]}
            rowActions={(g) => [
              { label: g.can_edit ? 'Open and edit' : 'Open', onSelect: () => setEditing(g.id) },
              { label: 'Preview who receives it', onSelect: () => setPreview(g.id) },
              ...(!isFutran ? [{ label: 'Send email to this group', onSelect: () => sendTo([g.id]) }] : []),
              ...(g.can_edit ? [{ label: 'Sync now', onSelect: () => sync([g.id]) }, { label: 'Duplicate', onSelect: () => act(() => api.post(`/mail/groups/${g.id}/duplicate`), `Made a copy of ${g.name}.`) }] : []),
              { label: 'Export members', onSelect: () => exportMembers([g]) },
              ...(g.can_edit && !g.is_default ? [{ label: 'Delete group', danger: true, onSelect: () => { if (window.confirm(`Delete the group ${g.name}? Emails already sent keep their recipient lists.`)) void act(() => api.delete(`/mail/groups/${g.id}`), `Deleted ${g.name}.`); } }] : []),
            ]}
            emptyText="No groups yet."
            initialSort={undefined}
          />
          <p className="small muted" style={{ margin: '12px 0 0' }}>Manual list: you add people. Rule: updates itself from roles, departments or offices. Directory group: copies members from Microsoft 365 or Google at each sync.</p>
        </Card>
        {editing && <GroupEditor key={editing} id={editing} list={d} owner={owner} clientId={clientId} onClose={() => setEditing(null)} onSaved={async (text) => { setMsg({ tone: 'success', text }); await refresh(); }} onOpen={(id) => setEditing(id)} />}
      </div>
      {preview && <PreviewDialog id={preview} onClose={() => setPreview(null)} />}
      {importing && <ImportDirectory list={d} clientId={clientId} onClose={() => setImporting(false)} onDone={async (text) => { setImporting(false); setMsg({ tone: 'success', text }); await refresh(); }} />}
      {bulkEdit && <BulkEdit rows={bulkEdit} onClose={() => setBulkEdit(null)} onDone={async (text) => { setBulkEdit(null); setMsg({ tone: 'success', text }); await refresh(); }} />}
    </div>
  );
}

function PreviewDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['mail-group', id], queryFn: () => api.get<GroupDetail>(`/mail/groups/${id}`) });
  const people = (q.data?.members ?? []).filter((m) => m.kind === 'person') as (Person & { member_id: string | null })[];
  return (
    <Dialog title={q.data ? `Who receives ${q.data.name}` : 'Who receives it'} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : !q.data ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : (
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>{q.data.member_count.toLocaleString()} {q.data.member_count === 1 ? 'person' : 'people'} today. Groups are expanded again when an email is sent, and leavers and people on leave are left out then.</p>
          {q.data.members.some((m) => m.kind === 'group') && <p className="small" style={{ margin: 0 }}>Includes the groups {q.data.members.filter((m) => m.kind === 'group').map((m) => m.name).join(', ')}.</p>}
          {people.length === 0 ? <EmptyState>Nobody is in this group yet.</EmptyState> : (
            <ul className="member-list">
              {people.slice(0, 300).map((p) => <li key={p.id}><div className="who"><strong>{p.name}</strong><span className="small muted">{p.email}{p.department ? ` · ${p.department}` : ''}</span></div></li>)}
            </ul>
          )}
        </div>
      )}
    </Dialog>
  );
}

function ImportDirectory({ list, clientId, onClose, onDone }: { list: GroupsList; clientId?: string; onClose: () => void; onDone: (text: string) => void }) {
  const [ids, setIds] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    try {
      const r = await api.post<{ created: string[] }>(`/mail/groups/import-directory${clientId ? `?client_id=${clientId}` : ''}`, { ids });
      onDone(r.created.length ? `Added ${r.created.join(', ')}.` : 'Those directory groups are already here.');
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Import groups from your directory" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>Each one becomes a group here whose members are copied at every directory sync. Your directory is not changed.</p>
        {list.directory_groups.map((g) => (
          <Checkbox key={g.id} label={`${g.name} (${g.member_count.toLocaleString()})`} checked={ids.includes(g.id)} onChange={() => setIds(ids.includes(g.id) ? ids.filter((x) => x !== g.id) : [...ids, g.id])} />
        ))}
        <div className="row"><Button variant="primary" onClick={go} disabled={!ids.length}>Import {ids.length || ''} {ids.length === 1 ? 'group' : 'groups'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function BulkEdit({ rows, onClose, onDone }: { rows: Group[]; onClose: () => void; onDone: (text: string) => void }) {
  const [usedBy, setUsedBy] = useState('');
  const [leave, setLeave] = useState<'keep' | 'on' | 'off'>('keep');
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    const editable = rows.filter((r) => r.can_edit);
    try {
      for (const g of editable) {
        const body: Record<string, unknown> = {};
        if (usedBy.trim()) body.used_by = usedBy.trim();
        if (leave !== 'keep') body.exclude_on_leave = leave === 'on';
        if (Object.keys(body).length) await api.patch(`/mail/groups/${g.id}`, body);
      }
      onDone(`Updated ${editable.length} ${editable.length === 1 ? 'group' : 'groups'}.${editable.length < rows.length ? ' Groups you cannot edit were left as they were.' : ''}`);
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Edit ${rows.length} ${rows.length === 1 ? 'group' : 'groups'}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Used by" help={H.usedBy} value={usedBy} onChange={(e) => setUsedBy(e.target.value)} placeholder="Leave blank to keep each group's own" />
        <SelectField label="People on leave" help={H.excludeOnLeave} value={leave} onChange={(e) => setLeave(e.target.value as 'keep' | 'on' | 'off')}
          options={[{ value: 'keep', label: 'Keep each group as it is' }, { value: 'on', label: 'Always leave them out' }, { value: 'off', label: 'Include them' }]} />
        <div className="row"><Button variant="primary" onClick={go}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

type Draft = { name: string; purpose: string; source: Group['source']; rule: Record<string, string>; directory_group_id: string; department_id: string; exclude_on_leave: boolean; used_by: string };

function GroupEditor({ id, list, owner, clientId, onClose, onSaved, onOpen }: { id: string; list: GroupsList; owner?: 'futran'; clientId?: string; onClose: () => void; onSaved: (text: string) => void; onOpen: (id: string) => void }) {
  const { data: me } = useMe();
  const isNew = id === 'new';
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['mail-group', id], queryFn: () => api.get<GroupDetail>(`/mail/groups/${id}`), enabled: !isNew });
  const isFutran = list.organization.type === 'futran';
  const leadOnly = list.my_departments !== null && !isFutran;
  const [draft, setDraft] = useState<Draft>({ name: '', purpose: '', source: 'manual', rule: { kind: isFutran ? 'role' : 'department' }, directory_group_id: '', department_id: leadOnly ? (list.my_departments?.[0] ?? '') : '', exclude_on_leave: true, used_by: '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const g = q.data;
    if (g) setDraft({ name: g.name, purpose: g.purpose ?? '', source: g.source, rule: (g.rule as Record<string, string>) ?? { kind: 'department' }, directory_group_id: g.directory_group_id ?? '', department_id: g.department_id ?? '', exclude_on_leave: g.exclude_on_leave, used_by: g.used_by ?? '' });
  }, [q.data]);
  if (!isNew && q.isLoading) return <Card className="group-panel"><Loading /></Card>;
  const g = q.data;
  const editable = isNew || !!g?.can_edit;
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const reload = () => qc.invalidateQueries({ queryKey: ['mail-group', id] });

  async function save() {
    setErr(null); setFe({}); setBusy(true);
    try {
      if (isNew) {
        const body = { name: draft.name, purpose: draft.purpose, source: draft.source, rule: draft.source === 'rule' ? draft.rule : draft.source === 'directory' && !draft.directory_group_id ? { kind: 'all_people' } : null,
          directory_group_id: draft.source === 'directory' ? draft.directory_group_id || null : null, department_id: draft.department_id || null, exclude_on_leave: draft.exclude_on_leave, used_by: draft.used_by };
        const made = await api.post<Group>(`/mail/groups${qs(owner, clientId)}`, body);
        onSaved(`Added ${made.name}.${made.source === 'manual' ? ' Now add its members.' : ''}`);
        onOpen(made.id);
      } else {
        await api.patch(`/mail/groups/${id}`, { ...(g?.is_default ? {} : { name: draft.name }), purpose: draft.purpose, exclude_on_leave: draft.exclude_on_leave, used_by: draft.used_by, ...(g?.source === 'rule' ? { rule: draft.rule } : {}) });
        await reload();
        onSaved(`Saved ${draft.name}.`);
      }
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }

  const ruleEditor = (
    <div className="stack-sm">
      <SelectField label="Rule" help={H.ruleKind} value={draft.rule.kind ?? ''} disabled={!editable} onChange={(e) => set({ rule: { kind: e.target.value } })}
        options={isFutran ? [{ value: 'all_users', label: 'Every active Futran user' }, { value: 'role', label: 'Everyone with a role' }] : [
          { value: 'department', label: 'Everyone in a department' }, { value: 'role', label: 'Everyone with a role' }, { value: 'office', label: 'Everyone in an office' },
          { value: 'dept_heads', label: 'All department heads' }, { value: 'all_people', label: 'Everyone' }]} />
      {draft.rule.kind === 'department' && <SelectField label="Department" help={H.ruleDepartment} value={draft.rule.department_id ?? ''} disabled={!editable} placeholder="Choose…" onChange={(e) => set({ rule: { ...draft.rule, department_id: e.target.value } })} options={list.departments.map((x) => ({ value: x.id, label: x.name }))} />}
      {draft.rule.kind === 'role' && <SelectField label="Role" help={H.ruleRole} value={draft.rule.role ?? ''} disabled={!editable} placeholder="Choose…" onChange={(e) => set({ rule: { ...draft.rule, role: e.target.value } })} options={isFutran ? FUTRAN_ROLES : ROLE_OPTIONS} />}
      {draft.rule.kind === 'office' && <TextField label="Office" help={H.ruleOffice} value={draft.rule.office ?? ''} disabled={!editable} onChange={(e) => set({ rule: { ...draft.rule, office: e.target.value } })} />}
      {fe.rule && <div className="error">{fe.rule}</div>}
    </div>
  );

  return (
    <Card className="group-panel" title={isNew ? 'Add group' : `${editable ? 'Edit group' : 'Group'}: ${g?.name ?? ''}`}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Group name *" help={H.groupName} value={draft.name} onChange={(e) => set({ name: e.target.value })} disabled={!editable || !!g?.is_default} error={fe.name} />
        <TextField label="Purpose" help={H.groupPurpose} value={draft.purpose} onChange={(e) => set({ purpose: e.target.value })} disabled={!editable} />
        {isNew ? (
          <FieldGroup legend="Members come from *" help={H.groupSource}>
            <div className="stack-sm" role="radiogroup">
              {([['manual', 'A list I keep'], ['rule', isFutran ? 'A rule (role)' : 'A rule (role, department, location)'], ...(!isFutran ? [['directory', 'A directory group']] : [])] as [Group['source'], string][]).map(([v, l]) => (
                <label key={v} className="check"><input type="radio" name="source" checked={draft.source === v} onChange={() => set({ source: v })} /><span>{l}</span></label>
              ))}
            </div>
          </FieldGroup>
        ) : <p className="small" style={{ margin: 0 }}><Badge tone={sourceTone(g!.source)}>{g!.source_label}</Badge> {g!.source !== 'manual' && <span className="muted">{g!.rule_text}</span>}</p>}
        {draft.source === 'rule' && (isNew || g?.source === 'rule') && ruleEditor}
        {draft.source === 'directory' && isNew && (
          <SelectField label="Directory group" help={H.directoryGroup} value={draft.directory_group_id} onChange={(e) => set({ directory_group_id: e.target.value })} placeholder="Everyone the directory sync imports"
            options={list.directory_groups.map((x) => ({ value: x.id, label: `${x.name} (${x.member_count})` }))} />
        )}
        {!isFutran && (isNew ? (
          <SelectField label="Department" help={H.groupDepartment} value={draft.department_id} onChange={(e) => set({ department_id: e.target.value })} placeholder={leadOnly ? undefined : 'Whole organisation'}
            options={list.departments.filter((x) => !leadOnly || list.my_departments?.includes(x.id)).map((x) => ({ value: x.id, label: x.name }))} />
        ) : g?.department ? <p className="small muted" style={{ margin: 0 }}>Department group: {g.department}</p> : null)}
        <TextField label="Used by" help={H.usedBy} value={draft.used_by} onChange={(e) => set({ used_by: e.target.value })} disabled={!editable} />
        {g && <Members g={g} list={list} owner={owner} clientId={clientId} editable={editable} onChanged={reload} />}
        <Checkbox label="Always exclude people on leave" help={H.excludeOnLeave} checked={draft.exclude_on_leave} disabled={!editable} onChange={(e) => set({ exclude_on_leave: e.target.checked })} />
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>{editable ? 'Cancel' : 'Close'}</Button>
          {editable && <Button variant="primary" onClick={save} disabled={busy}>{isNew ? 'Add group' : 'Save group'}</Button>}
        </div>
        {me && !editable && <p className="small muted" style={{ margin: 0 }}>You can see this group but not change it.</p>}
      </div>
    </Card>
  );
}

function Members({ g, list, owner, clientId, editable, onChanged }: { g: GroupDetail; list: GroupsList; owner?: 'futran'; clientId?: string; editable: boolean; onChanged: () => void }) {
  const [term, setTerm] = useState('');
  const [nested, setNested] = useState('');
  const [csv, setCsv] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const search = useQuery({ queryKey: ['mail-people', owner ?? clientId ?? 'own', term], queryFn: () => api.get<Person[]>(`/mail/people${qs(owner, clientId) ? qs(owner, clientId) + '&' : '?'}q=${encodeURIComponent(term)}`),
    enabled: editable && g.source === 'manual' && term.trim().length >= 2 });
  async function add(body: Record<string, string>) {
    setErr(null);
    try { await api.post(`/mail/groups/${g.id}/members`, body); setTerm(''); setNested(''); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  async function remove(memberId: string) {
    setErr(null);
    try { await api.delete(`/mail/groups/${g.id}/members/${memberId}`); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  async function importCsv() {
    setErr(null);
    try { const r = await api.post<{ added: number; errors: { message: string }[] }>(`/mail/groups/${g.id}/import`, { csv }); setCsv(null); onChanged(); if (r.errors.length) setErr(r.errors.map((x) => x.message).join(' ')); } catch (e) { setErr(errorMessage(e)); }
  }
  const typedEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(term.trim());
  const others = list.groups.filter((x) => x.id !== g.id && !g.members.some((m) => m.kind === 'group' && m.id === x.id));
  return (
    <div className="stack-sm">
      {err && <Alert tone="danger">{err}</Alert>}
      {g.source === 'manual' && editable && (
        <>
          <TextField label="Add a person" help={H.addPerson} value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Name or email" />
          {term.trim().length >= 2 && (
            <div className="suggest" role="listbox" aria-label="People found">
              {(search.data ?? []).map((p) => <button key={p.id} type="button" onClick={() => add({ person_id: p.id })}>{p.name} <span className="small muted">· {p.email}{p.department ? ` · ${p.department}` : ''}</span></button>)}
              {typedEmail && !(search.data ?? []).some((p) => p.email === term.trim().toLowerCase()) && <button type="button" onClick={() => add({ email: term.trim() })}>Add {term.trim()} as a new person</button>}
              {search.data && !search.data.length && !typedEmail && <div className="small muted" style={{ padding: 10 }}>Nobody found. Type a full email address to add someone new.</div>}
            </div>
          )}
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div style={{ flex: 1, minWidth: 0 }}><SelectField label="Include another group" help={H.addGroup} value={nested} onChange={(e) => setNested(e.target.value)} placeholder="Choose a group…" options={others.map((x) => ({ value: x.id, label: x.name }))} /></div>
            <Button onClick={() => add({ nested_group_id: nested })} disabled={!nested}>Add</Button>
          </div>
          <div><Button size="sm" variant="ghost" onClick={() => setCsv('')}>Import members from CSV</Button></div>
        </>
      )}
      <h3 style={{ fontSize: 13, margin: '6px 0 0', textTransform: 'uppercase', letterSpacing: 0.4, color: 'var(--muted)' }}>Members ({g.member_count.toLocaleString()})</h3>
      {g.members.length === 0 ? <p className="small muted" style={{ margin: 0 }}>{g.source === 'manual' ? 'No members yet.' : 'Nobody matches the rule today.'}</p> : (
        <ul className="member-list">
          {g.members.slice(0, 200).map((m) => (
            <li key={m.kind === 'group' ? `g${m.id}` : `p${m.id}`}>
              <div className="who">
                {m.kind === 'group' ? <><strong>{m.name}</strong><span className="small muted">Group · {m.member_count} {m.member_count === 1 ? 'person' : 'people'}</span></>
                  : <><strong>{m.name}</strong><span className="small muted">{m.job_title ?? m.email}{m.department ? ` · ${m.department}` : ''}{m.status !== 'active' ? ` · ${m.status === 'on_leave' ? 'on leave' : 'left'}` : ''}</span></>}
              </div>
              {editable && g.source === 'manual' && m.member_id && <Button size="sm" variant="ghost" onClick={() => remove(m.member_id!)} aria-label={`Remove ${m.name}`}>Remove</Button>}
            </li>
          ))}
        </ul>
      )}
      {g.members.length > 200 && <p className="small muted" style={{ margin: 0 }}>Showing the first 200. Export the group to see everyone.</p>}
      {csv !== null && (
        <Dialog title={`Import members into ${g.name}`} onClose={() => setCsv(null)}>
          <div className="stack">
            <TextArea label="CSV" help={H.csv} value={csv} onChange={(e) => setCsv(e.target.value)} rows={8} placeholder={'email,name\nana.ruiz@yourcompany.com,Ana Ruiz'} />
            <div className="row"><Button variant="primary" onClick={importCsv} disabled={!csv.trim()}>Import</Button><Button onClick={() => setCsv(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

/** Futran's view of one client's groups (/clients/:clientId/groups): read-only for the Chief Auditor and Auditors; the
 *  Futran Admin may set up the client's starting groups during onboarding (spec §27.1). */
export function ClientGroupsForFutran() {
  const { clientId = '' } = useParams();
  return (
    <div className="page">
      <PageHeader title="Client email groups" crumbs={[{ to: '/clients', label: 'Clients' }, { to: `/clients/${clientId}`, label: 'Client' }, { label: 'Email groups' }]}
        subtitle="The client's groups, expanded to people when an email is sent. The client's Client Admin and Chief AI Compliance Officer manage them." />
      <div className="stack">
        <ClientEmailStatus clientId={clientId} />
        <GroupsManager clientId={clientId} />
      </div>
    </div>
  );
}
