import { EMPLOYEE_BANDS, INDUSTRIES, REVENUE_BANDS, useCountries, type Company } from '@/api/clients';
import { Badge, Button, Card, FieldGroup, SelectField, TextArea, TextField } from '@/components/ui';
import { companyHelp as H } from '@/help/onboarding';
import { useStepForm, useWizardCtx } from './Wizard';

export function StepCompany() {
  const { data, errors, editable } = useWizardCtx();
  const countries = useCountries();
  const [f, setF] = useStepForm<Company>('company', data.company);
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v } as Company);
  const str = (k: string) => (f[k] as string | null) ?? '';
  const countryOpts = (countries.data ?? []).map((c) => ({ value: c.code, label: c.name }));
  const primary = (f.primary_jurisdictions as string[] | null) ?? [];
  const err = (k: string) => errors[`company.${k}`];
  return (
    <fieldset disabled={!editable} className="stack">
      <Card title="Company details">
        <div className="grid-2">
          <TextField label="Legal name *" help={H.legalName} value={str('legal_name')} onChange={(e) => set('legal_name', e.target.value)} error={err('legal_name')} />
          <TextField label="Trading name" value={str('trading_name')} onChange={(e) => set('trading_name', e.target.value)} help={H.tradingName} />
          <SelectField label="Industry *" help={H.industry} value={str('industry')} onChange={(e) => set('industry', e.target.value)} placeholder="Choose…" options={INDUSTRIES} error={err('industry')} />
          <FieldGroup legend="Employees *" help={H.employeeBand}>
            <div className="row" role="radiogroup" style={{ gap: 6 }}>
              {EMPLOYEE_BANDS.map((b) => (
                <label key={b} className="radio-pill"><input type="radio" name="employee_band" checked={f.employee_band === b} onChange={() => set('employee_band', b)} />{b.replace('-', '–').replace('1000+', '1,000+')}</label>
              ))}
            </div>
            {err('employee_band') && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{err('employee_band')}</p>}
          </FieldGroup>
          <TextField label="Exact number of employees" help={H.employeeCount} inputMode="numeric" value={str('employee_count')} onChange={(e) => set('employee_count', e.target.value)} error={err('employee_count')} />
          <SelectField label="Annual revenue (approximate)" value={str('annual_revenue_band')} onChange={(e) => set('annual_revenue_band', e.target.value)} placeholder="Choose…" options={REVENUE_BANDS.map((b) => ({ value: b, label: b }))} help={H.revenue} />
          <TextField label="Website" help={H.website} value={str('website')} onChange={(e) => set('website', e.target.value)} />
          <TextField label="Futran client reference" value={data.company.client_ref ?? ''} readOnly help={H.clientRef} />
          <TextField label="Number of AI systems in scope *" help={H.aiSystemsCount} inputMode="numeric" value={str('ai_systems_in_scope_count')} onChange={(e) => set('ai_systems_in_scope_count', e.target.value)} error={err('ai_systems_in_scope_count')} />
        </div>
      </Card>
      <Card title="Headquarters address">
        <div className="grid-2">
          <TextField label="Street *" help={H.hqStreet} value={str('hq_street')} onChange={(e) => set('hq_street', e.target.value)} error={err('hq_street')} />
          <TextField label="City *" help={H.hqCity} value={str('hq_city')} onChange={(e) => set('hq_city', e.target.value)} error={err('hq_city')} />
          <TextField label="State / region *" help={H.hqState} value={str('hq_state')} onChange={(e) => set('hq_state', e.target.value)} error={err('hq_state')} />
          <TextField label="Postal code *" help={H.hqPostal} value={str('hq_postal_code')} onChange={(e) => set('hq_postal_code', e.target.value)} error={err('hq_postal_code')} />
          <SelectField label="Country *" help={H.hqCountry} value={str('hq_country')} onChange={(e) => set('hq_country', e.target.value)} placeholder="Choose…" options={countryOpts} error={err('hq_country')} />
        </div>
      </Card>
      <Card title="Where the client operates">
        <div className="stack">
          <SelectField label="Primary countries of operation *" help={H.primaryCountries} value="" onChange={(e) => e.target.value && !primary.includes(e.target.value) && set('primary_jurisdictions', [...primary, e.target.value])} placeholder="Add a country…" options={countryOpts} error={err('primary_jurisdictions')} />
          <div className="row" style={{ gap: 6 }}>
            {primary.map((code) => (
              <Badge key={code} tone="navy">
                {countryOpts.find((c) => c.value === code)?.label ?? code}{' '}
                <Button size="sm" variant="ghost" aria-label={`Remove ${code}`} onClick={() => set('primary_jurisdictions', primary.filter((x) => x !== code))}>×</Button>
              </Badge>
            ))}
          </div>
          <TextArea label="Why the client is engaging Futran" value={str('engagement_reason')} onChange={(e) => set('engagement_reason', e.target.value)} help={H.engagementReason} />
        </div>
      </Card>
    </fieldset>
  );
}
