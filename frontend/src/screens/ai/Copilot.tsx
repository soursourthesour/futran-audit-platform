import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, SelectField, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { CONFIDENCE_LABEL, STATUS_LABEL, citeText, statusTone, useAISwitch, type Completeness, type CopilotPanel, type EvidenceRow, type Interaction } from '@/api/ai';
import { copilotHelp as H } from '@/help/ai';
import './copilot.css';

/** Screen 25: the AI copilot on the system assessment (spec §21 F1). Shown only when AI is on for the engagement and
 *  the person may use the copilot; the client never sees it. Nothing is saved until a named auditor accepts. */

type Msg = { tone: 'success' | 'danger'; text: string } | null;

function useBusy() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  async function run(fn: () => Promise<unknown>, ok?: string) {
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await fn(); if (ok) setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  return { busy, msg, setMsg, run };
}

export function useCopilotAllowed(engagementId: string | undefined) {
  const sw = useAISwitch(engagementId);
  return { on: !!sw.data?.enabled && !!sw.data?.can_use_copilot, sw: sw.data };
}

export function Quote({ c }: { c: Interaction['citations'][number] }) {
  return (
    <div className="cp-quote">
      {c.quote && <blockquote>“{c.quote}”</blockquote>}
      <div className="small muted">{citeText(c)}{!c.found && <> · <strong style={{ color: 'var(--danger)' }}>not found in the document</strong></>}</div>
    </div>
  );
}

function StatusBadge({ i }: { i: Interaction }) {
  if (i.status === 'suggested') return <Badge tone={i.confidence === 'high' ? 'success' : i.confidence === 'medium' ? 'warn' : 'muted'}>{CONFIDENCE_LABEL[i.confidence ?? 'low']}</Badge>;
  return <Badge tone={statusTone(i.status)}>{STATUS_LABEL[i.status]}{i.decided_by ? ` · ${i.decided_by}` : ''}</Badge>;
}

export function RejectDialog({ title, onClose, onReject }: { title: string; onClose: () => void; onReject: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={title} onClose={onClose}>
      <form className="stack" onSubmit={async (e) => { e.preventDefault(); if (busy) return; setBusy(true); try { await onReject(reason); onClose(); } catch (ex) { setErr(fieldErrors(ex).reason ?? errorMessage(ex)); } finally { setBusy(false); } }}>
        <TextArea label="Reason" help={H.reject} value={reason} onChange={(e) => setReason(e.target.value)} error={err ?? undefined} rows={3} autoFocus />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="danger" type="submit" disabled={busy}>Reject</Button></div>
      </form>
    </Dialog>
  );
}

