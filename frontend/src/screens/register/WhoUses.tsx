import { useMemo, useState } from 'react';
import type { Opt, RegPerson, UserSelection } from '@/api/register';
import { Button, Checkbox, FieldGroup, SelectField, TextField } from '@/components/ui';
import { whoHelp as H } from '@/help/register';

/* 11-03 C10: "Who uses it". By role level: job levels, AI compliance roles and (optionally) job titles from the client's
   user list. Named users: a searchable multi-select with a department filter, select all and clear. The number of
   users is calculated from the selection, the same way the server calculates it. */

export const JOB_LEVELS: Opt[] = [
  { value: 'executive', label: 'Executive' }, { value: 'department_head', label: 'Department head' }, { value: 'manager', label: 'Manager' },
  { value: 'level_3', label: 'Level 3' }, { value: 'level_2', label: 'Level 2' }, { value: 'level_1', label: 'Level 1' },
];
export const COMPLIANCE_ROLES: Opt[] = [
  { value: 'caico', label: 'Chief AI Compliance Officer' }, { value: 'client_admin', label: 'Client Admin' }, { value: 'exec_sponsor', label: 'Executive Sponsor' },
  { value: 'dpo', label: 'Data Protection Officer' }, { value: 'dept_compliance_lead', label: 'Department Compliance Lead' }, { value: 'contributor', label: 'Contributor' },
];

type Scope = { department_id: string; department_ids: string[]; company_wide: boolean; multi_dept: boolean };

/** People a role-level choice can reach: those in the system's departments, or everyone for a company-wide tool. */
export function inScope(people: RegPerson[], s: Scope): RegPerson[] {
  const depts = new Set([s.department_id, ...(s.multi_dept ? s.department_ids : [])].filter(Boolean));
  return depts.size && !s.company_wide ? people.filter((p) => p.department_id && depts.has(p.department_id)) : people;
}

export function countFor(scope: string, sel: UserSelection, people: RegPerson[], s: Scope): number | null {
  if (scope === 'named') return sel.user_ids?.length ? people.filter((p) => sel.user_ids!.includes(p.id)).length : null;
  if (scope !== 'role') return null;
  const levels = new Set(sel.job_levels ?? []); const roles = new Set(sel.compliance_roles ?? []); const titles = new Set((sel.job_titles ?? []).map((t) => t.trim().toLowerCase()));
  if (!levels.size && !roles.size && !titles.size) return null;
  return inScope(people, s).filter((p) => (p.job_level && levels.has(p.job_level)) || (p.compliance_roles ?? []).some((r) => roles.has(r)) || titles.has((p.job_title ?? '').trim().toLowerCase())).length;
}

function toggle(list: string[] | undefined, v: string): string[] {
  const l = list ?? [];
  return l.includes(v) ? l.filter((x) => x !== v) : [...l, v];
}

type Props = {
  scope: string; sel: UserSelection; people: RegPerson[]; departments: { id: string; name: string }[]; s: Scope;
  jobLevels?: Opt[]; complianceRoles?: Opt[]; onScope: (v: string) => void; onSel: (sel: UserSelection) => void; disabled?: boolean;
};

export function WhoUses({ scope, sel, people, departments, s, jobLevels = JOB_LEVELS, complianceRoles = COMPLIANCE_ROLES, onScope, onSel, disabled }: Props) {
  return (
    <div className="stack reg-who">
      <SelectField label="Who uses it" help={H.scope} value={scope} placeholder="Choose" disabled={disabled} onChange={(e) => onScope(e.target.value)}
        options={[{ value: 'role', label: 'By role level' }, { value: 'named', label: 'Named users' }]} hint="Named users are required for Tier 2 and 3." />
      {scope === 'role' && <ByRole sel={sel} people={people} s={s} jobLevels={jobLevels} complianceRoles={complianceRoles} onSel={onSel} disabled={disabled} />}
      {scope === 'named' && <Named sel={sel} people={people} departments={departments} onSel={onSel} disabled={disabled} />}
    </div>
  );
}

