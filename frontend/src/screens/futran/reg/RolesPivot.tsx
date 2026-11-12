import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Loading } from '@/components/ui';
import '@/styles/regmaster.css';
import '@/styles/futran-screens.css';

type Reg = { id: string; label: string; short_name: string; jurisdiction: string; jurisdiction_code: string; region: string; region_label: string };
type RoleCell = { level: string; needed_by_stage: string; needed_by_label: string; basis: string | null };
type CommCell = { level: string; basis: string | null; condition: string | null };
type Summary = { kind: 'role' | 'committee'; code: string; name: string; level: string; needed_by_stage: string | null; needed_by_label: string | null; laws: string[] };
export type Pivot = {
  regulations: Reg[]; selected: Reg[]; summary: Summary[];
  roles: { code: string; name: string; description: string | null; level: string; cells: Record<string, RoleCell> }[];
  committees: { committee_type: string; title: string; cells: Record<string, CommCell> }[];
};

const GROUPS = [{ level: 'company', title: 'Company-wide roles' }, { level: 'system', title: 'Roles for each AI system' }, { level: 'agent', title: 'Roles for each AI agent' }];
const Pill = ({ level }: { level: string }) => (level === 'required' ? <span className="reg-pill-req">Required</span> : <span className="reg-pill-rec">Recommended</span>);

/** Feedback 10 Nov F4: pick regulations; see the roles and committees they require, from the law library's own maps. */
export function RolesPivot({ selected, setSelected }: { selected: string[]; setSelected: (ids: string[]) => void }) {
  const key = selected.join(',');
  const q = useQuery({ queryKey: ['reg-roles-pivot', key], queryFn: () => api.get<Pivot>(`/reg/roles/pivot?laws=${encodeURIComponent(key)}`), placeholderData: keepPreviousData });
  const [text, setText] = useState('');
  const groups = useMemo(() => {
    const t = text.trim().toLowerCase();
    const out: { name: string; region: string; regs: Reg[] }[] = [];
    for (const r of q.data?.regulations ?? []) {
      if (t && !`${r.label} ${r.short_name} ${r.jurisdiction} ${r.region_label}`.toLowerCase().includes(t)) continue;
      const g = out.find((x) => x.name === r.jurisdiction);
      if (g) g.regs.push(r); else out.push({ name: r.jurisdiction, region: r.region_label, regs: [r] });
    }
    return out;
  }, [q.data, text]);
  if (q.isLoading && !q.data) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const toggle = (id: string) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const cols = d.selected;
  const roles = d.summary.filter((s) => s.kind === 'role');
  const comms = d.summary.filter((s) => s.kind === 'committee');
  return (
    <div className="stack">
      <section className="fx-picker" aria-label="Choose regulations">
        <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <div className="field" style={{ flex: '1 1 260px', margin: 0 }}>
            <label htmlFor="pivot-search">Find regulations</label>
            <input id="pivot-search" className="input" type="search" placeholder="Law, jurisdiction or region" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          {selected.length > 0 && <Button variant="ghost" onClick={() => setSelected([])}>Clear selection</Button>}
        </div>
        {cols.length > 0 && (
          <ul className="fx-picked" aria-label="Selected regulations">
            {cols.map((r) => <li key={r.id}><button type="button" onClick={() => toggle(r.id)} aria-label={`Remove ${r.label}`}>{r.label} ×</button></li>)}
          </ul>
        )}
        <div className="fx-picker-list" role="group" aria-label="Regulations by jurisdiction">
          {groups.length === 0 ? <p className="small muted">No regulation matches.</p> : groups.map((g) => (
            <fieldset key={g.name}>
              <legend>{g.name} <span className="small">· {g.region}</span></legend>
              {g.regs.map((r) => (
                <label key={r.id}><input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} />{r.label}{r.short_name && r.short_name !== r.label && <span className="small muted">{r.short_name}</span>}</label>
              ))}
            </fieldset>
          ))}
        </div>
      </section>
      {cols.length === 0 ? <Alert tone="info">Choose one or more regulations to see the roles and committees they require.</Alert> : (
        <>
          <Card title={`Needed by any selected regulation (${roles.length} ${roles.length === 1 ? 'role' : 'roles'}, ${comms.length} ${comms.length === 1 ? 'committee' : 'committees'})`}
            actions={<a className="btn" href={`/api/v1/reg/roles/pivot.csv?laws=${encodeURIComponent(key)}`} download>Export CSV</a>}>
            <p className="small muted" style={{ marginTop: 0 }}>Where the selected regulations differ, the stricter level and the earlier stage win.</p>
            <ul className="fx-summary" aria-label="Needed by any selected regulation">
              {d.summary.map((s) => (
                <li key={`${s.kind}-${s.code}`}><strong>{s.name}</strong> <Pill level={s.level} />{s.needed_by_label && <span className="small"> · needed by {s.needed_by_label}</span>}<div className="small muted">{s.laws.join(', ')}</div></li>
              ))}
            </ul>
          </Card>
          <Card title="Roles and committees by regulation">
            <div className="fx-pivot-wrap" tabIndex={0} role="region" aria-label="Roles by regulation, scrolls sideways">
              <table className="fx-pivot" aria-label="Roles by regulation">
                <thead><tr><th scope="col">Role or committee</th>{cols.map((r) => <th key={r.id} scope="col"><Link to={`/reg/${r.id}`}>{r.label}</Link><div className="small muted">{r.jurisdiction}</div></th>)}</tr></thead>
                <tbody>
                  {GROUPS.map((g) => {
                    const rows = d.roles.filter((r) => r.level === g.level);
                    if (!rows.length) return null;
                    return [
                      <tr key={g.level} className="grp"><td colSpan={cols.length + 1}>{g.title}</td></tr>,
                      ...rows.map((r) => (
                        <tr key={r.code}>
                          <th scope="row">{r.name}{r.description && <div className="small muted" style={{ fontWeight: 400 }}>{r.description}</div>}</th>
                          {cols.map((c) => {
                            const cell = r.cells[c.id];
                            return <td key={c.id} title={cell?.basis ?? undefined}>{cell ? <><Pill level={cell.level} /><span className="fx-stage">Needed by {cell.needed_by_label}</span></> : <span className="muted" aria-label="Not required">–</span>}</td>;
                          })}
                        </tr>
                      )),
                    ];
                  })}
                  {d.committees.length > 0 && <tr className="grp"><td colSpan={cols.length + 1}>Committees and programs</td></tr>}
                  {d.committees.map((c) => (
                    <tr key={c.committee_type}>
                      <th scope="row">{c.title}</th>
                      {cols.map((r) => {
                        const cell = c.cells[r.id];
                        return <td key={r.id} title={[cell?.basis, cell?.condition].filter(Boolean).join(' ') || undefined}>{cell ? <Pill level={cell.level} /> : <span className="muted" aria-label="Not required">–</span>}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="reg-note">Hover a cell to see its basis in the law. A regulation that requires none of these shows a dash in every row.</p>
          </Card>
          <p className="small muted"><Badge tone="muted">Source</Badge> The law library's role maps and committee rules for each regulation's current version.</p>
        </>
      )}
    </div>
  );
}
