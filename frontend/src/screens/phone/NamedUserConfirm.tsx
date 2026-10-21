import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Button, FieldGroup, Loading, TextArea } from '@/components/ui';
import { namedUserHelp as H } from '@/help/client';
import { PhoneShell } from '@/shells/Shells';

type View = { client_name: string; first_name: string; use_case: string; tool: string; oversight_role: string | null; policy_text: string; completed: boolean };

function YesNo({ label, help, value, onChange }: { label: string; help: string; value: boolean | null; onChange: (v: boolean) => void }) {
  return (
    <FieldGroup legend={label} help={help}>
      <div className="row" role="radiogroup" style={{ gap: 6 }}>
        <label className="radio-pill"><input type="radio" checked={value === true} onChange={() => onChange(true)} />Yes</label>
        <label className="radio-pill"><input type="radio" checked={value === false} onChange={() => onChange(false)} />No</label>
      </div>
    </FieldGroup>
  );
}

/** Personal, no-login confirmation for people named on Tier 2–3 use cases (schematic D13). */
export function NamedUserConfirm() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['confirm', token], queryFn: () => api.get<View>(`/public/confirm/${token}`), retry: false });
  const [a, setA] = useState<{ training_complete: boolean | null; policy_acknowledged: boolean | null; oversight_role_confirmed: boolean | null }>({ training_complete: null, policy_acknowledged: null, oversight_role_confirmed: null });
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  if (q.isLoading) return <PhoneShell title="AI use confirmation"><Loading /></PhoneShell>;
  if (!q.data) return <PhoneShell title="AI use confirmation"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const v = q.data;
  if (done || v.completed) return <PhoneShell title={`${v.client_name} · AI use`}><h1 style={{ fontSize: 22 }}>Thank you</h1><p>Your answers have been recorded.</p></PhoneShell>;
  const anyNo = a.training_complete === false || a.policy_acknowledged === false || a.oversight_role_confirmed === false;
  async function submit() {
    setErr(null);
    try { await api.post(`/public/confirm/${token}`, { ...a, unable_reason: reason }); setDone(true); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <PhoneShell title={`${v.client_name} · AI use`}>
      <div className="stack">
        <h1 style={{ fontSize: 22, margin: 0 }}>Hello {v.first_name}</h1>
        <p className="small" style={{ margin: 0 }}>You are named as someone who uses AI for <strong>{v.use_case}</strong> ({v.tool}). Three quick questions.</p>
        {err && <Alert tone="danger">{err}</Alert>}
        <YesNo label="Have you had training on using this AI tool?" help={H.training} value={a.training_complete} onChange={(x) => setA({ ...a, training_complete: x })} />
        <div className="card" style={{ padding: 12 }}><p className="small" style={{ margin: 0 }}>{v.policy_text}</p></div>
        <YesNo label="Have you read the AI use policy?" help={H.policy} value={a.policy_acknowledged} onChange={(x) => setA({ ...a, policy_acknowledged: x })} />
        <YesNo label={v.oversight_role ? `Do you carry out this review: "${v.oversight_role}"?` : 'Do you review the AI output before it is used?'} help={H.oversight} value={a.oversight_role_confirmed} onChange={(x) => setA({ ...a, oversight_role_confirmed: x })} />
        {anyNo && <TextArea label="Anything we should know? (optional)" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} />}
        <Button variant="primary" onClick={submit} disabled={a.training_complete === null || a.policy_acknowledged === null || a.oversight_role_confirmed === null}>Submit</Button>
      </div>
    </PhoneShell>
  );
}
