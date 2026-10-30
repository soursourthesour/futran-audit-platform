import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { type Step } from '@/api/mail';
import { Alert, Button, Checkbox, Dialog, Loading, SelectField } from '@/components/ui';
import { emailHelp as H } from '@/help/email';
import './email.css';

type Body = { department_ids: string[]; offices: string[]; exclude_responded: boolean; mode: 'personal' | 'bcc'; reminder_days: number[] };

/** "Send to all employees" on the attestation tracker (spec §27.1): the directory group Employees · All, with an
 *  optional department or office filter and "leave out people who already responded". Personal links by default. */
export function SendToAllEmployees({ clientId, departments, onSent }: { clientId: string; departments?: { id: string; name: string }[]; onSent: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Send to all employees</Button>
      {open && <SendAllDialog clientId={clientId} departments={departments} onClose={() => setOpen(false)} onSent={(t) => { setOpen(false); onSent(t); }} />}
    </>
  );
}

function SendAllDialog({ clientId, departments, onClose, onSent }: { clientId: string; departments?: { id: string; name: string }[]; onClose: () => void; onSent: (text: string) => void }) {
  const qc = useQueryClient();
  const [b, setB] = useState<Body>({ department_ids: [], offices: [], exclude_responded: true, mode: 'personal', reminder_days: [3, 7] });
  const [office, setOffice] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const body = { ...b, offices: office ? [office] : [] };
  const p = useQuery({ queryKey: ['send-all-preview', clientId, body], queryFn: () => api.post<{ steps: Step[]; total: number }>(`/clients/${clientId}/attestation/send-all/preview`, body), retry: false });
  const offices = useQuery({ queryKey: ['mail-send-options', 'own'], queryFn: () => api.get<{ offices: string[]; departments: { id: string; name: string }[] }>('/mail/send/options'), retry: false });
  const depts = departments ?? offices.data?.departments ?? [];
  async function send() {
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ recipients: number; status: string }>(`/clients/${clientId}/attestation/send-all`, body);
      await qc.invalidateQueries({ queryKey: ['attestation', clientId] });
      onSent(`Attestation sent to ${r.recipients.toLocaleString()} ${r.recipients === 1 ? 'employee' : 'employees'}, each with their own link. Reminders go only to people who have not answered.`);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const total = p.data?.total ?? 0;
  return (
    <Dialog title="Send to all employees" onClose={onClose} wide>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>Everyone in Employees · All gets an email with their own link. No sign-in is needed; their name and department are filled in from the directory. Answers mark them as responded and go into the AI inventory like any other answer.</p>
        <div className="grid-2">
          <SelectField label="Only this department" help={H.departments} value={b.department_ids[0] ?? ''} placeholder="All departments" onChange={(e) => setB({ ...b, department_ids: e.target.value ? [e.target.value] : [] })} options={depts.map((d) => ({ value: d.id, label: d.name }))} />
          <SelectField label="Only this office" help={H.offices} value={office} placeholder="All offices" onChange={(e) => setOffice(e.target.value)} options={(offices.data?.offices ?? []).map((o) => ({ value: o, label: o }))} />
          <SelectField label="Delivery" help={H.mode} value={b.mode} onChange={(e) => setB({ ...b, mode: e.target.value as Body['mode'] })} options={[{ value: 'personal', label: 'Personal link for each person' }, { value: 'bcc', label: 'One message in BCC with a one-time code' }]} />
          <SelectField label="Reminders" help={H.reminders} value={b.reminder_days.join(',')} onChange={(e) => setB({ ...b, reminder_days: e.target.value ? e.target.value.split(',').map(Number) : [] })} options={[{ value: '3,7', label: 'After 3 and 7 days' }, { value: '5', label: 'After 5 days' }, { value: '', label: 'None' }]} />
        </div>
        <Checkbox label="Leave out people who already responded" help={H.excludeResponded} checked={b.exclude_responded} onChange={(e) => setB({ ...b, exclude_responded: e.target.checked })} />
        <div className="expansion-box" aria-live="polite">
          <h3>Who will receive it</h3>
          {p.isLoading ? <Loading label="Counting…" /> : p.error ? <Alert tone="danger">{errorMessage(p.error)}</Alert> : (
            <table className="expansion"><tbody>{p.data!.steps.map((s, i) => <tr key={i} className={s.kind === 'total' ? 'total' : ''}><td>{s.label}</td><td>{s.count < 0 ? `− ${Math.abs(s.count).toLocaleString()}` : s.count.toLocaleString()}</td></tr>)}</tbody></table>
          )}
        </div>
        <p className="small muted" style={{ margin: 0 }}>To choose other groups or change the message, use <Link to="/send?template=attestation_request&exclude=responded&from=attestation">Send an email to groups</Link>.</p>
        <div className="row"><Button variant="primary" onClick={send} disabled={busy || !total}>Send to {total.toLocaleString()} {total === 1 ? 'employee' : 'employees'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
