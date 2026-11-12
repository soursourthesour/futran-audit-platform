import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, ApiError } from '@/api/client';
import { Alert, Button, Checkbox, Loading, TextArea, TextField } from '@/components/ui';
import { money, type PublicProposal } from '@/api/proposals';
import logoWhite from '@/assets/futran-logo-white.svg';
import '@/styles/proposals.css';

/** SM-12 Proposal acceptance: public, phone-friendly, no sign-in. One proposal version behind a personal link. */
export function ProposalAcceptance() {
  const { token = '' } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['public-proposal', token], queryFn: () => api.get<PublicProposal>(`/public/p/${token}`), retry: false, refetchOnWindowFocus: false });
  const [full, setFull] = useState(false);
  const [mode, setMode] = useState<'accept' | 'changes'>('accept');
  const [f, setF] = useState({ name: '', title: '', email: '', po_number: '' });
  const [ok, setOk] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [changes, setChanges] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const p = q.data;

  async function accept() {
    setBusy(true); setErr(null); setErrs({});
    const form = new FormData();
    Object.entries(f).forEach(([k, v]) => form.append(k, v));
    form.append('authorised', ok ? 'true' : '');
    if (file) form.append('po_file', file);
    try {
      await api.upload(`/public/p/${token}/accept`, form);
      setDone('Thank you. Your acceptance is recorded. Your Futran contact will be in touch about next steps.');
      qc.invalidateQueries({ queryKey: ['public-proposal', token] });
    } catch (e) {
      if (e instanceof ApiError && e.errors.length) setErrs(Object.fromEntries(e.errors.map((x) => [x.field, x.message])));
      setErr(errorMessage(e));
    } finally { setBusy(false); }
  }
  async function requestChanges() {
    setBusy(true); setErr(null);
    try {
      await api.post(`/public/p/${token}/changes`, { message: changes, name: f.name });
      setDone('Thank you. We have your request and will send a revised proposal.');
      qc.invalidateQueries({ queryKey: ['public-proposal', token] });
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <div className="pa">
      <header className="pa-head">
        <img className="pa-logo" src={logoWhite} alt="Futran Solutions" />
        {p && <span className="pa-for">Proposal for {p.company} · v{p.version}{p.valid_until ? ` · valid until ${p.valid_until_label}` : ''}</span>}
      </header>
      <main className="pa-main">
        {q.isLoading && <Loading />}
        {q.error && <Alert tone="danger">{errorMessage(q.error)}</Alert>}
        {p && (
          <>
            <div className="row pa-top">
              <h1 className="pa-h1">{p.title}</h1>
              <a className="btn btn-sm" href={`/api/v1/public/p/${token}/pdf`}>Download PDF</a>
            </div>
            <section className="card"><div className="card-body">
              <h2 className="pa-h2">What's included</h2>
              <ul className="pa-list">{p.included.map((i) => <li key={i.name}>{i.name}{i.summary && <span className="small muted"> — {i.summary}</span>}</li>)}</ul>
              {p.optional.length > 0 && <p className="small muted">Optional, when available: {p.optional.map((o) => o.name).join(', ')}. Not priced in this proposal.</p>}
            </div></section>
            <section className="card"><div className="card-body">
              <h2 className="pa-h2">Price</h2>
              <dl className="pb-dl">
                <dt>One-time services</dt><dd>{money(p.totals.one_time)}</dd>
                <dt>Annual subscription, year 1{p.discount_recurring_pct ? ` (after ${p.discount_recurring_pct}% discount)` : ''}</dt><dd>{money(p.totals.recurring_y1 - p.totals.discount)}</dd>
                <dt className="pb-strong">Total, year 1</dt><dd className="pb-strong">{money(p.totals.y1_total)}</dd>
                <dt>Annual after year 1</dt><dd>{money(p.totals.arr)}</dd>
              </dl>
              <h3 className="pa-h3">Terms</h3>
              <ul className="pa-list small">{p.terms.map((t) => <li key={t}>{t}</li>)}</ul>
            </div></section>
            <Button onClick={() => setFull(!full)} aria-expanded={full}>{full ? 'Hide the full proposal' : `Read the full proposal (${p.sections.length} sections)`}</Button>
            {full && (
              <article className="card pa-doc"><div className="card-body">
                {p.sections.map((s) => (
                  <section key={s.key}><h2 className="pa-h2">{s.number}. {s.title}</h2><div className="ps-body" dangerouslySetInnerHTML={{ __html: s.html }} /></section>
                ))}
              </div></article>
            )}
            {done && <Alert tone="success">{done}</Alert>}
            {p.accepted && !done && <Alert tone="success">Accepted by {p.accepted.name}, {p.accepted.title}{p.accepted.po_number ? ` · PO ${p.accepted.po_number}` : ''}.</Alert>}
            {p.status === 'changes_requested' && !done && <Alert>You asked for changes. Your Futran contact will send a revised proposal.</Alert>}
            {p.can_respond && !done && (
              <section className="card" aria-label="Respond"><div className="card-body stack-sm">
                <div className="pa-switch" role="tablist">
                  <button type="button" role="tab" aria-selected={mode === 'accept'} className={mode === 'accept' ? 'active' : ''} onClick={() => setMode('accept')}>Accept this proposal</button>
                  <button type="button" role="tab" aria-selected={mode === 'changes'} className={mode === 'changes' ? 'active' : ''} onClick={() => setMode('changes')}>Request changes</button>
                </div>
                {err && <Alert tone="danger">{err}</Alert>}
                {mode === 'accept' ? (
                  <>
                    <TextField label="Full name" autoComplete="name" value={f.name} error={errs.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
                    <TextField label="Title" autoComplete="organization-title" value={f.title} error={errs.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
                    <TextField label="Work email" type="email" autoComplete="email" value={f.email} error={errs.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
                    <TextField label="PO number (optional)" value={f.po_number} onChange={(e) => setF({ ...f, po_number: e.target.value })} />
                    <div className="field"><label htmlFor="pa-po">Purchase order file (optional)</label>
                      <input id="pa-po" type="file" className="input" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
                    <Checkbox label={`I am authorised to accept this proposal for ${p.company}.`} checked={ok} onChange={(e) => setOk(e.target.checked)} />
                    {errs.authorised && <div className="error">{errs.authorised}</div>}
                    <Button variant="primary" block disabled={busy} onClick={accept}>Accept proposal</Button>
                  </>
                ) : (
                  <>
                    <TextArea label="What would you like changed?" rows={5} value={changes} onChange={(e) => setChanges(e.target.value)} />
                    <Button variant="primary" block disabled={busy || !changes.trim()} onClick={requestChanges}>Send request</Button>
                  </>
                )}
                <p className="small muted">Your acceptance is recorded with the time and your details. Questions? Reply to {p.rep.name ?? 'your Futran contact'}'s email.</p>
              </div></section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
