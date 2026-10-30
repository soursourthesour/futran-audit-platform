import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { ROLE_STATUSES, STATUS_TONE, type RegSystem, type RolePerson, type RoleRow, type RolesPage } from '@/api/register';
import { Alert, Badge, Button, Checkbox, Dialog, FieldGroup, Loading, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { roleHelp as H } from '@/help/register';

export function personLabel(p: RolePerson) {
  return [p.name, p.job_title, p.committee_role ? `Committee: ${p.committee_role}` : null].filter(Boolean).join(' · ');
}

export function whoCell(r: Pick<RoleRow, 'status' | 'assignment' | 'inherited'>) {
  const a = r.assignment;
  if (!a) return <span className="muted">—</span>;
  if (a.status === 'assigned') return <>{a.user?.name}{a.user?.job_title ? ` · ${a.user.job_title}` : ''}{a.extra_users.length > 0 && <div className="small">and {a.extra_users.map((u) => u.name).join(', ')}</div>}</>;
  if (a.status === 'external') return <>{a.external_party}{a.external_contact && <div className="small muted">{a.external_contact}</div>}</>;
  if (a.status === 'pending_committee') return <span className="muted">Chosen when the committee is formed</span>;
  return <span className="muted">—</span>;
}

export function noteCell(r: Pick<RoleRow, 'status' | 'assignment' | 'inherited' | 'level' | 'due_for_gate'>) {
  const a = r.assignment;
  if (r.inherited) return <span className="small muted">Inherited from company settings</span>;
  if (!a) return <span className="small muted">{r.due_for_gate ? 'Needed before go-live' : 'Not answered'}</span>;
  if (a.status === 'pending_committee') return <span className="small">{fmtDate(a.target_date)}</span>;
  if (a.status === 'not_applicable') return <span className="small">{a.reason}</span>;
  if (a.status === 'no_such_person') return <span className="small reg-danger">{r.level === 'company' ? 'Ask the Chief AI Compliance Officer to assign' : r.due_for_gate ? 'Blocks go-live; raises a finding if still empty when live' : 'Recorded as a gap'}</span>;
  return <span className="small">{a.override ? `Override: ${a.override_reason}` : a.backup_user ? `Backup: ${a.backup_user.name}` : a.notes ?? ''}</span>;
}

export function StatusBadge({ status, label }: { status: string | null; label: string }) {
  return <Badge tone={status ? STATUS_TONE[status] ?? 'muted' : 'muted'}>{label}</Badge>;
}

export function RolesTab({ s, onChanged }: { s: RegSystem; onChanged: () => unknown }) {
  const q = useQuery({ queryKey: ['register-roles', s.id], queryFn: () => api.get<RolesPage>(`/register/${s.id}/roles`) });
  const [gapsOnly, setGapsOnly] = useState(false);
  const [editing, setEditing] = useState<RoleRow | null>(null);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const p = q.data;
  const show = (r: RoleRow) => !gapsOnly || (!r.filled && r.requirement === 'required');
  const company = p.rows.filter((r) => r.level === 'company' && show(r));
  const own = p.rows.filter((r) => r.level !== 'company' && show(r));
  const blockers = [...p.gate.roles, ...p.gate.requirements];
  const canEdit = (r: RoleRow) => (r.level === 'company' ? p.can.company : p.can.fill);
  const cols: GridColumn<RoleRow>[] = [
    { key: 'name', header: 'Role', value: (r) => r.number, render: (r) => <><strong>{r.name}</strong>{r.level === 'agent' && <div className="small muted">Agents</div>}</> },
    { key: 'by', header: 'Required by', value: (r) => r.required_by.join(', '), render: (r) => <span className="small">{r.required_by.join(' · ') || '—'}{r.basis && <div className="muted">{r.basis}</div>}</span> },
    { key: 'needed', header: 'Needed by', value: (r) => r.needed_by_label, render: (r) => r.requirement === 'recommended' ? <Badge tone="muted">Recommended</Badge> : r.needed_by_label },
    { key: 'status', header: 'Status', value: (r) => r.status_label, render: (r) => <StatusBadge status={r.status} label={r.status_label} /> },
    { key: 'who', header: 'Person or party', value: (r) => r.assignment?.user?.name ?? r.assignment?.external_party ?? '', render: whoCell },
    { key: 'note', header: 'Target date or reason', sortable: false, render: noteCell },
  ];
  return (
    <div className="stack">
      {blockers.length > 0 && s.stage !== 'live' && (
        <Alert tone="danger"><strong>{s.stage === 'ready_for_go_live' ? 'Go-live blocked' : 'Needed before go-live'}:</strong> {blockers.length} item{blockers.length === 1 ? '' : 's'} required at go-live {blockers.length === 1 ? 'is' : 'are'} not filled. {blockers.join('; ')}.</Alert>
      )}
      {s.laws.length === 0 && <Alert tone="warn">No laws are chosen for this system, so no role is required yet. Choose the laws on the Details tab.</Alert>}
      <div className="row reg-legend" aria-label="Status key">
        <span className="small muted">Status key:</span>{ROLE_STATUSES.map((x) => <StatusBadge key={x.value} status={x.value} label={x.label} />)}
        <span className="spacer" />
        <Checkbox label="Show only gaps" checked={gapsOnly} onChange={(e) => setGapsOnly(e.target.checked)} />
      </div>
      <p className="small muted" style={{ margin: 0 }}>Which roles are required, and by when, is worked out from the laws and the stage on this system.</p>
      <section className="card">
        <div className="card-header"><h2>Company-wide roles</h2><span className="small muted">Set by the Chief AI Compliance Officer, applied to every system</span></div>
        <div className="card-body">
          <DataGrid label="Company-wide roles" rows={company} rowId={(r) => r.role_id} rowLabel={(r) => r.name} columns={cols} emptyText="No company-wide role needs attention."
            rowActions={(r) => [{ label: p.can.company ? 'Override for this system' : 'Set under Governance roles', disabled: !p.can.company, onSelect: () => setEditing(r) }]} />
        </div>
      </section>
      <section className="card">
        <div className="card-header"><h2>Roles for this AI system</h2><span className="small muted">Filled by the Department Head</span></div>
        <div className="card-body">
          <DataGrid label="Roles for this AI system" rows={own} rowId={(r) => r.role_id} rowLabel={(r) => r.name} columns={cols} emptyText="No role for this system needs attention."
            rowActions={(r) => [{ label: 'Edit role', disabled: !canEdit(r), onSelect: () => setEditing(r) }]} />
        </div>
      </section>
      {editing && <RoleEditor s={s} row={editing} people={p.people} can={p.can} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await q.refetch(); await onChanged(); }} />}
    </div>
  );
}

