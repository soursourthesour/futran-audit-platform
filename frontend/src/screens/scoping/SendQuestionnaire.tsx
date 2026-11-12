import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Dialog, Loading, SelectField, TextArea, TextField } from '@/components/ui';

type Opt = {
  sections: { key: string; label: string; internal: boolean; unanswered: number; total: number; questions: { code: string; label: string; internal_only: boolean; locked: boolean; answered: boolean; default: boolean }[] }[];
  contacts: { id: string; name: string; title: string | null; email: string; role: string | null }[]; sender: string; own_mailbox: boolean; subject: string; message: string;
  company: string; rep_name: string; expires_days: number; reminder_choices: { value: string; label: string }[];
};

function inDays(n: number): string {
  const d = new Date(Date.now() + n * 86400000);
  return d.toISOString().slice(0, 10);
}

/** SM-06: send questions to a client contact as a personal no-login link from the rep's mailbox. */
export function SendQuestionnaire({ qid, onClose, onSent }: { qid: string; onClose: () => void; onSent: () => void }) {
  const q = useQuery({ queryKey: ['scoping-send', qid], queryFn: () => api.get<Opt>(`/scoping/${qid}/send-options`) });
  const [contact, setContact] = useState<string>('');
  const [other, setOther] = useState({ name: '', email: '' });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [due, setDue] = useState(inDays(7));
  const [rem, setRem] = useState('3,7');
  const [fwd, setFwd] = useState(true);
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    setPicked(new Set(d.sections.flatMap((s) => s.questions.filter((x) => x.default).map((x) => x.code))));
    setContact(d.contacts[0]?.id ?? 'other');
    setSubject(d.subject);
    setMessage(d.message);
  }, [d]);
  const who = useMemo(() => (contact === 'other' ? other : d?.contacts.find((c) => c.id === contact)), [contact, other, d]);
  const preview = useMemo(() => {
    if (!d) return [];
    const first = (who?.name ?? '').trim().split(/\s+/)[0] || '[First name]';
    const dueText = due ? new Date(due + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : 'when you can';
    return message.split(/\n\n+/).map((p) => p.replace(/\[First name\]/g, first).replace(/\[Company\]/g, d.company).replace(/\[Due date\]/g, dueText).replace(/\[Rep name\]/g, d.rep_name));
  }, [message, who, due, d]);

  if (q.isLoading) return <Dialog title="Send questionnaire to client" onClose={onClose} large><Loading /></Dialog>;
  if (!d) return <Dialog title="Send questionnaire to client" onClose={onClose} large><Alert tone="danger">{errorMessage(q.error)}</Alert></Dialog>;

  function toggleSection(key: string, on: boolean) {
    const s = d!.sections.find((x) => x.key === key)!;
    setPicked((p) => { const n = new Set(p); for (const x of s.questions) if (!x.locked) { if (on) n.add(x.code); else n.delete(x.code); } return n; });
  }
  async function send() {
    setErr(null); setFe({}); setBusy(true);
    try {
      const c = contact === 'other' ? { name: other.name, email: other.email } : { id: contact, name: who?.name, email: who?.email };
      await api.post(`/scoping/${qid}/send`, { contact: c, question_codes: [...picked], due_on: due || null, reminders: rem ? rem.split(',').map(Number) : [], allow_forward: fwd, subject, message });
      onSent();
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  const count = picked.size;
  return (
    <Dialog title="Send questionnaire to client" onClose={onClose} large>
      <div className="sc-send">
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          {err && <Alert tone="danger">{err}</Alert>}
          <SelectField label="To" value={contact} onChange={(e) => setContact(e.target.value)}
            options={[...d.contacts.map((c) => ({ value: c.id, label: `${c.name}${c.title ? ` · ${c.title}` : ''}` })), { value: 'other', label: 'Someone else…' }]} />
          {contact === 'other' && (
            <div className="sc-two">
              <TextField label="Name" value={other.name} onChange={(e) => setOther({ ...other, name: e.target.value })} error={fe.contact} />
              <TextField label="Email" type="email" value={other.email} onChange={(e) => setOther({ ...other, email: e.target.value })} error={fe.email} />
            </div>
          )}
          <fieldset className="sc-pick">
            <legend>Questions to include</legend>
            {d.sections.map((s) => {
              const free = s.questions.filter((x) => !x.locked);
              const on = free.length > 0 && free.every((x) => picked.has(x.code));
              const some = free.some((x) => picked.has(x.code));
              const label = s.key === 'RF' ? s.label : `${s.key}. ${s.label}`;
              return (
                <div key={s.key} className="sc-pick-row">
                  <label className="sc-option">
                    <input type="checkbox" disabled={s.internal} checked={on} ref={(el) => { if (el) el.indeterminate = some && !on; }} onChange={(e) => toggleSection(s.key, e.target.checked)} />
                    <span>{label} <span className="muted small">— {s.internal ? 'internal, never sent' : s.unanswered === 0 ? 'answered on call' : `${s.unanswered} unanswered`}</span></span>
                  </label>
                  {!s.internal && <button type="button" className="linklike small" aria-expanded={!!open[s.key]} onClick={() => setOpen({ ...open, [s.key]: !open[s.key] })}>{open[s.key] ? 'Hide questions' : 'Choose questions'}</button>}
                  {open[s.key] && (
                    <div className="sc-pick-qs">
                      {s.questions.map((x) => (
                        <label key={x.code} className="sc-option small">
                          <input type="checkbox" disabled={x.locked} checked={!x.locked && picked.has(x.code)} onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(x.code); else n.delete(x.code); return n; })} />
                          <span>{x.code} {x.label}{x.locked ? ' — internal, never sent' : x.answered ? ' — answered' : ''}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <label className="sc-option"><input type="checkbox" disabled checked={false} readOnly /><span className="muted">Budget, competitors, red flags, independence — internal, never sent</span></label>
            {fe.question_codes && <p className="field-error">{fe.question_codes}</p>}
          </fieldset>
          <div className="sc-two">
            <TextField label="Due date" type="date" value={due} onChange={(e) => setDue(e.target.value)} error={fe.due_on} />
            <SelectField label="Reminders" value={rem} onChange={(e) => setRem(e.target.value)} options={d.reminder_choices} />
          </div>
          <label className="sc-option"><input type="checkbox" checked={fwd} onChange={(e) => setFwd(e.target.checked)} /><span>Let the client forward to a colleague (they get their own link)</span></label>
          <p className="small">Sends from <strong>{d.sender}</strong> as a personal link. No login. Expires in {d.expires_days} days.{!d.own_mailbox && ' Connect your mailbox under Email to send from it.'}</p>
        </form>
        <section className="sc-preview" aria-label="Message preview">
          <TextField label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <TextArea label="Message" hint="[Link] marks where the button goes." rows={7} value={message} onChange={(e) => setMessage(e.target.value)} />
          <div className="sc-mail" aria-label="How the email looks">
            {preview.map((p, i) => p.trim() === '[Link]' ? <p key={i}><span className="sc-mail-btn">Open the questions</span></p> : <p key={i}>{p}</p>)}
          </div>
        </section>
      </div>
      <div className="row sc-dialog-actions">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={busy || count === 0} onClick={send}>{busy ? 'Sending…' : `Send ${count} question${count === 1 ? '' : 's'}`}</Button>
      </div>
    </Dialog>
  );
}
