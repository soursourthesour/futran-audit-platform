import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, EmptyState, Loading, TextArea, fmtDateTime } from '@/components/ui';
import { money, type ApprovalDetail, type ApprovalItem } from '@/api/proposals';
import '@/styles/proposals.css';

type Queue = { tab: string; items: ApprovalItem[]; counts: { mine: number; pricing: number; independence: number }; roles: string[] };
const TABS = [['mine', 'Mine'], ['pricing', 'Pricing'], ['independence', 'Independence'], ['decided', 'Decided']] as const;
const ROLE_LABEL: Record<string, string> = { sales_manager: 'Sales Manager', pricing_approver: 'Pricing Approver', chief_auditor: 'Chief Auditor' };

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  const days = Math.round(mins / 1440);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

/** SM-11 Approvals: the queue by rule, the selected request with its lines against the catalog, approve or return. */
export function Approvals() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'mine';
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['approvals', tab], queryFn: () => api.get<Queue>(`/sales/approvals?tab=${tab}`) });
  const selected = params.get('request') ?? q.data?.items[0]?.id ?? null;
  const det = useQuery({ queryKey: ['approval', selected], queryFn: () => api.get<ApprovalDetail>(`/sales/approvals/${selected}`), enabled: !!selected });
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { setNote(''); setErr(null); }, [selected]);

  async function decide(decision: 'approve' | 'return') {
    setErr(null);
    try {
      await api.post(`/sales/approvals/${selected}/decide`, { decision, note });
      setMsg(decision === 'approve' ? 'Approved for this proposal version.' : 'Returned to the rep with your note.');
      qc.invalidateQueries({ queryKey: ['approvals'] });
      qc.invalidateQueries({ queryKey: ['approval', selected] });
    } catch (e) { setErr(errorMessage(e)); }
  }
  const pick = (id: string) => { const n = new URLSearchParams(params); n.set('request', id); setParams(n); setMsg(null); };
  const d = det.data;
  const roles = q.data?.roles.map((r) => ROLE_LABEL[r]).join(', ');

  return (
    <div className="page ap-page">
      <div className="page-header"><div><h1>Approvals</h1>{roles && <p className="small muted">You decide as {roles}.</p>}</div></div>
      <nav className="tabs" aria-label="Approval queues">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" className={tab === k ? 'active' : ''} aria-current={tab === k ? 'page' : undefined} onClick={() => setParams({ tab: k })}>
            {label}{k !== 'decided' && q.data ? ` (${q.data.counts[k as 'mine']})` : ''}
          </button>
        ))}
      </nav>
      {msg && <Alert tone="success">{msg}</Alert>}
      <div className="ap-grid">
        <section className="card ap-list" aria-label="Requests">
          {q.isLoading ? <Loading /> : !q.data?.items.length ? <EmptyState>Nothing waiting here.</EmptyState> : (
            <ul>
              {q.data.items.map((i) => (
                <li key={i.id}>
                  <button type="button" className={`ap-item ${i.id === selected ? 'active' : ''}`} onClick={() => pick(i.id)} aria-current={i.id === selected ? 'true' : undefined}>
                    <span className="ap-item-head">{i.company} · Proposal v{i.version}</span>
                    <span><Badge tone={i.kind === 'independence' ? 'navy' : 'warn'}>{i.rule}</Badge> {i.message.split(':')[0]}</span>
                    <span className="small muted">{i.requested_by} · {ago(i.requested_at)}{i.status !== 'pending' ? ` · ${i.status}` : ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="small muted ap-foot">Independence requests (I-1 to I-3) go to the Chief Auditor. Discounts up to the limit go to the Sales Manager.</p>
        </section>
        <section className="card ap-detail" aria-label="Selected request">
          {!selected ? <EmptyState>Choose a request.</EmptyState> : !d ? <Loading /> : (
            <div className="card-body stack-sm">
              <h2>{d.rule} · {d.approver_label}</h2>
              <p><Link to={`/sales/proposals/${d.proposal_id}`}>{d.company} · Proposal v{d.version}</Link> · Year-1 {money(d.y1_total)}</p>
              <p>{d.message}</p>
              <div className="table-wrap">
                <table className="pb-table" aria-label="Lines against the catalog">
                  <thead><tr><th>Code</th><th>Line</th><th className="num">Qty</th><th className="num">Low</th><th className="num">List</th><th className="num">Price used</th><th className="num">High</th></tr></thead>
                  <tbody>
                    {d.lines.filter((l) => l.focus).map((l) => (
                      <tr key={l.code}>
                        <td><strong>{l.code}</strong></td><td>{l.name}{l.price_status === 'proposed' && <> <Badge tone="warn">Proposed</Badge></>}</td><td className="num">{l.qty}</td>
                        <td className="num">{money(l.low)}</td><td className="num">{money(l.list)}</td>
                        <td className={`num ${l.used !== null && l.low !== null && l.used < l.low ? 'ap-below' : ''}`}><strong>{money(l.used)}</strong>{l.edited && <div className="small muted">edited</div>}</td>
                        <td className="num">{money(l.high)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small"><strong>Margin note.</strong> {d.margin_note}{d.discount_recurring_pct ? ` Discount on recurring ${d.discount_recurring_pct}%.` : ''}{d.terms.payment_days ? ` Payment in ${d.terms.payment_days} days.` : ''}</p>
              {d.independence && <Alert tone={d.independence.flag ? 'warn' : 'info'}><strong>Independence.</strong> {d.independence.reason}</Alert>}
              <p className="small muted">Approving here applies to this proposal only. To make a price standard, a Price List Owner changes it in the <Link to="/staff/admin/catalog">master price list</Link>.</p>
              {d.status !== 'pending' ? (
                <p><Badge tone={d.status === 'approved' ? 'success' : 'danger'}>{d.status === 'approved' ? 'Approved' : d.status === 'returned' ? 'Returned' : 'Replaced'}</Badge> {d.decided_by && `by ${d.decided_by}`} {d.decided_at && fmtDateTime(d.decided_at)}{d.note && ` — ${d.note}`}</p>
              ) : d.can_decide ? (
                <>
                  <TextArea label={d.note_required ? 'Note (required to approve)' : 'Note to the rep'} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
                  {err && <Alert tone="danger">{err}</Alert>}
                  <div className="row">
                    <Button onClick={() => decide('return')}>Return with note</Button>
                    <Button variant="primary" onClick={() => decide('approve')}>Approve for this proposal</Button>
                  </div>
                </>
              ) : <Alert tone="warn">{d.why_not}</Alert>}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
