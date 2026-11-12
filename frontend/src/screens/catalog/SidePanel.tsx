import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { PRICE_LABEL, PRICE_TONE, SELL_LABEL, SELL_TONE, type Change, type Grid, type Item, type Pending } from '@/api/catalog';
import { Badge, Button, fmtDate, fmtDateTime } from '@/components/ui';
import { optionsFor, rawValue } from './PriceList';

const GROUPS: { title: string; fields: [string, string, ('text' | 'area' | 'number')?][] }[] = [
  { title: 'What it is', fields: [['product', 'Product'], ['name', 'Line item'], ['description', 'Short proposal description', 'area']] },
  { title: 'Price', fields: [['billing', 'Billing'], ['pricing_unit', 'Pricing unit'], ['basis', 'Basis ($ or %)'], ['periods_per_year', 'Periods per year', 'number'],
    ['low', 'Low', 'number'], ['list_price', 'List', 'number'], ['high', 'High', 'number'], ['price_status', 'Price status'], ['applies_to', '% items: applies to (codes or products)']] },
  { title: 'Sellability and delivery', fields: [['sellable_status', 'Sellable'], ['delivery_mode', 'Delivery mode'], ['platform_feature_ref', 'Platform feature / release'],
    ['included_quantities', 'Included'], ['engagement_type', 'Engagement type'], ['entitlement_key', 'Entitlement key'], ['remediation_of', 'Remediation of (finding domains)'],
    ['notes', 'Notes', 'area']] },
];

const NUMS = ['low', 'list_price', 'high'];
const fmtNum = (f: string, v: string) => (NUMS.includes(f) && v.trim() !== '' && Number.isFinite(Number(v.replace(/,/g, ''))) ? `$${Number(v.replace(/,/g, '')).toLocaleString('en-US')}` : v);

