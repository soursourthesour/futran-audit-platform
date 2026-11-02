import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { CONFIDENCE_LABEL, citeText, type LibraryItem, type QItem, type Questionnaire } from '@/api/ai';
import { questionnaireHelp as H } from '@/help/ai';
import './copilot.css';

/** F10 (spec §21): customer security and AI questionnaires, answered from the client's own approved answers, published
 *  policies and the latest signed Futran report. Client Admin and CAICO. */

type ListOut = { ai_enabled: boolean; has_signed_report: boolean; library_count: number; rows: Questionnaire[] };
const STATUS: Record<string, [string, 'navy' | 'success' | 'warn' | 'danger' | 'muted']> = {
  open: ['To answer', 'muted'], suggested: ['Draft to review', 'navy'], unsupported: ['No source found', 'danger'], accepted: ['Approved', 'success'], edited: ['Approved with edits', 'success'],
  answered: ['Answered', 'success'], rejected: ['Draft rejected', 'muted'],
};

function UploadDialog({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [customer, setCustomer] = useState('');
  const [title, setTitle] = useState('');
  const [due, setDue] = useState('');
  const [err, setErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  async function submit() {
    if (busy || !file) return;
    setBusy(true); setErr({});
    const form = new FormData();
    form.append('file', file); form.append('customer_name', customer); form.append('title', title);
    if (due) form.append('due_date', due);
    try { const q = await api.upload<Questionnaire>('/questionnaires', form); nav(`/questionnaires/${q.id}`); } catch (e) { setErr({ file: errorMessage(e), ...fieldErrors(e) }); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Upload a customer questionnaire" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <TextField label="Questionnaire file" type="file" accept=".xlsx,.docx,.pdf" help={H.file} onChange={(e) => setFile(e.target.files?.[0] ?? null)} error={err.file} />
        <TextField label="Customer" help={H.customer} value={customer} onChange={(e) => setCustomer(e.target.value)} />
        <TextField label="Title" help={H.title} value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextField label="Answers due" type="date" help={H.due} value={due} onChange={(e) => setDue(e.target.value)} error={err.due_date} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" disabled={busy || !file}>{busy ? 'Reading…' : 'Upload and find questions'}</Button></div>
      </form>
    </Dialog>
  );
}

function Library() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['answer-library'], queryFn: () => api.get<{ rows: LibraryItem[] }>('/answer-library') });
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ question: '', answer: '' });
  const [err, setErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const columns: GridColumn<LibraryItem>[] = [
    { key: 'question', header: 'Question', value: (r) => r.question },
    { key: 'answer', header: 'Approved answer', value: (r) => r.answer, render: (r) => <>{r.answer}{r.audited_by_futran && <> <Badge tone="success">Audited by Futran</Badge></>}</> },
    { key: 'source', header: 'From', value: (r) => (r.source === 'questionnaire' ? 'A questionnaire' : 'Added by hand') },
    { key: 'approved', header: 'Approved', value: (r) => r.approved_at ?? '', render: (r) => fmtDate(r.approved_at) },
  ];
  async function add() {
    if (busy) return;
    setBusy(true); setErr({});
    try { await api.post('/answer-library', f); setF({ question: '', answer: '' }); setAdding(false); await qc.invalidateQueries({ queryKey: ['answer-library'] }); } catch (e) { setErr(fieldErrors(e)); } finally { setBusy(false); }
  }
  return (
    <Card title="Answer library" actions={<Button onClick={() => setAdding(true)}>Add an answer</Button>}>
      <p className="small muted" style={{ marginTop: 0 }}>Answers you have approved. Drafts reuse them, and every approved questionnaire answer is added here.</p>
      {q.data && <DataGrid label="Answer library" rows={q.data.rows} rowId={(r) => r.id} rowLabel={(r) => r.question} columns={columns} search={{ label: 'Search answers', text: (r) => `${r.question} ${r.answer}` }}
        rowActions={(r) => [{ label: 'Archive', danger: true, onSelect: async () => { await api.post(`/answer-library/${r.id}/archive`); qc.invalidateQueries({ queryKey: ['answer-library'] }); } }]}
        emptyText="No approved answers yet." />}
      {adding && (
        <Dialog title="Add an approved answer" onClose={() => setAdding(false)}>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); add(); }}>
            <TextField label="Question" help={H.libraryQuestion} value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} error={err.question} />
            <TextArea label="Approved answer" help={H.libraryAnswer} value={f.answer} onChange={(e) => setF({ ...f, answer: e.target.value })} error={err.answer} rows={4} />
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" type="submit" disabled={busy}>Add</Button></div>
          </form>
        </Dialog>
      )}
    </Card>
  );
}

