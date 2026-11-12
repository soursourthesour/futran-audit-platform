import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Dialog, Loading, TextArea, TextField } from '@/components/ui';
import '@/styles/scoping.css';

type Rule = {
  code: string; line_code: string; inputs: Record<string, unknown>; qty_formula: Record<string, unknown>; reason_template: string; note: string | null; order: number; active: boolean;
  status: 'approved' | 'pending' | 'rejected'; pending: Record<string, unknown> | null; pending_by_name: string | null; pending_at: string | null; approved_by_name: string | null;
  approved_at: string | null; questions: string[]; flag: string | null;
};
type Data = { rules: Rule[]; flagged: number; catalog_installed: boolean; can_edit: boolean; can_approve: boolean; me: string };

type Cond = { q?: string | string[]; op?: string; value?: unknown; all?: Cond[]; any?: Cond[] };
const OPS: Record<string, string> = { eq: '=', ne: '≠', lt: '<', lte: '≤', gt: '>', gte: '≥', in: 'is one of', includes: 'includes', any_ticked: 'has any ticked', unknown: 'is unknown', between: 'between', count_between: 'ticked count between' };

function cond(c: Cond): string {
  if (c.all) return c.all.map(cond).join(' and ');
  if (c.any) return c.any.map(cond).join(' or ');
  const q = Array.isArray(c.q) ? c.q.join(' + ') : c.q;
  const v = Array.isArray(c.value) ? (c.op?.includes('between') ? `${c.value[0] ?? 0}–${c.value[1] ?? 'any'}` : c.value.join(', ')) : c.value ?? '';
  return `${q} ${OPS[c.op ?? ''] ?? c.op} ${v}`.trim();
}
function qty(f: Record<string, unknown>): string {
  if ('const' in f) return String(f.const);
  if ('answer' in f) return `${f.answer}${f.add ? ` ${Number(f.add) < 0 ? '−' : '+'} ${Math.abs(Number(f.add))}` : ''}${f.min ? ` (min ${f.min})` : ''}`;
  if ('count' in f) return `options ticked in ${f.count}${f.min ? ` (min ${f.min})` : ''}`;
  if ('sum' in f) return (f.sum as string[]).join(' + ');
  if ('excess_included' in f) return 'systems above the tier’s included count';
  return JSON.stringify(f);
}

