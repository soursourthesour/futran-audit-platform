import type { ReactNode } from 'react';
import {
  ACTIONS, AGENTASSURE, ALGORITHMS, AUTONOMY, CONSENT, CROSS_BORDER, DATA_CATEGORIES, DATA_SUBJECTS, HOSTING, IMPACT, PROVIDERS, SOURCING, STAGES, TRAINS, TYPES, VENDOR_DOCS,
  type Register, type RegSystem,
} from '@/api/register';
import { Checkbox, FieldGroup, SelectField, TextArea, TextField } from '@/components/ui';
import { systemHelp as H } from '@/help/register';

export type Form = {
  name: string; type: string; sourcing: string; department_id: string; company_wide: boolean; stage: string; purpose: string; users_scope: string; users_description: string; user_count: string;
  owner_user_id: string; vendor_id: string; new_vendor: boolean; vendor_name: string; ai_provider: string; model_name: string; model_version: string; algorithm_type: string; hosting: string;
  vendor_trains_on_data: string; vendor_documents: string[]; autonomy: string; guardrail_policy_ref: string; agentassure_status: string; actions: string[]; other_action: string;
  decision_impact: string; bias_next_due: string;
  data_categories: string[]; data_subjects: string[]; consent_basis: string; consent_ref: string; retention_period: string; cross_border: string;
};

export function emptyForm(deptId = ''): Form {
  return {
    name: '', type: '', sourcing: '', department_id: deptId, company_wide: false, stage: 'proposed', purpose: '', users_scope: '', users_description: '', user_count: '', owner_user_id: '',
    vendor_id: '', new_vendor: false, vendor_name: '', ai_provider: '', model_name: '', model_version: '', algorithm_type: '', hosting: '', vendor_trains_on_data: '', vendor_documents: [], autonomy: '',
    guardrail_policy_ref: '', agentassure_status: '', actions: [], other_action: '', decision_impact: '', bias_next_due: '', data_categories: [], data_subjects: [], consent_basis: '',
    consent_ref: '', retention_period: '', cross_border: '',
  };
}

export function formFrom(s: RegSystem): Form {
  const other = s.actions.find((a) => a.action_code === 'other');
  return {
    name: s.name, type: s.type, sourcing: s.sourcing, department_id: s.department?.id ?? '', company_wide: s.company_wide, stage: s.stage, purpose: s.purpose ?? '',
    users_scope: s.users_scope ?? '', users_description: s.users_description ?? '', user_count: s.user_count?.toString() ?? '', owner_user_id: s.owner?.id ?? '',
    vendor_id: s.vendor?.id ?? '', new_vendor: false, vendor_name: '', ai_provider: s.ai_provider ?? '', model_name: s.model_name ?? '', model_version: s.model_version ?? '', algorithm_type: s.algorithm_type ?? '',
    hosting: s.hosting ?? '', vendor_trains_on_data: s.vendor_trains_on_data ?? '', vendor_documents: s.vendor_documents, autonomy: s.autonomy ?? '', guardrail_policy_ref: s.guardrail_policy_ref ?? '',
    agentassure_status: s.agentassure_status ?? '', actions: s.actions.filter((a) => a.action_code !== 'other').map((a) => a.action_code), other_action: other?.description ?? '',
    decision_impact: s.decision_impact ?? '', bias_next_due: s.bias_next_due ?? '', data_categories: s.data.data_categories, data_subjects: s.data.data_subjects,
    consent_basis: s.data.consent_basis ?? '', consent_ref: s.data.consent_ref ?? '', retention_period: s.data.retention_period ?? '', cross_border: s.data.cross_border ?? '',
  };
}

