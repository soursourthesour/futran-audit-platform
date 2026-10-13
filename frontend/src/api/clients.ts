import { useQuery } from '@tanstack/react-query';
import { api, type FieldError } from '@/api/client';

export type Contact = { name?: string | null; title?: string | null; email?: string | null; phone?: string | null; not_appointed?: boolean; same_as_caico?: boolean };
export type TeamMember = { user_id: string; name?: string; role: string; conflict_confirmed: boolean };
export type Requirement = { id?: string; regulation_id: string | null; label: string; jurisdiction?: string | null; feature?: string | null; source: string; reason_text: string | null; in_scope?: boolean };
export type Location = { id?: string; site_name: string; street?: string | null; city?: string | null; subdivision_code?: string | null; country_code: string; employees_at_site?: number | null; in_scope: boolean; jurisdictions?: string[] };
export type Company = Record<string, string | number | string[] | null> & { client_ref?: string };
export type Scope = Record<string, string | string[] | null> & { departments: string[]; team: TeamMember[] };
export type Wizard = {
  client_id: string;
  engagement: { id: string; audit_ref: string; name: string; status: string; stage: number; returned_comment: string | null };
  company: Company;
  locations: { locations: Location[]; requirements: Requirement[] };
  scope: Scope;
  contacts: Record<string, Contact>;
};
export type Suggestion = { regulation_id: string | null; label: string; jurisdiction_code: string; jurisdiction_name: string; feature: string; feature_label: string; reason: string; source: string; prechecked: boolean };
export type TeamOption = { user_id: string; name: string; email: string; roles: string[] };
export type Place = { id: string; code: string; name: string; level: string };
export type SaveResult = { saved_at: string; errors: FieldError[] };

export function useWizard(clientId: string) {
  return useQuery({ queryKey: ['wizard', clientId], queryFn: () => api.get<Wizard>(`/clients/${clientId}/wizard`), staleTime: Infinity, refetchOnWindowFocus: false });
}
export function useSuggestions(clientId: string, version: number) {
  return useQuery({ queryKey: ['suggestions', clientId, version], queryFn: () => api.get<Suggestion[]>(`/clients/${clientId}/suggestions`) });
}
export function useTeamOptions() {
  return useQuery({ queryKey: ['team-options'], queryFn: () => api.get<TeamOption[]>('/clients/team-options'), staleTime: 60_000 });
}
export function useCountries() {
  return useQuery({ queryKey: ['jurisdictions', 'countries'], queryFn: () => api.get<Place[]>('/jurisdictions?level=country'), staleTime: Infinity });
}
export function useSubdivisions(country: string | null | undefined) {
  return useQuery({ queryKey: ['jurisdictions', 'children', country], queryFn: () => api.get<Place[]>(`/jurisdictions?parent=${country}`), enabled: !!country, staleTime: Infinity });
}
export function saveStep(clientId: string, step: string, payload: unknown) {
  return api.put<SaveResult>(`/clients/${clientId}/wizard/${step}`, payload);
}

export const INDUSTRIES = [
  { value: 'staffing', label: 'Staffing and recruitment' },
  { value: 'bfsi', label: 'Banking and financial services (BFSI)' },
  { value: 'healthcare', label: 'Healthcare' },
  { value: 'insurance', label: 'Insurance' },
  { value: 'pharma', label: 'Pharma and life sciences' },
  { value: 'public_sector', label: 'Public sector' },
  { value: 'property', label: 'Property management' },
  { value: 'other', label: 'Other' },
];
export const EMPLOYEE_BANDS = ['1-49', '50-249', '250-999', '1000+'];
export const REVENUE_BANDS = ['Under $10M', '$10M to $100M', '$100M to $1B', 'Over $1B'];
export const FRAMEWORKS = [
  { value: 'nist_ai_rmf', label: 'NIST AI RMF 1.0' }, { value: 'eu_ai_act', label: 'EU AI Act' }, { value: 'iso_42001', label: 'ISO/IEC 42001' },
  { value: 'gdpr', label: 'GDPR' }, { value: 'hipaa', label: 'HIPAA' }, { value: 'dpdp', label: 'India DPDP Act' }, { value: 'soc2', label: 'SOC 2' },
  { value: 'iso_27001', label: 'ISO/IEC 27001' }, { value: 'rbi_free_ai', label: 'RBI FREE-AI' }, { value: 'other', label: 'Other' },
];
export const DATA_ENVIRONMENTS = [{ value: 'production', label: 'Production' }, { value: 'uat', label: 'UAT / staging' }, { value: 'dev', label: 'Development' }];
export const DEPARTMENT_PRESETS = ['HR and recruiting', 'Sales and marketing', 'Finance', 'Engineering and IT', 'Operations', 'Customer support', 'Legal and compliance', 'Clinical'];
export const ENGAGEMENT_TYPES = [
  { value: 'initial_assessment', label: 'Initial AI governance assessment' },
  { value: 'll144_bias_audit', label: 'LL144 bias audit' },
  { value: 'annual_review', label: 'Annual review' },
];
