import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Dialog, Loading, TextArea } from '@/components/ui';
import { money, type Diff, type Line, type Proposal, type RuleState } from '@/api/proposals';
import '@/styles/proposals.css';

const STATUS_TONE: Record<string, 'warn' | 'success' | 'navy' | 'danger' | 'muted' | 'default'> = {
  draft: 'warn', awaiting_approval: 'warn', approved: 'success', sent: 'navy', viewed: 'navy', changes_requested: 'warn', accepted: 'success',
  expired: 'muted', superseded: 'muted',
};
const BADGE_TONE: Record<string, 'warn' | 'success' | 'navy' | 'danger' | 'muted'> = {
  'Proposed price': 'warn', Approved: 'success', 'Existing price': 'success', Edited: 'navy', 'Manual delivery': 'navy', Roadmap: 'muted',
  'Below Low': 'danger', 'Above High': 'warn', 'No price': 'danger', 'Not on the price list': 'danger',
};
const SOURCE: Record<string, string> = { rule: 'Rule', package: 'Package', manual: 'Added' };

type CatalogRef = { items: { code: string; name: string; can_add: boolean }[] };

export function statusBadge(status: string, label: string) {
  return <Badge tone={STATUS_TONE[status] ?? 'default'}>{label}</Badge>;
}