/** The API payload. Blank selects are sent as null so a cleared answer is saved as cleared. */
export function payload(f: Form): Record<string, unknown> {
  const n = (v: string) => v || null;
  const agent = f.type === 'agent';
  return {
    name: f.name, type: n(f.type), sourcing: n(f.sourcing), department_id: f.company_wide ? n(f.department_id) : n(f.department_id), company_wide: f.company_wide, stage: f.stage, purpose: n(f.purpose),
    users_scope: n(f.users_scope), users_description: n(f.users_description), user_count: f.user_count === '' ? null : f.user_count, owner_user_id: n(f.owner_user_id),
    vendor_id: f.new_vendor ? null : n(f.vendor_id), ...(f.new_vendor && f.vendor_name.trim() ? { vendor_name: f.vendor_name.trim() } : {}), ai_provider: n(f.ai_provider), model_name: n(f.model_name), model_version: n(f.model_version),
    algorithm_type: n(f.algorithm_type), hosting: n(f.hosting), vendor_trains_on_data: n(f.vendor_trains_on_data), vendor_documents: f.vendor_documents,
    autonomy: agent ? n(f.autonomy) : null, guardrail_policy_ref: n(f.guardrail_policy_ref), agentassure_status: n(f.agentassure_status),
    actions: agent ? [...f.actions.map((a) => ({ action_code: a })), ...(f.other_action.trim() ? [{ action_code: 'other', description: f.other_action }] : [])] : [],
    decision_impact: n(f.decision_impact), bias_next_due: n(f.bias_next_due),
    data: { data_categories: f.data_categories, data_subjects: f.data_subjects, consent_basis: n(f.consent_basis), consent_ref: n(f.consent_ref), retention_period: n(f.retention_period), cross_border: n(f.cross_border) },
  };
}

type Props = { f: Form; set: (f: Form) => void; fe: Record<string, string>; d: Pick<Register, 'departments' | 'people' | 'vendors' | 'can'>; disabled?: boolean; editing?: boolean };

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

export function Card({ n, title, children, aside }: { n?: number; title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="card reg-form-card">
      <div className="card-header"><h2>{n ? `${n} · ` : ''}{title}</h2>{aside}</div>
      <div className="card-body stack">{children}</div>
    </section>
  );
}

export function WhatItIs({ f, set, fe, d, disabled, editing, n }: Props & { n?: number }) {
  const depts = d.departments.filter((x) => x.can_edit || x.id === f.department_id);
  return (
    <Card n={n} title="What it is">
      <fieldset disabled={disabled} className="reg-plain stack">
        <TextField label="Name *" help={H.name} value={f.name} onChange={(e) => set({ ...f, name: e.target.value })} error={fe.name} />
        <div className="grid-2">
          <SelectField label="Type *" help={H.type} value={f.type} placeholder="Choose" onChange={(e) => set({ ...f, type: e.target.value })} options={TYPES} error={fe.type} />
          <SelectField label="Built or bought *" help={H.sourcing} value={f.sourcing} placeholder="Choose" onChange={(e) => set({ ...f, sourcing: e.target.value })} options={SOURCING} error={fe.sourcing} />
          <SelectField label={f.company_wide ? 'Department' : 'Department *'} help={H.department} value={f.department_id} placeholder={f.company_wide ? 'None' : 'Choose'} onChange={(e) => set({ ...f, department_id: e.target.value })} options={depts.map((x) => ({ value: x.id, label: x.name }))} error={fe.department_id} />
          <SelectField label="Stage *" help={H.stage} value={f.stage} onChange={(e) => set({ ...f, stage: e.target.value })} options={STAGES.filter((s) => s.value !== 'live' || f.stage === 'live').filter((s) => editing || s.value !== 'retired')} error={fe.stage} disabled={f.stage === 'live' || f.stage === 'retired'} />
        </div>
        {d.can.org_wide && <Checkbox label="Company-wide tool, managed by the Chief AI Compliance Officer" help={H.companyWide} checked={f.company_wide} onChange={(e) => set({ ...f, company_wide: e.target.checked })} />}
        <TextArea label="Purpose *" help={H.purpose} value={f.purpose} onChange={(e) => set({ ...f, purpose: e.target.value })} error={fe.purpose} />
        <div className="grid-2">
          <SelectField label="Who uses it" help={H.usersScope} value={f.users_scope} placeholder="Choose" onChange={(e) => set({ ...f, users_scope: e.target.value })} options={[{ value: 'role', label: 'Role level' }, { value: 'named', label: 'Named users' }]} hint="Named users are required for Tier 2 and 3." />
          <TextField label="Users" help={H.usersDescription} value={f.users_description} onChange={(e) => set({ ...f, users_description: e.target.value })} />
          <TextField label="Number of users" help={H.userCount} inputMode="numeric" value={f.user_count} onChange={(e) => set({ ...f, user_count: e.target.value.replace(/[^0-9]/g, '') })} error={fe.user_count} />
          <SelectField label="System owner" help={H.owner} value={f.owner_user_id} placeholder="Not named yet" onChange={(e) => set({ ...f, owner_user_id: e.target.value })} options={d.people.map((p) => ({ value: p.id, label: p.job_title ? `${p.name} · ${p.job_title}` : p.name }))} error={fe.owner_user_id} />
        </div>
      </fieldset>
    </Card>
  );
}

