import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import type { Block, PolicyDoc, Question } from '@/api/wsi';
import { Alert, Badge, Button, Checkbox, Dialog, FieldGroup, Loading, PageHeader, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { BlockEditor, BlockView } from './Blocks';
import { POLICY_TONE } from './Policies';
import { policyHelp as H } from '@/help/wsi';
import './wsi.css';

const STEPS = ['Answer questions', 'Review draft', 'Approve', 'Staff acknowledgment'];

function stepOf(p: PolicyDoc): number {
  if (p.status === 'draft') return 1;  // the questions and the draft are on the same screen
  if (p.status === 'awaiting_approval') return 2;
  return 3;
}

/** Policy builder `/policies/:id` (screen 27): guided answers, the generated draft, edits, approval and acknowledgments. */
export function PolicyBuilder() {
  const { policyId = '' } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['policy', policyId], queryFn: () => api.get<PolicyDoc>(`/policies/${policyId}`) });
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [dirtyText, setDirtyText] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'info'; text: string } | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [dialog, setDialog] = useState<'regen' | 'return' | 'approve' | 'review' | 'ack' | null>(null);
  useEffect(() => { if (q.data) { setAnswers(q.data.answers ?? {}); setBlocks(q.data.blocks ?? []); setDirtyText(false); } }, [q.data]);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const p = q.data;
  const can = p.can ?? { edit: false, approve: false, request_review: false };
  const step = stepOf(p);
  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null); setFe({});
    try { await fn(); setMsg({ tone: 'success', text: ok }); setDialog(null); await qc.invalidateQueries({ queryKey: ['policy', policyId] }); await qc.invalidateQueries({ queryKey: ['policies'] }); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); setFe(fieldErrors(e)); }
    finally { setBusy(false); }
  }
  const regenerate = () => run(() => api.put(`/policies/${p.id}/answers`, { answers, regenerate: true }), 'Draft regenerated from your answers.');
  const saveText = () => run(() => api.put(`/policies/${p.id}/text`, { blocks }), 'Text saved.');
  const submit = () => run(async () => { if (dirtyText) await api.put(`/policies/${p.id}/text`, { blocks }); await api.put(`/policies/${p.id}/answers`, { answers }); await api.post(`/policies/${p.id}/submit`); },
    'Sent to the Chief AI Compliance Officer for approval.');
  return (
    <div className="page">
      <PageHeader title={p.title}
        crumbs={[{ to: '/governance', label: 'Governance' }, ...(p.commitment ? [{ label: `Commitment: ${p.commitment.description}` }] : []), { to: '/policies', label: 'Policies' }, { label: 'Policy builder' }]}
        subtitle={<><span>Futran template v{p.template.version} · version {p.version_no} · <Badge tone={POLICY_TONE[p.status]}>{p.status_label}</Badge></span>
          <ol className="wsi-steps" aria-label="Steps">{STEPS.map((s, i) => <li key={s} aria-current={i === step ? 'step' : undefined}>{s}</li>)}</ol></>}
        actions={p.commitment && p.commitment.status !== 'closed' ? <Badge tone="warn">Commitment due {fmtDate(p.commitment.target_date)}</Badge> : p.commitment ? <Badge tone="success">Commitment closed</Badge> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {p.return_note && p.status === 'draft' && <Alert tone="warn">Returned for changes: {p.return_note}</Alert>}
      {p.status === 'awaiting_approval' && !can.approve && <Alert tone="info">Sent for approval by {p.submitted_by} on {fmtDateTime(p.submitted_at)}. The Chief AI Compliance Officer approves or returns it.</Alert>}
      {p.status === 'published' && <Alert tone="success">Approved by {p.approved_by} on {fmtDate(p.approved_at)} and published. Next review by {fmtDate(p.review_due)}.</Alert>}
      {p.status === 'retired' && <Alert tone="info">This version has been replaced by a later one.</Alert>}
      <div className="wsi-two">
        <section className="card wsi-side" aria-labelledby="pb-choices-h">
          <div className="card-header"><h2 id="pb-choices-h">Your choices</h2></div>
          <div className="card-body stack">
            {(p.questions ?? []).map((qn) => <QuestionField key={qn.key} q={qn} value={answers[qn.key]} error={fe[qn.key]} disabled={!can.edit} onChange={(v) => setAnswers({ ...answers, [qn.key]: v })} />)}
            {can.edit && <Button disabled={busy} onClick={() => (p.edited ? setDialog('regen') : regenerate())}>Regenerate draft</Button>}
          </div>
        </section>
        <section className="card wsi-main" aria-labelledby="pb-draft-h">
          <div className="card-header"><h2 id="pb-draft-h">{can.edit ? 'Draft · editable' : 'Policy text'}</h2><span className="small muted">Text from Futran template; your choices filled in{p.edited ? '; edited by hand' : ''}</span></div>
          <div className="card-body stack">
            {can.edit ? (
              <>
                <BlockEditor blocks={blocks} onChange={(b) => { setBlocks(b); setDirtyText(true); }} />
                <div className="row"><Button variant="primary" disabled={busy || !dirtyText} onClick={saveText}>Save text</Button>{dirtyText && <span className="small muted">Unsaved changes</span>}</div>
              </>
            ) : <div className="wsi-doc"><BlockView blocks={p.blocks ?? []} /></div>}
          </div>
        </section>
      </div>
      <section className="card"><div className="card-body wsi-footer">
        <p className="small" style={{ margin: 0, maxWidth: 720, lineHeight: 1.5 }}>On approval the policy is published, a staff acknowledgment campaign can start, and the commitment closes with this policy as evidence. Want Futran to tailor it? Advisory customization can be quoted; the Futran team that tailors it cannot audit it later.</p>
        <div className="row">
          <a className="btn" href={`/api/v1/policies/${p.id}/pdf`}>Download PDF</a>
          {can.request_review && <Button disabled={busy} onClick={() => setDialog('review')}>Request Futran review</Button>}
          {p.futran_review_requested_at && <Badge tone="navy">Futran review requested {fmtDate(p.futran_review_requested_at)}</Badge>}
          {can.edit && <Button variant="primary" disabled={busy} onClick={submit}>Send for approval</Button>}
          {p.status === 'awaiting_approval' && can.approve && <><Button disabled={busy} onClick={() => setDialog('return')}>Return for changes</Button><Button variant="primary" disabled={busy} onClick={() => setDialog('approve')}>Approve and publish</Button></>}
          {p.status === 'published' && can.approve && <><Button disabled={busy} onClick={() => setDialog('ack')}>Ask staff to acknowledge</Button><Button disabled={busy} onClick={() => run(() => api.post(`/policies/${p.id}/new-version`), 'A new draft version has been started. Open it from Policies.')}>Start a new version</Button></>}
        </div>
      </div></section>
      {(p.status === 'published' || p.status === 'retired') && <Acknowledgments p={p} />}
      {dialog === 'regen' && (
        <Dialog title="Regenerate the draft?" onClose={() => setDialog(null)}>
          <div className="stack"><p style={{ margin: 0 }}>{H.regenerate}</p><div className="row"><Button variant="danger" disabled={busy} onClick={regenerate}>Regenerate</Button><Button onClick={() => setDialog(null)}>Keep my edits</Button></div></div>
        </Dialog>
      )}
      {dialog === 'return' && <NoteDialog title="Return for changes" label="What needs to change" help={H.returnNote} busy={busy} onClose={() => setDialog(null)} onSave={(note) => run(() => api.post(`/policies/${p.id}/return`, { note }), 'Returned to the author.')} />}
      {dialog === 'review' && <NoteDialog title="Request Futran review" label="What would you like Futran to look at?" help={H.futranNote} optional busy={busy} onClose={() => setDialog(null)} onSave={(note) => run(() => api.post(`/policies/${p.id}/futran-review`, { note }), 'Futran has been asked to review this policy. They will reply with a quote.')} />}
      {dialog === 'approve' && <AckDialog title="Approve and publish" busy={busy} onClose={() => setDialog(null)} onSave={(ack) => run(() => api.post(`/policies/${p.id}/approve`, { acknowledgment: ack }), ack ? 'Published. Staff have been asked to acknowledge it.' : 'Published.')} withSkip />}
      {dialog === 'ack' && <AckDialog title="Ask staff to acknowledge" busy={busy} onClose={() => setDialog(null)} onSave={(ack) => run(() => api.post(`/policies/${p.id}/acknowledgments/send`, ack ?? {}), 'Acknowledgment links sent to people who have not acknowledged yet.')} />}
    </div>
  );
}