function EditDialog({ i, onClose, onSave }: { i: Interaction; onClose: () => void; onSave: (body: { value: unknown; detail: string; create_finding?: boolean }) => Promise<unknown> }) {
  const q = i.output.question as { type: string; options: { value: string; label: string }[] };
  const [value, setValue] = useState<string>(String(i.output.value ?? ''));
  const [detail, setDetail] = useState<string>(i.output.detail ?? '');
  const [err, setErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const choice = q.options && q.options.length > 0;
  return (
    <Dialog title={`Edit and accept ${i.target_code}`} onClose={onClose}>
      <form className="stack" onSubmit={async (e) => { e.preventDefault(); if (busy) return; setBusy(true); try { await onSave({ value, detail }); onClose(); } catch (ex) { setErr({ value: errorMessage(ex), ...fieldErrors(ex) }); } finally { setBusy(false); } }}>
        {choice ? <SelectField label="Answer" help={H.editValue} value={value} options={q.options} onChange={(e) => setValue(e.target.value)} error={err.value} />
          : <TextArea label="Answer" help={H.editValue} value={value} onChange={(e) => setValue(e.target.value)} error={err.value} rows={3} />}
        <TextArea label="Detail" help={H.editDetail} value={detail} onChange={(e) => setDetail(e.target.value)} rows={2} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" disabled={busy}>Accept with edits</Button></div>
      </form>
    </Dialog>
  );
}

function EvidenceRequestDialog({ i, onClose, onDone }: { i: Interaction; onClose: () => void; onDone: () => void }) {
  const label = (i.output.question as { label: string }).label;
  const [description, setDescription] = useState(`Evidence for ${i.target_code} ${label}`);
  const [due, setDue] = useState(new Date(Date.now() + 10 * 864e5).toISOString().slice(0, 10));
  const [err, setErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Create evidence request" onClose={onClose}>
      <form className="stack" onSubmit={async (e) => { e.preventDefault(); if (busy) return; setBusy(true); try { await api.post(`/ai/interactions/${i.id}/evidence-request`, { description, due_date: due }); onDone(); onClose(); } catch (ex) { setErr({ description: errorMessage(ex), ...fieldErrors(ex) }); } finally { setBusy(false); } }}>
        <TextArea label="What the client should provide" help={H.evidenceDescription} value={description} onChange={(e) => setDescription(e.target.value)} error={err.description} rows={3} />
        <TextField label="Due date" type="date" help={H.evidenceDue} value={due} onChange={(e) => setDue(e.target.value)} error={err.due_date} />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" disabled={busy}>Send request</Button></div>
      </form>
    </Dialog>
  );
}

function SuggestionCard({ i, locked, onChanged }: { i: Interaction; locked: boolean; onChanged: () => void }) {
  const { busy, msg, run } = useBusy();
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const label = (i.output.question as { label: string } | undefined)?.label;
  const draft = i.output.draft_finding as { title: string; severity: string } | null;
  const [replace, setReplace] = useState(false);
  const open = i.status === 'suggested' && !locked;
  const cur = i.current ?? null;
  // a verified answer, or a different one an auditor recorded, is only replaced when the auditor ticks the box
  const guarded = !!cur && (cur.verified || (cur.side === 'futran' && (cur.status !== 'answered' || JSON.stringify(cur.value) !== JSON.stringify(i.output.value))));
  const blocked = guarded && !replace;
  const withOverride = (body: Record<string, unknown>) => (guarded ? { ...body, override: true } : body);
  const accept = (body: Record<string, unknown>) => run(async () => { await api.post(`/ai/interactions/${i.id}/accept`, withOverride(body)); onChanged(); });
  return (
    <article className={`cp-card cp-${i.status}`} aria-label={`Suggestion for ${i.target_code}`}>
      <div className="cp-head"><strong>{i.target_code} · {label}</strong><StatusBadge i={i} /></div>
      {i.status !== 'unsupported' ? (
        <>
          <div className="small muted">Suggested answer:</div>
          <div className="cp-answer">{i.output.display ?? String(i.output.value ?? '')}</div>
          {cur && (
            <div className="small" aria-label="Current answer">
              <span className="muted">Current answer:</span> {cur.status === 'answered' ? (cur.display ?? String(cur.value ?? '')) : cur.status === 'na' ? 'Not applicable' : cur.status === 'not_yet_in_place' ? `Not yet in place${cur.display ? ` (${cur.display})` : ''}` : cur.status}
              {' '}<Badge tone={cur.verified ? 'success' : 'muted'}>{cur.verified ? 'Verified' : cur.side === 'futran' ? 'Recorded by an auditor' : 'Client answer'}</Badge>
            </div>
          )}
          {i.citations.map((c, n) => <Quote key={n} c={c} />)}
          {draft && <div className="cp-draft"><span className="small muted">Suggested draft finding ({draft.severity}):</span> {draft.title}</div>}
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          {open && guarded && (
            <label className="small row" style={{ gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              {cur?.verified ? 'Replace the verified answer (its verification is cleared)' : 'Replace the answer an auditor recorded'}
            </label>
          )}
          {open && (
            <div className="row cp-actions">
              {draft ? <>
                <Button variant="primary" disabled={busy || blocked} onClick={() => accept({})}>Accept answer</Button>
                <Button disabled={busy || blocked} onClick={() => accept({ create_finding: true })}>Accept answer + create draft finding</Button>
              </> : <Button variant="primary" disabled={busy || blocked} onClick={() => accept({})}>Accept</Button>}
              <Button disabled={busy || blocked} onClick={() => setEditing(true)}>Edit</Button>
              <Button variant="danger" disabled={busy} onClick={() => setRejecting(true)}>Reject</Button>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="small" style={{ margin: '4px 0' }}>{i.output.note ?? 'No passage in the uploaded documents answers this question.'}</p>
          {i.citations.filter((c) => !c.found).map((c, n) => <Quote key={n} c={c} />)}
          <p className="small muted" style={{ margin: '4px 0' }}>Ask in interview, or request the document from the client. An unsupported suggestion cannot be accepted.</p>
          {i.follow_up && <div className="small"><Badge tone="navy">{i.follow_up === 'interview' ? 'On the interview list' : `Evidence requested (${i.follow_up_ref})`}</Badge></div>}
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          {!locked && i.status === 'unsupported' && (
            <div className="row cp-actions">
              <Button disabled={busy || i.follow_up === 'interview'} onClick={() => run(async () => { await api.post(`/ai/interactions/${i.id}/interview`); onChanged(); })}>Add to interview list</Button>
              <Button disabled={busy || i.follow_up === 'evidence_request'} onClick={() => setRequesting(true)}>Create evidence request</Button>
              <Button variant="danger" disabled={busy} onClick={() => setRejecting(true)}>Reject</Button>
            </div>
          )}
        </>
      )}
      {i.reason && <div className="small muted">Reason: {i.reason}</div>}
      {editing && <EditDialog i={i} onClose={() => setEditing(false)} onSave={async (b) => { await api.post(`/ai/interactions/${i.id}/accept`, withOverride(b)); onChanged(); }} />}
      {rejecting && <RejectDialog title={`Reject the suggestion for ${i.target_code}`} onClose={() => setRejecting(false)} onReject={async (reason) => { await api.post(`/ai/interactions/${i.id}/reject`, { reason }); onChanged(); }} />}
      {requesting && <EvidenceRequestDialog i={i} onClose={() => setRequesting(false)} onDone={onChanged} />}
    </article>
  );
}

/** "Copilot suggestions" for one section of the assessment. */
export function CopilotSuggestions({ systemId, section, title, locked, onAnswersChanged }: { systemId: string; section: string; title: string; locked: boolean; onAnswersChanged: () => void }) {
  const qc = useQueryClient();
  const key = ['copilot', systemId, section];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<CopilotPanel>(`/systems/${systemId}/copilot?section=${encodeURIComponent(section)}`) });
  const { busy, msg, setMsg, run } = useBusy();
  if (!q.data) return q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : null;
  const d = q.data;
  const changed = () => { qc.invalidateQueries({ queryKey: ['copilot', systemId] }); onAnswersChanged(); };
  const high = d.suggestions.filter((s) => s.status === 'suggested' && s.confidence === 'high');
  const docs = d.documents.filter((x) => x.pages > 0);
  return (
    <Card className="cp-panel" title={`Copilot suggestions: §${section} ${title}`}
      actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {!locked && <Button disabled={busy || docs.length === 0} onClick={() => run(async () => { await api.post(`/systems/${systemId}/copilot/prefill`, { sub_section: section }); changed(); })}>{busy ? 'Reading documents…' : d.suggestions.length ? 'Read the documents again' : 'Suggest answers from documents'}</Button>}
        {!locked && high.length > 0 && <Button variant="primary" disabled={busy} onClick={() => run(async () => {
          const r = await api.post<{ accepted: number; skipped: string[] }>(`/systems/${systemId}/copilot/accept-high`, { ids: high.map((h) => h.id) });
          changed();
          const kept = r.skipped?.length ? ` ${r.skipped.join(', ')} kept ${r.skipped.length === 1 ? 'its' : 'their'} current answer${r.skipped.length === 1 ? '' : 's'}, which ${r.skipped.length === 1 ? 'is' : 'are'} verified or recorded by an auditor; accept ${r.skipped.length === 1 ? 'it' : 'them'} one at a time to replace.` : '';
          setMsg({ tone: 'success', text: `${r.accepted} high-confidence suggestion${r.accepted === 1 ? '' : 's'} accepted. Each acceptance is logged; verify the answers as usual.${kept}` });
        })}>Accept all high-confidence ({high.length})</Button>}
      </div>}>
      <p className="small muted" style={{ marginTop: 0 }} title={H.documents}>
        Read from {docs.length} uploaded document{docs.length === 1 ? '' : 's'} · nothing is saved until you accept · every action is logged
        {d.documents.some((x) => x.error) && <> · {d.documents.filter((x) => x.error).length} file{d.documents.filter((x) => x.error).length === 1 ? '' : 's'} could not be read</>}
      </p>
      {d.suggestions.some((x) => x.provider === 'fake') && <p className="small muted">These suggestions come from the platform's built-in demonstration model, because no AI service is connected.</p>}
      {docs.length === 0 && <Alert tone="info">Upload the client's policies, model cards, vendor terms or SOC 2 reports as evidence first. The copilot reads only documents uploaded to this engagement.</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="stack-sm">{d.suggestions.map((i) => <SuggestionCard key={i.id} i={i} locked={locked} onChanged={changed} />)}</div>
    </Card>
  );
}

/** Evidence check on the checklists: does the linked evidence support each item? It never ticks or unticks. */
export function EvidenceCheck({ systemId, sections, locked, onChanged }: { systemId: string; sections: string[]; locked: boolean; onChanged: () => void }) {
  const [rows, setRows] = useState<EvidenceRow[] | null>(null);
  const [section, setSection] = useState(sections[0] ?? '');
  const { busy, msg, run } = useBusy();
  const verdict: Record<string, [string, 'success' | 'warn' | 'danger']> = { supports: ['Supports', 'success'], partly: ['Partly supports', 'warn'], does_not_support: ['Does not support', 'danger'] };
  return (
    <Card title="Evidence check" actions={<div className="row" style={{ gap: 8 }}>
      {sections.length > 1 && <div style={{ minWidth: 160 }}><SelectField label="Checklist" help={H.checklist} value={section} options={sections.map((s) => ({ value: s, label: `Checklist ${s}` }))} onChange={(e) => setSection(e.target.value)} /></div>}
      <Button disabled={busy} onClick={() => run(async () => setRows((await api.post<{ items: EvidenceRow[] }>(`/systems/${systemId}/copilot/evidence-check`, { section })).items))}>{busy ? 'Checking…' : 'Check the linked evidence'}</Button>
    </div>}>
      <p className="small muted" style={{ marginTop: 0 }}>For each item with linked evidence, the copilot says whether the files support it and why. It never ticks an item; you decide.</p>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {rows && <ul className="cp-list">{rows.map((r) => (
        <li key={r.code}>
          <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}><span><span className="small muted">{r.code}</span> {r.text}</span>
            {r.suggestion?.output.verdict ? <Badge tone={verdict[r.suggestion.output.verdict][1]}>{verdict[r.suggestion.output.verdict][0]}</Badge> : <Badge tone="muted">No evidence linked</Badge>}</div>
          {r.suggestion && <>
            <div className="small">{r.suggestion.output.reason}</div>
            {r.suggestion.citations.map((c, n) => <Quote key={n} c={c} />)}
            {r.suggestion.status === 'unsupported' && <div className="small" style={{ color: 'var(--danger)' }}>Unsupported: the quoted passage is not in the linked file.</div>}
            {!locked && r.suggestion.status === 'suggested' && <DecideRow i={r.suggestion} acceptLabel="Record in the auditor note" onDone={(i) => { setRows(rows.map((x) => x.code === r.code ? { ...x, suggestion: i } : x)); onChanged(); }} />}
            {r.suggestion.status !== 'suggested' && r.suggestion.status !== 'unsupported' && <Badge tone={statusTone(r.suggestion.status)}>{STATUS_LABEL[r.suggestion.status]}</Badge>}
          </>}
        </li>))}</ul>}
    </Card>
  );
}

export function DecideRow({ i, acceptLabel = 'Accept', body = {}, onDone, extra }: { i: Interaction; acceptLabel?: string; body?: Record<string, unknown>; onDone: (i: Interaction) => void; extra?: ReactNode }) {
  const { busy, msg, run } = useBusy();
  const [rejecting, setRejecting] = useState(false);
  return (
    <div className="stack-sm">
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="row cp-actions">
        <Button variant="primary" disabled={busy} onClick={() => run(async () => onDone(await api.post<Interaction>(`/ai/interactions/${i.id}/accept`, body)))}>{acceptLabel}</Button>
        {extra}
        <Button variant="danger" disabled={busy} onClick={() => setRejecting(true)}>Reject</Button>
      </div>
      {rejecting && <RejectDialog title="Reject the suggestion" onClose={() => setRejecting(false)} onReject={async (reason) => onDone(await api.post<Interaction>(`/ai/interactions/${i.id}/reject`, { reason }))} />}
    </div>
  );
}

function Tile({ n, children, tone }: { n: number; children: ReactNode; tone?: 'danger' | 'warn' }) {
  return <div className={`cp-tile ${n > 0 ? tone ?? 'warn' : 'ok'}`}><div className="cp-n">{n}</div><div className="small">{children}</div></div>;
}

/** Completeness review before sign-offs 5 and 7: the deterministic checks, and contradictions found by the copilot. */
export function CompletenessReview({ systemId, onOpen }: { systemId: string; onOpen: (section: string) => void }) {
  const [signoff, setSignoff] = useState(5);
  const qc = useQueryClient();
  const key = ['copilot-completeness', systemId, signoff];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Completeness>(`/systems/${systemId}/copilot/completeness?signoff=${signoff}`) });
  const { busy, msg, run } = useBusy();
  const [openList, setOpenList] = useState(false);
  const d = q.data;
  const contra = (d?.contradictions ?? []).filter((c) => c.status !== 'rejected');
  return (
    <Card title={<>Completeness review <span className="small muted">before sign-off {signoff}</span></>} actions={<div className="row" style={{ gap: 8 }}>
      <div style={{ minWidth: 150 }}><SelectField label="Before" help={H.signoff} value={String(signoff)} options={[{ value: '5', label: 'Sign-off 5' }, { value: '7', label: 'Sign-off 7' }]} onChange={(e) => setSignoff(Number(e.target.value))} /></div>
      <Button disabled={busy} onClick={() => run(async () => { await api.post(`/systems/${systemId}/copilot/completeness`, { signoff }); await qc.invalidateQueries({ queryKey: ['copilot-completeness', systemId] }); })}>{busy ? 'Reviewing…' : 'Run completeness review'}</Button>
    </div>}>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {d && <>
        <div className="cp-tiles">
          <Tile n={d.unanswered_required.length} tone="danger">required question{d.unanswered_required.length === 1 ? '' : 's'} unanswered{d.unanswered_required.length ? ` (${[...new Set(d.unanswered_required.map((x) => '§' + x.sub_section))].slice(0, 4).join(', ')})` : ''}</Tile>
          <Tile n={d.ticks_without_evidence.length}>checklist tick{d.ticks_without_evidence.length === 1 ? '' : 's'} with no linked evidence</Tile>
          <Tile n={contra.length} tone="danger">contradiction{contra.length === 1 ? '' : 's'} between interview answers and documents{d.contradictions_checked_at ? '' : ' (not checked yet)'}</Tile>
          <Tile n={d.missing_source_person.length}>answer{d.missing_source_person.length === 1 ? '' : 's'} missing a source person</Tile>
        </div>
        <Button size="sm" onClick={() => setOpenList(!openList)} aria-expanded={openList}>{openList ? 'Hide the items' : 'Open each item'}</Button>
        {openList && <ul className="cp-list">
          {d.unanswered_required.map((x) => <li key={`u${x.code}`}><button type="button" className="linklike" onClick={() => onOpen(x.sub_section)}>{x.code}</button> {x.label} <Badge tone="danger">Unanswered</Badge></li>)}
          {d.ticks_without_evidence.map((x) => <li key={`t${x.code}`}>{x.code} {x.text} <Badge tone="warn">No evidence</Badge></li>)}
          {d.missing_source_person.map((x) => <li key={`m${x.code}`}><button type="button" className="linklike" onClick={() => onOpen(x.sub_section)}>{x.code}</button> {x.label} <Badge tone="warn">No source person</Badge></li>)}
        </ul>}
        {contra.map((c) => (
          <div key={c.id} className="cp-card" style={{ marginTop: 8 }}>
            <div className="cp-head"><strong>{c.target_code} · contradiction</strong><StatusBadge i={c} /></div>
            <div className="small">Interview: {c.output.interview_says} Document: {c.output.document_says}</div>
            {c.citations.map((x, n) => <Quote key={n} c={x} />)}
            {c.status === 'suggested' && <DecideRow i={c} acceptLabel="Confirm and follow up" onDone={() => qc.invalidateQueries({ queryKey: ['copilot-completeness', systemId] })} />}
          </div>
        ))}
        {d.contradictions_checked_at && <p className="small muted">Contradictions last checked {fmtDateTime(d.contradictions_checked_at)}. The other counts are always current.</p>}
      </>}
    </Card>
  );
}

/** "Ask the copilot": answers only from the engagement's documents, with checked citations. */
export function AskCopilot({ path, placeholder }: { path: string; placeholder?: string }) {
  const [question, setQuestion] = useState('');
  const [answers, setAnswers] = useState<Interaction[]>([]);
  const { busy, msg, run } = useBusy();
  return (
    <Card title="Ask the copilot">
      <form className="row cp-ask" onSubmit={(e) => { e.preventDefault(); run(async () => { const r = await api.post<Interaction>(path, { question }); setAnswers([r, ...answers]); setQuestion(''); }); }}>
        <div style={{ flex: 1, minWidth: 0 }}><TextField label="Question" help={H.ask} value={question} placeholder={placeholder ?? 'Which evidence supports checklist 6.4 item 5 (independent validation)?'} onChange={(e) => setQuestion(e.target.value)} /></div>
        <Button variant="primary" type="submit" disabled={busy || !question.trim()}>{busy ? 'Reading…' : 'Ask a question'}</Button>
      </form>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {answers.map((a) => (
        <div key={a.id} className="cp-card" style={{ marginTop: 8 }}>
          <div className="cp-head"><strong>{a.output.question}</strong>{a.status === 'unsupported' ? <Badge tone="danger">Unsupported</Badge> : <Badge tone="navy">{CONFIDENCE_LABEL[a.confidence ?? 'low']}</Badge>}</div>
          <p style={{ margin: '4px 0' }}>{a.output.answer}</p>
          {a.citations.map((c, n) => <Quote key={n} c={c} />)}
          {a.status === 'unsupported' && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>No passage in the documents supports this answer. Do not rely on it.</p>}
        </div>
      ))}
    </Card>
  );
}

function SummaryCard({ systemId }: { systemId: string }) {
  const [s, setS] = useState<Interaction | null>(null);
  const { busy, msg, run } = useBusy();
  return (
    <Card title="System summary" actions={<Button disabled={busy} onClick={() => run(async () => setS(await api.post<Interaction>(`/systems/${systemId}/copilot/summary`, {})))}>{busy ? 'Writing…' : s ? 'Write again' : 'Write a summary'}</Button>}>
      <p className="small muted" style={{ marginTop: 0 }}>A plain-language summary of this system's answers and findings, for the Chief Auditor. It is a suggestion; nothing changes until you accept it.</p>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {s && <div className="cp-card"><div className="cp-head"><span /><StatusBadge i={s} /></div><p style={{ margin: '4px 0' }}>{s.output.summary}</p>
        <div className="small muted">Relies on: {s.citations.map((c) => c.label).join(', ') || 'nothing cited'}</div>
        {s.status === 'suggested' && <DecideRow i={s} onDone={setS} />}</div>}
    </Card>
  );
}

