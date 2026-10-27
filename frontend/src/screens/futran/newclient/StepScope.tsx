import { useState } from 'react';
import { DATA_ENVIRONMENTS, DEPARTMENT_PRESETS, ENGAGEMENT_TYPES, FRAMEWORKS, useTeamOptions, type Scope } from '@/api/clients';
import { Button, Card, Checkbox, FieldGroup, SelectField, TextArea, TextField } from '@/components/ui';
import { scopeHelp as H } from '@/help/onboarding';
import { useStepForm, useWizardCtx } from './Wizard';

const SINGLE_ROLES = [
  { role: 'chief_auditor', label: 'Chief Auditor (Lead Auditor) *', help: H.chiefAuditor, needs: ['chief_auditor'], required: true },
  { role: 'engagement_manager', label: 'Engagement Manager *', help: H.engagementManager, needs: [], required: true },
  { role: 'qa_reviewer', label: 'QA Reviewer', help: H.qaReviewer, needs: ['qa_reviewer', 'chief_auditor'], required: false },
  { role: 'legal_reviewer', label: 'Legal / compliance reviewer', help: H.legalReviewer, needs: [], required: false },
];

/** Role names as the conflict confirmation records them. The Chief Auditor is also the engagement's Lead Auditor. */
export const ROLE_ORDER = ['chief_auditor', 'engagement_manager', 'auditor', 'qa_reviewer', 'legal_reviewer'];
export const TEAM_ROLE_LABELS: Record<string, string> = {
  chief_auditor: 'Chief Auditor (Lead Auditor)', engagement_manager: 'Engagement Manager', auditor: 'Auditor', qa_reviewer: 'QA Reviewer', legal_reviewer: 'Legal / compliance reviewer',
};
export function rolesLabel(roles: string[]): string {
  const names = roles.map((r) => TEAM_ROLE_LABELS[r] ?? r);
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

export function StepScope() {
  const { data, errors, editable } = useWizardCtx();
  const people = useTeamOptions();
  const [f, setF] = useStepForm<Scope>('scope', data.scope);
  const [newDept, setNewDept] = useState('');
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v } as Scope);
  const str = (k: string) => (f[k] as string | null) ?? '';
  const list = (k: string) => (f[k] as string[] | null) ?? [];
  const toggleIn = (k: string, v: string) => set(k, list(k).includes(v) ? list(k).filter((x) => x !== v) : [...list(k), v]);
  const err = (k: string) => errors[`scope.${k}`];
  const client = data.company.trading_name || data.company.legal_name || 'the client';
  const teamErrors = Object.entries(errors).filter(([k]) => k.startsWith('scope.team')).map(([, v]) => v);

  const team = f.team ?? [];
  const holder = (role: string) => team.find((t) => t.role === role)?.user_id ?? '';
  const setSingle = (role: string, userId: string) => {
    const rest = team.filter((t) => t.role !== role);
    set('team', userId ? [...rest, { user_id: userId, role, conflict_confirmed: false }] : rest);
  };
  const auditors = team.filter((t) => t.role === 'auditor').map((t) => t.user_id);
  const toggleAuditor = (id: string) => set('team', auditors.includes(id) ? team.filter((t) => !(t.role === 'auditor' && t.user_id === id)) : [...team, { user_id: id, role: 'auditor', conflict_confirmed: false }]);
  // One confirmation per person, covering every role they hold on this engagement.
  const confirmPerson = (userId: string, v: boolean) => set('team', team.map((t) => (t.user_id === userId ? { ...t, conflict_confirmed: v } : t)));
  const teamPeople = [...new Set(team.map((t) => t.user_id))].map((id) => {
    const rows = team.filter((t) => t.user_id === id);
    const roles = ROLE_ORDER.filter((r) => rows.some((t) => t.role === r));
    return { id, roles, confirmed: rows.every((t) => t.conflict_confirmed) };
  }).sort((a, b) => ROLE_ORDER.indexOf(a.roles[0]) - ROLE_ORDER.indexOf(b.roles[0]));
  const nameOf = (id: string) => people.data?.find((p) => p.user_id === id)?.name ?? team.find((t) => t.user_id === id)?.name ?? 'Team member';
  const opts = (needs: string[]) => (people.data ?? []).filter((p) => !needs.length || p.roles.some((r) => needs.includes(r))).map((p) => ({ value: p.user_id, label: p.name }));
  const depts = [...new Set([...DEPARTMENT_PRESETS, ...f.departments])];

  return (
    <fieldset disabled={!editable} className="stack">
      <Card title="Engagement">
        <div className="stack">
          <FieldGroup legend="Engagement type *" help={H.type}>
            <div className="row" role="radiogroup" style={{ gap: 6 }}>
              {ENGAGEMENT_TYPES.map((t) => <label key={t.value} className="radio-pill"><input type="radio" name="type" checked={f.type === t.value} onChange={() => set('type', t.value)} />{t.label}</label>)}
            </div>
          </FieldGroup>
          <div className="grid-2">
            <TextField type="date" label="Audit period start *" help={H.periodStart} value={str('period_start')} onChange={(e) => set('period_start', e.target.value)} error={err('period_start')} />
            <TextField type="date" label="Audit period end *" help={H.periodEnd} value={str('period_end')} onChange={(e) => set('period_end', e.target.value)} error={err('period_end')} />
            <TextField type="date" label="Engagement start *" help={H.fieldworkStart} value={str('fieldwork_start')} onChange={(e) => set('fieldwork_start', e.target.value)} error={err('fieldwork_start')} />
            <TextField type="date" label="Engagement letter signed by" help={H.letterDue} value={str('letter_due')} onChange={(e) => set('letter_due', e.target.value)} />
            <TextField type="date" label="Target date for the draft report *" help={H.draftTarget} value={str('draft_report_target')} onChange={(e) => set('draft_report_target', e.target.value)} error={err('draft_report_target')} />
            <TextField type="date" label="Target date for the final report *" help={H.finalTarget} value={str('final_report_target')} onChange={(e) => set('final_report_target', e.target.value)} error={err('final_report_target')} />
            <TextField label="Audit methodology version" help={H.methodology} value={str('methodology_version')} onChange={(e) => set('methodology_version', e.target.value)} />
          </div>
        </div>
      </Card>
      <Card title="Scope and boundaries">
        <div className="stack">
          <FieldGroup legend="Departments or functions in scope *" help={H.departments}>
            <div className="row" style={{ gap: 6 }}>
              {depts.map((d) => <label key={d} className="radio-pill"><input type="checkbox" checked={f.departments.includes(d)} onChange={() => set('departments', f.departments.includes(d) ? f.departments.filter((x) => x !== d) : [...f.departments, d])} />{d}</label>)}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <input className="input" style={{ maxWidth: 280 }} aria-label="Another department" placeholder="Another department" value={newDept} onChange={(e) => setNewDept(e.target.value)} />
              <Button size="sm" onClick={() => { if (newDept.trim()) { set('departments', [...f.departments, newDept.trim()]); setNewDept(''); } }}>Add</Button>
            </div>
            {err('departments') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('departments')}</p>}
          </FieldGroup>
          <TextArea label="AI systems in scope *" value={list('planned_systems').join('\n')} onChange={(e) => set('planned_systems', e.target.value.split('\n'))} help={H.plannedSystems} error={err('planned_systems')} />
          <TextArea label="AI systems excluded, with the reason" help={H.systemsExcluded} value={str('systems_excluded')} onChange={(e) => set('systems_excluded', e.target.value)} />
          <TextArea label="Business processes in scope *" help={H.businessProcesses} value={str('business_processes')} onChange={(e) => set('business_processes', e.target.value)} error={err('business_processes')} />
          <FieldGroup legend="Data environments in scope *" help={H.dataEnvironments}>
            <div className="row" style={{ gap: 6 }}>{DATA_ENVIRONMENTS.map((d) => <label key={d.value} className="radio-pill"><input type="checkbox" checked={list('data_environments').includes(d.value)} onChange={() => toggleIn('data_environments', d.value)} />{d.label}</label>)}</div>
            {err('data_environments') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('data_environments')}</p>}
          </FieldGroup>
          <TextArea label="Geographic scope *" help={H.geographicScope} value={str('geographic_scope')} onChange={(e) => set('geographic_scope', e.target.value)} error={err('geographic_scope')} />
          <FieldGroup legend="Regulatory frameworks in scope *" help={H.frameworks}>
            <div className="row" style={{ gap: 6 }}>{FRAMEWORKS.map((x) => <label key={x.value} className="radio-pill"><input type="checkbox" checked={list('frameworks').includes(x.value)} onChange={() => toggleIn('frameworks', x.value)} />{x.label}</label>)}</div>
            {err('frameworks') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('frameworks')}</p>}
          </FieldGroup>
          <TextArea label="Exclusions and limitations" help={H.exclusions} value={str('exclusions')} onChange={(e) => set('exclusions', e.target.value)} />
        </div>
      </Card>
      <Card title="Futran team">
        <div className="stack">
          {teamErrors.length > 0 && <ul className="small" style={{ color: 'var(--danger)', margin: 0, paddingLeft: 18 }}>{teamErrors.map((m) => <li key={m}>{m}</li>)}</ul>}
          <div className="grid-2">
            {SINGLE_ROLES.map((r) => (
              <SelectField key={r.role} label={r.label} value={holder(r.role)} onChange={(e) => setSingle(r.role, e.target.value)} placeholder={r.required ? 'Choose…' : 'None'} options={opts(r.needs)} help={r.help || undefined} />
            ))}
          </div>
          <FieldGroup legend="Auditors *" help={H.auditors}>
            <div className="row" style={{ gap: 6 }}>
              {(people.data ?? []).filter((p) => p.roles.includes('auditor') || p.roles.includes('chief_auditor')).map((p) => (
                <label key={p.user_id} className="radio-pill"><input type="checkbox" checked={auditors.includes(p.user_id)} onChange={() => toggleAuditor(p.user_id)} />{p.name}</label>
              ))}
            </div>
          </FieldGroup>
          {team.length > 0 && (
            <FieldGroup legend="Conflict of interest" help={H.conflict}>
              <p className="small muted" style={{ margin: '0 0 6px' }}>Each team member confirms no conflict of interest with {client}: no recent consulting, implementation or employment relationship.</p>
              <div className="stack-sm">
                {teamPeople.map((p) => <Checkbox key={p.id} label={`${nameOf(p.id)} has confirmed no conflict of interest as ${rolesLabel(p.roles)}`} checked={p.confirmed} onChange={(e) => confirmPerson(p.id, e.target.checked)} />)}
              </div>
            </FieldGroup>
          )}
        </div>
      </Card>
    </fieldset>
  );
}
