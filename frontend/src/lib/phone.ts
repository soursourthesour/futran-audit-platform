import { AsYouType, getCountries, getCountryCallingCode, isValidPhoneNumber, parsePhoneNumberFromString, type CountryCode } from 'libphonenumber-js/min';

export type DialCountry = { code: CountryCode; name: string; dial: string };

let cache: DialCountry[] | null = null;

/** Every country with its English name and dial code, sorted by name. */
export function dialCountries(): DialCountry[] {
  if (cache) return cache;
  let names: Intl.DisplayNames | null = null;
  try { names = new Intl.DisplayNames(['en'], { type: 'region' }); } catch { names = null; }
  cache = getCountries()
    .map((code) => ({ code, name: names?.of(code) ?? code, dial: `+${getCountryCallingCode(code)}` }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return cache;
}

export function isCountry(code: string | null | undefined): code is CountryCode {
  return !!code && getCountries().includes(code as CountryCode);
}

/** A stored number shown for reading: +1 212 555 0100. Numbers saved without a country code are shown as saved. */
export function formatPhone(value: string | null | undefined): string {
  if (!value) return '';
  if (!value.startsWith('+')) return value;
  return parsePhoneNumberFromString(value)?.formatInternational() ?? value;
}

/** Split a stored value into the country and the national part for editing. */
export function splitPhone(value: string | null | undefined, fallback: CountryCode): { country: CountryCode; national: string; legacy: boolean } {
  if (!value) return { country: fallback, national: '', legacy: false };
  if (!value.startsWith('+')) return { country: fallback, national: value, legacy: true };
  const p = parsePhoneNumberFromString(value);
  if (!p) return { country: fallback, national: value, legacy: false };
  return { country: (p.country ?? fallback) as CountryCode, national: p.formatNational(), legacy: false };
}

/** The E.164 form (+12125550100) of what was typed, or null when nothing was typed. A number typed with a leading + keeps its own code. */
export function toE164(national: string, country: CountryCode): string | null {
  const text = national.trim();
  if (!text) return null;
  const p = text.startsWith('+') ? parsePhoneNumberFromString(text) : parsePhoneNumberFromString(text, country);
  if (p) return p.number;
  const digits = text.replace(/\D/g, '');
  if (!digits) return null;
  return text.startsWith('+') ? `+${digits}` : `+${getCountryCallingCode(country)}${digits.replace(/^0+/, '')}`;
}

export function validPhone(e164: string | null): boolean {
  return !!e164 && isValidPhoneNumber(e164);
}

export function formatAsYouType(national: string, country: CountryCode): string {
  if (national.trim().startsWith('+')) return national;
  return new AsYouType(country).input(national);
}

export function countryOfNumber(text: string): CountryCode | undefined {
  return text.trim().startsWith('+') ? parsePhoneNumberFromString(text.trim())?.country : undefined;
}
