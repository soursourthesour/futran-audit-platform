import { useQuery } from '@tanstack/react-query';
import { api } from './client';

export type Law = {
  id: string;
  jurisdiction_code: string;
  jurisdiction_name: string;
  short_name: string;
  feature: string;
  feature_label: string;
  type: string;
  type_text: string | null;
  enforcer: string | null;
  trigger_text: string | null;
  obligations_text: string | null;
  developments_text: string | null;
  most_affected: string | null;
  full_text: string | null;
  summary: string;
  applies_to: 'deployer' | 'developer' | 'both';
  verify_flag: boolean;
  public_summary: boolean;
  origin: string;
};
export type LawGroup = { jurisdiction: { code: string; name: string; level: string }; laws: Law[] };
export type Jurisdiction = { id: string; code: string; name: string; level: string; parent_code: string | null; has_laws: boolean; aliases: string[]; feature_notes: Record<string, string> };
export type Feature = { value: string; label: string };

export function useFeatures() {
  return useQuery({ queryKey: ['features'], queryFn: () => api.get<Feature[]>('/laws/features'), staleTime: Infinity });
}

export function useLawJurisdictions() {
  return useQuery({ queryKey: ['jurisdictions', 'has_laws'], queryFn: () => api.get<Jurisdiction[]>('/jurisdictions?has_laws=true'), staleTime: 300_000 });
}

export function useLaws(codes: string[] | 'all', feature: string, q: string, excludeDeveloper = false) {
  const params = new URLSearchParams();
  params.set('codes', codes === 'all' ? 'all' : codes.join(','));
  if (feature) params.set('feature', feature);
  if (q.trim()) params.set('q', q.trim());
  if (excludeDeveloper) params.set('exclude_developer', '1');
  const key = params.toString();
  return useQuery({ queryKey: ['laws', key], queryFn: () => api.get<LawGroup[]>(`/laws?${key}`), enabled: codes === 'all' || codes.length > 0 });
}

export const TYPE_LABELS: Record<string, string> = {
  statute: 'Statute', regulation: 'Regulation', executive: 'Executive action', voluntary: 'Voluntary', pending: 'Pending', policy: 'Policy', guidance: 'Guidance',
};
