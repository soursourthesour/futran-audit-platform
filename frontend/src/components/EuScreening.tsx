import { Badge, Checkbox, FieldGroup, SelectField } from '@/components/ui';

/** EU AI Act risk level beside the Futran tier (11-25 change). Three screening questions decide the level; the server
 *  works it out (app/euaiact/risk.py) so the rules live in one place. */
export type EuLevel = 'prohibited' | 'high_risk' | 'limited' | 'minimal';
export type EuScreening = { art5: string[]; annex_iii_area: string | null; annex_i: boolean; art6_3_exception: boolean; art50: string[]; gpai: boolean };
export type EuOptions = { levels: Record<EuLevel, string>; art5: Record<string, string>; art50: Record<string, string>; annex_iii_areas: Record<string, string>; annex_i_label: string; art6_3_label: string; gpai_label: string };
export type EuFields = { eu_screening: EuScreening | null; eu_risk_level: EuLevel | null; eu_risk_label: string; eu_risk_reason: string; eu_gpai?: boolean };

export const EMPTY_SCREENING: EuScreening = { art5: [], annex_iii_area: null, annex_i: false, art6_3_exception: false, art50: [], gpai: false };

const TONE: Record<EuLevel, 'danger' | 'warn' | 'navy' | 'muted'> = { prohibited: 'danger', high_risk: 'warn', limited: 'navy', minimal: 'muted' };

export function euBadge(level: EuLevel | null | undefined, label?: string | null) {
  if (!level) return <span className="muted small">{label || 'Not screened'}</span>;
  return <Badge tone={TONE[level]}>{label || level}</Badge>;
}

export const EU_HELP = {
  level: "The EU AI Act's own category, separate from the Futran tier: prohibited (Art. 5), high-risk (Annex I or III), limited risk (Art. 50 transparency) or minimal risk. A classification signed off by the legal reviewer overrides the screening.",
  art5: 'Practices the EU AI Act bans outright. Most business uses are none of these. Emotion recognition at work is the one HR teams most often meet.',
  annex: 'Annex III lists the areas where a use of AI is high-risk, such as hiring and managing workers, credit scoring and access to public services.',
  art50: 'Uses that carry transparency duties: people must be told they are dealing with AI, or that content is AI-made.',
};

/** Multi-choice with an explicit "None of these", so an unanswered question is different from a "no". */
function Choices({ legend, help, options, value, onChange, disabled, name }: { legend: string; help: string; options: Record<string, string>; value: string[]; onChange: (v: string[]) => void; disabled?: boolean; name: string }) {
  const none = value.includes('none');
  const toggle = (k: string) => onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value.filter((x) => x !== 'none'), k]);
  return (
    <FieldGroup legend={legend} help={help}>
      <div className="stack-sm">
        {Object.entries(options).map(([k, label]) => <Checkbox key={k} name={name} label={label} checked={value.includes(k)} disabled={disabled} onChange={() => toggle(k)} />)}
        <Checkbox name={name} label="None of these" checked={none} disabled={disabled} onChange={() => onChange(none ? [] : ['none'])} />
      </div>
    </FieldGroup>
  );
}

export function EuScreeningFields({ options, value, onChange, disabled, errors = {} }: { options: EuOptions; value: EuScreening; onChange: (v: EuScreening) => void; disabled?: boolean; errors?: Record<string, string> }) {
  const area = value.annex_iii_area;
  return (
    <div className="stack">
      <Choices name="eu-art5" legend="1. Is it used for any of these banned practices?" help={EU_HELP.art5} options={options.art5} value={value.art5} onChange={(art5) => onChange({ ...value, art5 })} disabled={disabled} />
      {errors['eu_screening.art5'] && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>{errors['eu_screening.art5']}</p>}
      <SelectField label="2. Is it used in one of these high-risk areas (Annex III)?" help={EU_HELP.annex} value={area ?? ''} disabled={disabled} error={errors['eu_screening.annex_iii_area']}
        onChange={(e) => onChange({ ...value, annex_iii_area: e.target.value || null, art6_3_exception: e.target.value && e.target.value !== 'none' ? value.art6_3_exception : false })}
        placeholder="Choose…" options={[...Object.entries(options.annex_iii_areas).map(([v, label]) => ({ value: v, label })), { value: 'none', label: 'None of these areas' }]} />
      {area && area !== 'none' && <Checkbox label={options.art6_3_label} checked={value.art6_3_exception} disabled={disabled} onChange={(e) => onChange({ ...value, art6_3_exception: e.target.checked })} />}
      <Checkbox label={options.annex_i_label} checked={value.annex_i} disabled={disabled} onChange={(e) => onChange({ ...value, annex_i: e.target.checked })} />
      <Choices name="eu-art50" legend="3. Does it do any of these?" help={EU_HELP.art50} options={options.art50} value={value.art50} onChange={(art50) => onChange({ ...value, art50 })} disabled={disabled} />
      {errors['eu_screening.art50'] && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>{errors['eu_screening.art50']}</p>}
      <Checkbox label={options.gpai_label} checked={value.gpai} disabled={disabled} onChange={(e) => onChange({ ...value, gpai: e.target.checked })} />
    </div>
  );
}

export function EuLevelSummary({ level, label, reason }: { level: EuLevel | null | undefined; label?: string | null; reason?: string | null }) {
  return (
    <div className="stack-sm">
      <div>{euBadge(level, label)}</div>
      <p className="small" style={{ margin: 0 }}>{reason || 'Not screened against the EU AI Act yet.'}</p>
    </div>
  );
}
