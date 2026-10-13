import { useState } from 'react';
import { DATA_ENVIRONMENTS, DEPARTMENT_PRESETS, ENGAGEMENT_TYPES, FRAMEWORKS, useTeamOptions, type Scope, type TeamMember } from '@/api/clients';
import { Button, Card, Checkbox, SelectField, TextArea, TextField } from '@/components/ui';
import { useStepForm, useWizardCtx } from './Wizard';

const SINGLE_ROLES = [
  { role: 'chief_auditor', label: 'Chief Auditor (Lead Auditor) *', help: 'Approves this draft and signs the final report.', needs: ['chief_auditor'], required: true },
  { role: 'engagement_manager', label: 'Engagement Manager *', help: 'Approves any AI system added after initiation.', needs: [], required: true },
  { role: 'qa_reviewer', label: 'QA Reviewer', help: 'Required if the Chief Auditor writes findings.', needs: ['qa_reviewer', 'chief_auditor'], required: false },
  { role: 'legal_reviewer', label: 'Legal / compliance reviewer', help: '', needs: [], required: false },
];

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
  const confirm = (m: TeamMember, v: boolean) => set('team', team.map((t) => (t.user_id === m.user_id && t.role === m.role ? { ...t, conflict_confirmed: v } : t)));
  const nameOf = (id: string) => people.data?.find((p) => p.user_id === id)?.name ?? team.find((t) => t.user_id === id)?.name ?? 'Team member';
  const opts = (needs: string[]) => (people.data ?? []).filter((p) => !needs.length || p.roles.some((r) => needs.includes(r))).map((p) => ({ value: p.user_id, label: p.name }));
  const depts = [...new Set([...DEPARTMENT_PRESETS, ...f.departments])];

  return (
    <fieldset disabled={!editable} className="stack">
      <Card title="Engagement">
        <div className="stack">
          <fieldset>
            <legend>Engagement type *</legend>
            <div className="row" role="radiogroup" style={{ gap: 6 }}>
              {ENGAGEMENT_TYPES.map((t) => <label key={t.value} className="radio-pill"><input type="radio" name="type" checked={f.type === t.value} onChange={() => set('type', t.value)} />{t.label}</label>)}
            </div>
          </fieldset>
          <div className="grid-2">
            <TextField type="date" label="Audit period start *" value={str('period_start')} onChange={(e) => set('period_start', e.target.value)} error={err('period_start')} />
            <TextField type="date" label="Audit period end *" value={str('period_end')} onChange={(e) => set('period_end', e.target.value)} error={err('period_end')} />
            <TextField type="date" label="Engagement start *" value={str('fieldwork_start')} onChange={(e) => set('fieldwork_start', e.target.value)} error={err('fieldwork_start')} />
            <TextField type="date" label="Engagement letter signed by" value={str('letter_due')} onChange={(e) => set('letter_due', e.target.value)} />
            <TextField type="date" label="Target date for the draft report *" value={str('draft_report_target')} onChange={(e) => set('draft_report_target', e.target.value)} error={err('draft_report_target')} />
            <TextField type="date" label="Target date for the final report *" value={str('final_report_target')} onChange={(e) => set('final_report_target', e.target.value)} error={err('final_report_target')} />
            <TextField label="Audit methodology version" value={str('methodology_version')} onChange={(e) => set('methodology_version', e.target.value)} />
          </div>
        </div>
      </Card>
      <Card title="Scope and boundaries">
        <div className="stack">
          <fieldset>
            <legend>Departments or functions in scope *</legend>
            <div className="row" style={{ gap: 6 }}>
              {depts.map((d) => <label key={d} className="radio-pill"><input type="checkbox" checked={f.departments.includes(d)} onChange={() => set('departments', f.departments.includes(d) ? f.departments.filter((x) => x !== d) : [...f.departments, d])} />{d}</label>)}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <input className="input" style={{ maxWidth: 280 }} aria-label="Another department" placeholder="Another department" value={newDept} onChange={(e) => setNewDept(e.target.value)} />
              <Button size="sm" onClick={() => { if (newDept.trim()) { set('departments', [...f.departments, newDept.trim()]); setNewDept(''); } }}>Add</Button>
            </div>
            <p className="small muted" style={{ margin: '4px 0 0' }}>The client confirms the final department list in the initiation package.</p>
            {err('departments') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('departments')}</p>}
          </fieldset>
          <TextArea label="AI systems in scope *" value={list('planned_systems').join('\n')} onChange={(e) => set('planned_systems', e.target.value.split('\n'))} help="One per line, using the client's name for each system. Adding a system after initiation needs the Engagement Manager's approval." error={err('planned_systems')} />
          <TextArea label="AI systems excluded, with the reason" value={str('systems_excluded')} onChange={(e) => set('systems_excluded', e.target.value)} />
          <TextArea label="Business processes in scope *" value={str('business_processes')} onChange={(e) => set('business_processes', e.target.value)} error={err('business_processes')} />
          <fieldset>
            <legend>Data environments in scope *</legend>
            <div className="row" style={{ gap: 6 }}>{DATA_ENVIRONMENTS.map((d) => <label key={d.value} className="radio-pill"><input type="checkbox" checked={list('data_environments').includes(d.value)} onChange={() => toggleIn('data_environments', d.value)} />{d.label}</label>)}</div>
            {err('data_environments') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('data_environments')}</p>}
          </fieldset>
          <TextArea label="Geographic scope *" value={str('geographic_scope')} onChange={(e) => set('geographic_scope', e.target.value)} error={err('geographic_scope')} />
          <fieldset>
            <legend>Regulatory frameworks in scope *</legend>
            <div className="row" style={{ gap: 6 }}>{FRAMEWORKS.map((x) => <label key={x.value} className="radio-pill"><input type="checkbox" checked={list('frameworks').includes(x.value)} onChange={() => toggleIn('frameworks', x.value)} />{x.label}</label>)}</div>
            {err('frameworks') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('frameworks')}</p>}
          </fieldset>
          <TextArea label="Exclusions and limitations" value={str('exclusions')} onChange={(e) => set('exclusions', e.target.value)} />
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
          <fieldset>
            <legend>Auditors *</legend>
            <div className="row" style={{ gap: 6 }}>
              {(people.data ?? []).filter((p) => p.roles.includes('auditor') || p.roles.includes('chief_auditor')).map((p) => (
                <label key={p.user_id} className="radio-pill"><input type="checkbox" checked={auditors.includes(p.user_id)} onChange={() => toggleAuditor(p.user_id)} />{p.name}</label>
              ))}
            </div>
          </fieldset>
          {team.length > 0 && (
            <fieldset>
              <legend>Conflict of interest</legend>
              <p className="small muted" style={{ margin: '0 0 6px' }}>Each team member confirms no conflict of interest with {client}: no recent consulting, implementation or employment relationship.</p>
              <div className="stack-sm">
                {team.map((m) => <Checkbox key={`${m.user_id}-${m.role}`} label={`${nameOf(m.user_id)} has confirmed no conflict of interest`} checked={m.conflict_confirmed} onChange={(e) => confirm(m, e.target.checked)} />)}
              </div>
            </fieldset>
          )}
        </div>
      </Card>
    </fieldset>
  );
}