function InterviewList({ systemId }: { systemId: string }) {
  const q = useQuery({ queryKey: ['copilot', systemId, '_interview'], queryFn: () => api.get<CopilotPanel>(`/systems/${systemId}/copilot`) });
  const rows = q.data?.interview_list ?? [];
  return (
    <Card title={`Interview list (${rows.length})`}>
      {rows.length === 0 ? <p className="small muted" style={{ margin: 0 }}>Questions the documents do not answer, added from the suggestions, appear here to ask in interview.</p>
        : <ul className="cp-list">{rows.map((r) => <li key={r.id}><strong>{r.target_code}</strong> {(r.output.question as { label: string }).label}</li>)}</ul>}
    </Card>
  );
}

/** The "Copilot" page of the assessment: completeness review, ask, interview list and summary. */
export function CopilotTab({ systemId, onOpen }: { systemId: string; onOpen: (section: string) => void }) {
  return (
    <div className="stack">
      <CompletenessReview systemId={systemId} onOpen={onOpen} />
      <AskCopilot path={`/systems/${systemId}/copilot/ask`} />
      <InterviewList systemId={systemId} />
      <SummaryCard systemId={systemId} />
    </div>
  );
}

/** "AI use on this engagement" line under the copilot. */
export function AIUseFooter({ engagementId }: { engagementId: string }) {
  const sw = useAISwitch(engagementId).data;
  if (!sw?.enabled) return null;
  return (
    <p className="small muted cp-footer">
      AI use on this engagement: enabled by {sw.enabled_by ?? 'the Chief Auditor'} · client consented: {sw.consent_note} · enterprise model terms (no training on inputs)
      {sw.can_view_log && <> · <Link to={`/engagements/${engagementId}/ai-log`}>view AI interaction log</Link></>}
    </p>
  );
}

