import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import { STAGE_OPTIONS, stageLabel, type RoleCatalogue as Catalogue, type RoleRow } from '@/api/regmaster';
import { roleHelp as H } from '@/help/regmaster';
import { RegTabs } from './LawLibrary';
import '@/styles/regmaster.css';

const LEVELS = [{ value: 'company', label: 'Company' }, { value: 'system', label: 'System' }, { value: 'agent', label: 'Agent' }];
const GROUPS: { level: string; title: string }[] = [{ level: 'company', title: 'Company-wide roles' }, { level: 'system', title: 'Roles for each AI system' }, { level: 'agent', title: 'Roles for each AI agent' }];

export function RoleCatalogue() {
  const [show, setShow] = useState('top');
  const q = useQuery({ queryKey: ['reg-roles', show], queryFn: () => api.get<Catalogue>(`/reg/roles?laws=${show}`) });
  const [editing, setEditing] = useState<RoleRow | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading && !q.data) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="Role and committee catalogue"
        subtitle="The 21 governance roles and which law requires each. A client's required roles are the union of the columns for the laws that apply to them; where laws differ, the stricter level and the earlier stage win. A refresh can propose a change to any cell." />
      <RegTabs />
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
        <div style={{ minWidth: 220 }}><SelectField label="Show laws" help={H.show} value={show} onChange={(e) => setShow(e.target.value)} options={[{ value: 'top', label: '10 most used' }, { value: 'all', label: `All laws with role maps` }]} /></div>
        <p className="small muted" style={{ margin: 0 }}><span className="reg-pill-req">Req</span> required by the law · <span className="reg-pill-rec">Rec</span> recommended or best practice · Company: filled once · System: per AI system · Agent: agents only</p>
      </div>
      <Card>
        <div className="reg-matrix-wrap" tabIndex={0} role="region" aria-label="Role by law matrix">
          <table className="reg-matrix">
            <thead><tr><th>Role and responsibility</th><th>Level</th><th>Needed by</th>{d.laws.map((l) => <th key={l.id} title={l.short_name}><Link to={`/reg/${l.id}`}>{l.label}</Link></th>)}{d.can_edit && <th><span className="sr-only">Actions</span></th>}</tr></thead>
            <tbody>
              {GROUPS.map((g) => {
                const rows = d.roles.filter((r) => r.level === g.level);
                if (!rows.length) return null;
                return [
                  <tr key={g.level} className="grp"><td colSpan={3 + d.laws.length + (d.can_edit ? 1 : 0)}>{g.title}</td></tr>,
                  ...rows.map((r) => (
                    <tr key={r.code}>
                      <td className="role-name"><strong>{r.name}</strong><div className="reg-sub">{r.description}</div></td>
                      <td>{LEVELS.find((x) => x.value === r.level)?.label}</td>
                      <td className="small">{stageLabel(r.default_stage)}</td>
                      {d.laws.map((l) => {
                        const c = d.cells[r.code]?.[l.id];
                        return <td key={l.id} className="cell" title={c?.basis ?? undefined}>{c ? (c.level === 'required' ? <span className="reg-pill-req">Req</span> : <span className="reg-pill-rec">Rec</span>) : <span className="muted" aria-label="Not required">–</span>}</td>;
                      })}
                      {d.can_edit && <td><Button size="sm" onClick={() => setEditing(r)} aria-label={`Edit ${r.name}`}>Edit</Button></td>}
                    </tr>
                  )),
                ];
              })}
            </tbody>
          </table>
        </div>
        <p className="reg-note">Each cell links to the requirement and citation on the law record. Hover a cell to see its basis.</p>
      </Card>
      <h2 style={{ marginTop: 28 }}>Committee and program rules</h2>
      <div className="reg-committees" style={{ marginTop: 12 }}>
        {d.committees.map((c) => (
          <Card key={c.committee_type} title={c.title}>
            <p className="small"><Badge tone={c.level === 'required' ? 'success' : 'navy'}>{c.level === 'required' ? 'Required' : 'Recommended'}</Badge> {c.sources.map((s) => s.basis || s.law).join('; ')}</p>
            {c.sources.some((s) => s.condition) && <p className="small muted">{c.sources.map((s) => s.condition).filter(Boolean).join(' ')}</p>}
            <ul>{c.items.map((i) => <li key={i} className="small">{i}</li>)}</ul>
          </Card>
        ))}
      </div>
      {editing && <RoleEditor role={editing} cat={d} onClose={() => setEditing(null)} onDone={(m) => { setEditing(null); setFlash(m); q.refetch(); }} />}
    </div>
  );
}