export function VendorModel({ f, set, fe, d, disabled, n }: Props & { n?: number }) {
  return (
    <Card n={n} title="Vendor and model">
      <fieldset disabled={disabled} className="reg-plain stack">
        <div className="grid-2">
          <SelectField label="Vendor" help={H.vendor} value={f.new_vendor ? '_new' : f.vendor_id} placeholder="None" onChange={(e) => set({ ...f, vendor_id: e.target.value === '_new' ? '' : e.target.value, new_vendor: e.target.value === '_new' })}
            options={[...d.vendors.map((v) => ({ value: v.id, label: v.name })), { value: '_new', label: 'Add a new vendor' }]} hint="From the company vendor register" error={fe.vendor_id} />
          {f.new_vendor && <TextField label="New vendor's name" help={H.vendor} value={f.vendor_name} onChange={(e) => set({ ...f, vendor_name: e.target.value })} />}
          <SelectField label="Underlying AI provider" help={H.provider} value={f.ai_provider} placeholder="Choose" onChange={(e) => set({ ...f, ai_provider: e.target.value })} options={PROVIDERS} error={fe.ai_provider} />
          <TextField label="Model or algorithm" help={H.modelName} value={f.model_name} onChange={(e) => set({ ...f, model_name: e.target.value })} error={fe.model_name} />
          <TextField label="Model version" help={H.modelVersion} value={f.model_version} onChange={(e) => set({ ...f, model_version: e.target.value })} />
          <SelectField label="Algorithm type" help={H.algorithm} value={f.algorithm_type} placeholder="Choose" onChange={(e) => set({ ...f, algorithm_type: e.target.value })} options={ALGORITHMS} error={fe.algorithm_type} />
          <SelectField label="Hosting" help={H.hosting} value={f.hosting} placeholder="Choose" onChange={(e) => set({ ...f, hosting: e.target.value })} options={HOSTING} />
          <SelectField label="Vendor trains on our data?" help={H.trains} value={f.vendor_trains_on_data} placeholder="Choose" onChange={(e) => set({ ...f, vendor_trains_on_data: e.target.value })} options={TRAINS} />
        </div>
        <FieldGroup legend="Vendor documents received" help={H.vendorDocs}>
          <div className="grid-2">{VENDOR_DOCS.map((x) => <Checkbox key={x.value} label={x.label} checked={f.vendor_documents.includes(x.value)} onChange={() => set({ ...f, vendor_documents: toggle(f.vendor_documents, x.value) })} />)}</div>
        </FieldGroup>
      </fieldset>
    </Card>
  );
}

