import { useMemo, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, Loading, PageHeader, SelectField, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { type Opp, type OppList, PIPELINE, STAGE_TONE, oppLink, usd } from '@/api/sales';
import { salesHelp as H } from '@/help/sales';
import { LogOpportunity } from './LogOpportunity';
import '@/styles/sales.css';

type Msg = { tone: 'success' | 'danger'; text: string } | null;
const PRODUCT_FILTER = [
  { value: 'audit', label: 'Audit' }, { value: 'monitor', label: 'Monitor' }, { value: 'll144', label: 'LL144' }, { value: 'agent_assure', label: 'Agent Assure' },
  { value: 'agentwarden', label: 'AgentWarden' }, { value: 'other', label: 'Other services' },
];

/** /opportunities (v0.6 S1) now lives at /sales/opportunities; old links keep their filters, and ?open=<id> opens the record. */
export function OpportunitiesRedirect() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const open = params.get('open');
  if (open) return <Navigate to={oppLink(open)} replace />;
  return <Navigate to={`/sales/opportunities${search}`} replace />;
}

export function CompanyCell({ o }: { o: Opp }) {
  return (
    <span className="stack-xs">
      <Link to={oppLink(o.id)}><strong>{o.company.name}</strong></Link>
      <span className="small muted">
        <Badge tone={o.company.kind === 'prospect' ? 'navy' : 'default'}>{o.company.kind === 'prospect' ? 'Prospect' : 'Client'}</Badge>
        {[o.company.industry, o.company.hq].filter(Boolean).length > 0 && ` ${[o.company.industry, o.company.hq].filter(Boolean).join(' · ')}`}
      </span>
    </span>
  );
}

