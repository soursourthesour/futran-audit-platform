import type { Contact } from '@/api/clients';
import { Card, Checkbox, TextField } from '@/components/ui';
import { useStepForm, useWizardCtx } from './Wizard';

type Contacts = Record<string, Contact>;

export function StepContacts() {
  const { data, errors, editable } = useWizardCtx();
  const initial: Contacts = {
    caico: {}, client_admin: { same_as_caico: true }, exec_sponsor: {}, dpo: {}, project_lead: { same_as_caico: true }, technical_lead: {}, compliance_lead: {},
    ...data.contacts,
  };
  const [c, setC] = useStepForm<Contacts>('contacts', initial);
  const set = (role: string, patch: Partial<Contact>) => setC({ ...c, [role]: { ...c[role], ...patch } });
  const v = (role: string, k: keyof Contact) => (c[role]?.[k] as string | null | undefined) ?? '';
  const err = (role: string, k: string) => errors[`contacts.${role}.${k}`];
  const field = (role: string, k: keyof Contact, label: string, type = 'text') => (
    <TextField label={label} type={type} value={v(role, k)} onChange={(e) => set(role, { [k]: e.target.value })} error={err(role, k)} />
  );
  const caicoName = c.caico?.name || 'the Chief AI Compliance Officer';

  return (
    <fieldset disabled={!editable} className="stack">
      <Card title="Chief AI Compliance Officer">
        <p className="small muted" style={{ marginTop: 0 }}>Required. Receives the initiation package and signs the engagement letter.</p>
        <div className="grid-2">
          {field('caico', 'name', 'Full name *')}
          {field('caico', 'title', 'Job title *')}
          {field('caico', 'email', 'Work email *', 'email')}
          {field('caico', 'phone', 'Phone', 'tel')}
        </div>
      </Card>
      <Card title="Client Admin">
        <p className="small muted" style={{ marginTop: 0 }}>Creates departments and staff accounts on the client side. No access to audit content.</p>
        <fieldset>
          <legend>Who is Client Admin</legend>
          <div className="row" role="radiogroup" style={{ gap: 6 }}>
            <label className="radio-pill"><input type="radio" name="admin_same" checked={!!c.client_admin?.same_as_caico} onChange={() => set('client_admin', { same_as_caico: true })} />Same person as {caicoName}</label>
            <label className="radio-pill"><input type="radio" name="admin_same" checked={!c.client_admin?.same_as_caico} onChange={() => set('client_admin', { same_as_caico: false, name: '', title: '', email: '' })} />A different person</label>
          </div>
        </fieldset>
        {!c.client_admin?.same_as_caico && (
          <div className="grid-2" style={{ marginTop: 12 }}>
            {field('client_admin', 'name', 'Full name *')}
            {field('client_admin', 'title', 'Job title')}
            {field('client_admin', 'email', 'Work email *', 'email')}
          </div>
        )}
      </Card>
      <Card title="Optional roles">
        <p className="small muted" style={{ marginTop: 0 }}>These can be left blank. The client names them later from the roles note, and nobody is invited until named.</p>
        <div className="stack">
          <h3 style={{ fontSize: 15, margin: 0 }}>Executive Sponsor</h3>
          <div className="grid-2">{field('exec_sponsor', 'name', 'Full name')}{field('exec_sponsor', 'email', 'Work email', 'email')}</div>
          <Checkbox label={`Not appointed: ${caicoName} approves in their place`} checked={!!c.exec_sponsor?.not_appointed} onChange={(e) => set('exec_sponsor', { not_appointed: e.target.checked })} />
          <h3 style={{ fontSize: 15, margin: '8px 0 0' }}>Data Protection Officer</h3>
          <div className="grid-2">{field('dpo', 'name', 'Full name')}{field('dpo', 'email', 'Work email', 'email')}</div>
          <Checkbox label={`Not appointed: ${caicoName} covers these duties`} checked={!!c.dpo?.not_appointed} onChange={(e) => set('dpo', { not_appointed: e.target.checked })} />
        </div>
      </Card>
      <Card title="Project contacts">
        <div className="stack">
          <Checkbox label={`The client project lead is ${caicoName}`} checked={!!c.project_lead?.same_as_caico} onChange={(e) => set('project_lead', { same_as_caico: e.target.checked })} />
          {!c.project_lead?.same_as_caico && (
            <div className="grid-2">{field('project_lead', 'name', 'Project lead name')}{field('project_lead', 'title', 'Job title')}{field('project_lead', 'email', 'Work email', 'email')}{field('project_lead', 'phone', 'Phone', 'tel')}</div>
          )}
          <div className="grid-2">
            {field('technical_lead', 'name', 'Technical lead name')}
            {field('technical_lead', 'title', 'Technical lead job title')}
            {field('compliance_lead', 'name', 'Compliance lead name')}
            {field('compliance_lead', 'title', 'Compliance lead job title')}
          </div>
        </div>
      </Card>
    </fieldset>
  );
}
