import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, fmtDate, fileUrl } from '@/components/ui';
import { BASIS_OPTIONS, label, type Applicability as Data, type ClientLaw } from '@/api/regmaster';
import { applicabilityHelp as H } from '@/help/regmaster';
import '@/styles/regmaster.css';

type Jur = { code: string; name: string; level: string; parent_code: string | null };
const LETTER_STATUS: Record<string, string> = { draft: 'not sent', approved: 'approved, not sent', sent: 'sent' };

export function Applicability() {
  const { clientId = '' } = useParams();
  const q = useQuery({ queryKey: ['applicability', clientId], queryFn: () => api.get<Data>(`/clients/${clientId}/applicability`) });
  const [adding, setAdding] = useState(false);
  const [law, setLaw] = useState<ClientLaw | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const letter = d.letter;
  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); await q.refetch(); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const removeGeo = (id: string, name: string) => act(() => api.delete(`/clients/${clientId}/geographies/${id}`), `${name} removed. The laws were worked out again.`);
  return (
    <div className="page">
      <PageHeader title="Client applicability and intro letter"
        crumbs={[{ to: '/clients', label: 'Clients' }, { to: `/clients/${clientId}`, label: d.client.name }, { label: 'Applicability and intro letter' }]}
        subtitle="The client's geographies decide the laws, committees, roles and rules from the law library. The intro letter to the Chief AI Compliance Officer is drafted from the same result." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="reg-two" style={{ marginTop: 16 }}>
        <div className="stack">
          <Card title="1 · Where the client operates" actions={d.can_edit ? <Button size="sm" onClick={() => setAdding(true)}>Add a geography</Button> : undefined}>
            {d.geographies.length ? (
              <div className="reg-geo">{d.geographies.map((g) => (
                <span key={g.id} className="chip">{g.parent ? `${g.parent} · ` : ''}{g.name} <span className="muted small">({label(BASIS_OPTIONS, g.basis).toLowerCase()})</span>
                  {d.can_edit && <button type="button" className="btn btn-ghost btn-sm" aria-label={`Remove ${g.name} (${g.basis})`} disabled={busy} onClick={() => removeGeo(g.id, g.name)}>Remove</button>}</span>
              ))}</div>
            ) : <EmptyState>No geographies yet. They come from the client's sites in client set-up (step 2), or add one here.</EmptyState>}
            <p className="reg-note">Taken from client set-up (step 2). Add where employees, candidates, customers and data are, not only offices.</p>
          </Card>
          <Card title={`2 · Laws that apply (${d.laws_in.length})`}>
            {d.laws_in.length ? <ul className="reg-law-list">{d.laws_in.map((l) => (
              <li key={l.regulation_id}>
                <div className="row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                  <div><Badge tone={l.kind === 'Binding' ? 'success' : l.kind === 'Baseline' ? 'navy' : 'muted'}>{l.kind}</Badge> <Link to={`/reg/${l.regulation_id}`}><strong>{l.label}</strong></Link>{l.override && <> <Badge tone="warn">Set by hand</Badge></>}
                    <div className="reg-sub">{l.reason}</div></div>
                  {d.can_edit && <Button size="sm" onClick={() => setLaw(l)} aria-label={`Scope questions for ${l.label}`}>Questions</Button>}
                </div>
              </li>))}</ul> : <EmptyState>No laws in scope yet.</EmptyState>}
            {d.laws_out.length > 0 && (
              <details style={{ marginTop: 12 }}>
                <summary className="small" style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}><strong>Not in scope ({d.laws_out.length}) and why</strong></summary>
                <ul className="reg-law-list">{d.laws_out.map((l) => (
                  <li key={l.regulation_id} className="small"><div className="row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'nowrap' }}>
                    <span><strong>{l.label}</strong>: {l.reason}</span>
                    {d.can_edit && <Button size="sm" onClick={() => setLaw(l)} aria-label={`Scope questions for ${l.label}`}>Questions</Button>}</div></li>
                ))}</ul>
              </details>
            )}
          </Card>
          <Card title={`Roles (${d.roles.length}) and committees`}>
            <ul className="reg-law-list">{d.roles.map((r) => (
              <li key={r.code} className="small"><strong>{r.name}</strong> · {r.level === 'required' ? <span className="reg-pill-req">Required</span> : <span className="reg-pill-rec">Recommended</span>} · needed by {label([{ value: 'program_setup', label: 'program set-up' }, { value: 'procurement', label: 'procurement' }, { value: 'development', label: 'development' }, { value: 'go_live', label: 'go-live' }, { value: 'ongoing', label: 'ongoing' }, { value: 'yearly', label: 'every year' }], r.needed_by)}
                <div className="reg-sub">{r.sources.map((s) => `${s.law} (${s.level})`).join(' · ')}</div></li>))}</ul>
            {d.committees.map((c) => <p key={c.committee_type} className="small" style={{ marginTop: 10 }}><strong>{c.title}</strong>: {c.level === 'required' ? 'required' : 'recommended'} ({c.sources.map((s) => s.law).join(', ')})</p>)}
          </Card>
        </div>
        <div className="stack">
          {d.changes_since_letter && d.changes_since_letter.items.length > 0 && (
            <Alert tone="warn">
              <strong>Changes since letter v{d.changes_since_letter.version_no}{d.changes_since_letter.sent_at ? ` (sent ${fmtDate(d.changes_since_letter.sent_at)})` : ''}</strong>
              <div className="small">{d.changes_since_letter.approved_count} approved law changes affect this client:</div>
              <ul style={{ margin: '6px 0', paddingLeft: 20 }}>{d.changes_since_letter.items.map((c, i) => <li key={i} className="small">{c.text}</li>)}</ul>
              {d.can_edit && (!letter || letter.status === 'sent') && <Button size="sm" disabled={busy} onClick={() => act(() => api.post(`/clients/${clientId}/letters`), `Update letter v${(letter?.version_no ?? 0) + 1} drafted.`)}>Draft update letter (v{(letter?.version_no ?? 0) + 1})</Button>}
            </Alert>
          )}
          <Card title={<div><h2 style={{ display: 'inline' }}>3 · Intro letter preview</h2> {letter && <Badge tone={letter.status === 'sent' ? 'success' : letter.status === 'approved' ? 'navy' : 'warn'}>{`v${letter.version_no} · ${LETTER_STATUS[letter.status]}`}</Badge>}</div>}
            actions={<>
              {d.can_edit && (!letter || letter.status === 'sent') && <Button disabled={busy} onClick={() => act(() => api.post(`/clients/${clientId}/letters`), 'Letter drafted from the current result.')}>{letter ? 'Draft new version' : 'Draft the letter'}</Button>}
              {letter?.status === 'draft' && d.can_edit && <><Button disabled={busy} onClick={() => act(() => api.post(`/clients/${clientId}/letters`), 'Draft refreshed from the current result.')}>Refresh draft</Button><Button onClick={() => setEditing(true)}>Edit text</Button></>}
              {letter?.file_id && <a className="btn" href={fileUrl(letter.file_id)}>Download PDF</a>}
              {letter?.status === 'draft' && d.can_approve && <Button variant="primary" disabled={busy} onClick={() => act(() => api.post(`/clients/${clientId}/letters/${letter.id}/approve`), 'Letter approved. It goes with the initiation package.')}>Approve</Button>}
              {letter?.status === 'approved' && d.can_approve && <Button variant="primary" disabled={busy} onClick={() => act(() => api.post(`/clients/${clientId}/letters/${letter.id}/send`), `Letter sent to ${d.caico?.name ?? 'the Chief AI Compliance Officer'}.`)}>Send to {d.caico?.name ?? 'the client'}</Button>}
            </>}>
            {letter?.status === 'draft' && !d.can_approve && <Alert>The Chief Auditor approves and sends the letter.</Alert>}
            {!d.caico && <Alert tone="warn">No Chief AI Compliance Officer is recorded yet (client set-up, step 4). The letter can be drafted and approved, but not sent.</Alert>}
            {letter ? <div className="letter-body" data-testid="letter-preview" dangerouslySetInnerHTML={{ __html: letter.html ?? '' }} /> : <EmptyState>No letter yet. Draft it once the client's geographies are recorded.</EmptyState>}
            {letter && <p className="reg-note">{letter.approved_by ? `Approved by ${letter.approved_by} on ${fmtDate(letter.approved_at)}. ` : ''}{letter.sent_at ? `Sent ${fmtDate(letter.sent_at)}. ` : ''}Rule versions used: {letter.versions.join(', ') || '—'}.</p>}
          </Card>
          {d.letters.length > 1 && (
            <Card title="Earlier letters">
              <ul className="reg-law-list">{d.letters.slice(1).map((x) => <li key={x.id} className="small">v{x.version_no} · {LETTER_STATUS[x.status]}{x.sent_at ? ` ${fmtDate(x.sent_at)}` : ''}{x.file_id && <> · <a href={fileUrl(x.file_id)}>PDF</a></>}</li>)}</ul>
            </Card>
          )}
        </div>
      </div>
      {adding && <AddGeography clientId={clientId} onClose={() => setAdding(false)} onDone={(m) => { setAdding(false); setMsg({ tone: 'success', text: m }); q.refetch(); }} />}
      {law && <ScopeQuestions clientId={clientId} law={law} onClose={() => setLaw(null)} onDone={(m) => { setLaw(null); setMsg({ tone: 'success', text: m }); q.refetch(); }} />}
      {editing && letter && <EditLetter clientId={clientId} letterId={letter.id} initial={letter.edited_text} onClose={() => setEditing(false)} onDone={() => { setEditing(false); q.refetch(); }} />}
    </div>
  );
}