function QuestionField({ q, value, error, disabled, onChange }: { q: Question; value: unknown; error?: string; disabled: boolean; onChange: (v: unknown) => void }) {
  if (q.type === 'text') return <TextField label={q.label} help={q.help} value={String(value ?? '')} error={error} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
  if (q.type === 'textarea') return <TextArea label={q.label} help={q.help} rows={3} value={String(value ?? '')} error={error} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
  if (q.type === 'list') return <TextArea label={q.label} help={q.help} hint="One per line." rows={3} value={((value as string[]) ?? []).join('\n')} error={error} disabled={disabled} onChange={(e) => onChange(e.target.value.split('\n'))} />;
  if (q.type === 'yesno') return <Checkbox label={q.label} help={q.help} checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />;
  if (q.type === 'choice') return (
    <FieldGroup legend={q.label} help={q.help} className="stack-sm">
      {(q.options ?? []).map((o) => <label key={o.value} className="check"><input type="radio" name={q.key} checked={value === o.value} disabled={disabled} onChange={() => onChange(o.value)} /><span>{o.label}</span></label>)}
      {error && <span className="error">{error}</span>}
    </FieldGroup>
  );
  const vals = (value as string[]) ?? [];
  return (
    <FieldGroup legend={q.label} help={q.help} className="stack-sm">
      {(q.options ?? []).map((o) => <Checkbox key={o.value} label={o.label} checked={vals.includes(o.value)} disabled={disabled} onChange={(e) => onChange(e.target.checked ? [...vals, o.value] : vals.filter((v) => v !== o.value))} />)}
      {error && <span className="error">{error}</span>}
    </FieldGroup>
  );
}