function Editor({ r, onClose, onSaved }: { r: Rule | null; onClose: () => void; onSaved: (m: string) => void }) {
  const src = (r?.pending as Partial<Rule> | null) ?? r;
  const [f, setF] = useState({ code: r?.code ?? '', line_code: src?.line_code ?? '', reason_template: src?.reason_template ?? '', note: src?.note ?? '',
    inputs: JSON.stringify(src?.inputs ?? { all: [] }, null, 2), qty_formula: JSON.stringify(src?.qty_formula ?? { const: 1 }, null, 2) });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null); setFe({});
    let inputs, qf;
    try { inputs = JSON.parse(f.inputs); } catch { setFe({ inputs: 'The conditions are not valid JSON.' }); return; }
    try { qf = JSON.parse(f.qty_formula); } catch { setFe({ qty_formula: 'The quantity is not valid JSON.' }); return; }
    const body = { code: f.code, line_code: f.line_code, reason_template: f.reason_template, note: f.note || null, inputs, qty_formula: qf };
    try {
      if (r) await api.put(`/scoping/rules/${r.code}`, body); else await api.post('/scoping/rules', body);
      onSaved(`${r ? r.code : f.code} sent to the Pricing Approver. The approved version keeps running until then.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={r ? `Edit ${r.code}` : 'Add a mapping rule'} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {!r && <TextField label="Rule code" hint="e.g. MR-20" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} error={fe.code} />}
        <TextField label="Price list code it proposes" value={f.line_code} onChange={(e) => setF({ ...f, line_code: e.target.value })} error={fe.line_code} />
        <TextArea label="When (conditions, JSON)" hint='e.g. {"all": [{"q": "SQ-C.07", "op": "between", "value": [0, 10]}]}' rows={6} className="mono" value={f.inputs} onChange={(e) => setF({ ...f, inputs: e.target.value })} error={fe.inputs} />
        <TextArea label="Quantity (JSON)" hint='e.g. {"const": 1} or {"answer": "SQ-B.06", "add": -1}' rows={3} className="mono" value={f.qty_formula} onChange={(e) => setF({ ...f, qty_formula: e.target.value })} error={fe.qty_formula} />
        <TextField label="Reason shown to the rep" hint="{SQ-C.07} is the answer, {SQ-C.07.confidence} its confidence, {qty} the quantity" value={f.reason_template} onChange={(e) => setF({ ...f, reason_template: e.target.value })} error={fe.reason_template} />
        <TextField label="Note (optional)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <div className="row" style={{ gap: 8 }}><Button variant="primary" onClick={save}>Send for approval</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** SM-14 Mapping rules tab content: rules as data; the Futran Admin edits, the Pricing Approver approves. A rule whose
 *  line code is not in the price list is flagged here for repair, never dropped. */
export function MappingRulesTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['scoping-rules'], queryFn: () => api.get<Data>('/scoping/rules') });
  const [edit, setEdit] = useState<Rule | null | 'new'>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [only, setOnly] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['scoping-rules'] });
  if (q.isLoading) return <Loading />;
  const d = q.data;
  if (!d) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  async function act(r: Rule, path: string, body?: unknown, done?: string) {
    try { await api.post(`/scoping/rules/${r.code}/${path}`, body); setMsg({ tone: 'success', text: done ?? `${r.code} updated.` }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const rows = d.rules.filter((r) => !only || r.flag || r.pending || r.status === 'pending');
  return (
    <div className="stack">
      {!d.catalog_installed && <Alert tone="info">The price list is not installed yet, so rules cannot be checked against it.</Alert>}
      {d.flagged > 0 && <Alert tone="warn">{d.flagged} rule{d.flagged === 1 ? '' : 's'} point to a code that is not in the price list, or is retired. They stay here, flagged, until repaired.</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="row sc-toolbar">
        <span className="small muted">{d.rules.length} rules · spec §4.5 seeded</span>
        <label className="small sc-option"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} />Only flagged or waiting</label>
        {d.can_edit && <Button variant="primary" onClick={() => setEdit('new')}>Add a rule</Button>}
      </div>
      <div className="sc-table-wrap"><table className="sc-table">
        <thead><tr><th>Rule</th><th>Line</th><th>When</th><th>Quantity</th><th>Reason</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.code} className={r.active ? '' : 'muted'}>
            <td className="nowrap"><strong>{r.code}</strong></td>
            <td className="nowrap">{r.line_code}{r.flag && <span className="block"><Badge tone="danger">{r.flag.includes('could not be applied') ? 'Cannot run' : 'Not in price list'}</Badge></span>}</td>
            <td className="small">{cond(r.inputs as Cond)}{r.note && <span className="block muted">{r.note}</span>}{r.flag && <span className="block sc-flag">{r.flag}</span>}</td>
            <td className="small">{qty(r.qty_formula)}</td>
            <td className="small">{r.reason_template}</td>
            <td className="small">
              {r.status === 'pending' ? <Badge tone="warn">New, waiting approval</Badge> : r.status === 'rejected' ? <Badge tone="muted">Returned</Badge> : <Badge tone="success">Approved</Badge>}
              {r.pending && <span className="block"><Badge tone="warn">{r.pending.active !== undefined && r.pending.active !== r.active ? (r.pending.active ? 'Switch on waiting approval' : 'Switch off waiting approval') : 'Edit waiting approval'}</Badge> by {r.pending_by_name}</span>}
              {!r.active && <span className="block"><Badge tone="muted">Switched off</Badge></span>}
              {r.approved_by_name && r.status === 'approved' && <span className="block muted">{r.approved_by_name}</span>}
            </td>
            <td><div className="stack-xs">
              {d.can_edit && <Button size="sm" onClick={() => setEdit(r)}>Edit</Button>}
              {d.can_edit && <Button size="sm" onClick={() => act(r, 'active', { active: !r.active }, `${r.code}: ${r.active ? 'switch off' : 'switch on'} sent to the Pricing Approver. The rule runs as it is until then.`)}>{r.active ? 'Ask to switch off' : 'Ask to switch on'}</Button>}
              {d.can_approve && (r.pending || r.status === 'pending') && <><Button size="sm" variant="primary" onClick={() => act(r, 'approve', undefined, `${r.code} approved.`)}>Approve</Button><Button size="sm" onClick={() => act(r, 'reject', undefined, `${r.code} returned.`)}>Return</Button></>}
            </div></td>
          </tr>
        ))}</tbody>
      </table></div>
      {edit && <Editor r={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={(m) => { setEdit(null); setMsg({ tone: 'success', text: m }); void refresh(); }} />}
    </div>
  );
}
