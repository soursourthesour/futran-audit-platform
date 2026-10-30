import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { oppHelp as H } from '@/help/monitoring';
import '@/styles/monitoring.css';

type Opp = {
  id: string; organization_id: string; client_name: string; trigger: string; trigger_label: string; service: string; service_kind: string; why_now: string | null; value: number | null;
  owner_id: string | null; owner_name: string | null; stage: string; stage_label: string; next_step: string | null; system_types: string[]; system_count: number; addon_status: string | null;
  needs_ca_approval: boolean; approval: string; ca_decision: string | null; ca_approved_by_name: string | null; ca_note: string | null; can_send_offer: boolean; created_at: string; closed_at: string | null;
  activities?: { id: string; kind: string; summary: string; by: string | null; at: string }[];
};
type Data = {
  items: Opp[]; kpis: { open: number; created_by_triggers_this_month: number; waiting_approval: number; pipeline_value: number; won_this_quarter: number };
  owners: { id: string; name: string }[]; clients: { id: string; name: string }[]; triggers: { value: string; label: string }[]; stages: { value: string; label: string }[]; can_approve: boolean;
};
type Msg = { tone: 'success' | 'danger'; text: string } | null;
const STAGE_TONE: Record<string, 'navy' | 'warn' | 'success' | 'muted'> = { new: 'navy', contacted: 'navy', proposal: 'warn', won: 'success', lost: 'muted' };
const APPROVAL_TONE: Record<string, 'warn' | 'success' | 'danger' | 'muted' | 'navy'> = { Needed: 'warn', Requested: 'navy', Approved: 'success', Declined: 'danger', 'Not needed': 'muted' };
const KINDS = [
  { value: 'audit', label: 'Audit' }, { value: 'bias_audit', label: 'Bias audit' }, { value: 'readiness', label: 'Readiness review' }, { value: 'addon', label: 'Add-on (tracing module)' },
  { value: 'advisory', label: 'Advisory' }, { value: 'training', label: 'Training' }, { value: 'remediation', label: 'Remediation support' }, { value: 'other', label: 'Other' },
];
const usd = (v: number | null) => (v === null || v === undefined ? '—' : `$${v.toLocaleString('en-US')}`);