function AddGeography({ clientId, onClose, onDone }: { clientId: string; onClose: () => void; onDone: (m: string) => void }) {
  const [text, setText] = useState('');
  const [code, setCode] = useState('');
  const [basis, setBasis] = useState('customers');
  const [err, setErr] = useState<string | null>(null);
  const found = useQuery({ queryKey: ['jur-search', text], queryFn: () => api.get<Jur[]>(`/jurisdictions?q=${encodeURIComponent(text)}`), enabled: text.trim().length >= 2 });
  async function save() {
    setErr(null);
    try { await api.post(`/clients/${clientId}/geographies`, { jurisdiction_code: code, basis }); onDone('Geography added. The laws were worked out again.'); }
    catch (e) { setErr(errorMessage(e) + (fieldErrors(e).jurisdiction_code ? ` ${fieldErrors(e).jurisdiction_code}` : '')); }
  }
  const opts = (found.data ?? []).slice(0, 30).map((j) => ({ value: j.code, label: `${j.name}${j.parent_code ? ` (${j.parent_code})` : ''} · ${j.level}` }));
  return (
    <Dialog title="Add a geography" onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="field"><label htmlFor="geo-search">Search</label><input id="geo-search" className="input" value={text} onChange={(e) => { setText(e.target.value); setCode(''); }} placeholder="Colorado, Germany, New York City…" /></div>
      <SelectField label="Geography *" help={H.geography} value={code} onChange={(e) => setCode(e.target.value)} options={opts} placeholder={text.trim().length < 2 ? 'Type at least 2 letters' : opts.length ? 'Choose one' : 'No match'} />
      <SelectField label="Basis *" help={H.basis} value={basis} onChange={(e) => setBasis(e.target.value)} options={BASIS_OPTIONS} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!code} onClick={save}>Add</Button></div>
    </Dialog>
  );
}