/** SM-02 Opportunities: manual and automatic, as a list or a board by stage (spec §4.12). */
export function SalesOpportunities() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { data: me } = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['opportunities'], queryFn: () => api.get<OppList>('/opportunities') });
  const [msg, setMsg] = useState<Msg>(null);
  const [bulkOwner, setBulkOwner] = useState<Opp[] | null>(null);
  const [bulkStage, setBulkStage] = useState<Opp[] | null>(null);
  const view = params.get('view') === 'board' ? 'board' : 'list';
  const logging = params.get('log') === '1';
  const flagOnly = params.get('flag') === '1';
  const staleOnly = params.get('stale') === '1';
  const setParam = (k: string, v: string | null) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  const refresh = () => qc.invalidateQueries({ queryKey: ['opportunities'] });
  const d = q.data;
  const meId = me?.user.id ?? '';
  const rows = useMemo(() => (d?.items ?? []).filter((o) => (!flagOnly || o.independence_flag) && (!staleOnly || o.stale)), [d, flagOnly, staleOnly]);
  const openCount = (d?.items ?? []).filter((o) => !['won', 'lost'].includes(o.stage)).length;

  async function patch(o: Opp, body: Record<string, unknown>, done: string) {
    try { await api.patch(`/opportunities/${o.id}`, body); await refresh(); setMsg({ tone: 'success', text: done }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const columns: GridColumn<Opp>[] = [
    { key: 'company', header: 'Company', value: (o) => o.company.name, render: (o) => <CompanyCell o={o} /> },
    { key: 'source', header: 'Source / trigger', value: (o) => `${o.source_label ?? ''} ${o.trigger_label}`, render: (o) => (
      <span className="stack-xs"><span>{o.is_automatic ? 'Automatic' : o.source_label ?? 'Added by hand'}</span><span className="small muted">{o.is_automatic ? o.trigger_label : o.trigger_event_label ?? o.why_now ?? ''}</span></span>
    ) },
    { key: 'products', header: 'Products', value: (o) => o.products_labels.join(', ') || o.service, render: (o) => <span className="clamp-3">{o.products_labels.length ? o.products_labels.join(', ') : o.service}</span> },
    { key: 'value', header: 'Value', value: (o) => o.value ?? 0, render: (o) => <span className="nowrap">{usd(o.value)}</span> },
    { key: 'stage', header: 'Stage', value: (o) => o.stage_label, render: (o) => <Badge tone={STAGE_TONE[o.stage]}>{o.stage_label}</Badge> },
    { key: 'next', header: 'Next step', value: (o) => o.next_step ?? '', render: (o) => (
      <span className="stack-xs"><span>{o.next_step ?? '—'}</span>{o.stale ? <span className="small text-warn">Stale · no activity for 14 days</span> : o.next_step_due ? <span className="small muted">Due {fmtDate(o.next_step_due)}</span> : null}</span>
    ) },
    { key: 'owner', header: 'Owner', value: (o) => o.owner_name ?? '' },
    { key: 'flags', header: 'Flags', value: (o) => (o.independence_flag ? 'Independence' : ''), render: (o) => (
      <span className="stack-xs">{o.independence_flag ? <Badge tone="warn">Independence</Badge> : <span className="muted">—</span>}{o.needs_ca_approval && o.approval !== 'Not needed' && <span className="small muted">Chief Auditor: {o.approval}</span>}</span>
    ) },
  ];
  const rowActions = (o: Opp): GridRowAction[] => [
    { label: 'Open', onSelect: () => nav(oppLink(o.id)) },
    { label: 'Log activity', disabled: !o.can_edit, onSelect: () => nav(`${oppLink(o.id)}?tab=activity`) },
    { label: 'Start scoping', disabled: !o.can_edit, onSelect: () => nav(`${oppLink(o.id)}/scoping`) },
    { label: 'Build estimate', disabled: !o.can_edit, onSelect: () => nav(`/sales/estimate?opportunity=${o.id}`) },
    { label: 'Change owner', disabled: !d?.can_reassign, onSelect: () => setBulkOwner([o]) },
    { label: 'Mark lost', disabled: !o.can_edit || o.stage === 'lost', onSelect: () => nav(`${oppLink(o.id)}?lose=1`) },
  ];

  return (
    <div className="page sales-page">
      <PageHeader title="Opportunities" subtitle={d ? `Manual and automatic · ${openCount} open` : undefined}
        actions={<>
          <div className="pills" role="tablist" aria-label="View">
            <button type="button" role="tab" className="pill" aria-selected={view === 'list'} onClick={() => setParam('view', null)}>List</button>
            <button type="button" role="tab" className="pill" aria-selected={view === 'board'} onClick={() => setParam('view', 'board')}>Board</button>
          </div>
          {d?.can_work && <Button variant="primary" onClick={() => setParam('log', '1')}>Log opportunity</Button>}
        </>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!d ? <Loading /> : (
        <>
          <div className="row sales-toggles">
            <Checkbox label="Independence flag only" checked={flagOnly} onChange={(e) => setParam('flag', e.target.checked ? '1' : null)} help={H.independence} />
            <Checkbox label="Stale only" checked={staleOnly} onChange={(e) => setParam('stale', e.target.checked ? '1' : null)} help={H.stale} />
          </div>
          {view === 'list' ? (
            <Card>
              <DataGrid label="Opportunities" rows={rows} rowId={(o) => o.id} rowLabel={(o) => `${o.company.name}: ${o.name}`} columns={columns} selectable={d.can_work}
                initialFilters={{ stage: params.get('stage') ?? 'open', ...(params.get('owner') ? { owner: params.get('owner')! } : {}), ...(params.get('source') ? { source: params.get('source')! } : {}),
                                  ...(params.get('trigger') ? { trigger: params.get('trigger')! } : {}), ...(params.get('product') ? { product: params.get('product')! } : {}) }}
                bulkActions={[
                  ...(d.can_reassign ? [{ label: 'Assign owner', run: async (r: Opp[]) => setBulkOwner(r) }] : []),
                  ...(d.can_work ? [{ label: 'Change stage', run: async (r: Opp[]) => setBulkStage(r) }] : []),
                  { label: 'Export', run: async (r: Opp[]) => { window.location.href = `/api/v1/opportunities/export.csv?ids=${r.map((o) => o.id).join(',')}`; } },
                ]}
                rowActions={rowActions}
                filters={[
                  { key: 'stage', label: 'Stage', options: [{ value: 'open', label: 'All open' }, ...d.stages], test: (o, v) => (v === 'open' ? !['won', 'lost'].includes(o.stage) : o.stage === v) },
                  { key: 'source', label: 'Source', options: [{ value: 'manual', label: 'Manual' }, { value: 'auto', label: 'Automatic trigger' }, { value: 'partner', label: 'Partner referral' }],
                    test: (o, v) => (v === 'manual' ? !o.is_automatic : v === 'auto' ? o.is_automatic : o.source === 'referral_partner' || !!o.partner_id) },
                  { key: 'trigger', label: 'Trigger', options: d.triggers, test: (o, v) => o.trigger === v },
                  { key: 'product', label: 'Product', options: PRODUCT_FILTER, test: (o, v) => (v === 'other' ? !o.products_of_interest.some((p) => PRODUCT_FILTER.some((f) => f.value === p && f.value !== 'other')) : o.products_of_interest.includes(v)) },
                  { key: 'owner', label: 'Owner', options: [{ value: 'me', label: 'Me' }, ...d.owners.map((o) => ({ value: o.id, label: o.name }))], test: (o, v) => (v === 'me' ? o.owner_id === meId : o.owner_id === v) },
                ]}
                search={{ label: 'Search opportunities', text: (o) => `${o.company.name} ${o.name} ${o.service} ${o.why_now ?? ''} ${o.next_step ?? ''}` }}
                emptyText="No opportunities yet. Log one, or they appear when a trigger fires." />
              <p className="small muted">Sales sees the trigger and the system type, never audit findings or evidence. An offer to a flagged company waits for the Chief Auditor's approval.</p>
            </Card>
          ) : <Board rows={rows} onMove={(o, stage) => patch(o, { stage }, `${o.company.name}: moved to ${d.stages.find((s) => s.value === stage)?.label ?? stage}.`)} canMove={d.can_work} />}
        </>
      )}
      {logging && d && me && <LogOpportunity opts={d} me={me.user.id} onClose={() => setParam('log', null)} />}
      {bulkOwner && d && (
        <Dialog title="Assign owner" onClose={() => setBulkOwner(null)}>
          <BulkPick label="Owner" options={d.owners.map((o) => ({ value: o.id, label: o.name }))} onSave={async (v) => {
            const r = await api.post<{ changed: number; skipped: number }>('/opportunities/bulk', { ids: bulkOwner.map((o) => o.id), owner_id: v });
            setBulkOwner(null); await refresh(); setMsg({ tone: 'success', text: `${r.changed} reassigned${r.skipped ? `; ${r.skipped} left as they were` : ''}.` });
          }} />
        </Dialog>
      )}
      {bulkStage && d && (
        <Dialog title="Change stage" onClose={() => setBulkStage(null)}>
          <BulkPick label="Stage" help={H.stage} options={d.stages.filter((s) => s.value !== 'lost')} onSave={async (v) => {
            const r = await api.post<{ changed: number; skipped: number }>('/opportunities/bulk', { ids: bulkStage.map((o) => o.id), stage: v });
            setBulkStage(null); await refresh();
            setMsg({ tone: 'success', text: `${r.changed} moved${r.skipped ? `; ${r.skipped} left as they were (approval, qualification or ownership rules)` : ''}.` });
          }} />
        </Dialog>
      )}
    </div>
  );
}

function Board({ rows, onMove, canMove }: { rows: Opp[]; onMove: (o: Opp, stage: string) => void; canMove: boolean }) {
  const cols = [...PIPELINE.map((s) => ({ stage: s, rows: rows.filter((o) => o.stage === s || (s === 'new' && o.stage === 'contacted')) })),
    { stage: 'on_hold', rows: rows.filter((o) => o.stage === 'on_hold') }];
  const label = (s: string) => ({ new: 'New', qualified: 'Qualified', scoping: 'Scoping', proposal: 'Proposal', negotiation: 'Negotiation', on_hold: 'On hold' })[s] ?? s;
  return (
    <div className="sales-board" aria-label="Opportunities by stage">
      {cols.map((c) => (
        <section key={c.stage} className="sales-col" aria-label={label(c.stage)}
          onDragOver={(e) => { if (canMove) e.preventDefault(); }}
          onDrop={(e) => { const id = e.dataTransfer.getData('text/plain'); const o = rows.find((r) => r.id === id); if (o && o.can_edit && o.stage !== c.stage) onMove(o, c.stage); }}>
          <header><strong>{label(c.stage)}</strong><span className="small muted">{c.rows.length} · {usd(c.rows.reduce((t, o) => t + (o.value ?? 0), 0))}</span></header>
          {c.rows.map((o) => (
            <article key={o.id} className="sales-card" draggable={canMove && !!o.can_edit} onDragStart={(e) => e.dataTransfer.setData('text/plain', o.id)}>
              <Link to={oppLink(o.id)}><strong>{o.company.name}</strong></Link>
              <div className="small">{o.products_labels.join(', ') || o.name}</div>
              <div className="row small"><span>{usd(o.value)}</span><span className="muted">{o.owner_name ?? 'No owner'}</span></div>
              <div className="row small">
                <Badge tone={o.company.kind === 'prospect' ? 'navy' : 'default'}>{o.company.kind === 'prospect' ? 'Prospect' : 'Client'}</Badge>
                {o.is_automatic && <Badge tone="muted">Automatic</Badge>}
                {o.independence_flag && <Badge tone="warn">Independence</Badge>}
                {o.stale && <Badge tone="danger">Stale</Badge>}
              </div>
              {canMove && o.can_edit && (
                <label className="small sales-move">Move to{' '}
                  <select value={o.stage} onChange={(e) => onMove(o, e.target.value)} aria-label={`Move ${o.company.name} to stage`}>
                    {[...PIPELINE, 'on_hold'].map((s) => <option key={s} value={s}>{label(s)}</option>)}
                  </select>
                </label>
              )}
            </article>
          ))}
          {c.rows.length === 0 && <p className="small muted">None</p>}
        </section>
      ))}
    </div>
  );
}

function BulkPick({ label, help, options, onSave }: { label: string; help?: string; options: { value: string; label: string }[]; onSave: (v: string) => Promise<void> }) {
  const [v, setV] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="stack">
      {err && <Alert tone="danger">{err}</Alert>}
      <SelectField label={label} help={help} value={v} onChange={(e) => setV(e.target.value)} options={options} placeholder="Choose" />
      <div><Button variant="primary" disabled={!v} onClick={() => onSave(v).catch((e) => setErr(errorMessage(e)))}>Save</Button></div>
    </div>
  );
}