function num(v: string): number | null {
  const t = v.replace(/[$,\s]/g, '');
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

/** SM-09 Proposal builder. */
export function ProposalBuilder() {
  const { id = '' } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ['proposal', id], queryFn: () => api.get<Proposal>(`/sales/proposals/${id}`) });
  const cat = useQuery({ queryKey: ['estimator-ref'], queryFn: () => api.get<CatalogRef>('/sales/estimator'), retry: false });
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Line | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const p = q.data;

  async function call(fn: () => Promise<Proposal>, ok?: string) {
    setErr(null); setMsg(null);
    try {
      const out = await fn();
      qc.setQueryData(['proposal', id], out);
      qc.invalidateQueries({ queryKey: ['proposal-diff', id] });
      if (ok) setMsg(ok);
      return out;
    } catch (e) { setErr(errorMessage(e)); return null; }
  }

  if (q.isLoading) return <Loading />;
  if (!p) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const editable = p.editable && p.can_work;
  const approvals = p.rules.filter((r) => r.kind === 'approval');
  const toRequest = approvals.filter((r) => r.state === 'missing' || r.state === 'returned' || r.state === 'outdated');
  const live = p.lines.filter((l) => !l.removed_reason);
  const removed = p.lines.filter((l) => l.removed_reason);
  const prev = p.versions.find((v) => v.version === p.version - 1);

  async function requestApprovals() {
    setErr(null);
    try {
      const out = await api.post<{ requested: string[]; proposal: Proposal }>(`/sales/proposals/${id}/approvals`);
      qc.setQueryData(['proposal', id], out.proposal);
      setMsg(out.requested.length ? `Sent for approval: ${out.requested.join(', ')}.` : 'Nothing new to ask for.');
    } catch (e) { setErr(errorMessage(e)); }
  }
  async function newVersion() {
    try {
      const out = await api.post<Proposal>(`/sales/proposals/${id}/versions`);
      nav(`/sales/proposals/${out.id}`);
    } catch (e) { setErr(errorMessage(e)); }
  }

  return (
    <div className="page pb-page">
      <div className="page-header">
        <div>
          <Link to={`/sales/opportunities/${p.opportunity_id}`} className="small">{p.company}{p.prospect ? ' · prospect' : ''}</Link>
          <h1>Proposal v{p.version} {statusBadge(p.status, p.status === 'draft' && p.approvals_needed.length ? 'Draft · needs approval' : p.status_label)}</h1>
          <p className="small muted">
            {p.questionnaire_version ? `Questionnaire v${p.questionnaire_version} (locked) · ` : ''}Catalog v{p.catalog_version ?? '—'} · {p.valid_until ? `valid until ${p.valid_until}` : `valid ${p.valid_days} days from send`}
          </p>
        </div>
        <div className="pb-head-controls">
          <label className="pb-inline">Package
            <select className="select" value={p.package ?? ''} disabled={!editable} onChange={(e) => e.target.value && call(() => api.post(`/sales/proposals/${id}/package`, { package: e.target.value }), 'Package lines updated.')}>
              <option value="">Choose…</option>
              {p.packages.map((k) => <option key={k.key} value={k.key}>{k.name}</option>)}
            </select>
          </label>
          <label className="pb-inline">Version
            <select className="select" value={p.id} onChange={(e) => nav(`/sales/proposals/${e.target.value}`)}>
              {p.versions.map((v) => <option key={v.id} value={v.id}>v{v.version} ({v.status_label.toLowerCase()})</option>)}
            </select>
          </label>
          {prev && <Button onClick={() => setShowDiff((s) => !s)} aria-expanded={showDiff}>{showDiff ? 'Hide changes' : `Changes since v${prev.version}`}</Button>}
          {!p.editable && p.can_work && p.status !== 'accepted' && p.versions[p.versions.length - 1].id === p.id && <Button onClick={newVersion}>Start v{p.version + 1}</Button>}
        </div>
      </div>
      {err && <Alert tone="danger">{err}</Alert>}
      {msg && <Alert tone="success">{msg}</Alert>}
      {!p.editable && <Alert>Version {p.version} is {p.status_label.toLowerCase()} and can't change. {p.status !== 'accepted' && 'Start a new version to make changes.'}</Alert>}
      {showDiff && prev && <DiffPanel id={id} from={prev.version} to={p.version} />}
      {p.editable && p.price_changes.length > 0 && (
        <Alert tone="warn">
          <strong>List prices changed since this draft.</strong> {p.price_changes.map((c) => {
            const lp = c.changes.list_price;
            return lp ? `${c.code}: ${money(lp.from as number)} → ${money(lp.to as number)}` : `${c.code}: ${Object.keys(c.changes).map((k) => k.replace('_', ' ')).join(', ')} changed`;
          }).join('; ')}. The draft keeps its prices; kept prices are checked against the current list when you send.
          {editable && <div className="row" style={{ marginTop: 8 }}><Button size="sm" variant="primary" onClick={() => call(() => api.post(`/sales/proposals/${id}/current-prices`), 'Updated to current list prices.')}>Update to current list prices</Button></div>}
        </Alert>
      )}

      <section className="card" aria-label="Lines">
        {editable && <AddLine items={cat.data?.items ?? []} onAdd={(code, qty) => call(() => api.post(`/sales/proposals/${id}/lines`, { code, qty }), `${code} added.`)} />}
        <div className="table-wrap">
          <table className="pb-table" aria-label="Proposal lines">
            <thead>
              <tr><th>Code</th><th>Line item</th><th>Why it's here</th><th className="num">Qty</th><th>Billing</th><th className="num">List</th><th className="num">Edited price</th>
                <th className="num">Unit used</th><th className="num">Periods</th><th className="num">Year-1 value</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {live.length === 0 && <tr><td colSpan={12} className="muted">No lines yet. Pick a package or add a line by code.</td></tr>}
              {live.map((l) => (
                <LineRow key={l.id} l={l} editable={editable} open={open === l.id} onToggle={() => setOpen(open === l.id ? null : l.id)}
                  onPatch={(body, ok) => call(() => api.patch(`/sales/proposals/${id}/lines/${l.id}`, body), ok)}
                  onRemove={() => (l.source === 'rule' ? setRemoving(l) : call(() => api.post(`/sales/proposals/${id}/lines/${l.id}/remove`, {}), `${l.code} removed.`))} />
              ))}
            </tbody>
          </table>
        </div>
        {removed.length > 0 && (
          <details className="pb-removed">
            <summary>{removed.length} suggested line{removed.length !== 1 ? 's' : ''} removed</summary>
            <ul>
              {removed.map((l) => (
                <li key={l.id}><strong>{l.code}</strong> {l.name} — {l.removed_reason}
                  {editable && <Button size="sm" variant="ghost" onClick={() => call(() => api.post(`/sales/proposals/${id}/lines/${l.id}/restore`), `${l.code} restored.`)}>Restore</Button>}</li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <div className="pb-bottom">
        <div className="stack">
          <RulesPanel rules={p.rules} independence={p.independence} />
          <TermsPanel p={p} editable={editable} onSave={(body) => call(() => api.patch(`/sales/proposals/${id}`, body), 'Saved.')} />
        </div>
        <div className="stack">
          <section className="card pb-totals" aria-label="Totals">
            <div className="card-header"><h2>Totals</h2></div>
            <div className="card-body">
              <dl className="pb-dl">
                <dt>One-time</dt><dd>{money(p.totals.one_time)}</dd>
                {!!p.totals.one_time_discount && <><dt>One-time discount ({p.terms.discount_one_time_pct}%)</dt><dd>{money(-p.totals.one_time_discount)}</dd></>}
                <dt>Recurring, year 1</dt><dd>{money(p.totals.recurring_y1)}</dd>
                <dt>Discount on recurring ({p.discount_recurring_pct}%)</dt><dd>{money(-p.totals.discount)}</dd>
                <dt className="pb-strong">Year-1 total</dt><dd className="pb-strong">{money(p.totals.y1_total)}</dd>
                <dt>Annual recurring after year 1</dt><dd>{money(p.totals.arr)}</dd>
              </dl>
              <div className="row pb-actions">
                {editable && <Button variant="primary" onClick={requestApprovals} disabled={!p.can_request}>Request approvals ({toRequest.length})</Button>}
                <Link className="btn" to={`/sales/proposals/${id}/send`}>{p.editable ? 'Preview and send' : 'Document and send log'}</Link>
              </div>
              {p.editable && p.send_blockers.length > 0 && <p className="small muted">Before sending: {p.send_blockers.map((b) => b.rule).join(', ')}.</p>}
            </div>
          </section>
          <SectionsPanel p={p} editable={editable} onSave={(key, body) => call(() => api.put(`/sales/proposals/${id}/sections/${key}`, { body }), 'Section saved.')} />
        </div>
      </div>

      {removing && (
        <RemoveDialog line={removing} onClose={() => setRemoving(null)}
          onConfirm={async (reason) => { const out = await call(() => api.post(`/sales/proposals/${id}/lines/${removing.id}/remove`, { reason }), `${removing.code} removed.`); if (out) setRemoving(null); }} />
      )}
    </div>
  );
}

function AddLine({ items, onAdd }: { items: CatalogRef['items']; onAdd: (code: string, qty: number) => void }) {
  const [code, setCode] = useState('');
  const [qty, setQty] = useState('1');
  return (
    <form className="pb-add" onSubmit={(e) => { e.preventDefault(); const c = code.split(' ')[0].trim(); if (c) { onAdd(c, Number(qty) || 1); setCode(''); setQty('1'); } }}>
      <div className="field"><label htmlFor="pb-add-code">Add line by code or name</label>
        <input id="pb-add-code" className="input" list="pb-codes" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. L-01" />
        <datalist id="pb-codes">{items.filter((i) => i.can_add).map((i) => <option key={i.code} value={`${i.code} ${i.name}`} />)}</datalist>
      </div>
      <div className="field pb-qty"><label htmlFor="pb-add-qty">Qty</label><input id="pb-add-qty" className="input" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
      <Button type="submit" variant="primary">Add line</Button>
    </form>
  );
}

function LineRow({ l, editable, open, onToggle, onPatch, onRemove }: {
  l: Line; editable: boolean; open: boolean; onToggle: () => void; onPatch: (body: Record<string, unknown>, ok?: string) => void; onRemove: () => void;
}) {
  const [qty, setQty] = useState(String(l.qty));
  const [price, setPrice] = useState(l.override_price === null ? '' : String(l.override_price));
  const [deliv, setDeliv] = useState(l.deliverables ?? '');
  useEffect(() => { setQty(String(l.qty)); setPrice(l.override_price === null ? '' : String(l.override_price)); setDeliv(l.deliverables ?? ''); }, [l]);
  const roadmap = l.sellable_status === 'roadmap';
  const pct = l.basis === '%';
  return (
    <>
      <tr className={roadmap ? 'pb-optional' : undefined}>
        <td><strong>{l.code}</strong></td>
        <td>
          <button type="button" className="pb-link" onClick={onToggle} aria-expanded={open}>{l.name}</button>
          {pct && l.percent_of !== null && <div className="small muted">{l.unit_price_used}% of {money(l.percent_of)}</div>}
        </td>
        <td className="small">{roadmap ? 'Shown under "Optional, when available" with no price (P-7)' : l.reason ?? SOURCE[l.source]}{l.rule_code && <div className="muted">{l.rule_code}</div>}</td>
        <td className="num">{editable ? <input className="input pb-num" aria-label={`Quantity for ${l.code}`} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)}
          onBlur={() => Number(qty) !== l.qty && onPatch({ qty: Number(qty) })} /> : l.qty}</td>
        <td className="small">{l.billing_label}{l.billing !== 'one_time' && l.periods_per_year > 1 ? ` × ${l.periods_per_year}` : ''}</td>
        <td className="num">{pct ? (l.list_price !== null ? `${l.list_price}%` : '—') : money(l.list_price)}{l.low !== null && !roadmap && <div className="small muted">{pct ? `${l.low}–${l.high}%` : `${money(l.low)}–${money(l.high)}`}</div>}</td>
        <td className="num">
          {editable && !roadmap && l.on_catalog ? (
            <>
              <input className="input pb-num" aria-label={`Edited price for ${l.code}`} inputMode="decimal" placeholder="List" value={price} onChange={(e) => setPrice(e.target.value)}
                onBlur={() => { const n = num(price); if (n !== l.override_price && !Number.isNaN(n)) onPatch({ override_price: n }, n === null ? `${l.code} reset to the list price.` : undefined); }} />
              {l.override_price !== null && <Button size="sm" variant="ghost" onClick={() => onPatch({ override_price: null }, `${l.code} reset to the list price.`)}>Reset to list price</Button>}
            </>
          ) : l.override_price !== null ? money(l.override_price) : '—'}
        </td>
        <td className="num">{roadmap ? '—' : pct ? (l.unit_price_used !== null ? `${l.unit_price_used}%` : '—') : money(l.unit_price_used)}</td>
        <td className="num">{l.billing === 'one_time' ? 1 : l.periods_per_year}</td>
        <td className="num"><strong>{roadmap ? 'No price' : money(l.line_value)}</strong></td>
        <td><div className="pb-badges">{l.badges.map((b) => <Badge key={b} tone={BADGE_TONE[b]}>{b}</Badge>)}</div></td>
        <td>{editable && <Button size="sm" variant="ghost" aria-label={`Remove ${l.code}`} onClick={onRemove}>Remove</Button>}</td>
      </tr>
      {open && (
        <tr className="pb-expand">
          <td colSpan={12}>
            <div className="pb-deliv">
              <TextArea label={`What we'll do — ${l.code} (shown in the proposal)`} rows={7} value={deliv} disabled={!editable} onChange={(e) => setDeliv(e.target.value)}
                hint={l.deliverables_edited ? 'Tailored for this proposal. Clear it to go back to the price list wording.' : 'From the master price list. Edits stay on this proposal only.'} />
              {editable && <div className="row"><Button size="sm" variant="primary" onClick={() => onPatch({ deliverables_text: deliv }, 'Wording saved.')}>Save wording</Button>
                {l.deliverables_edited && <Button size="sm" onClick={() => onPatch({ deliverables_text: '' }, 'Wording reset to the price list.')}>Use price list wording</Button>}</div>}
              {l.edited_by && <p className="small muted">Price edited by {l.edited_by}.</p>}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

const STATE_LABEL: Record<string, string> = { missing: 'Not requested', pending: 'Waiting', approved: 'Approved', returned: 'Returned', outdated: 'Needs asking again' };
const STATE_TONE: Record<string, 'warn' | 'success' | 'danger' | 'muted'> = { missing: 'warn', pending: 'warn', approved: 'success', returned: 'danger', outdated: 'danger' };

function RulesPanel({ rules, independence }: { rules: RuleState[]; independence: Proposal['independence'] }) {
  const pricing = rules.filter((r) => !r.rule.startsWith('I-'));
  const ind = rules.filter((r) => r.rule.startsWith('I-'));
  return (
    <section className="card" aria-label="Guardrails and approvals">
      <div className="card-header"><h2>Guardrails and approvals</h2></div>
      <div className="card-body stack-sm">
        {pricing.length === 0 && <p className="muted">No approvals needed: every line is at an approved or existing list price with no discount.</p>}
        {pricing.map((r, i) => <RuleRow key={`${r.rule}-${i}`} r={r} />)}
        <div className={`pb-rule ${independence.flag ? 'pb-rule-flag' : ''}`}>
          <strong>Independence.</strong> {independence.flag ? independence.reason : 'No flag on this opportunity.'}
        </div>
        {ind.map((r, i) => <RuleRow key={`${r.rule}-${i}`} r={r} />)}
      </div>
    </section>
  );
}

function RuleRow({ r }: { r: RuleState }) {
  const head = r.kind === 'approval' ? `${r.rule} · ${r.approver} needed.` : r.kind === 'blocked' ? `${r.rule === 'PRICE' ? 'Price' : r.rule} · Blocks sending.` : `${r.rule} · Note.`;
  return (
    <div className={`pb-rule pb-rule-${r.kind}`}>
      <div className="row"><strong>{head}</strong>{r.state && <Badge tone={STATE_TONE[r.state]}>{STATE_LABEL[r.state]}</Badge>}</div>
      <div className="small">{r.message}</div>
      {r.note && <div className="small muted">Note: {r.note}</div>}
    </div>
  );
}

function TermsPanel({ p, editable, onSave }: { p: Proposal; editable: boolean; onSave: (body: Record<string, unknown>) => void }) {
  const [d, setD] = useState(String(p.discount_recurring_pct));
  const [days, setDays] = useState(String(p.valid_days));
  const [t, setT] = useState(p.terms);
  useEffect(() => { setD(String(p.discount_recurring_pct)); setDays(String(p.valid_days)); setT(p.terms); }, [p]);
  const set = (k: keyof typeof t, v: unknown) => setT({ ...t, [k]: v });
  return (
    <section className="card" aria-label="Discount and terms">
      <div className="card-header"><h2>Discount and terms</h2></div>
      <div className="card-body">
        <fieldset className="pb-terms" disabled={!editable}>
          <div className="field"><label htmlFor="pb-disc">Discount on recurring (%)</label><input id="pb-disc" className="input" inputMode="decimal" value={d} onChange={(e) => setD(e.target.value)} />
            <div className="help">Up to {p.discount_limit_pct}% goes to the Sales Manager; above it, the Pricing Approver.</div></div>
          <div className="field"><label htmlFor="pb-days">Valid for (days)</label><input id="pb-days" className="input" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></div>
          <div className="field"><label htmlFor="pb-pay">Payment (days)</label><input id="pb-pay" className="input" inputMode="numeric" value={t.payment_days ?? ''} onChange={(e) => set('payment_days', e.target.value)} />
            <div className="help">Over 30 days needs the Pricing Approver (P-6).</div></div>
          <div className="field"><label htmlFor="pb-term">Contract term</label>
            <select id="pb-term" className="select" value={t.term_years ?? 1} onChange={(e) => set('term_years', Number(e.target.value))}>
              <option value={1}>1 year</option><option value={2}>2 years</option><option value={3}>3 years</option></select></div>
          <div className="field"><label htmlFor="pb-region">Data residency</label>
            <select id="pb-region" className="select" value={t.data_region ?? ''} onChange={(e) => set('data_region', e.target.value)}>
              <option value="">Not stated</option>{Object.entries(p.regions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="field"><label htmlFor="pb-sla">Service levels (SLA)</label><input id="pb-sla" className="input" value={t.sla ?? ''} onChange={(e) => set('sla', e.target.value)} /></div>
          <div className="field"><label htmlFor="pb-credits">SLA credits (custom term)</label><input id="pb-credits" className="input" value={t.sla_credits ?? ''} onChange={(e) => set('sla_credits', e.target.value)} /></div>
          <div className="field"><label htmlFor="pb-liab">Liability (custom term)</label><input id="pb-liab" className="input" value={t.custom_liability ?? ''} onChange={(e) => set('custom_liability', e.target.value)} /></div>
          <div className="field"><label htmlFor="pb-onetime">One-time discount (%)</label><input id="pb-onetime" className="input" inputMode="decimal" value={t.discount_one_time_pct ?? ''} onChange={(e) => set('discount_one_time_pct', e.target.value)} />
            <div className="help">Any one-time discount needs the Pricing Approver (P-3).</div></div>
        </fieldset>
        {editable && <Button variant="primary" onClick={() => onSave({ discount_recurring_pct: Number(d) || 0, valid_days: Number(days) || 30, terms: t })}>Save terms</Button>}
      </div>
    </section>
  );
}

function SectionsPanel({ p, editable, onSave }: { p: Proposal; editable: boolean; onSave: (key: string, body: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [text, setText] = useState('');
  return (
    <section className="card" aria-label="Sections">
      <div className="card-header"><h2>Sections</h2></div>
      <div className="card-body">
        <ol className="pb-sections">
          {p.sections.map((s) => (
            <li key={s.key}>
              <div className="row"><strong>{s.title}</strong>{s.edited && <Badge tone="navy">Edited</Badge>}
                {editable && s.key !== 'independence' && <Button size="sm" variant="ghost" onClick={() => { setEdit(s.key); setText(s.body); }}>Edit</Button>}
                {s.key === 'independence' && <span className="small muted">Fixed wording (I-4)</span>}</div>
              {edit === s.key ? (
                <div className="stack-sm">
                  <TextArea label={`${s.title} wording`} rows={6} value={text} onChange={(e) => setText(e.target.value)} hint="Merge fields: [Company], [Rep name], [Valid until], [Version], [Date]. Clear it to use the template." />
                  <div className="row"><Button size="sm" variant="primary" onClick={() => { onSave(s.key, text); setEdit(null); }}>Save section</Button><Button size="sm" onClick={() => setEdit(null)}>Cancel</Button></div>
                </div>
              ) : <p className="small muted pb-clip">{s.body || 'Built from the lines.'}</p>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return v >= 100 ? money(v) : String(v);
  return String(v);
}

function DiffPanel({ id, from, to }: { id: string; from: number; to: number }) {
  const q = useQuery({ queryKey: ['proposal-diff', id], queryFn: () => api.get<Diff>(`/sales/proposals/${id}/diff`) });
  const d = q.data;
  return (
    <section className="card pb-diff" aria-label={`Changes from v${from} to v${to}`}>
      <div className="card-header"><h2>Changes from v{from} to v{to}</h2></div>
      <div className="card-body">
        {!d ? <Loading /> : d.lines.length + d.terms.length === 0 ? <p className="muted">No changes yet.</p> : (
          <ul className="pb-diff-list">
            {d.lines.map((l) => (
              <li key={l.code} className={`pb-diff-${l.kind}`}>
                <Badge tone={l.kind === 'added' ? 'success' : l.kind === 'removed' ? 'danger' : 'warn'}>{l.kind === 'added' ? 'Added' : l.kind === 'removed' ? 'Removed' : 'Changed'}</Badge>
                <strong>{l.code}</strong> {l.name}
                {l.changes.map((c) => <span key={c.field} className="small"> · {c.field}{c.field === 'wording' ? ' tailored' : `: ${fmtVal(c.from)} → ${fmtVal(c.to)}`}</span>)}
                {l.reason && <span className="small muted"> · {l.reason}</span>}
              </li>
            ))}
            {d.terms.map((t) => <li key={t.field}><Badge tone="warn">Terms</Badge> {t.field}: {fmtVal(t.from)} → {fmtVal(t.to)}</li>)}
            {Object.entries(d.totals).filter(([k]) => k === 'y1_total').map(([k, v]) => <li key={k}><Badge tone="navy">Total</Badge> Year-1 total: {money(v.from)} → {money(v.to)}</li>)}
          </ul>
        )}
      </div>
    </section>
  );
}

function RemoveDialog({ line, onClose, onConfirm }: { line: Line; onClose: () => void; onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState('');
  return (
    <Dialog title={`Remove ${line.code}`} onClose={onClose}>
      <div className="stack-sm">
        <p>{line.name} was suggested by a mapping rule ({line.reason}). Say why it comes off this proposal; the reason stays on the record.</p>
        <TextArea label="Reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="row"><Button variant="danger" disabled={!reason.trim()} onClick={() => onConfirm(reason)}>Remove line</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