function NoteDialog({ title, label, help, optional, busy, onClose, onSave }: { title: string; label: string; help: string; optional?: boolean; busy: boolean; onClose: () => void; onSave: (note: string) => void }) {
  const [note, setNote] = useState('');
  return (
    <Dialog title={title} onClose={onClose}>
      <div className="stack">
        <TextArea label={label} help={help} rows={4} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={busy || (!optional && !note.trim())} onClick={() => onSave(note)}>{title}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

type GroupOpt = { id: string; name: string };

function AckDialog({ title, busy, onClose, onSave, withSkip }: { title: string; busy: boolean; onClose: () => void; onSave: (ack: Record<string, unknown> | null) => void; withSkip?: boolean }) {
  const groups = useQuery({ queryKey: ['mail-groups-lite'], queryFn: () => api.get<{ groups: (GroupOpt & { system_key: string | null })[] }>('/mail/groups') });
  const [chosen, setChosen] = useState<string[]>([]);
  const [remind, setRemind] = useState(true);
  const all = groups.data?.groups.find((g) => g.system_key === 'all_employees');
  const ids = chosen.length ? chosen : all ? [all.id] : [];
  return (
    <Dialog title={title} onClose={onClose}>
      <div className="stack">
        {withSkip && <p style={{ margin: 0 }}>Publishing closes the commitment with this policy as its evidence. Choose who is asked to read and acknowledge it.</p>}
        <FieldGroup legend="Send acknowledgment links to" help={H.ackGroups} className="stack-sm">
          {(groups.data?.groups ?? []).map((g) => <Checkbox key={g.id} label={g.name} checked={ids.includes(g.id)} onChange={(e) => setChosen(e.target.checked ? [...ids, g.id] : ids.filter((x) => x !== g.id))} />)}
        </FieldGroup>
        <Checkbox label="Remind people who have not acknowledged after 3 and 7 days" help={H.reminders} checked={remind} onChange={(e) => setRemind(e.target.checked)} />
        <div className="row">
          <Button variant="primary" disabled={busy || !ids.length} onClick={() => onSave({ group_ids: ids, reminder_days: remind ? [3, 7] : [] })}>{withSkip ? 'Publish and send' : 'Send'}</Button>
          {withSkip && <Button disabled={busy} onClick={() => onSave(null)}>Publish without sending</Button>}
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Dialog>
  );
}

type AckRow = { email: string; name: string | null; status: string | null; department: string | null; acknowledged_at: string | null };

function Acknowledgments({ p }: { p: PolicyDoc }) {
  const q = useQuery({ queryKey: ['policy-acks', p.id], queryFn: () => api.get<{ stats: { sent: number; acknowledged: number; outstanding: number }; rows: AckRow[] }>(`/policies/${p.id}/acknowledgments`), retry: false });
  if (!q.data) return null;
  const s = q.data.stats;
  return (
    <section className="card" aria-labelledby="pb-ack-h">
      <div className="card-header"><h2 id="pb-ack-h">Staff acknowledgment</h2><span className="small muted">{s.acknowledged} of {s.sent} acknowledged</span></div>
      <div className="card-body">
        <DataGrid label="Acknowledgments" rows={q.data.rows} rowId={(r) => r.email} rowLabel={(r) => r.name ?? r.email} initialSort={{ key: 'name', dir: 'asc' }} emptyText="Nobody has been asked yet."
          search={{ label: 'Search people', text: (r) => `${r.name ?? ''} ${r.email}` }}
          filters={[{ key: 'state', label: 'Status', options: [{ value: 'yes', label: 'Acknowledged' }, { value: 'no', label: 'Not yet' }], test: (r, v) => (v === 'yes') === Boolean(r.acknowledged_at) }]}
          columns={[
            { key: 'name', header: 'Name', value: (r) => r.name ?? r.email },
            { key: 'email', header: 'Email', value: (r) => r.email },
            { key: 'ack', header: 'Acknowledged', value: (r) => r.acknowledged_at ?? '', render: (r) => r.acknowledged_at ? <Badge tone="success">{fmtDate(r.acknowledged_at)}</Badge> : <Badge tone="muted">Not yet</Badge> },
          ]}
          rowActions={(r) => [{ label: 'Copy email address', onSelect: () => { void navigator.clipboard?.writeText(r.email); } }]} />
      </div>
    </section>
  );
}