/** "Ask the copilot" on the fieldwork view: answers from every document uploaded to the engagement. */
export function FieldworkAsk({ clientId }: { clientId: string }) {
  const page = useQuery({ queryKey: ['client-page', clientId], queryFn: () => api.get<{ engagement: { id: string } }>(`/clients/${clientId}`) });
  const eid = page.data?.engagement.id;
  const { on } = useCopilotAllowed(eid);
  if (!eid || !on) return null;
  return <AskCopilot path={`/engagements/${eid}/copilot/ask`} placeholder="Does any document describe who reviews the tool's recommendations before an offer is made?" />;
}

/** "Draft the text" on a draft finding: condition, criteria, cause, effect and recommendation, applied only on accept. */
export function DraftFindingText({ findingId, onApplied }: { findingId: string; onApplied: () => void }) {
  const [s, setS] = useState<Interaction | null>(null);
  const { busy, msg, run } = useBusy();
  const o = s?.output ?? {};
  return (
    <div className="stack-sm">
      {!s && <Button size="sm" disabled={busy} onClick={() => run(async () => setS(await api.post<Interaction>(`/findings/${findingId}/copilot/draft-text`)))}>{busy ? 'Drafting…' : 'Draft the finding text with the copilot'}</Button>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {s && <div className="cp-card">
        <div className="cp-head"><strong>{o.title}</strong><Badge tone={s.status === 'suggested' ? 'navy' : statusTone(s.status)}>{s.status === 'suggested' ? `Suggested · ${o.severity}` : STATUS_LABEL[s.status]}</Badge></div>
        <dl className="small" style={{ margin: 0 }}>
          {(['condition', 'criteria', 'cause', 'effect', 'recommendation'] as const).map((k) => <div key={k}><dt style={{ display: 'inline', fontWeight: 600 }}>{k[0].toUpperCase() + k.slice(1)}: </dt><dd style={{ display: 'inline', margin: 0 }}>{o[k]}</dd></div>)}
        </dl>
        <div className="small muted">Based on: {s.citations.map((c) => `${c.label} (${c.quote})`).join('; ') || 'the finding as recorded'}</div>
        {s.status === 'suggested' && <DecideRow i={s} acceptLabel="Use this text" onDone={(i) => { setS(i); onApplied(); }} />}
      </div>}
    </div>
  );
}
