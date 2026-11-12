import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { money, PRICE_LABEL, PRICE_TONE, SELL_LABEL, SELL_TONE, signedMoney, type EstLine, type Estimate, type EstimatorRef, type Evaluation, type Item, type Terms } from '@/api/catalog';
import { Alert, Badge, Button, Checkbox, fmtDateTime, Loading, PageHeader } from '@/components/ui';
import '@/styles/catalog.css';

type Raw = { code: string; qty: number; edited_price: number | null; description?: string | null; deliverables_override?: string | null };
const EMPTY_TOTALS = { one_time: 0, recurring_y1: 0, discount: 0, y1_total: 0, arr: 0 };

function parseMoney(s: string): number | null {
  const t = s.replace(/[,$\s]/g, '');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function PriceInput({ line, onChange }: { line: EstLine; onChange: (v: number | null) => void }) {
  const fmt = (v: number | null) => (v === null ? '' : v.toLocaleString('en-US', { maximumFractionDigits: 2 }));
  const [draft, setDraft] = useState(fmt(line.unit_price_used));
  useEffect(() => setDraft(fmt(line.unit_price_used)), [line.unit_price_used]);
  const commit = () => { const n = parseMoney(draft); if (n === null) setDraft(fmt(line.unit_price_used)); else onChange(n === line.list_price ? null : n); };
  return (
    <input aria-label={`Unit price ${line.code}`} className={`price-input${line.edited ? ' cell-changed' : ''}`} value={draft} inputMode="decimal"
      onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }} />
  );
}

