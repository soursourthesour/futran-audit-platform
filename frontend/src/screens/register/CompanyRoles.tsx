import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import type { Assignment, RolePerson } from '@/api/register';
import { Alert, Badge, Button, Dialog, Loading, PageHeader, SelectField, TextField, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { committeeHelp as H } from '@/help/register';
import { RoleEditor, StatusBadge, personLabel } from './RolesTab';
import './register.css';

type CompanyRow = { role_id: string; code: string; number: number; name: string; description: string | null; main_sources: string | null; required_by: string[]; status: string | null; status_label: string; assignment: Assignment | null; applies_to: number; blocks_go_live_on: number; overrides: number };
type CompanyPage = { rows: CompanyRow[]; kpis: { systems: number; departments: number; roles_no_person: number; roles_pending: number; systems_blocked: number }; by_department: { department: string; systems: number; no_such_person: number; pending: number; blocked: number }[]; people: RolePerson[]; can: { set: boolean; mark_na: boolean } };
type Member = { id: string; user_id: string | null; name: string; job_title: string | null; external_party: string | null; committee_role: string; committee_role_label: string; covers_role_id: string | null; covers_role: string | null; department: string | null };
type Committee = { committee: { id: string; status: string; target_date: string | null; formed_on: string | null; charter_evidence_id: string | null; charter_note: string | null; meeting_cadence: string | null; approval_scope: string | null; recorded_by: string | null }; members: Member[]; can: { record: boolean; members: boolean } };
type CatalogRole = { id: string; name: string; level: string };

const COMMITTEE_ROLES = [{ value: 'chair', label: 'Chair' }, { value: 'secretary', label: 'Secretary' }, { value: 'legal', label: 'Legal member' }, { value: 'technical', label: 'Technical member' }, { value: 'business', label: 'Business member' }, { value: 'external_advisor_non_voting', label: 'External advisor, non-voting' }];
const CADENCE = [{ value: 'monthly', label: 'Monthly' }, { value: 'quarterly', label: 'Quarterly' }, { value: 'as_needed', label: 'As needed' }];
const SCOPE = [{ value: 'tier3_and_exceptions', label: 'Tier 3 systems and exceptions' }, { value: 'all_new_systems', label: 'All new AI systems' }];

export function CompanyRoles() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['company-roles'], queryFn: () => api.get<CompanyPage>('/governance/company-roles') });
  const cq = useQuery({ queryKey: ['committee'], queryFn: () => api.get<Committee>('/governance/committee') });
  const cat = useQuery({ queryKey: ['register', 'role-catalog'], queryFn: () => api.get<CatalogRole[]>('/register/role-catalog') });
  const [editing, setEditing] = useState<CompanyRow | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading || cq.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data || !cq.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error ?? cq.error)}</Alert></div>;
  const p = q.data;
  const k = p.kpis;
  const refresh = () => Promise.all([q.refetch(), cq.refetch(), qc.invalidateQueries({ queryKey: ['register'] })]);
  return (
    <div className="page reg-page">
      <PageHeader title="Company-wide roles and AI Governance Committee" subtitle="Roles set here apply to every AI system unless a system overrides them. Committee members become choices in every role list." />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <div className="reg-kpis" role="list" aria-label="Roles summary">
        <div className="tile reg-kpi" role="listitem"><div className="value">{k.systems}</div><div className="label">AI systems, {k.departments} departments</div></div>
        <div className={`tile reg-kpi ${k.roles_no_person ? 'reg-kpi-danger' : ''}`} role="listitem"><div className="value">{k.roles_no_person}</div><div className="label">Required roles with no person</div></div>
        <div className={`tile reg-kpi ${k.roles_pending ? 'reg-kpi-warn' : ''}`} role="listitem"><div className="value">{k.roles_pending}</div><div className="label">Roles waiting for the committee</div></div>
        <div className={`tile reg-kpi ${k.systems_blocked ? 'reg-kpi-danger' : ''}`} role="listitem"><div className="value">{k.systems_blocked}</div><div className="label">Systems blocked at go-live</div></div>
      </div>
      <section className="card">
        <div className="card-header"><h2>Company-wide roles</h2></div>
        <div className="card-body">
          <DataGrid label="Company-wide roles" rows={p.rows} rowId={(r) => r.role_id} rowLabel={(r) => r.name}
            columns={[
              { key: 'role', header: 'Role', value: (r) => r.number, render: (r) => <><strong>{r.name}</strong><div className="small muted">{r.required_by.length ? r.required_by.join(' · ') : r.main_sources}</div></> },
              { key: 'status', header: 'Status', value: (r) => r.status_label, render: (r) => <StatusBadge status={r.status} label={r.status_label} /> },
              { key: 'who', header: 'Person or party', value: (r) => r.assignment?.user?.name ?? r.assignment?.external_party ?? '', render: (r) => r.assignment?.status === 'assigned' ? <>{r.assignment.user?.name}{r.assignment.user?.job_title ? ` · ${r.assignment.user.job_title}` : ''}</> : r.assignment?.status === 'external' ? r.assignment.external_party : r.assignment?.status === 'not_applicable' ? <span className="small">{r.assignment.reason}</span> : r.assignment?.status === 'pending_committee' ? <span className="small">Target {fmtDate(r.assignment.target_date)}</span> : <span className="muted">—</span> },
              { key: 'backup', header: 'Backup', value: (r) => r.assignment?.backup_user?.name ?? '', render: (r) => r.assignment?.backup_user?.name ?? '—' },
              { key: 'applies', header: 'Applies to', value: (r) => r.applies_to, render: (r) => <>{r.applies_to} system{r.applies_to === 1 ? '' : 's'}{r.blocks_go_live_on > 0 && <div className="small reg-danger">Blocks go-live on {r.blocks_go_live_on}</div>}{r.overrides > 0 && <div className="small muted">{r.overrides} override{r.overrides === 1 ? '' : 's'}</div>}</> },
            ]}
            rowActions={(r) => [{ label: 'Edit role', disabled: !p.can.set, onSelect: () => setEditing(r) }]} />
        </div>
      </section>
      <section className="card">
        <div className="card-header"><h2>Roles missing, by department</h2></div>
        <div className="card-body stack-sm">
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Department</th><th>Systems</th><th>No such person</th><th>Pending</th><th>Blocked</th></tr></thead>
            <tbody>{p.by_department.map((d) => <tr key={d.department}><td>{d.department}</td><td>{d.systems}</td><td>{d.no_such_person}</td><td>{d.pending}</td><td>{d.blocked}</td></tr>)}</tbody>
          </table></div>
          <p className="small muted" style={{ margin: 0 }}>Company-wide roles count once for each system they block.</p>
        </div>
      </section>
      <CommitteeCard c={cq.data} people={p.people} catalog={cat.data ?? []} onChanged={refresh} onFlash={setFlash} />
      <p className="small muted" style={{ margin: 0 }}>The Chief AI Compliance Officer sets and changes company-wide roles, marks a required role Not applicable with a reason, approves go-live and records the committee. The Client Admin adds people to the user list and the committee member list that feed every role list, and imports systems by CSV.</p>
      {editing && <RoleEditor s={null} row={{ role_id: editing.role_id, name: editing.name, description: editing.description, level: 'company', extra_checks: null, requirement: editing.applies_to > 0 ? 'required' : 'recommended', assignment: editing.assignment, inherited: false }}
        people={p.people} can={{ mark_na: p.can.mark_na }} url={`/governance/company-roles/${editing.role_id}`} onClose={() => setEditing(null)}
        onSaved={async () => { setEditing(null); await refresh(); setFlash({ tone: 'success', text: `${editing.name} saved. Every system that inherits it is updated.` }); }} />}
    </div>
  );
}

