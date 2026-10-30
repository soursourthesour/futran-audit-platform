import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useAddons, type AddonSystem } from '@/api/tracing';
import { Alert, Badge, Button, Dialog, FieldGroup, Loading, SelectField, TextArea } from '@/components/ui';
import { unlockHelp as H } from '@/help/tracing';
import './tracing.css';

/** R8: choose systems (recommended ones ticked), plan, approver and trial, then send to the Executive Sponsor. */
export function UnlockDialog({ systemId, onClose, onSent }: { systemId?: string; onClose: () => void; onSent: (message: string) => void }) {
  const q = useAddons();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [plan, setPlan] = useState('per_system');
  const [trial, setTrial] = useState(true);
  const [approver, setApprover] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const d = q.data;
  useEffect(() => {
    if (!d || picked) return;
    setPicked(new Set(d.systems.filter((s) => s.status === 'locked' && (s.recommended || s.id === systemId)).map((s) => s.id)));
    if (d.sponsors.length === 1) setApprover(d.sponsors[0].id);
  }, [d, picked, systemId]);
  const open = useMemo(() => (d?.systems ?? []).filter((s) => s.status === 'locked'), [d]);
  const chosen = picked ?? new Set<string>();
  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    setPicked(next);
  }
  async function send() {
    setBusy(true); setErr(null); setFe({});
    try {
      await api.post('/addons/tracing/requests', { system_ids: [...chosen], plan, trial, approver_id: approver, note });
      await Promise.all([qc.invalidateQueries({ queryKey: ['addons'] }), qc.invalidateQueries({ queryKey: ['tracing'] }), qc.invalidateQueries({ queryKey: ['register'] })]);
      const who = d?.sponsors.find((x) => x.id === approver)?.name ?? 'your Executive Sponsor';
      onSent(`Sent to ${who} for approval. Futran's sales team has been told.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  const planObj = d?.plans.find((p) => p.value === plan);
  const summary = `${chosen.size} system${chosen.size === 1 ? '' : 's'} · ${planObj?.label.toLowerCase() ?? ''} plan · ${trial ? `${d?.trial_days ?? 30}-day trial` : 'paid from today'}`;
  return (
    <Dialog title="Unlock the tracing and incident module" onClose={onClose} large>
      {!d ? (q.isLoading ? <Loading /> : <Alert tone="danger">{errorMessage(q.error)}</Alert>) : !d.can_request ? (
        <Alert tone="info">Your Chief AI Compliance Officer or Client Admin asks for the add-on, and your Executive Sponsor approves it.</Alert>
      ) : (
        <div className="stack">
          <p style={{ margin: 0 }}>Choose the AI systems to trace. Recommended ones are ticked: Tier 3 systems, agents that take actions, and systems with a past incident.</p>
          {err && <Alert tone="danger">{err}</Alert>}
          <FieldGroup legend="AI systems *" help={H.systems}>
            {fe.system_ids && <div className="error">{fe.system_ids}</div>}
            <table className="trc-pick" aria-label="AI systems to trace">
              <thead><tr><th scope="col"><span className="sr-only">Trace</span></th><th scope="col">AI system</th><th scope="col">Dept</th><th scope="col">Tier</th><th scope="col">Stage</th><th scope="col">Why</th></tr></thead>
              <tbody>
                {d.systems.map((s) => <PickRow key={s.id} s={s} checked={chosen.has(s.id)} onToggle={() => toggle(s.id)} />)}
              </tbody>
            </table>
            {open.length === 0 && <p className="small muted">Every system already has the module or is waiting for approval.</p>}
          </FieldGroup>
          <FieldGroup legend="Plan *" help={H.plan}>
            <div className="trc-plans">
              {d.plans.map((p) => (
                <label key={p.value} className={`option-card ${plan === p.value ? 'checked' : ''}`}>
                  <input type="radio" name="trc-plan" checked={plan === p.value} onChange={() => setPlan(p.value)} />
                  <div><strong>{p.label}</strong><span>{p.hint}{p.value === 'per_system' ? ` ${chosen.size} selected.` : p.count !== null ? ` ${p.count} system${p.count === 1 ? '' : 's'} now.` : ''}</span></div>
                </label>
              ))}
            </div>
          </FieldGroup>
          <div className="grid-2">
            <SelectField label="Approver *" help={H.approver} value={approver} onChange={(e) => setApprover(e.target.value)} error={fe.approver_id}
              placeholder={d.sponsors.length ? 'Choose the Executive Sponsor' : 'No Executive Sponsor has a login'} options={d.sponsors.map((u) => ({ value: u.id, label: `${u.name} · Executive Sponsor` }))} />
            <FieldGroup legend="Start" help={H.start}>
              <div className="radio-group">
                <label className="radio-pill"><input type="radio" name="trc-start" checked={trial} onChange={() => setTrial(true)} />{d.trial_days}-day free trial, then paid</label>
                <label className="radio-pill"><input type="radio" name="trc-start" checked={!trial} onChange={() => setTrial(false)} />Paid from today</label>
              </div>
            </FieldGroup>
          </div>
          <TextArea label="Note to Futran (optional)" help={H.note} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          <p className="small muted" style={{ margin: 0 }}>Sending creates a request for your Executive Sponsor. Once approved, the module unlocks on the chosen systems and Futran's sales team confirms the order with you. Futran auditors keep reviewing these systems independently; buying the module does not change audit results.</p>
          <div className="row trc-dialog-foot">
            <span className="small"><strong>{summary}</strong></span>
            <span className="row"><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || chosen.size === 0} onClick={send}>Send for approval</Button></span>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function PickRow({ s, checked, onToggle }: { s: AddonSystem; checked: boolean; onToggle: () => void }) {
  const locked = s.status === 'locked';
  return (
    <tr className={checked ? 'sel' : undefined}>
      <td><input type="checkbox" aria-label={`Trace ${s.name}`} checked={locked && checked} disabled={!locked} onChange={onToggle} /></td>
      <td data-label="AI system"><strong>{s.name}</strong><div className="small muted">{s.type_label}</div></td>
      <td data-label="Dept">{s.department ?? '—'}</td>
      <td data-label="Tier">{s.tier_label ?? '—'}</td>
      <td data-label="Stage">{s.stage_label}</td>
      <td data-label="Why">
        {s.status === 'active' ? <Badge tone="success">Active</Badge> : s.status === 'requested' ? <Badge tone="navy">Waiting for approval</Badge>
          : s.recommended ? <><Badge tone="warn">Recommended</Badge> <span className="small">{s.reasons.join('; ')}</span></> : <span className="small muted">Optional</span>}
      </td>
    </tr>
  );
}