export function Opportunities() {
  const [params, setParams] = useSearchParams();
  const { data: me } = useMe();
  const q = useQuery({ queryKey: ['opportunities'], queryFn: () => api.get<Data>('/opportunities') });
  const qc = useQueryClient();
  const [msg, setMsg] = useState<Msg>(null);
  const [adding, setAdding] = useState(false);
  const [bulkOwner, setBulkOwner] = useState<Opp[] | null>(null);
  const [bulkStage, setBulkStage] = useState<Opp[] | null>(null);
  const openId = params.get('open');
  const refresh = () => qc.invalidateQueries({ queryKey: ['opportunities'] });
  const d = q.data;
  async function patch(o: Opp, body: Record<string, unknown>, done: string) {
    try { await api.patch(`/opportunities/${o.id}`, body); await refresh(); setMsg({ tone: 'success', text: done }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function requestApproval(o: Opp) {
    try { await api.post(`/opportunities/${o.id}/request-approval`, { note: '' }); await refresh(); setMsg({ tone: 'success', text: 'The Chief Auditors have been asked to approve.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const columns: GridColumn<Opp>[] = [
    { key: 'client', header: 'Client', value: (o) => o.client_name, render: (o) => <button type="button" className="linklike left" onClick={() => setParams({ open: o.id })}><strong>{o.client_name}</strong></button> },
    { key: 'trigger', header: 'Trigger', value: (o) => o.trigger_label },
    { key: 'service', header: 'Service', value: (o) => o.service, render: (o) => <span>{o.service}{o.system_types.length > 0 && <span className="small muted block">{o.system_types.join(', ')}{o.system_count ? ` · ${o.system_count} ${o.system_count === 1 ? 'system' : 'systems'}` : ''}</span>}{o.addon_status && <span className="block"><Badge tone="navy">Add-on {o.addon_status}</Badge></span>}</span> },
    { key: 'why', header: 'Why now', value: (o) => o.why_now ?? '', render: (o) => <span className="clamp-3">{o.why_now}</span> },
    { key: 'value', header: 'Value', value: (o) => o.value ?? 0, render: (o) => <span className="nowrap">{usd(o.value)}</span> },
    { key: 'owner', header: 'Owner', value: (o) => o.owner_name ?? '' },
    { key: 'stage', header: 'Stage', value: (o) => o.stage_label, render: (o) => <Badge tone={STAGE_TONE[o.stage]}>{o.stage_label}</Badge> },
    { key: 'next', header: 'Next step', value: (o) => o.next_step ?? '', edit: { onSave: (o, v) => api.patch(`/opportunities/${o.id}`, { next_step: v }).then(refresh), label: (o) => `Next step for ${o.client_name}` } },
    { key: 'approval', header: 'Chief Auditor approval', value: (o) => o.approval, render: (o) => <span className="stack-xs"><Badge tone={APPROVAL_TONE[o.approval] ?? 'muted'}>{o.approval}</Badge>{o.needs_ca_approval && <span className="small muted">Current audit client</span>}</span> },
  ];
  const rowActions = (o: Opp): GridRowAction[] => [
    { label: 'Open opportunity', onSelect: () => setParams({ open: o.id }) },
    { label: 'Log a call or email', onSelect: () => setParams({ open: o.id, log: '1' }) },
    { label: 'Send proposal', disabled: !o.can_send_offer, onSelect: () => setParams({ open: o.id, proposal: '1' }) },
    ...(o.needs_ca_approval && !o.ca_decision ? [{ label: 'Ask Chief Auditor to approve', onSelect: () => requestApproval(o) }] : []),
    { label: 'Mark won', onSelect: () => patch(o, { stage: 'won' }, `${o.client_name}: marked won.`) },
    { label: 'Mark lost', onSelect: () => patch(o, { stage: 'lost' }, `${o.client_name}: marked lost.`) },
  ];
  return (
    <div className="page">
      <PageHeader title="Opportunities" subtitle="Created automatically when a client asks to unlock an add-on, a new rule or deadline affects them, a relevant case appears, or a high-risk system has no tracing. Shared by the Sales Team and the Chief Auditor."
        actions={<Button variant="primary" onClick={() => setAdding(true)}>Add opportunity</Button>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!d ? <Loading /> : (
        <>
          <div className="grid-tiles kpis">
            <div className="tile"><div className="label">Open opportunities</div><div className="value">{d.kpis.open}</div></div>
            <div className="tile"><div className="label">Created by triggers this month</div><div className="value">{d.kpis.created_by_triggers_this_month}</div></div>
            <div className="tile"><div className="label">Waiting for Chief Auditor approval</div><div className="value">{d.kpis.waiting_approval}</div></div>
            <div className="tile"><div className="label">Pipeline value</div><div className="value">{usd(d.kpis.pipeline_value)}</div></div>
            <div className="tile"><div className="label">Won this quarter</div><div className="value">{d.kpis.won_this_quarter}</div></div>
          </div>
          <Card>
            <DataGrid label="Opportunities" rows={d.items} rowId={(o) => o.id} rowLabel={(o) => `${o.client_name}: ${o.service}`} columns={columns} selectable
              bulkActions={[
                { label: 'Assign owner', run: async (rows) => setBulkOwner(rows) },
                { label: 'Change stage', run: async (rows) => setBulkStage(rows) },
                { label: 'Export', run: () => { window.location.href = '/api/v1/opportunities/export.csv'; } },
              ]}
              rowActions={rowActions}
              filters={[
                { key: 'trigger', label: 'Trigger', options: d.triggers, test: (o, v) => o.trigger === v },
                { key: 'stage', label: 'Stage', options: d.stages, test: (o, v) => o.stage === v },
                { key: 'owner', label: 'Owner', options: [{ value: 'me', label: 'Me' }, ...d.owners.map((o) => ({ value: o.id, label: o.name }))], test: (o, v) => (v === 'me' ? o.owner_id === me?.user.id : o.owner_id === v) },
              ]}
              search={{ label: 'Search opportunities', text: (o) => `${o.client_name} ${o.service} ${o.why_now ?? ''}` }}
              emptyText="No opportunities yet. They appear when a trigger fires, or add one." />
            <p className="small muted">Sales sees the trigger and the system type, never audit findings or evidence. An offer to a current audit client waits for Chief Auditor approval, and Futran does not sell the fix for a finding it raised in the same engagement.</p>
          </Card>
        </>
      )}
      {adding && d && <AddOpp d={d} onClose={() => setAdding(false)} onDone={(t) => { setAdding(false); setMsg({ tone: 'success', text: t }); refresh(); }} />}
      {openId && d && <OppDialog id={openId} d={d} log={params.get('log') === '1'} proposal={params.get('proposal') === '1'} onClose={() => setParams({})} onChanged={refresh} />}
      {bulkOwner && d && (
        <Dialog title="Assign owner" onClose={() => setBulkOwner(null)}>
          <BulkPick label="Owner" help={H.owner} options={d.owners.map((o) => ({ value: o.id, label: o.name }))} onSave={async (v) => { await api.post('/opportunities/bulk', { ids: bulkOwner.map((o) => o.id), owner_id: v }); setBulkOwner(null); refresh(); }} />
        </Dialog>
      )}
      {bulkStage && d && (
        <Dialog title="Change stage" onClose={() => setBulkStage(null)}>
          <BulkPick label="Stage" help={H.stage} options={d.stages} onSave={async (v) => { await api.post('/opportunities/bulk', { ids: bulkStage.map((o) => o.id), stage: v }); setBulkStage(null); refresh(); }} />
        </Dialog>
      )}
    </div>
  );
}

function BulkPick({ label, help, options, onSave }: { label: string; help: string; options: { value: string; label: string }[]; onSave: (v: string) => Promise<void> }) {
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

function AddOpp({ d, onClose, onDone }: { d: Data; onClose: () => void; onDone: (t: string) => void }) {
  const [f, setF] = useState({ organization_id: '', service: '', service_kind: 'other', why_now: '', value: '', owner_id: '', next_step: '' });
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setErr(null); setErrs({});
    try {
      await api.post('/opportunities', { ...f, value: f.value ? Number(f.value) : null, owner_id: f.owner_id || null, next_step: f.next_step || null });
      onDone('Opportunity added.');
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); }
  }
  return (
    <Dialog title="Add opportunity" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Client" help={H.client} value={f.organization_id} onChange={set('organization_id')} options={d.clients.map((c) => ({ value: c.id, label: c.name }))} placeholder="Choose" error={errs.organization_id} />
        <TextField label="Service" help={H.service} value={f.service} onChange={set('service')} error={errs.service} />
        <SelectField label="Type of service" help={H.kind} value={f.service_kind} onChange={set('service_kind')} options={KINDS} />
        <TextField label="Why now" help={H.why} value={f.why_now} onChange={set('why_now')} />
        <TextField label="Value (US dollars)" help={H.value} type="number" min={0} value={f.value} onChange={set('value')} error={errs.value} />
        <SelectField label="Owner" help={H.owner} value={f.owner_id} onChange={set('owner_id')} options={d.owners.map((o) => ({ value: o.id, label: o.name }))} placeholder="Me" />
        <TextField label="Next step" help={H.nextStep} value={f.next_step} onChange={set('next_step')} />
        <div className="row"><Button variant="primary" disabled={!f.organization_id || !f.service} onClick={save}>Add opportunity</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function OppDialog({ id, d, log, proposal, onClose, onChanged }: { id: string; d: Data; log: boolean; proposal: boolean; onClose: () => void; onChanged: () => void }) {
  const q = useQuery({ queryKey: ['opportunity', id], queryFn: () => api.get<Opp>(`/opportunities/${id}`) });
  const qc = useQueryClient();
  const [kind, setKind] = useState(proposal ? 'proposal' : 'call');
  const [text, setText] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (proposal) setKind('proposal'); }, [proposal]);
  if (q.isLoading || !q.data) return <Dialog title="Opportunity" onClose={onClose}><Loading /></Dialog>;
  const o = q.data;
  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); setText(''); setNote(''); await qc.invalidateQueries({ queryKey: ['opportunity', id] }); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  }
  const logIt = () => run(() => (kind === 'proposal' ? api.post(`/opportunities/${o.id}/send-proposal`, { summary: text }) : api.post(`/opportunities/${o.id}/activities`, { kind, summary: text })));
  return (
    <Dialog title={`${o.client_name} · ${o.service}`} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <dl className="kv">
          <dt>Trigger</dt><dd>{o.trigger_label}{o.why_now ? `: ${o.why_now}` : ''}</dd>
          <dt>AI systems</dt><dd>{o.system_types.length ? o.system_types.join(', ') : '—'}</dd>
          <dt>Stage</dt><dd><Badge tone={STAGE_TONE[o.stage]}>{o.stage_label}</Badge></dd>
          <dt>Owner</dt><dd>{o.owner_name ?? '—'}</dd>
          <dt>Value</dt><dd>{usd(o.value)}</dd>
          <dt>Chief Auditor approval</dt><dd><Badge tone={APPROVAL_TONE[o.approval] ?? 'muted'}>{o.approval}</Badge>{o.ca_approved_by_name ? ` · ${o.ca_approved_by_name}` : ''}{o.ca_note ? ` · ${o.ca_note}` : ''}</dd>
        </dl>
        {o.needs_ca_approval && !o.can_send_offer && <Alert tone="warn">{H.approval}{o.ca_decision === 'declined' ? ' The Chief Auditor declined this offer.' : ''}</Alert>}
        {d.can_approve && o.needs_ca_approval && (
          <div className="stack-sm approve-box">
            <TextField label="Approval note" help={H.approval} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row"><Button variant="primary" onClick={() => run(() => api.post(`/opportunities/${o.id}/approve`, { decision: 'approve', note }))}>Approve the offer</Button><Button onClick={() => run(() => api.post(`/opportunities/${o.id}/approve`, { decision: 'decline', note }))}>Decline</Button></div>
          </div>
        )}
        {!d.can_approve && o.needs_ca_approval && !o.ca_decision && <div><Button onClick={() => run(() => api.post(`/opportunities/${o.id}/request-approval`, { note: '' }))}>Ask Chief Auditor to approve</Button></div>}
        <fieldset className="stack-sm">
          <legend>{log ? 'Log a call or email' : 'Log activity'}</legend>
          <SelectField label="What happened" help={H.activity} value={kind} onChange={(e) => setKind(e.target.value)}
            options={[{ value: 'call', label: 'Call' }, { value: 'email', label: 'Email' }, { value: 'meeting', label: 'Meeting' }, { value: 'note', label: 'Note' }, { value: 'proposal', label: 'Proposal sent' }, { value: 'outcome', label: 'Outcome' }]} />
          <TextArea label="Summary" help={H.summary} value={text} onChange={(e) => setText(e.target.value)} rows={2} />
          <div><Button variant="primary" disabled={!text.trim() || (kind === 'proposal' && !o.can_send_offer)} onClick={logIt}>{kind === 'proposal' ? 'Log the proposal' : 'Log it'}</Button></div>
        </fieldset>
        <div>
          <strong>Activity</strong>
          {!o.activities?.length ? <p className="small muted">Nothing logged yet.</p> : (
            <ul className="activity">{o.activities.map((a) => <li key={a.id}><span className="small muted">{fmtDateTime(a.at)} · {a.by ?? 'System'} · {a.kind.replace('_', ' ')}</span><span>{a.summary}</span></li>)}</ul>
          )}
        </div>
      </div>
    </Dialog>
  );
}