function RoleEditor({ role, cat, onClose, onDone }: { role: RoleRow; cat: Catalogue; onClose: () => void; onDone: (m: string) => void }) {
  const [f, setF] = useState({ name: role.name, level: role.level, default_stage: role.default_stage, extra_checks: role.extra_checks ?? '', description: role.description ?? '' });
  const start = Object.fromEntries(cat.laws.map((l) => [l.id, { level: cat.cells[role.code]?.[l.id]?.level ?? 'not_required', needed_by_stage: cat.cells[role.code]?.[l.id]?.needed_by_stage ?? role.default_stage }]));
  const [levels, setLevels] = useState<Record<string, { level: string; needed_by_stage: string }>>(start);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const changed = cat.laws.filter((l) => JSON.stringify(levels[l.id]) !== JSON.stringify(start[l.id]));
  async function save() {
    setErr(null); setErrs({});
    try {
      const meta = Object.fromEntries(Object.entries({ ...f, extra_checks: f.extra_checks || null }).filter(([k, v]) => v !== ((role as unknown as Record<string, unknown>)[k] ?? (k === 'extra_checks' ? null : ''))));
      if (Object.keys(meta).length) await api.patch(`/reg/roles/${role.code}`, meta);
      for (const l of changed) {
        const v = levels[l.id];
        await api.post(`/reg/laws/${l.id}/proposals`, { changes: [{ field_path: `role_map.${role.code}`, new_value: v.level === 'not_required' ? null : { level: v.level, needed_by_stage: v.needed_by_stage }, change_type: 'role_mapping' }], summary: `${role.name}: ${v.level.replace('_', ' ')} under ${l.label}`, reason: reason || null });
      }
      onDone(`${Object.keys(meta).length ? 'Role details saved. ' : ''}${changed.length ? `${changed.length} level ${changed.length === 1 ? 'change' : 'changes'} sent to the Chief Auditor as proposed changes.` : ''}`.trim() || 'Nothing changed.');
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); }
  }
  return (
    <Dialog title={`Edit role: ${role.name}`} onClose={onClose} large>
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="reg-form-grid">
        <TextField label="Role name *" help={H.name} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={errs.name} />
        <SelectField label="Level *" help={H.level} value={f.level} onChange={(e) => setF({ ...f, level: e.target.value })} options={LEVELS} />
        <SelectField label="Default needed by *" help={H.stage} value={f.default_stage} onChange={(e) => setF({ ...f, default_stage: e.target.value })} options={STAGE_OPTIONS} />
        <SelectField label="Extra checks when assigned" help={H.checks} value={f.extra_checks} onChange={(e) => setF({ ...f, extra_checks: e.target.value })} placeholder="None" options={[{ value: 'oversight_confirmations', label: 'Training completed + authority to override' }]} />
      </div>
      <TextArea label="Responsibility (shown in the intro letter) *" help={H.description} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} error={errs.description} rows={2} />
      <div className="table-wrap" style={{ marginTop: 12 }}>
        <table className="table">
          <thead><tr><th>Law</th><th>Level</th><th>Needed by</th><th>Basis</th></tr></thead>
          <tbody>{cat.laws.map((l) => (
            <tr key={l.id}>
              <td>{l.label}</td>
              <td><select className="select" aria-label={`Level under ${l.label}`} value={levels[l.id].level} onChange={(e) => setLevels({ ...levels, [l.id]: { ...levels[l.id], level: e.target.value } })}>
                <option value="required">Required</option><option value="recommended">Recommended</option><option value="not_required">Not required</option></select></td>
              <td><select className="select" aria-label={`Needed by under ${l.label}`} value={levels[l.id].needed_by_stage} disabled={levels[l.id].level === 'not_required'} onChange={(e) => setLevels({ ...levels, [l.id]: { ...levels[l.id], needed_by_stage: e.target.value } })}>
                {STAGE_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}</select></td>
              <td className="small">{cat.cells[role.code]?.[l.id]?.basis ?? '—'}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {changed.length > 0 && <>
        <Alert tone="warn">Changing a level updates the required roles on every client AI system under that law, once the Chief Auditor approves.</Alert>
        <TextField label="Reason for change" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} />
      </>}
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save{changed.length ? ' as proposed change' : ''}</Button></div>
    </Dialog>
  );
}
