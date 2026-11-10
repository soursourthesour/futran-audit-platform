import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { CONFIDENCE_LABEL, type Obligation } from '@/api/ai';
import { obligationHelp as H } from '@/help/ai';
import { RejectDialog } from './Copilot';
import './copilot.css';

/** F5 obligation extraction (spec §21): proposals from the law's stored text, approved by the Legal Reviewer or the
 *  Chief Auditor. Approved obligations show on the law record and feed lineage. */

const ACTORS = [{ value: 'employer', label: 'Employer' }, { value: 'deployer', label: 'Deployer' }, { value: 'developer', label: 'Developer' }, { value: 'provider', label: 'Provider' }, { value: 'data_fiduciary', label: 'Data fiduciary' }];
const actorLabel = (a: string) => ACTORS.find((x) => x.value === a)?.label ?? a;

function ApproveDialog({ o, onClose, onDone }: { o: Obligation; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ text: o.text, actor: o.actor, action: o.action ?? '', condition: o.condition ?? '', deadline: o.deadline ?? '', citation: o.citation ?? '', questions: o.question_ids.join(', ') });
  const [err, setErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    if (busy) return;
    setBusy(true); setErr({});
    const body = { text: f.text, actor: f.actor, action: f.action || null, condition: f.condition || null, deadline: f.deadline || null, citation: f.citation || null,
      question_ids: f.questions.split(',').map((x) => x.trim()).filter(Boolean) };
    try { await api.post(`/obligations/${o.id}/approve`, body); onDone(); onClose(); } catch (e) { setErr({ text: errorMessage(e), ...fieldErrors(e), questions: fieldErrors(e).question_ids }); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Approve obligation" onClose={onClose} wide>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
        {o.quote && <div className="cp-quote"><blockquote>“{o.quote}”</blockquote><div className="small muted">Quoted from the law's stored text{o.citation ? ` · ${o.citation}` : ''}</div></div>}
        <TextArea label="Obligation" help={H.text} value={f.text} onChange={set('text')} error={err.text} rows={2} />
        <div className="grid-2">
          <SelectField label="Who must act" help={H.actor} value={f.actor} options={ACTORS} onChange={set('actor')} error={err.actor} />
          <TextField label="Section" help={H.citation} value={f.citation} onChange={set('citation')} />
        </div>
        <TextField label="Action" help={H.action} value={f.action} onChange={set('action')} />
        <TextField label="Condition" help={H.condition} value={f.condition} onChange={set('condition')} />
        <TextField label="Deadline" help={H.deadline} value={f.deadline} onChange={set('deadline')} />
        <TextField label="Template questions" help={H.questions} value={f.questions} onChange={set('questions')} error={err.questions} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" disabled={busy}>Approve</Button></div>
      </form>
    </Dialog>
  );
}

function PendingList({ rows, onDone, showLaw }: { rows: Obligation[]; onDone: () => void; showLaw?: boolean }) {
  const [approving, setApproving] = useState<Obligation | null>(null);
  const [rejecting, setRejecting] = useState<Obligation | null>(null);
  const columns: GridColumn<Obligation>[] = [
    ...(showLaw ? [{ key: 'law', header: 'Law', value: (o: Obligation) => o.law ?? '', render: (o: Obligation) => <Link to={`/reg/${o.regulation_id}`}>{o.law}</Link> }] : []),
    { key: 'text', header: 'Proposed obligation', value: (o) => o.text, render: (o) => <><div>{o.text}</div>{o.quote && <div className="small muted">“{o.quote}”</div>}</> },
    { key: 'actor', header: 'Who', value: (o) => actorLabel(o.actor) },
    { key: 'deadline', header: 'Deadline', value: (o) => o.deadline ?? '' },
    { key: 'citation', header: 'Section', value: (o) => o.citation ?? '' },
    { key: 'links', header: 'Linked', value: (o) => [...o.requirements, ...o.question_ids].join(', ') },
    { key: 'status', header: 'Check', value: (o) => o.status, render: (o) => o.status === 'unsupported' ? <Badge tone="danger">Quote not in the law text</Badge> : <Badge tone="navy">{CONFIDENCE_LABEL[o.confidence ?? 'low']}</Badge> },
  ];
  return (
    <>
      <DataGrid label="Proposed obligations" rows={rows} rowId={(o) => o.id} rowLabel={(o) => o.text} columns={columns} emptyText="Nothing waiting for review."
        rowActions={(o) => [{ label: 'Approve', onSelect: () => setApproving(o), disabled: o.status === 'unsupported' }, { label: 'Reject', danger: true, onSelect: () => setRejecting(o) }]} />
      {approving && <ApproveDialog o={approving} onClose={() => setApproving(null)} onDone={onDone} />}
      {rejecting && <RejectDialog title="Reject the proposed obligation" onClose={() => setRejecting(null)} onReject={async (reason) => { await api.post(`/obligations/${rejecting.id}/reject`, { reason }); onDone(); }} />}
    </>
  );
}

type LawObligations = { law: { id: string; short_name: string }; approved: Obligation[]; pending: Obligation[]; can_extract: boolean; can_approve: boolean };

/** Panel on the law record (M2). */
export function ObligationsPanel({ lawId }: { lawId: string }) {
  const qc = useQueryClient();
  const key = ['obligations', lawId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<LawObligations>(`/reg/laws/${lawId}/obligations`) });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (!q.data) return null;
  const d = q.data;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: key }), qc.invalidateQueries({ queryKey: ['nav-badges'] })]);
  async function extract() {
    if (busy) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.post<{ obligations: Obligation[]; message?: string | null }>(`/reg/laws/${lawId}/obligations/extract`);
      await refresh();
      setMsg({ tone: r.message ? 'danger' : 'success', text: `${r.obligations.length} obligation${r.obligations.length === 1 ? '' : 's'} proposed. None is used until a reviewer approves it.${r.message ? ` ${r.message}` : ''}` });
    }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  return (
    <Card title={`Obligations (${d.approved.length})`} actions={d.can_extract ? <Button disabled={busy} onClick={extract}>{busy ? 'Reading the law…' : 'Extract obligations'}</Button> : undefined}>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {d.approved.length === 0 ? <p className="small muted" style={{ marginTop: 0 }}>No approved obligations yet.{d.can_extract ? ' "Extract obligations" proposes them from the stored text of the law; a Legal Reviewer or the Chief Auditor approves each one.' : ''}</p>
        : <ul className="cp-list">{d.approved.map((o) => (
          <li key={o.id}><div><strong>{actorLabel(o.actor)}</strong>: {o.text}</div>
            <div className="small muted">{[o.citation, o.deadline && `Deadline: ${o.deadline}`, o.requirements.length ? `Requirements ${o.requirements.join(', ')}` : '', o.question_ids.length ? `Questions ${o.question_ids.join(', ')}` : '', `Approved by ${o.approved_by}`].filter(Boolean).join(' · ')}</div></li>))}</ul>}
      {d.can_approve && d.pending.length > 0 && <div style={{ marginTop: 12 }}><h3 style={{ fontSize: '1rem', margin: '0 0 8px' }}>Waiting for review ({d.pending.length})</h3><PendingList rows={d.pending} onDone={refresh} /></div>}
    </Card>
  );
}

/** The reviewers' queue across all laws (the Legal Reviewer holds no other law-library permission). */
export function ObligationQueue() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['obligation-queue'], queryFn: () => api.get<{ rows: Obligation[] }>('/reg/obligations') });
  return (
    <div className="page">
      <PageHeader title="Obligations to review" subtitle="Obligations the AI proposed from the stored text of each law. Approve, edit or reject each one; only approved obligations show on the law record and in lineage." />
      {q.isLoading ? <Loading /> : !q.data ? <Alert tone="danger">{errorMessage(q.error)}</Alert>
        : q.data.rows.length === 0 ? <EmptyState>Nothing waiting for review.</EmptyState>
          : <PendingList rows={q.data.rows} showLaw onDone={() => Promise.all([qc.invalidateQueries({ queryKey: ['obligation-queue'] }), qc.invalidateQueries({ queryKey: ['nav-badges'] })])} />}
    </div>
  );
}
