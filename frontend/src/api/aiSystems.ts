import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { Register, RegSystem } from '@/api/register';
import type { Tool, UseCaseRow } from '@/screens/client/Inventory';

/** 11-10 U1: one list of the client's AI. Each row is read from its own record (nothing is converted); the backend scopes
 *  every source as the old register, inventory and audit systems screens did. */
export type AiKind = 'system' | 'tool' | 'use_case';
export type AiSource = 'register' | 'inventory' | 'attestation' | 'discovery' | 'audit';
export type AiAudit = { system_id: string; reference_id: string; status: string; status_label: string; can_answer: boolean; answered?: number; applicable?: number; pct?: number };
export type AiRow = {
  key: string; kind: AiKind; type_label: string; subtype: string | null; name: string; detail: string | null;
  sources: AiSource[]; source_label: string; departments: { id: string; name: string }[]; company_wide: boolean;
  stage: string | null; stage_label: string | null; tier: number | null;
  /** null: this person cannot see the register, so nothing is said either way */
  registered: boolean | null; in_register_as: { id: string; name: string } | null;
  in_audit: boolean | null; audit: AiAudit | null;
  system: RegSystem | null; tool: Tool | null; use_case: UseCaseRow | null; open: string | null;
  can: { approve_tool?: boolean; review_use_case?: boolean };
};
export type AiList = {
  rows: AiRow[];
  register: Omit<Register, 'systems'> | null;
  inventory: { tiers: Record<string, number>; can_add_tool: boolean; can_add_use_case: boolean } | null;
  audit: { engagement_id: string; audit_ref: string; locked: boolean; can_answer_governance_questions: boolean; systems: number } | null;
};

export const SOURCE_OPTIONS: { value: AiSource; label: string }[] = [
  { value: 'register', label: 'Register' }, { value: 'inventory', label: 'Inventory' }, { value: 'attestation', label: 'Attestation' },
  { value: 'discovery', label: 'Discovery' }, { value: 'audit', label: 'Audit' },
];
export const TYPE_OPTIONS = [
  { value: 'system', label: 'System' }, { value: 'tool', label: 'Tool or agent' }, { value: 'use_case', label: 'Use case' },
  { value: 'inventory', label: 'Tools and use cases (the inventory)' },
];

export const useAiSystems = () => useQuery({ queryKey: ['ai-systems'], queryFn: () => api.get<AiList>('/ai-systems') });