function ScopeQuestions({ clientId, law, onClose, onDone }: { clientId: string; law: ClientLaw; onClose: () => void; onDone: (m: string) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>(Object.fromEntries(law.questions.filter((q) => q.manual).map((q) => [String(q.order), q.answer ?? ''])));
  const [mode, setMode] = useState(law.override ? 'manual' : 'auto');
  const [inScope, setInScope] = useState(law.override ? 'yes' : '');
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      if (mode === 'manual') {
        await api.put(`/clients/${clientId}/applicability/${law.regulation_id}/override`, { in_scope: inScope === 'yes', reason });
      } else {
        if (law.override) await api.put(`/clients/${clientId}/applicability/${law.regulation_id}/override`, { in_scope: null });
        const body = Object.fromEntries(law.questions.map((q) => [String(q.order), answers[String(q.order)] || null]));
        await api.put(`/clients/${clientId}/applicability/${law.regulation_id}/answers`, { answers: body });
      }
      onDone(`${law.label}: scope saved.`);
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Scope: ${law.label}`} onClose={onClose}>
      {err && <Alert tone="danger">{err}</Alert>}
      <SelectField label="How scope is decided" value={mode} onChange={(e) => setMode(e.target.value)} options={[{ value: 'auto', label: 'From the scope questions' }, { value: 'manual', label: 'Set by hand' }]} />
      {mode === 'auto' ? law.questions.map((q) => (
        <SelectField key={q.order} label={`${q.order}. ${q.question_text}`} help={H.answer} value={answers[String(q.order)] ?? ''} onChange={(e) => setAnswers({ ...answers, [String(q.order)]: e.target.value })}
          placeholder={`Pre-filled: ${q.answer && !q.manual ? q.answer : 'not known'}`} options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]} />
      )) : <>
        <SelectField label="In scope?" value={inScope} onChange={(e) => setInScope(e.target.value)} placeholder="Choose" options={[{ value: 'yes', label: 'In scope' }, { value: 'no', label: 'Not in scope' }]} />
        <TextArea label="Reason *" help={H.overrideReason} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      </>}
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={mode === 'manual' && (!inScope || !reason.trim())} onClick={save}>Save</Button></div>
    </Dialog>
  );
}

function EditLetter({ clientId, letterId, initial, onClose, onDone }: { clientId: string; letterId: string; initial: { opening?: string; closing?: string }; onClose: () => void; onDone: () => void }) {
  const [opening, setOpening] = useState(initial.opening ?? '');
  const [closing, setClosing] = useState(initial.closing ?? '');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try { await api.patch(`/clients/${clientId}/letters/${letterId}`, { opening, closing }); onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title="Edit letter text" onClose={onClose} large>
      <p className="small muted">The law, committee, role and rule sections come from the applicability result and the approved law versions. Edit those in the law library.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <TextArea label="Opening paragraph" help={H.opening} value={opening} onChange={(e) => setOpening(e.target.value)} rows={4} placeholder="Leave blank for the standard opening." />
      <TextArea label="Note after section 5" help={H.closing} value={closing} onChange={(e) => setClosing(e.target.value)} rows={3} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></div>
    </Dialog>
  );
}
