import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import type { CountryCode } from 'libphonenumber-js/min';
import { countryOfNumber, dialCountries, formatAsYouType, isCountry, splitPhone, toE164, validPhone } from '@/lib/phone';
import { ComboInput, type ComboOption } from './ComboInput';
import { FieldHelp } from './FieldHelp';

/**
 * A phone number with a searchable country dial-code picker. The value is stored in E.164 (+12125550100).
 * A number saved before country codes were required is shown as saved until someone edits it.
 */
export function PhoneField({ label, help, value, onChange, defaultCountry, error, disabled }: {
  label: ReactNode; help?: ReactNode; value: string | null | undefined; onChange: (e164: string | null) => void;
  defaultCountry?: string | null; error?: string; disabled?: boolean;
}) {
  const fid = useId();
  const fallback: CountryCode = isCountry(defaultCountry) ? defaultCountry : 'US';
  const start = useMemo(() => splitPhone(value, fallback), []); // the stored value is read once; edits stay local
  const [country, setCountry] = useState<CountryCode>(start.country);
  const [national, setNational] = useState(start.national);
  const [legacy, setLegacy] = useState(start.legacy);
  const [touched, setTouched] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const all = dialCountries();
  const current = all.find((c) => c.code === country);

  // A blank number follows the headquarters country until the user chooses one.
  useEffect(() => {
    if (!national && !touched && isCountry(defaultCountry)) setCountry(defaultCountry);
  }, [defaultCountry]);

  const options: ComboOption[] = useMemo(() => {
    const q = (query ?? '').trim().toLowerCase().replace(/^\+/, '');
    const hits = !q ? all : all.filter((c) => c.name.toLowerCase().includes(q) || c.code.toLowerCase() === q || c.dial.slice(1).startsWith(q));
    return hits.map((c) => ({ id: c.code, label: `${c.name} ${c.dial}` }));
  }, [query, all]);

  function emit(nat: string, cc: CountryCode) {
    setLegacy(false);
    onChange(toE164(nat, cc));
  }
  function typeNumber(text: string) {
    setNational(text);
    const own = countryOfNumber(text);
    if (own) setCountry(own);
    emit(text, own ?? country);
  }
  function chooseCountry(o: ComboOption) {
    const cc = o.id as CountryCode;
    setCountry(cc);
    setQuery(null);
    setTouched(true);
    if (national.trim()) emit(national.replace(/^\+\d+\s*/, ''), cc);
  }

  const e164 = legacy ? null : toE164(national, country);
  const localError = touched && national.trim() && !legacy && !validPhone(e164) ? `Enter a valid phone number for ${current?.name ?? 'the country chosen'}.` : undefined;
  const shownError = error ?? localError;
  const ids = [shownError ? `${fid}-err` : null, legacy ? `${fid}-note` : null].filter(Boolean).join(' ') || undefined;
  const labelText = typeof label === 'string' ? label.replace(/\s*\*$/, '') : 'phone number';

  return (
    <div className="field">
      {help ? <div className="field-label"><label htmlFor={fid}>{label}</label><FieldHelp label={label}>{help}</FieldHelp></div> : <label htmlFor={fid}>{label}</label>}
      <div className="phone-row">
        <ComboInput
          aria-label={`Country code for ${labelText}`}
          value={query ?? (current ? `${current.name} ${current.dial}` : '')}
          onChange={(t) => { setQuery(t); setOpen(true); }}
          options={options}
          open={open}
          onOpenChange={(v) => { setOpen(v); if (!v) setQuery(null); }}
          onPick={chooseCountry}
          onFocus={(e) => { e.currentTarget.select(); }}
          onClick={() => setOpen(true)}
          emptyText="No country matches."
          status={open ? `${options.length} countries` : ''}
          disabled={disabled}
        />
        <input
          id={fid}
          className="input"
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          value={national}
          onChange={(e) => typeNumber(e.target.value)}
          onBlur={() => { setTouched(true); if (!legacy && national.trim()) setNational(formatAsYouType(national, country)); }}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={ids}
          disabled={disabled}
        />
      </div>
      {legacy && <div className="field-note" id={`${fid}-note`}>Saved without a country code. Check the country and type the number again to add it.</div>}
      {shownError && <div className="error" id={`${fid}-err`}>{shownError}</div>}
    </div>
  );
}
