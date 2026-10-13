import { useMemo, useState } from 'react';
import { useFeatures, useLawJurisdictions, useLaws, TYPE_LABELS, type Law } from '@/api/laws';
import { Badge, Button, EmptyState, Loading, SelectField, TextField } from '@/components/ui';

export type GeoOption = { value: string; label: string; codes: string[] | 'all' };

type Props = {
  /** Extra geography choices shown first, e.g. "Client jurisdictions + parents". */
  presets?: GeoOption[];
  /** IDs already in scope: shown ticked and disabled. */
  selectedIds?: Set<string>;
  /** Pick mode: shows checkboxes and an "Add N laws" button. Browse mode: rows are clickable. */
  mode?: 'pick' | 'browse';
  onAdd?: (laws: Law[]) => void;
  onOpen?: (law: Law) => void;
  developerNote?: string;
  sourceLabel?: string;
};

export function LawPicker({ presets = [], selectedIds, mode = 'pick', onAdd, onOpen, developerNote = 'Frontier developers only; not relevant to a deployer.', sourceLabel }: Props) {
  const juris = useLawJurisdictions();
  const features = useFeatures();
  const geoOptions: GeoOption[] = useMemo(() => {
    const opts: GeoOption[] = [...presets, { value: 'all', label: 'All jurisdictions', codes: 'all' }];
    const js = (juris.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
    for (const j of js) opts.push({ value: j.code, label: `${j.name}${j.level === 'state' && j.parent_code ? ` (${j.parent_code})` : ''}`, codes: [j.code] });
    return opts;
  }, [presets, juris.data]);
  const [geo, setGeo] = useState<string>(presets[0]?.value ?? 'US');
  const [feature, setFeature] = useState('');
  const [q, setQ] = useState('');
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const chosen = geoOptions.find((o) => o.value === geo) ?? geoOptions[0];
  const laws = useLaws(chosen?.codes ?? 'all', feature, q);
  const all = (laws.data ?? []).flatMap((g) => g.laws);

  function toggle(id: string) {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setTicked(next);
  }

  return (
    <div className="stack">
      <div className="grid-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <SelectField label="Geography" value={geo} onChange={(e) => setGeo(e.target.value)} options={geoOptions.map((o) => ({ value: o.value, label: o.label }))} />
        <SelectField label="AI feature" value={feature} onChange={(e) => setFeature(e.target.value)} placeholder="All features" options={features.data ?? []} />
        <TextField label="Search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Law name, topic or keyword" />
      </div>
      {laws.isLoading ? <Loading /> : !laws.data?.length ? <EmptyState>No laws match these filters.</EmptyState> : (
        <div className="stack" style={{ gap: 20 }}>
          {laws.data.map((g) => (
            <section key={g.jurisdiction.code} aria-label={g.jurisdiction.name}>
              <h3 style={{ fontSize: 14, color: 'var(--muted)', marginBottom: 8 }}>{g.jurisdiction.name} · {g.laws.length} {g.laws.length === 1 ? 'law' : 'laws'}</h3>
              <div className="card">
                {g.laws.map((law, i) => {
                  const inScope = selectedIds?.has(law.id);
                  const dev = law.applies_to === 'developer';
                  const body = (
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row" style={{ gap: 8 }}>
                        <strong>{law.short_name}</strong>
                        {law.verify_flag && <Badge tone="warn">Verify</Badge>}
                        {law.type !== 'statute' && <Badge tone="muted">{TYPE_LABELS[law.type] ?? law.type}</Badge>}
                      </div>
                      <div className="small muted" style={{ marginTop: 4 }}>{dev ? developerNote : law.summary}</div>
                    </div>
                  );
                  return (
                    <div key={law.id} style={{ display: 'flex', gap: 12, padding: '12px 16px', borderTop: i ? '1px solid var(--line-soft)' : undefined, opacity: dev && mode === 'pick' ? 0.55 : 1, alignItems: 'flex-start' }}>
                      {mode === 'pick' ? (
                        <label style={{ display: 'flex', gap: 12, flex: 1, cursor: dev || inScope ? 'default' : 'pointer', minHeight: 44 }}>
                          <input type="checkbox" style={{ width: 20, height: 20, marginTop: 2, accentColor: 'var(--navy)' }} disabled={dev || inScope} checked={!!inScope || ticked.has(law.id)} onChange={() => toggle(law.id)} aria-label={`Include ${law.short_name}`} />
                          {body}
                        </label>
                      ) : (
                        <button type="button" onClick={() => onOpen?.(law)} style={{ all: 'unset', cursor: 'pointer', display: 'flex', flex: 1, minHeight: 44 }}>{body}</button>
                      )}
                      <span className="small muted" style={{ whiteSpace: 'nowrap' }}>{law.feature_label}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
      {(mode === 'pick' || sourceLabel) && (
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="small muted">{sourceLabel ?? 'Reference data maintained by Futran Admin.'}</span>
          {mode === 'pick' && <Button variant="primary" disabled={!ticked.size} onClick={() => { onAdd?.(all.filter((l) => ticked.has(l.id))); setTicked(new Set()); }}>Add {ticked.size || ''} {ticked.size === 1 ? 'law' : 'laws'}</Button>}
        </div>
      )}
    </div>
  );
}