export function Questionnaires() {
  const q = useQuery({ queryKey: ['questionnaires'], queryFn: () => api.get<ListOut>('/questionnaires') });
  const [uploading, setUploading] = useState(false);
  const [tab, setTab] = useState<'list' | 'library'>('list');
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const columns: GridColumn<Questionnaire>[] = [
    { key: 'title', header: 'Questionnaire', value: (r) => r.title, render: (r) => <Link to={`/questionnaires/${r.id}`}>{r.title}</Link> },
    { key: 'customer', header: 'Customer', value: (r) => r.customer_name ?? '' },
    { key: 'format', header: 'Format', value: (r) => r.format.toUpperCase() },
    { key: 'progress', header: 'Answered', value: (r) => r.counts.approved / Math.max(1, r.counts.questions), render: (r) => `${r.counts.approved} of ${r.counts.questions}` },
    { key: 'review', header: 'To review', value: (r) => r.counts.to_review },
    { key: 'due', header: 'Due', value: (r) => r.due_date ?? '', render: (r) => fmtDate(r.due_date) },
    { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <Badge tone={r.status === 'completed' ? 'success' : 'navy'}>{r.status === 'completed' ? 'Completed' : 'In progress'}</Badge> },
  ];
  return (
    <div className="page">
      <PageHeader title="Customer questionnaires" subtitle="Answer your customers' security and AI due-diligence questionnaires from your approved answers, your published policies and your latest signed Futran report."
        actions={<Button variant="primary" onClick={() => setUploading(true)}>Upload a questionnaire</Button>} />
      {!d.ai_enabled && <Alert tone="info">Drafting answers with AI is off for your organization. You can still upload questionnaires, answer them and export them in their original format.</Alert>}
      <div className="tabs" role="tablist" aria-label="Questionnaire sections" style={{ marginTop: 12 }}>
        <button type="button" role="tab" aria-selected={tab === 'list'} className={tab === 'list' ? 'active' : ''} onClick={() => setTab('list')}>Questionnaires ({d.rows.length})</button>
        <button type="button" role="tab" aria-selected={tab === 'library'} className={tab === 'library' ? 'active' : ''} onClick={() => setTab('library')}>Answer library ({d.library_count})</button>
      </div>
      <div style={{ marginTop: 12 }}>
        {tab === 'list' ? (d.rows.length ? <DataGrid label="Questionnaires" rows={d.rows} rowId={(r) => r.id} rowLabel={(r) => r.title} columns={columns} />
          : <EmptyState>No questionnaires yet. Upload one your customer sent you.</EmptyState>) : <Library />}
      </div>
      {uploading && <UploadDialog onClose={() => setUploading(false)} />}
    </div>
  );
}