function ByRole({ sel, people, s, jobLevels, complianceRoles, onSel, disabled }: { sel: UserSelection; people: RegPerson[]; s: Scope; jobLevels: Opt[]; complianceRoles: Opt[]; onSel: (x: UserSelection) => void; disabled?: boolean }) {
  const pool = inScope(people, s);
  const [q, setQ] = useState('');
  const titles = useMemo(() => {
    const m = new Map<string, number>();
    pool.forEach((p) => { const t = (p.job_title ?? '').trim(); if (t) m.set(t, (m.get(t) ?? 0) + 1); });
    return [...m].sort((a, b) => a[0].localeCompare(b[0]));
  }, [pool]);
  const shownTitles = titles.filter(([t]) => !q.trim() || t.toLowerCase().includes(q.trim().toLowerCase()) || (sel.job_titles ?? []).includes(t));
  const n = (pred: (p: RegPerson) => boolean) => pool.filter(pred).length;
  const anyLevel = people.some((p) => p.job_level);
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>{s.company_wide ? 'Counted across the whole company.' : 'Counted among the people in the departments that use it.'} A person is counted once if they match any choice.</p>
      <FieldGroup legend="Job levels" help={H.levels}>
        {!anyLevel && <p className="small muted" style={{ margin: '0 0 6px' }}>No job levels are recorded in the user list yet, so these count nobody until they are added under People.</p>}
        <div className="grid-2">{jobLevels.map((x) => <Checkbox key={x.value} disabled={disabled} label={`${x.label} (${n((p) => p.job_level === x.value)})`} checked={(sel.job_levels ?? []).includes(x.value)} onChange={() => onSel({ ...sel, job_levels: toggle(sel.job_levels, x.value) })} />)}</div>
      </FieldGroup>
      <FieldGroup legend="AI compliance roles" help={H.roles}>
        <div className="grid-2">{complianceRoles.map((x) => <Checkbox key={x.value} disabled={disabled} label={`${x.label} (${n((p) => (p.compliance_roles ?? []).includes(x.value))})`} checked={(sel.compliance_roles ?? []).includes(x.value)} onChange={() => onSel({ ...sel, compliance_roles: toggle(sel.compliance_roles, x.value) })} />)}</div>
      </FieldGroup>
      {titles.length > 0 && (
        <FieldGroup legend="Job titles (optional)" help={H.titles}>
          {titles.length > 8 && <TextField label="Find a job title" value={q} disabled={disabled} onChange={(e) => setQ(e.target.value)} />}
          <div className="reg-pick-list" role="group" aria-label="Job titles">{shownTitles.map(([t, c]) => <Checkbox key={t} disabled={disabled} label={`${t} (${c})`} checked={(sel.job_titles ?? []).includes(t)} onChange={() => onSel({ ...sel, job_titles: toggle(sel.job_titles, t) })} />)}</div>
        </FieldGroup>
      )}
    </div>
  );
}

function Named({ sel, people, departments, onSel, disabled }: { sel: UserSelection; people: RegPerson[]; departments: { id: string; name: string }[]; onSel: (x: UserSelection) => void; disabled?: boolean }) {
  const [q, setQ] = useState('');
  const [dept, setDept] = useState('');
  const names = Object.fromEntries(departments.map((d) => [d.id, d.name]));
  const term = q.trim().toLowerCase();
  const shown = people.filter((p) => (!dept || (dept === '_none' ? !p.department_id : p.department_id === dept)) && (!term || `${p.name} ${p.job_title ?? ''}`.toLowerCase().includes(term)));
  const chosen = new Set(sel.user_ids ?? []);
  return (
    <div className="stack">
      <div className="grid-2">
        <TextField label="Search people" type="search" value={q} disabled={disabled} onChange={(e) => setQ(e.target.value)} placeholder="Name or job title" />
        <SelectField label="Department" value={dept} disabled={disabled} placeholder="All departments" onChange={(e) => setDept(e.target.value)} options={[...departments.map((d) => ({ value: d.id, label: d.name })), { value: '_none', label: 'No department' }]} />
      </div>
      <div className="row">
        <Button size="sm" disabled={disabled || !shown.length} onClick={() => onSel({ ...sel, user_ids: [...new Set([...(sel.user_ids ?? []), ...shown.map((p) => p.id)])] })}>Select all{q || dept ? ' shown' : ''} ({shown.length})</Button>
        <Button size="sm" variant="ghost" disabled={disabled || !chosen.size} onClick={() => onSel({ ...sel, user_ids: (sel.user_ids ?? []).filter((id) => !shown.some((p) => p.id === id)) })}>Clear{q || dept ? ' shown' : ''}</Button>
        <span className="small muted" aria-live="polite">{chosen.size} selected</span>
      </div>
      <div className="reg-pick-list" role="group" aria-label="People">
        {shown.length === 0 && <p className="small muted" style={{ margin: 0 }}>No one matches.</p>}
        {shown.map((p) => (
          <Checkbox key={p.id} disabled={disabled} checked={chosen.has(p.id)} onChange={() => onSel({ ...sel, user_ids: toggle(sel.user_ids, p.id) })}
            label={<>{p.name}<span className="small muted">{[p.job_title, p.department_id ? names[p.department_id] : null].filter(Boolean).map((x) => ` · ${x}`).join('')}</span></>} />
        ))}
      </div>
    </div>
  );
}
