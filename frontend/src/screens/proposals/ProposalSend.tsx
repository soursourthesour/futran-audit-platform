import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Loading, TextArea, TextField, fmtDateTime } from '@/components/ui';
import type { SendPage } from '@/api/proposals';
import { statusBadge } from './ProposalBuilder';
import '@/styles/proposals.css';

const KIND: Record<string, string> = {
  sent: 'Sent', reminder: 'Reminder sent', opened: 'Link opened', accepted: 'Accepted', changes_requested: 'Changes requested', expired: 'Expired',
  not_delivered: 'Not delivered', handoff_failed: 'Hand-off needs attention',
};

/** SM-10 Proposal preview and send. */
export function ProposalSend() {
  const { id = '' } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['proposal-send', id], queryFn: () => api.get<SendPage>(`/sales/proposals/${id}/document`) });
  const [to, setTo] = useState([{ name: '', email: '' }]);
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    setSubject((s) => s || d.default_subject);
    setMessage((m) => m || d.default_message);
    if (d.contacts.length) setTo((t) => (t.length === 1 && !t[0].email ? [{ name: d.contacts[0].name, email: d.contacts[0].email }] : t));
  }, [d]);
  if (q.isLoading) return <Loading />;
  if (!d) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const p = d.proposal;
  const approved = d.approvals.filter((a) => a.state === 'approved');

  async function send() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await api.post<{ sent: number }>(`/sales/proposals/${id}/send`, { recipients: to.filter((r) => r.email.trim()), subject, message });
      setMsg(`Sent to ${out.sent} ${out.sent === 1 ? 'person' : 'people'}. Version ${p.version} is now frozen.`);
      await qc.invalidateQueries({ queryKey: ['proposal-send', id] });
      qc.invalidateQueries({ queryKey: ['proposal', id] });
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function remind(linkId: string) {
    setErr(null);
    try {
      await api.post(`/sales/proposals/${id}/links/${linkId}/remind`);
      setMsg('Reminder sent with a fresh link; the old link no longer works.');
      qc.invalidateQueries({ queryKey: ['proposal-send', id] });
    } catch (e) { setErr(errorMessage(e)); }
  }

  return (
    <div className="page ps-page">
      <div className="page-header">
        <div>
          <Link className="small" to={`/sales/proposals/${id}`}>{p.company} · back to the builder</Link>
          <h1>Proposal v{p.version} {statusBadge(p.status, p.status_label)}</h1>
          <p className="small muted">{p.valid_until ? `Valid until ${p.valid_until}` : `If sent today, valid until ${d.valid_until_if_sent}`} · Year-1 total {p.totals.y1_total?.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}</p>
        </div>
      </div>
      {err && <Alert tone="danger">{err}</Alert>}
      {msg && <Alert tone="success">{msg}</Alert>}
      <div className="ps-grid">
        <nav className="ps-toc card" aria-label="Sections">
          <ol>{d.sections.map((s) => <li key={s.key}><a href={`#sec-${s.key}`}>{s.number}. {s.title}</a></li>)}</ol>
        </nav>
        <article className="ps-doc card" aria-label="Document preview">
          {d.sections.map((s) => (
            <section key={s.key} id={`sec-${s.key}`} className={`ps-sec ps-sec-${s.key}`}>
              {s.key === 'cover' ? <><p className="ps-kicker">Futran Solutions · AI governance advisory</p><h2 className="ps-title">{p.title}</h2></> : <h2>{s.number}. {s.title}</h2>}
              <div className="ps-body" dangerouslySetInnerHTML={{ __html: s.html }} />
            </section>
          ))}
        </article>
        <aside className="stack ps-side">
          <section className="card"><div className="card-header"><h2>Export</h2></div>
            <div className="card-body row">
              <a className="btn" href={`/api/v1/sales/proposals/${id}/export.pdf`}>PDF</a>
              <a className="btn" href={`/api/v1/sales/proposals/${id}/export.docx`}>Word</a>
            </div>
          </section>
          {p.editable && d.can_work && (
            <section className="card" aria-label="Send to client"><div className="card-header"><h2>Send to client</h2></div>
              <div className="card-body stack-sm">
                {to.map((r, i) => (
                  <div key={i} className="ps-to">
                    <TextField label={i === 0 ? 'To: name' : `Name ${i + 1}`} value={r.name} onChange={(e) => setTo(to.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                    <TextField label={i === 0 ? 'Email' : `Email ${i + 1}`} type="email" value={r.email} onChange={(e) => setTo(to.map((x, j) => (j === i ? { ...x, email: e.target.value } : x)))} />
                  </div>
                ))}
                {to.length < 10 && <Button size="sm" variant="ghost" onClick={() => setTo([...to, { name: '', email: '' }])}>Add another person</Button>}
                <TextField label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
                <TextArea label="Message" rows={6} value={message} onChange={(e) => setMessage(e.target.value)} hint="Each person gets their own acceptance link, which expires with the proposal. [First name] and [Company] are filled in." />
                <p className="small muted">From: {d.sender}</p>
                {d.send_blockers.length > 0 ? (
                  <Alert tone="warn"><strong>Can't send yet.</strong><ul className="ps-blockers">{d.send_blockers.map((b, i) => <li key={i}>{b.message}</li>)}</ul></Alert>
                ) : (
                  <p className="small">{approved.length ? `All approvals complete: ${approved.map((a) => `${a.rule} (${a.approver})`).join(', ')}.` : 'No approvals needed.'}</p>
                )}
                <Button variant="primary" disabled={busy || d.send_blockers.length > 0 || !to.some((r) => r.email.trim())} onClick={send}>Send from my mailbox</Button>
              </div>
            </section>
          )}
          {d.links.length > 0 && (
            <section className="card" aria-label="Acceptance links"><div className="card-header"><h2>Acceptance links</h2></div>
              <div className="card-body">
                <ul className="ps-links">
                  {d.links.map((l) => (
                    <li key={l.id}>
                      <div><strong>{l.name}</strong> <span className="small muted">{l.email}</span></div>
                      <div className="small">{l.active ? (l.opened_at ? <Badge tone="success">Opened {l.open_count}×</Badge> : <Badge tone="warn">Not opened</Badge>) : <Badge tone="muted">Replaced</Badge>} expires {fmtDateTime(l.expires_at)}</div>
                      {l.active && d.can_work && ['sent', 'viewed', 'changes_requested'].includes(p.status) && <Button size="sm" onClick={() => remind(l.id)}>Send reminder</Button>}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}
          <section className="card" aria-label="Send log"><div className="card-header"><h2>Send log</h2></div>
            <div className="card-body">
              {d.log.length === 0 ? <p className="muted small">Nothing sent yet.</p> : (
                <ul className="ps-log">{d.log.map((e, i) => <li key={i}><strong>{KIND[e.kind] ?? e.kind}</strong> · v{e.version} · {fmtDateTime(e.at)}{e.by ? ` · ${e.by}` : ''}{e.detail && <div className="small muted">{e.detail}</div>}</li>)}</ul>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