export function SidePanel({ g, item, dirty, setCell, focus, onClose, onHistory, onSuggest }: {
  g: Grid; item: Item; dirty: Record<string, string>; setCell: (code: string, field: string, v: string) => void; focus: string | null;
  onClose: () => void; onHistory: () => void; onSuggest: () => void;
}) {
  const editable = g.can_edit && item.status === 'active';
  const hist = useQuery({ queryKey: ['catalog-history', item.code], queryFn: () => api.get<{ items: Change[]; pending: Pending[]; usage: { estimates: number; proposals: number | null } }>(`/catalog/items/${item.code}/history`) });
  const deliv = useRef<HTMLTextAreaElement>(null);
  const box = useRef<HTMLElement>(null);
  useEffect(() => { (focus === 'deliverables' ? deliv.current : box.current?.querySelector<HTMLElement>('h2'))?.focus(); }, [item.code, focus]);
  const val = (f: string) => dirty[f] ?? rawValue(item, f);
  const changed = (f: string) => dirty[f] !== undefined;
  const unsaved = Object.keys(dirty);
  const usage = hist.data?.usage;

  function field(f: string, label: string, kind: 'text' | 'area' | 'number' = 'text') {
    const id = `sp-${f}`;
    const opts = optionsFor(g, f);
    const cls = changed(f) ? 'cell-changed' : '';
    if (!editable) {
      const shown = opts ? opts.find((o) => o.value === val(f))?.label ?? val(f) : val(f);
      return <div key={f} className="sp-field"><span className="sp-label">{label}</span><span className={kind === 'area' ? 'pre' : ''}>{shown || <span className="muted">—</span>}</span></div>;
    }
    return (
      <div key={f} className="sp-field">
        <label htmlFor={id} className="sp-label">{label}{changed(f) && <span className="small cell-changed-text"> · unsaved</span>}</label>
        {opts ? (
          <select id={id} className={cls} value={val(f)} onChange={(e) => setCell(item.code, f, e.target.value)}>{opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
        ) : kind === 'area' ? (
          <textarea id={id} className={cls} rows={3} value={val(f)} onChange={(e) => setCell(item.code, f, e.target.value)} />
        ) : (
          <input id={id} className={cls} value={val(f)} inputMode={kind === 'number' ? 'decimal' : undefined} onChange={(e) => setCell(item.code, f, e.target.value)} />
        )}
      </div>
    );
  }

  return (
    <aside ref={box} className="side-panel" aria-label={`${item.code} details`}>
      <div className="side-panel-head">
        <h2 tabIndex={-1}>{item.code} · {item.name}</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>
      <div className="row">
        <Badge tone={PRICE_TONE[item.price_status]}>{PRICE_LABEL[item.price_status]}</Badge>
        <Badge tone={SELL_TONE[item.sellable_status]}>{SELL_LABEL[item.sellable_status]}</Badge>
        {item.status === 'retired' && <Badge tone="muted">Retired</Badge>}
        {item.is_starter && <Badge tone="muted">Starter data</Badge>}
      </div>
      <section className="sp-group">
        <label htmlFor="sp-deliverables" className="sp-label"><strong>Deliverables — what the client gets</strong>{changed('deliverables') && <span className="small cell-changed-text"> · unsaved</span>}</label>
        <p className="small muted">Written for sales to read to the client: what is delivered, how, what the client provides and typical duration. Shown on estimates, proposals and the acceptance page.</p>
        {editable ? (
          <textarea id="sp-deliverables" ref={deliv} rows={12} className={changed('deliverables') ? 'cell-changed' : ''} value={val('deliverables')} onChange={(e) => setCell(item.code, 'deliverables', e.target.value)} />
        ) : (
          <div id="sp-deliverables" className="pre deliverables-read" tabIndex={-1} ref={deliv as unknown as React.RefObject<HTMLDivElement>}>{item.deliverables || <span className="muted">No deliverables yet.</span>}</div>
        )}
      </section>
      {GROUPS.map((grp) => (
        <section key={grp.title} className="sp-group">
          <h3>{grp.title}</h3>
          <div className="sp-grid">{grp.fields.map(([f, label, kind]) => field(f, label, kind))}</div>
        </section>
      ))}
      {usage && (
        <p className="small">Used in {usage.estimates} saved estimate{usage.estimates === 1 ? '' : 's'}{usage.proposals !== null ? ` and ${usage.proposals} draft proposal${usage.proposals === 1 ? '' : 's'}` : ''}. New text and prices show on estimates and drafts; sent proposals keep the text and prices they were sent with.</p>
      )}
      <section className="sp-group">
        <h3>History</h3>
        <ul className="sp-history">
          {unsaved.length > 0 && <li className="cell-changed-text">Unsaved: {unsaved.map((f) => (f === 'deliverables' || f === 'description' || f === 'notes' ? `${g.enums.fields[f] ?? f} text edited` : `${g.enums.fields[f] ?? f} ${fmtNum(f, rawValue(item, f)) || '—'} → ${fmtNum(f, dirty[f]) || '—'}`)).join('; ')}</li>}
          {(hist.data?.pending ?? []).map((p) => <li key={p.id}>{p.status === 'awaiting_check' ? 'Waiting for second check' : `Pending from ${fmtDate(p.effective_from)}`}: {p.label} {p.old_display || '—'} → {p.new_display || '—'} · {p.by}</li>)}
          {(hist.data?.items ?? []).filter((h) => h.status === 'applied').slice(0, 5).map((h) => (
            <li key={h.id}>v{h.version} · {fmtDateTime(h.at)} · {h.field === 'created' ? 'Item added' : `${h.label} ${h.old_display || '—'} → ${h.new_display || '—'}`} · {h.by}{h.reason ? ` — ${h.reason}` : ''}</li>
          ))}
        </ul>
        <div className="row">
          <Button size="sm" onClick={onHistory}>View full history</Button>
          {!g.can_edit && g.can_suggest && <Button size="sm" onClick={onSuggest}>Suggest a change</Button>}
        </div>
      </section>
      {editable && unsaved.length > 0 && <p className="small muted">Changes here join the unsaved changes on the grid. Save them there with one reason.</p>}
    </aside>
  );
}
