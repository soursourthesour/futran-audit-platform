/** 'Microsoft Copilot', but 'Otter.ai' (not 'Otter.ai Otter.ai') when vendor and product are the same name, ignoring
 *  case and surrounding spaces (OBS-07). The backend has the same rule in app/core/names.py. */
export function toolName(vendor: string | null | undefined, product: string | null | undefined): string {
  const v = (vendor ?? '').trim();
  const p = (product ?? '').trim();
  if (!v || v.toLocaleLowerCase() === p.toLocaleLowerCase()) return p || v;
  return p ? `${v} ${p}` : v;
}