export function AgentActions({ f, set, fe, disabled, n }: Props & { n?: number }) {
  return (
    <Card n={n} title="What the agent can do" aside={<span className="badge">Agents only</span>}>
      <fieldset disabled={disabled} className="reg-plain stack">
        <FieldGroup legend="Actions and tools *" help={H.actions}>
          <div className="grid-2">{ACTIONS.map((x) => <Checkbox key={x.value} label={x.label} checked={f.actions.includes(x.value)} onChange={() => set({ ...f, actions: toggle(f.actions, x.value) })} />)}</div>
        </FieldGroup>
        <TextField label="Other action or tool" help={H.otherAction} value={f.other_action} onChange={(e) => set({ ...f, other_action: e.target.value })} error={fe.actions} />
        <FieldGroup legend="How much it acts on its own *" help={H.autonomy}>
          <div className="stack-sm">{AUTONOMY.map((x) => <label key={x.value} className="radio-pill reg-radio"><input type="radio" name="autonomy" checked={f.autonomy === x.value} onChange={() => set({ ...f, autonomy: x.value })} />{x.label}</label>)}</div>
          {fe.autonomy && <p className="small reg-danger" style={{ margin: '4px 0 0' }}>{fe.autonomy}</p>}
        </FieldGroup>
        <div className="grid-2">
          <TextField label="Runtime controls" help={H.guardrail} placeholder="For example Futran GuardRail policy HR-Scheduling-v1" value={f.guardrail_policy_ref} onChange={(e) => set({ ...f, guardrail_policy_ref: e.target.value })} />
          <SelectField label="Pre-release testing" help={H.agentassure} value={f.agentassure_status} placeholder="Choose" onChange={(e) => set({ ...f, agentassure_status: e.target.value })} options={AGENTASSURE} />
        </div>
      </fieldset>
    </Card>
  );
}

export function DataConsent({ f, set, fe, disabled, n, aside }: Props & { n?: number; aside?: ReactNode }) {
  return (
    <Card n={n} title="Data and consent" aside={aside}>
      <fieldset disabled={disabled} className="reg-plain stack">
        <FieldGroup legend="Data used" help={H.dataCategories}>
          <div className="grid-2">{DATA_CATEGORIES.map((x) => <Checkbox key={x.value} label={x.label} checked={f.data_categories.includes(x.value)} onChange={() => set({ ...f, data_categories: toggle(f.data_categories, x.value) })} />)}</div>
        </FieldGroup>
        <FieldGroup legend="Whose data" help={H.dataSubjects}>
          <div className="grid-2">{DATA_SUBJECTS.map((x) => <Checkbox key={x.value} label={x.label} checked={f.data_subjects.includes(x.value)} onChange={() => set({ ...f, data_subjects: toggle(f.data_subjects, x.value) })} />)}</div>
        </FieldGroup>
        <div className="grid-2">
          <SelectField label="Was consent obtained?" help={H.consent} value={f.consent_basis} placeholder="Choose" onChange={(e) => set({ ...f, consent_basis: e.target.value })} options={CONSENT} error={fe['data.consent_basis']} />
          <TextField label="Consent date or version" help={H.consentRef} value={f.consent_ref} onChange={(e) => set({ ...f, consent_ref: e.target.value })} />
          <TextField label="Retention period" help={H.retention} placeholder="For example 4 years" value={f.retention_period} onChange={(e) => set({ ...f, retention_period: e.target.value })} />
          <SelectField label="Data leaves the country?" help={H.crossBorder} value={f.cross_border} placeholder="Choose" onChange={(e) => set({ ...f, cross_border: e.target.value })} options={CROSS_BORDER} />
        </div>
      </fieldset>
    </Card>
  );
}

export function ImpactField({ f, set, fe, disabled }: Pick<Props, 'f' | 'set' | 'fe' | 'disabled'>) {
  return (
    <FieldGroup legend="Effect on decisions about people" help={H.impact}>
      <fieldset disabled={disabled} className="reg-plain stack-sm">{IMPACT.map((x) => <label key={x.value} className="radio-pill reg-radio"><input type="radio" name="impact" checked={f.decision_impact === x.value} onChange={() => set({ ...f, decision_impact: x.value })} />{x.label}</label>)}</fieldset>
      {fe.decision_impact && <p className="small reg-danger" style={{ margin: '4px 0 0' }}>{fe.decision_impact}</p>}
    </FieldGroup>
  );
}

/** Field errors from the API, keyed by field; "data.x" keys are kept as they are. */
export function scrollToError() {
  setTimeout(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);
}
