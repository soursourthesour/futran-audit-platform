import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { DiscoveredTool } from '@/api/discovery';

/** G-05 manual discovery import (Release 2 B5). */
export type ImportField = { key: string; label: string; required: boolean };
export type ExportTypeRow = { value: string; label: string; source: string; parsed_into: string; summary_only: boolean; fields: ImportField[] };
export type Preset = { id: string; export_type: string; name: string; mapping: Record<string, string> };
export type Finding = { key: string; label: string; service: string; service_kind: string; tool_ids: string[]; opportunity_id: string | null };
export type Unmatched = { name: string; department: string | null; user_count: number; matched_tool_id?: string | null };
export type ImportRow = {
  id: string; export_type: string; export_label: string; filename: string; sha256: string; size: number; rows_read: number; rows_matched: number; tools_found: number;
  mapping: Record<string, string>; unmatched: Unmatched[]; unmatched_count: number | null; findings?: Finding[]; evidence_file_id: string | null; summary_only: boolean; engagement_id: string | null;
  imported_by: string | null; imported_at: string; tools?: ImportTool[];
};
export type ImportTool = DiscoveredTool & { import_type: string | null; import_id: string | null };
export type ImportPage = {
  engagement: { id: string; name: string; audit_ref: string | null; client_id: string; client_name: string } | null;
  organization: { id: string; name: string };
  export_types: ExportTypeRow[]; presets: Preset[]; imports: ImportRow[]; tools: ImportTool[]; vendors: { key: string; label: string }[]; can_decide: boolean;
};
export type PreviewTool = { vendor_key: string; vendor: string; product: string; category: string; department: string; user_count: number; detail: string | null; declared: boolean };
export type Analysis = {
  export_type: string; filename: string; headers: string[]; mapping: Record<string, string>; rows_read: number; rows_matched: number;
  preview: { cells: Record<string, string>; match: string | null }[]; tools: PreviewTool[]; unmatched: Unmatched[]; unmatched_count: number; attestation_exists: boolean; sha256: string; summary_only: boolean;
};

/** Where the endpoints live: on the engagement for Futran, under Integrations for the Client Admin. */
export function importBase(engagementId?: string) {
  return engagementId ? `/engagements/${engagementId}/discovery` : '/integrations';
}

export function useImportPage(engagementId?: string) {
  const base = importBase(engagementId);
  return useQuery({ queryKey: ['discovery-import', engagementId ?? 'client'], queryFn: () => api.get<ImportPage>(`${base}/import`) });
}
