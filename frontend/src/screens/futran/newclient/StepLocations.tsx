import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { useCountries, useSubdivisions, useSuggestions, type Location, type Requirement, type Suggestion } from '@/api/clients';
import type { Law } from '@/api/laws';
import { LawPicker } from '@/components/LawPicker';
import { Badge, Button, Card, EmptyState, FieldHelp, Loading } from '@/components/ui';
import { locationHelp as H } from '@/help/onboarding';
import { useStepForm, useWizardCtx } from './Wizard';

const keyOf = (x: { regulation_id: string | null; label: string }) => x.regulation_id ?? `text:${x.label}`;

export function StepLocations() {
  const { clientId, data, errors, editable, autosave } = useWizardCtx();
  const [locs, setLocs] = useStepForm<{ locations: Location[] }>('locations', { locations: data.locations.locations });
  const [version, setVersion] = useState(0);
  const sugg = useSuggestions(clientId, version);
  const [reqs, setReqs] = useState<Requirement[]>(data.locations.requirements);
  const seen = useRef<Set<string> | null>(null);
  const [picking, setPicking] = useState(false);

  // Bump the suggestion query after a location change has had time to save.
  const locKey = JSON.stringify(locs.locations.map((l) => [l.country_code, l.subdivision_code, l.city, l.in_scope]));
  useEffect(() => {
    const t = window.setTimeout(() => setVersion((v) => v + 1), 1200);
    return () => window.clearTimeout(t);
  }, [locKey]);

  // Pre-checked suggestions are included the first time they appear; after that the auditor's choice stands.
  useEffect(() => {
    if (!sugg.data) return;
    const pre = sugg.data.filter((s) => s.prechecked);
    if (seen.current === null) {
      seen.current = new Set(sugg.data.map(keyOf));
      if (reqs.length === 0 && pre.length) saveReqs(pre.map(fromSuggestion));
      return;
    }
    const fresh = pre.filter((s) => !seen.current!.has(keyOf(s)) && !reqs.some((r) => keyOf(r) === keyOf(s)));
    sugg.data.forEach((s) => seen.current!.add(keyOf(s)));
    if (fresh.length) saveReqs([...reqs, ...fresh.map(fromSuggestion)]);
  }, [sugg.data]);

  function saveReqs(next: Requirement[]) {
    setReqs(next);
    autosave('requirements', { requirements: next });
  }

  const rows = useMemo(() => {
    const byKey = new Map<string, { s?: Suggestion; r?: Requirement }>();
    for (const s of sugg.data ?? []) if (s.prechecked) byKey.set(keyOf(s), { s });
    for (const r of reqs) byKey.set(keyOf(r), { ...byKey.get(keyOf(r)), r });
    return [...byKey.entries()];
  }, [sugg.data, reqs]);
  const included = new Set(reqs.map(keyOf));

  function toggle(k: string, s?: Suggestion, r?: Requirement) {
    if (included.has(k)) saveReqs(reqs.filter((x) => keyOf(x) !== k));
    else saveReqs([...reqs, r ?? fromSuggestion(s!)]);
  }
  function addLaws(laws: Law[]) {
    const extra = laws.filter((l) => !included.has(l.id)).map((l) => ({ regulation_id: l.id, label: l.short_name, jurisdiction: l.jurisdiction_name, feature: l.feature, source: 'manual', reason_text: 'Added by the auditor' }));
    saveReqs([...reqs, ...extra]);
    setPicking(false);
  }
  const update = (i: number, patch: Partial<Location>) => setLocs({ locations: locs.locations.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const clientCodes = [...new Set((sugg.data ?? []).map((s) => s.jurisdiction_code))];

  return (
    <fieldset disabled={!editable} className="stack">
      <Card title="Locations" actions={<Button size="sm" onClick={() => setLocs({ locations: [...locs.locations, { site_name: '', country_code: 'US', in_scope: true }] })}>Add location</Button>}>
        <div className="stack">
          <p className="small muted">Sites where staff work or where candidates are hired. Each site pulls in the laws of its city, state, country and any regional group (for example the EU).</p>
          {errors['locations.locations'] && <p className="small" style={{ color: 'var(--danger)' }}>{errors['locations.locations']}</p>}
          {locs.locations.length === 0 ? <EmptyState>No sites yet. Add the headquarters first.</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th><Th label="Site" help={H.site} /></th><th><Th label="Country" help={H.country} /></th><th><Th label="State or region" help={H.region} /></th><th><Th label="City" help={H.city} /></th><th>Laws from</th><th><Th label="In scope" help={H.inScope} /></th><th /></tr></thead>
                <tbody>
                  {locs.locations.map((l, i) => (
                    <LocationRow key={l.id ?? `new-${i}`} loc={l} index={i} error={errors[`locations.locations.${i}.country_code`]} onChange={(p) => update(i, p)} onRemove={() => setLocs({ locations: locs.locations.filter((_, j) => j !== i) })} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
      <Card title={`Laws and frameworks in scope · ${included.size}`} actions={<Button size="sm" onClick={() => setPicking(!picking)}>{picking ? 'Close the law matrix' : 'Add from the law matrix'}</Button>}>
        <div className="stack">
          <p className="small muted">Suggested from the sites, the industry and how the client uses AI. Confirm each one.</p>
          {errors['locations.requirements'] && <p className="small" style={{ color: 'var(--danger)' }}>{errors['locations.requirements']}</p>}
          {picking && (
            <div className="card" style={{ padding: 16 }}>
              <LawPicker mode="pick" presets={clientCodes.length ? [{ value: 'client', label: 'Client jurisdictions', codes: clientCodes }] : []} selectedIds={new Set(reqs.map((r) => r.regulation_id).filter(Boolean) as string[])} onAdd={addLaws} sourceLabel="Futran AI Law Matrix" />
            </div>
          )}
          {sugg.isLoading ? <Loading /> : rows.length === 0 ? <EmptyState>Add a site to see the laws that apply.</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th><Th label="Include" help={H.include} /></th><th>Law</th><th>Geography · feature</th><th>Why suggested</th></tr></thead>
                <tbody>
                  {rows.map(([k, { s, r }]) => (
                    <tr key={k}>
                      <td><input type="checkbox" style={{ width: 20, height: 20, accentColor: 'var(--navy)' }} checked={included.has(k)} onChange={() => toggle(k, s, r)} aria-label={`Include ${s?.label ?? r?.label}`} /></td>
                      <td><strong>{s?.label ?? r?.label}</strong>{(s?.source ?? r?.source) === 'futran_default' && <> <Badge tone="navy">Futran default</Badge></>}</td>
                      <td className="small">{s ? `${s.jurisdiction_name} · ${s.feature_label}` : [r?.jurisdiction, r?.feature?.replace(/_/g, ' ')].filter(Boolean).join(' · ')}</td>
                      <td className="small muted" style={{ whiteSpace: 'normal' }}>{s?.reason ?? r?.reason_text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </fieldset>
  );
}

/** A table column heading with a help icon. */
function Th({ label, help }: { label: string; help: string }) {
  return <span className="label-row">{label}<FieldHelp label={label}>{help}</FieldHelp></span>;
}

function fromSuggestion(s: Suggestion): Requirement {
  return { regulation_id: s.regulation_id, label: s.label, jurisdiction: s.jurisdiction_name, feature: s.feature, source: s.source, reason_text: s.reason };
}

function LocationRow({ loc, index, error, onChange, onRemove }: { loc: Location; index: number; error?: string; onChange: (p: Partial<Location>) => void; onRemove: () => void }) {
  const countries = useCountries();
  const subs = useSubdivisions(loc.country_code);
  const label = `site ${index + 1}`;
  const params = new URLSearchParams({ country: loc.country_code, ...(loc.subdivision_code ? { subdivision: loc.subdivision_code } : {}), ...(loc.city ? { city: loc.city } : {}) });
  const resolved = useQuery({ queryKey: ['resolve', params.toString()], queryFn: () => api.get<{ name: string }[]>(`/jurisdictions/resolve?${params}`), enabled: !!loc.country_code, staleTime: Infinity });
  return (
    <tr>
      <td><input className="input" aria-label={`Name of ${label}`} value={loc.site_name} placeholder="Headquarters" onChange={(e) => onChange({ site_name: e.target.value })} /></td>
      <td>
        <select className="input" aria-label={`Country of ${label}`} value={loc.country_code} onChange={(e) => onChange({ country_code: e.target.value, subdivision_code: null })}>
          {(countries.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </select>
        {error && <div className="small" style={{ color: 'var(--danger)' }}>{error}</div>}
      </td>
      <td>
        <select className="input" aria-label={`State or region of ${label}`} value={loc.subdivision_code ?? ''} onChange={(e) => onChange({ subdivision_code: e.target.value || null })}>
          <option value="">Whole country / various</option>
          {(subs.data ?? []).filter((s) => s.level === 'state').map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
      </td>
      <td><input className="input" aria-label={`City of ${label}`} value={loc.city ?? ''} onChange={(e) => onChange({ city: e.target.value })} /></td>
      <td className="small muted" style={{ whiteSpace: 'normal', maxWidth: 220 }}>{(resolved.data ?? []).map((j) => j.name).join(' · ')}</td>
      <td><input type="checkbox" style={{ width: 20, height: 20, accentColor: 'var(--navy)' }} checked={loc.in_scope} onChange={(e) => onChange({ in_scope: e.target.checked })} aria-label={`${label} in scope`} /></td>
      <td><Button size="sm" variant="ghost" onClick={onRemove} aria-label={`Remove ${label}`}>Remove</Button></td>
    </tr>
  );
}