function CommitteeCard({ c, people, catalog, onChanged, onFlash }: { c: Committee; people: RolePerson[]; catalog: CatalogRole[]; onChanged: () => unknown; onFlash: (f: { tone: 'success' | 'danger'; text: string }) => void }) {
  const cm = c.committee;
  const [f, setF] = useState({ target_date: cm.target_date ?? '', formed_on: cm.formed_on ?? '', charter_note: cm.charter_note ?? '', meeting_cadence: cm.meeting_cadence ?? '', approval_scope: cm.approval_scope ?? '' });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [member, setMember] = useState<Member | 'new' | null>(null);
  useEffect(() => setF({ target_date: cm.target_date ?? '', formed_on: cm.formed_on ?? '', charter_note: cm.charter_note ?? '', meeting_cadence: cm.meeting_cadence ?? '', approval_scope: cm.approval_scope ?? '' }), [cm]);
  const formed = cm.status === 'formed';
  const ro = !c.can.record || formed;
  async function saveDraft() {
    setFe({});
    try { await api.put('/governance/committee', { target_date: f.target_date || null, charter_note: f.charter_note, meeting_cadence: f.meeting_cadence || null, approval_scope: f.approval_scope || null }); await onChanged(); onFlash({ tone: 'success', text: 'Committee draft saved.' }); }
    catch (e) { setFe(fieldErrors(e)); onFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function record() {
    setFe({});
    try { await api.post('/governance/committee/formed', { ...f, target_date: f.target_date || null, meeting_cadence: f.meeting_cadence || null, approval_scope: f.approval_scope || null }); await onChanged(); onFlash({ tone: 'success', text: 'The committee is recorded as formed. Department Heads were told to pick a member for each role marked Pending committee.' }); }
    catch (e) { setFe(fieldErrors(e)); onFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function remove(m: Member) {
    try { await api.delete(`/governance/committee/members/${m.id}`); await onChanged(); } catch (e) { onFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  return (
    <section className="card">
      <div className="card-header"><h2>AI Governance Committee</h2>{formed ? <Badge tone="success">Formed {fmtDate(cm.formed_on)}</Badge> : <Badge tone="warn">Not yet formed{cm.target_date ? ` · target ${fmtDate(cm.target_date)}` : ''}</Badge>}</div>
      <div className="card-body stack">
        {!formed && <p className="small" style={{ margin: 0 }}>Record the committee when it is formed. Saving notifies Department Heads of the roles marked Pending committee so they can pick a member.</p>}
        <fieldset disabled={ro} className="reg-plain">
          <div className="grid-2">
            {!formed && <TextField label="Target date" help={H.target} type="date" value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} error={fe.target_date} />}
            <TextField label="Date formed *" help={H.formedOn} type="date" value={f.formed_on} onChange={(e) => setF({ ...f, formed_on: e.target.value })} error={fe.formed_on} />
            <TextField label="Charter *" help={H.charter} placeholder="For example AI Governance Committee Charter v1" value={f.charter_note} onChange={(e) => setF({ ...f, charter_note: e.target.value })} error={fe.charter} />
            <SelectField label="Meets" help={H.cadence} value={f.meeting_cadence} placeholder="Choose" onChange={(e) => setF({ ...f, meeting_cadence: e.target.value })} options={CADENCE} />
            <SelectField label="Approves" help={H.scope} value={f.approval_scope} placeholder="Choose" onChange={(e) => setF({ ...f, approval_scope: e.target.value })} options={SCOPE} />
          </div>
        </fieldset>
        {fe.members && <Alert tone="danger">{fe.members}</Alert>}
        <DataGrid label="Committee members" rows={c.members} rowId={(m) => m.id} rowLabel={(m) => m.name} emptyText="No members yet."
          columns={[
            { key: 'name', header: 'Member', value: (m) => m.name, render: (m) => <>{m.name}{m.job_title && <div className="small muted">{m.job_title}</div>}</> },
            { key: 'role', header: 'Committee role', value: (m) => m.committee_role_label },
            { key: 'covers', header: 'Covers governance role', value: (m) => m.covers_role ?? '', render: (m) => m.covers_role ?? (m.committee_role === 'external_advisor_non_voting' ? <span className="small muted">None (keeps audit independence)</span> : '—') },
            { key: 'dept', header: 'Department', value: (m) => m.department ?? '', render: (m) => m.department ?? '—' },
          ]}
          rowActions={(m) => [{ label: 'Edit member', disabled: !c.can.members, onSelect: () => setMember(m) }, { label: 'Remove from the committee', danger: true, disabled: !c.can.members, onSelect: () => void remove(m) }]} />
        <div className="row">
          {c.can.members && <Button onClick={() => setMember('new')}>Add a member</Button>}
          {c.can.record && !formed && <><Button onClick={saveDraft}>Save draft</Button><Button variant="primary" onClick={record}>Record committee as formed</Button></>}
        </div>
      </div>
      {member && <MemberDialog m={member === 'new' ? null : member} people={people} catalog={catalog} onClose={() => setMember(null)} onDone={async () => { setMember(null); await onChanged(); }} />}
    </section>
  );
}

function MemberDialog({ m, people, catalog, onClose, onDone }: { m: Member | null; people: RolePerson[]; catalog: CatalogRole[]; onClose: () => void; onDone: () => unknown }) {
  const [f, setF] = useState({ kind: m?.external_party ? 'external' : 'user', user_id: m?.user_id ?? '', external_party: m?.external_party ?? '', committee_role: m?.committee_role ?? 'business', covers_role_id: m?.covers_role_id ?? '' });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setErr(null); setFe({});
    const body = { user_id: f.kind === 'user' ? f.user_id || null : null, external_party: f.kind === 'external' ? f.external_party : null, committee_role: f.committee_role, covers_role_id: f.covers_role_id || null };
    try { if (m) await api.patch(`/governance/committee/members/${m.id}`, body); else await api.post('/governance/committee/members', body); await onDone(); }
    catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={m ? `Edit ${m.name}` : 'Add a committee member'} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="radio-group" role="radiogroup" aria-label="Member">
          <label className="radio-pill"><input type="radio" checked={f.kind === 'user'} onChange={() => setF({ ...f, kind: 'user' })} />A person in the company</label>
          <label className="radio-pill"><input type="radio" checked={f.kind === 'external'} onChange={() => setF({ ...f, kind: 'external' })} />An external party</label>
        </div>
        {f.kind === 'user' ? <SelectField label="Member *" help={H.member} value={f.user_id} placeholder="Choose" onChange={(e) => setF({ ...f, user_id: e.target.value })} options={people.map((p) => ({ value: p.id, label: personLabel({ ...p, committee_role: null }) }))} error={fe.user_id} />
          : <TextField label="External party *" help={H.externalParty} value={f.external_party} onChange={(e) => setF({ ...f, external_party: e.target.value })} error={fe.user_id ?? fe.external_party} />}
        <SelectField label="Committee role *" help={H.committeeRole} value={f.committee_role} onChange={(e) => setF({ ...f, committee_role: e.target.value, covers_role_id: e.target.value === 'external_advisor_non_voting' ? '' : f.covers_role_id })} options={COMMITTEE_ROLES} error={fe.committee_role} />
        <SelectField label="Covers governance role" help={H.covers} value={f.covers_role_id} placeholder="None" disabled={f.committee_role === 'external_advisor_non_voting'} onChange={(e) => setF({ ...f, covers_role_id: e.target.value })} options={catalog.map((r) => ({ value: r.id, label: r.name }))} error={fe.covers_role_id} />
        <div className="row"><Button variant="primary" onClick={go}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