export function Estimator() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const ref = useQuery({ queryKey: ['estimator'], queryFn: () => api.get<EstimatorRef>('/sales/estimator') });
  const estimateId = params.get('id');
  const [lines, setLines] = useState<Raw[]>([]);
  const [name, setName] = useState('');
  const [oppId, setOppId] = useState(params.get('opportunity') ?? '');
  const [pkg, setPkg] = useState('');
  const [pendingPkg, setPendingPkg] = useState<string | null>(null);
  const [discount, setDiscount] = useState('0');
  const [term, setTerm] = useState(1);
  const [region, setRegion] = useState('');
  const [terms, setTerms] = useState<Terms>({});
  const [saved, setSaved] = useState<Estimate | null>(null);
  const [ev, setEv] = useState<Evaluation | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'warn' | 'info'; text: string } | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [tailoring, setTailoring] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [changes, setChanges] = useState<Estimate['price_changes']>([]);
  const [busy, setBusy] = useState(false);
  const loadedId = useRef<string | null>(null);

  // load a saved estimate (?id=)
  useEffect(() => {
    if (!estimateId || loadedId.current === estimateId) return;
    loadedId.current = estimateId;
    api.get<Estimate>(`/sales/estimates/${estimateId}`).then((e) => {
      const changed = new Map((e.price_changes ?? []).map((c) => [c.code, c.old]));
      setLines((e.lines ?? []).map((l) => ({ code: l.code, qty: l.qty, edited_price: l.edited ? l.edited_price : changed.has(l.code) ? changed.get(l.code)! : null,
        description: l.description_override, deliverables_override: l.deliverables_override })));
      setName(e.name); setOppId(e.opportunity_id ?? ''); setPkg(e.package ?? ''); setDiscount(String(e.discount_recurring_pct)); setTerm(e.term);
      setRegion(e.data_region ?? ''); setTerms(e.terms ?? {}); setSaved(e); setChanges(e.price_changes ?? []);
    }).catch((err) => setMsg({ tone: 'danger', text: errorMessage(err) }));
  }, [estimateId]);

  // price the lines on the server whenever they change
  useEffect(() => {
    const d = Number(discount);
    if (!lines.length) { setEv(null); return; }
    const t = setTimeout(() => {
      api.post<Evaluation>('/sales/estimates/preview', { lines, discount_recurring_pct: Number.isFinite(d) ? d : 0, terms, term, data_region: region || null })
        .then((r) => { setEv(r); setMsg((m) => (m?.tone === 'danger' ? null : m)); })
        .catch((err) => setMsg({ tone: 'danger', text: err instanceof ApiError && err.errors.length ? err.errors.map((x) => x.message).join(' ') : errorMessage(err) }));
    }, 150);
    return () => clearTimeout(t);
  }, [lines, discount, terms, term, region]);

  const r = ref.data;
  const items = useMemo(() => new Map((r?.items ?? []).map((i) => [i.code, i])), [r]);
  const matches = useMemo(() => {
    const n = search.trim().toLowerCase();
    if (!n || !r) return [];
    return r.items.filter((i) => `${i.code} ${i.name} ${i.deliverables ?? ''}`.toLowerCase().includes(n)).slice(0, 8);
  }, [search, r]);
  if (!r) return <div className="page"><Loading /></div>;

  const priced = new Map((ev?.lines ?? []).map((l) => [l.code, l]));
  const totals = ev?.totals ?? EMPTY_TOTALS;
  const update = (code: string, patch: Partial<Raw>) => setLines((ls) => ls.map((l) => (l.code === code ? { ...l, ...patch } : l)));

  function addItem(it: Item) {
    if (!it.can_add) { setMsg({ tone: 'warn', text: it.why_not ?? `${it.code} can't be added.` }); return; }
    setLines((ls) => (ls.some((l) => l.code === it.code) ? ls.map((l) => (l.code === it.code ? { ...l, qty: l.qty + 1 } : l)) : [...ls, { code: it.code, qty: 1, edited_price: null }]));
    setSearch('');
    setMsg(null);
  }
  function applyPackage(key: string) {
    const p = r!.packages.find((x) => x.key === key);
    setPkg(key);
    setLines(p ? p.lines.filter((l) => !l.problem && items.get(l.code)?.can_add).map((l) => ({ code: l.code, qty: l.qty, edited_price: null })) : []);
    setPendingPkg(null);
  }
  function choosePackage(key: string) {
    if (lines.length) setPendingPkg(key); else applyPackage(key);
  }
  function searchKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && matches[0]) { e.preventDefault(); addItem(matches[0]); }
  }
  async function save() {
    if (!name.trim()) { setMsg({ tone: 'danger', text: 'Name the estimate before saving.' }); return; }
    setBusy(true);
    try {
      const e = await api.post<Estimate>('/sales/estimates', { thread_id: saved?.thread_id ?? null, name, opportunity_id: oppId || null, package: pkg || null, lines,
        discount_recurring_pct: Number(discount) || 0, term, data_region: region || null, terms });
      setSaved(e); setChanges([]); loadedId.current = e.id;
      setParams({ id: e.id }, { replace: true });
      setMsg({ tone: 'success', text: `Saved as v${e.version}.` });
    } catch (err) { setMsg({ tone: 'danger', text: err instanceof ApiError && err.errors.length ? err.errors.map((x) => x.message).join(' ') : errorMessage(err) }); }
    finally { setBusy(false); }
  }
  async function convert() {
    try {
      const out = await api.post<{ proposal_id: string }>(`/sales/estimates/${saved!.id}/convert`);
      navigate(`/sales/proposals/${out.proposal_id}`);
    } catch (err) { setMsg({ tone: 'danger', text: errorMessage(err) }); }
  }
  const norm = (ls: { code: string; qty: number; edited_price: number | null; description?: string | null; deliverables_override?: string | null }[]) =>
    JSON.stringify(ls.map((l) => [l.code, l.qty, l.edited_price ?? null, l.description || null, l.deliverables_override || null]));
  const dirty = !saved || norm(lines) !== norm((saved.lines ?? []).map((l) => ({ code: l.code, qty: l.qty, edited_price: l.edited ? l.edited_price : null,
    description: l.description_override, deliverables_override: l.deliverables_override })));
  const approvals = (ev?.approvals ?? []).filter((a) => a.kind === 'approval');
  const notes = (ev?.approvals ?? []).filter((a) => a.kind !== 'approval');

  return (
    <div className="page estimator-page">
      <PageHeader title="Estimator" subtitle={`Prices start from the master price list (catalog version ${r.catalog_version}). Edit any line for this client and save; the master does not change. Internal only: estimates are never sent to clients.`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="est-top">
        <label className="field-inline">Estimate name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Northbank, first pass" aria-label="Estimate name" /></label>
        <label className="field-inline">Opportunity (optional)<select value={oppId} onChange={(e) => setOppId(e.target.value)} aria-label="Opportunity (optional)">
          <option value="">None</option>{r.opportunities.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select></label>
        <label className="field-inline">Start from package<select value={pkg} onChange={(e) => choosePackage(e.target.value)} aria-label="Start from package">
          <option value="">Choose…</option>{r.packages.map((p) => <option key={p.key} value={p.key}>{p.lines.length ? p.name : `${p.name} (empty)`}</option>)}
        </select></label>
      </div>
      {pendingPkg !== null && (
        <Alert tone="warn">Replace the {lines.length} line{lines.length === 1 ? '' : 's'} on this estimate with the {r.packages.find((p) => p.key === pendingPkg)?.name} package?{' '}
          <Button size="sm" variant="primary" onClick={() => applyPackage(pendingPkg)}>Replace lines</Button> <Button size="sm" onClick={() => setPendingPkg(null)}>Keep my lines</Button></Alert>
      )}
      {changes && changes.length > 0 && (
        <Alert tone="warn">
          {changes.length} list price{changes.length === 1 ? '' : 's'} changed since you saved ({changes.map((c) => `${c.code} ${money(c.old)} → ${money(c.new)}`).join('; ')}). Update these lines?{' '}
          <Button size="sm" variant="primary" onClick={() => { setLines((ls) => ls.map((l) => (changes.some((c) => c.code === l.code) ? { ...l, edited_price: null } : l))); setChanges([]); }}>Update these lines</Button>{' '}
          <Button size="sm" onClick={() => setChanges([])}>Keep my prices</Button>
          <span className="small block">Kept prices count as edited prices.</span>
        </Alert>
      )}

      <div className="est-add">
        <label className="field-inline grow">Add item<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={searchKey}
          placeholder="Type a code or name, e.g. L-01 or bias audit" aria-label="Add item by code or name" aria-controls="est-matches" /></label>
        <Link className="btn" to="/staff/admin/catalog">Browse price list</Link>
        <Checkbox label="Show deliverables on every line" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
        {matches.length > 0 && (
          <ul id="est-matches" className="est-matches" aria-label="Matching items">
            {matches.map((i) => (
              <li key={i.code}>
                <button type="button" onClick={() => addItem(i)} disabled={!i.can_add} aria-label={`Add ${i.code} ${i.name}`}>
                  <strong>{i.code}</strong> {i.name} <span className="muted">· {money(i.list_price, i.basis)} · {i.billing_label}</span>
                  {!i.can_add && <span className="small block">{i.why_not}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="est-table-wrap">
        <table className="est-table" aria-label="Estimate lines">
          <thead><tr><th>Code</th><th>Line item</th><th>Qty</th><th>Billing</th><th>Price for this client</th><th>List · range</th><th className="num">Year-1 value</th><th>Status</th><th><span className="sr-only">Remove</span></th></tr></thead>
          <tbody>
            {lines.map((raw) => {
              const l = priced.get(raw.code);
              const it = items.get(raw.code);
              const name = l?.name ?? it?.name ?? raw.code;
              const expanded = showAll || open.has(raw.code);
              const tailor = tailoring.has(raw.code);
              return (
                <Fragment key={raw.code}>
                  <tr className={l?.edited ? 'row-dirty' : ''}>
                    <td data-label="Code"><strong>{raw.code}</strong></td>
                    <td data-label="Line item">
                      {name}
                      <button type="button" className="linklike block small" aria-expanded={expanded} onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(raw.code)) n.delete(raw.code); else n.add(raw.code); return n; })}>
                        What the client gets
                      </button>
                      {(raw.description || raw.deliverables_override) && <span className="small muted block">Tailored for this client</span>}
                    </td>
                    <td data-label="Qty"><input aria-label={`Qty ${raw.code}`} className="qty-input" inputMode="numeric" value={raw.qty}
                      onChange={(e) => { const n = Number(e.target.value); update(raw.code, { qty: Number.isFinite(n) && n > 0 ? n : raw.qty }); }} /></td>
                    <td data-label="Billing">{l?.billing_label ?? it?.billing_label}</td>
                    <td data-label="Price for this client">
                      {l ? <PriceInput line={l} onChange={(v) => update(raw.code, { edited_price: v })} /> : '…'}
                      {l?.edited && (
                        <span className="small block edited-note">
                          <Badge tone="warn">Edited</Badge> {signedMoney(l.value_difference)} · <button type="button" className="linklike" onClick={() => update(raw.code, { edited_price: null })}>Reset to list price</button>
                          {l.edited_by && <span className="muted block">by {l.edited_by}</span>}
                        </span>
                      )}
                    </td>
                    <td data-label="List · range" className="nowrap">{money(l?.list_price ?? it?.list_price ?? null, l?.basis ?? it?.basis)} · {it?.range || (l?.fixed ? 'fixed' : '—')}</td>
                    <td data-label="Year-1 value" className="num">{l ? money(l.line_value) : '…'}{l?.basis === '%' && <span className="small muted block">of {money(l.percent_of ?? 0)}</span>}</td>
                    <td data-label="Status"><span className="stack-xs">
                      {l && <Badge tone={PRICE_TONE[l.price_status]}>{PRICE_LABEL[l.price_status]}</Badge>}
                      {l && l.sellable_status !== 'available' && <Badge tone={SELL_TONE[l.sellable_status]}>{SELL_LABEL[l.sellable_status]}</Badge>}
                      {l?.item_status === 'retired' && <Badge tone="muted">Retired</Badge>}
                    </span></td>
                    <td data-label="Remove"><Button size="sm" variant="ghost" aria-label={`Remove ${raw.code}`} onClick={() => setLines((ls) => ls.filter((x) => x.code !== raw.code))}>×</Button></td>
                  </tr>
                  {expanded && (
                    <tr className="deliv-row">
                      <td colSpan={9}>
                        <div className="deliv-box">
                          <div className="row"><strong>What the client gets · {raw.code} {name}</strong>
                            {!showAll && <button type="button" className="linklike small" onClick={() => setOpen((s) => { const n = new Set(s); n.delete(raw.code); return n; })}>Hide</button>}
                          </div>
                          {tailor ? (
                            <div className="stack-sm">
                              <label className="sp-label" htmlFor={`d-${raw.code}`}>What the client gets, for this client</label>
                              <textarea id={`d-${raw.code}`} rows={6} value={raw.deliverables_override ?? l?.catalog_deliverables ?? ''} onChange={(e) => update(raw.code, { deliverables_override: e.target.value })} />
                              <label className="sp-label" htmlFor={`desc-${raw.code}`}>Description on the proposal</label>
                              <input id={`desc-${raw.code}`} value={raw.description ?? l?.description ?? ''} onChange={(e) => update(raw.code, { description: e.target.value })} />
                              <div className="row">
                                <Button size="sm" onClick={() => setTailoring((s) => { const n = new Set(s); n.delete(raw.code); return n; })}>Done</Button>
                                <Button size="sm" variant="ghost" onClick={() => update(raw.code, { deliverables_override: null, description: null })}>Use the price list text</Button>
                              </div>
                              <p className="small muted">This changes the text on this estimate only. The master price list keeps its wording.</p>
                            </div>
                          ) : (
                            <>
                              <div className="pre">{l?.deliverables || <span className="muted">The price list has no deliverables for this item yet.</span>}</div>
                              <button type="button" className="linklike small" onClick={() => setTailoring((s) => new Set(s).add(raw.code))}>Edit for this client</button>
                            </>
                          )}
                          {l?.assumption && <p className="small assumption"><strong>Assumption:</strong> {l.assumption}</p>}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {lines.length === 0 && <tr><td colSpan={9}><span className="muted">No lines yet. Start from a package or add items by code or name.</span></td></tr>}
          </tbody>
        </table>
      </div>

      <div className="est-bottom">
        <section className="card est-totals" aria-label="Totals">
          <div className="card-body stack-sm">
            <h2>Totals</h2>
            <div className="est-terms">
              <label className="field-inline">Discount on recurring (%)<input value={discount} onChange={(e) => setDiscount(e.target.value)} inputMode="decimal" aria-label="Discount on recurring (%)" /></label>
              <label className="field-inline">Term<select value={term} onChange={(e) => setTerm(Number(e.target.value))} aria-label="Term">{r.terms.map((t) => <option key={t} value={t}>{t} year{t === 1 ? '' : 's'}</option>)}</select></label>
              <label className="field-inline">Data region<select value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Data region"><option value="">Not set</option>{Object.entries(r.regions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            </div>
            <details>
              <summary>Custom terms</summary>
              <div className="est-terms">
                <label className="field-inline">Payment (days)<input inputMode="numeric" value={terms.payment_days ?? ''} onChange={(e) => setTerms({ ...terms, payment_days: e.target.value ? Number(e.target.value) : undefined })} aria-label="Payment terms in days" /></label>
                <label className="field-inline">One-time discount (%)<input inputMode="decimal" value={terms.discount_one_time_pct ?? ''} onChange={(e) => setTerms({ ...terms, discount_one_time_pct: e.target.value ? Number(e.target.value) : undefined })} aria-label="One-time discount (%)" /></label>
                <label className="field-inline grow">Custom liability<input value={terms.custom_liability ?? ''} onChange={(e) => setTerms({ ...terms, custom_liability: e.target.value || undefined })} aria-label="Custom liability terms" /></label>
                <Checkbox label="SLA credits" checked={!!terms.sla_credits} onChange={(e) => setTerms({ ...terms, sla_credits: e.target.checked || undefined })} />
              </div>
            </details>
            <dl className="totals">
              <dt>One-time</dt><dd>{money(totals.one_time)}</dd>
              <dt>Recurring, year 1</dt><dd>{money(totals.recurring_y1)}</dd>
              <dt>Discount</dt><dd>{totals.discount ? `−${money(totals.discount)}` : '$0'}</dd>
              <dt className="strong">Year-1 total</dt><dd className="strong">{money(totals.y1_total)}</dd>
              <dt>Annual recurring after year 1</dt><dd>{money(totals.arr)}</dd>
            </dl>
          </div>
        </section>
        <section className="card est-guard" aria-label="Approvals a proposal would need">
          <div className="card-body stack-sm">
            <h2>Approvals a proposal would need</h2>
            {!ev ? <p className="muted">Add lines to see guardrail warnings.</p> : (
              <>
                <p>{ev.summary}</p>
                {approvals.length > 0 && <ul className="guard-list">{approvals.map((a) => <li key={a.rule}><Badge tone="warn">{a.rule}</Badge> <strong>{a.approver}</strong>: {a.message}</li>)}</ul>}
                {notes.length > 0 && <ul className="guard-list">{notes.map((a) => <li key={a.rule}><Badge tone={a.kind === 'blocked' ? 'danger' : 'muted'}>{a.rule}</Badge> {a.message}</li>)}</ul>}
                <p className="small muted">Saving never needs approval. A proposal built from this needs these approvals before it can be sent.</p>
              </>
            )}
            <div className="row">
              <Button variant="primary" onClick={save} disabled={busy}>{saved ? 'Save as new version' : 'Save estimate'}</Button>
              <Button onClick={convert} disabled={!saved || !saved.can_convert || dirty}>Convert to proposal</Button>
            </div>
            {saved && <p className="small">Saved as v{saved.version} by {saved.saved_by}, {fmtDateTime(saved.saved_at)}.{dirty ? ' You have changes since then.' : ''} Saving never needs approval.</p>}
            {(!saved || !saved.can_convert) && <p className="small muted">{saved?.convert_note ?? r.convert_note ?? 'Save the estimate first; then convert it to a proposal.'}</p>}
            {saved?.versions && saved.versions.length > 1 && (
              <details><summary>Versions ({saved.versions.length})</summary>
                <ul>{saved.versions.map((v) => <li key={v.id}>{v.id === saved.id ? <strong>v{v.version}</strong> : <a href={`/sales/estimate?id=${v.id}`}>v{v.version}</a>} · {v.saved_by} · {fmtDateTime(v.saved_at)} · {money(v.y1_total)}</li>)}</ul>
              </details>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