function ItemRow({ qid, it, onDone }: { qid: string; it: QItem; onDone: () => void }) {
  const [answer, setAnswer] = useState(it.answer ?? '');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [status, tone] = STATUS[it.status] ?? [it.status, 'muted'];
  async function go(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await fn(); setEditing(false); onDone(); } catch (e) { setErr(fieldErrors(e).answer ?? errorMessage(e)); } finally { setBusy(false); }
  }
  const draft = it.status === 'suggested';
  const writable = editing || ['open', 'unsupported', 'rejected'].includes(it.status);
  return (
    <div className="qn-item" aria-label={it.question}>
      <div className="row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <span className="qn-q">{it.question}</span>
        <span className="row" style={{ gap: 6 }}>{it.audited_by_futran && <Badge tone="success">Audited by Futran</Badge>}<Badge tone={tone}>{status}</Badge>{draft && it.confidence && <Badge tone="muted">{CONFIDENCE_LABEL[it.confidence]}</Badge>}</span>
      </div>
      {it.section && <div className="small muted">{it.section}</div>}
      {!writable && it.answer && <p style={{ margin: 0 }}>{it.answer}</p>}
      {it.citations.map((c, n) => <div key={n} className="cp-quote">{c.quote && <blockquote>“{c.quote}”</blockquote>}<div className="small muted">{citeText(c)}{!c.found && ' · not found in the source'}</div></div>)}
      {it.status === 'unsupported' && <div className="small muted">None of your sources answers this. Write the answer yourself.</div>}
      {writable && <TextArea label="Answer" help={H.answer} value={answer} onChange={(e) => setAnswer(e.target.value)} rows={3} error={err ?? undefined} />}
      {!writable && err && <Alert tone="danger">{err}</Alert>}
      <div className="row cp-actions">
        {draft && !editing && <>
          <Button variant="primary" disabled={busy} onClick={() => go(() => api.post(`/questionnaires/${qid}/items/${it.id}/accept`, {}))}>Approve</Button>
          <Button disabled={busy} onClick={() => { setAnswer(it.answer ?? ''); setEditing(true); }}>Edit</Button>
          <Button variant="danger" disabled={busy} onClick={() => go(() => api.post(`/questionnaires/${qid}/items/${it.id}/reject`, { reason: 'Not right for this customer.' }))}>Reject</Button>
        </>}
        {draft && editing && <Button variant="primary" disabled={busy} onClick={() => go(() => api.post(`/questionnaires/${qid}/items/${it.id}/accept`, { answer }))}>Approve with edits</Button>}
        {!draft && writable && <Button variant="primary" disabled={busy || !answer.trim()} onClick={() => go(() => api.put(`/questionnaires/${qid}/items/${it.id}`, { answer }))}>Save answer</Button>}
        {!draft && !writable && <Button disabled={busy} onClick={() => setEditing(true)}>Change</Button>}
        {editing && <Button onClick={() => setEditing(false)}>Cancel</Button>}
      </div>
    </div>
  );
}

export function QuestionnaireDetail() {
  const { questionnaireId = '' } = useParams();
  const qc = useQueryClient();
  const key = ['questionnaire', questionnaireId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Questionnaire>(`/questionnaires/${questionnaireId}`) });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: key }), qc.invalidateQueries({ queryKey: ['questionnaires'] }), qc.invalidateQueries({ queryKey: ['answer-library'] })]);
  async function act(fn: () => Promise<unknown>, ok: string) {
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await fn(); await refresh(); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const c = d.counts;
  return (
    <div className="page">
      <PageHeader title={d.title} crumbs={[{ to: '/questionnaires', label: 'Customer questionnaires' }, { label: d.title }]}
        subtitle={<>{d.customer_name ?? 'Customer not named'} · {d.filename} · {c.approved} of {c.questions} answered{c.to_review ? ` · ${c.to_review} drafts to review` : ''}{d.due_date ? ` · due ${fmtDate(d.due_date)}` : ''}</>}
        actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {d.ai_enabled && <Button disabled={busy} onClick={() => act(() => api.post(`/questionnaires/${d.id}/draft`), 'Answers drafted. Review each one; nothing goes to the customer until you approve it.')}>{busy ? 'Drafting…' : 'Draft answers'}</Button>}
          <a className="btn" href={`/api/v1/questionnaires/${d.id}/export`}>{d.format === 'pdf' ? 'Export as Word' : `Export ${d.format.toUpperCase()}`}</a>
          {d.status !== 'completed' && <Button variant="primary" disabled={busy} onClick={() => act(() => api.post(`/questionnaires/${d.id}/complete`), 'Marked complete.')}>Mark complete</Button>}
        </div>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {d.format === 'pdf' && <Alert tone="info">PDF files cannot be edited in place, so the export is a Word document with each question and its answer, in order.</Alert>}
      <Card title={`Questions (${c.questions})`}>
        <p className="small muted" style={{ marginTop: 0 }}>Drafts cite their source. Answers drawn from your signed Futran report are marked "Audited by Futran". Approved answers are added to your answer library.</p>
        {(d.items ?? []).map((it) => <ItemRow key={it.id} qid={d.id} it={it} onDone={refresh} />)}
      </Card>
    </div>
  );
}