export function RoleEditor({ s, row, people, can, onClose, onSaved, url }: {
  s: RegSystem | null; row: Pick<RoleRow, 'role_id' | 'name' | 'description' | 'level' | 'extra_checks' | 'requirement' | 'assignment' | 'inherited'>; people: RolePerson[];
  can: { mark_na: boolean; company?: boolean }; onClose: () => void; onSaved: () => unknown; url?: string;
}) {
  const a = row.inherited ? null : row.assignment;
  const override = !!s && row.level === 'company';
  const [f, setF] = useState({
    status: a?.status ?? 'assigned', user_id: a?.user?.id ?? '', backup_user_id: a?.backup_user?.id ?? '', effective_from: a?.effective_from ?? '', external_party: a?.external_party ?? '',
    external_contact: a?.external_contact ?? '', target_date: a?.target_date ?? '', reason: a?.reason ?? '', training_completed: a?.training_completed ?? false,
    has_authority_to_override: a?.has_authority_to_override ?? false, notes: a?.notes ?? '', override_reason: a?.override_reason ?? '', evidence_ids: a?.evidence_ids ?? [] as string[],
  });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const opts = people.map((p) => ({ value: p.id, label: personLabel(p) }));
  const naLocked = row.requirement === 'required' && !can.mark_na;
  async function uploadEvidence(file?: File) {
    if (!file || !s) return;
    const fd = new FormData();
    fd.append('file', file);
    try { const r = await api.upload<{ id: string }>(`/register/${s.id}/evidence`, fd); setF((x) => ({ ...x, evidence_ids: [...x.evidence_ids, r.id] })); } catch (e) { setErr(errorMessage(e)); }
  }
  async function save() {
    setBusy(true); setErr(null); setFe({});
    try {
      await api.put(url ?? `/register/${s!.id}/roles/${row.role_id}`, { ...f, ...(override ? { override: true } : {}) });
      await onSaved();
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  const statusText: Record<string, string> = {
    assigned: 'Pick from the company\'s users', external: 'A vendor, auditor or service provider', no_such_person: 'Recorded as a gap; blocks go-live for this role',
    pending_committee: 'Pick the person once the committee is formed', not_applicable: naLocked ? 'Only the Chief AI Compliance Officer can choose this for a required role' : 'Say why it does not apply',
  };
  return (
    <Dialog title={row.name} onClose={onClose} wide>
      <div className="stack">
        {row.description && <p className="small" style={{ margin: 0 }}>{row.description}</p>}
        {override && <Alert tone="info">This role is set company-wide. Saving here overrides it for {s!.name} only. The Chief AI Compliance Officer sees every override.</Alert>}
        {err && <Alert tone="danger">{err}</Alert>}
        <FieldGroup legend="Is there such a person? *" help={H.status}>
          <div className="stack-sm">
            {ROLE_STATUSES.map((x) => (
              <label key={x.value} className="radio-pill reg-radio"><input type="radio" name="role-status" value={x.value} checked={f.status === x.value} disabled={x.value === 'not_applicable' && naLocked} onChange={() => setF({ ...f, status: x.value })} />
                <span><strong>{x.value === 'assigned' ? 'Yes, assign a person' : x.value === 'external' ? 'Yes, an external party' : x.label}</strong> <span className="small muted">{statusText[x.value]}</span></span></label>
            ))}
          </div>
          {fe.status && <p className="small reg-danger">{fe.status}</p>}
        </FieldGroup>
        {f.status === 'assigned' && (
          <div className="grid-2">
            <SelectField label="Person *" help={H.person} value={f.user_id} placeholder="Choose" onChange={(e) => setF({ ...f, user_id: e.target.value })} options={opts} error={fe.user_id} />
            <SelectField label="Backup person" help={H.backup} value={f.backup_user_id} placeholder="None" onChange={(e) => setF({ ...f, backup_user_id: e.target.value })} options={opts} error={fe.backup_user_id} />
            <TextField label="Effective from" help={H.effectiveFrom} type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} error={fe.effective_from} />
          </div>
        )}
        {f.status === 'external' && (
          <div className="grid-2">
            <TextField label="External party *" help={H.party} value={f.external_party} onChange={(e) => setF({ ...f, external_party: e.target.value })} error={fe.external_party} />
            <TextField label="Contact" help={H.contact} value={f.external_contact} onChange={(e) => setF({ ...f, external_contact: e.target.value })} />
          </div>
        )}
        {f.status === 'pending_committee' && <TextField label="Target date *" help={H.target} type="date" value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} error={fe.target_date} />}
        {f.status === 'not_applicable' && <TextArea label="Reason *" help={H.reason} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} error={fe.reason} />}
        {row.extra_checks === 'oversight_confirmations' && ['assigned', 'external'].includes(f.status) && (
          <div className="stack-sm">
            <Checkbox label="Has completed AI oversight training" help={H.training} checked={!!f.training_completed} onChange={(e) => setF({ ...f, training_completed: e.target.checked })} />
            <Checkbox label="Has the authority to stop or override the system's output" help={H.authority} checked={!!f.has_authority_to_override} onChange={(e) => setF({ ...f, has_authority_to_override: e.target.checked })} />
          </div>
        )}
        {override && <TextArea label="Why this system does not use the company-wide person *" help={H.overrideReason} value={f.override_reason} onChange={(e) => setF({ ...f, override_reason: e.target.value })} error={fe.override_reason} />}
        {s && <TextField label="Evidence (appointment letter or RACI)" help={H.evidence} type="file" hint={f.evidence_ids.length ? `${f.evidence_ids.length} file${f.evidence_ids.length === 1 ? '' : 's'} attached` : undefined} onChange={(e) => void uploadEvidence(e.target.files?.[0])} />}
        <TextArea label="Notes" help={H.notes} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        <div className="row"><Button variant="primary" disabled={busy} onClick={save}>Save role</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
