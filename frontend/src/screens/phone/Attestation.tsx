import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Checkbox, Loading, Progress, SelectField, TextField } from '@/components/ui';
import { PhoneShell } from '@/shells/Shells';

type Opt = { value: string; label: string };
type Info = { client_name: string; policy_version: string; policy_text: string; departments: { id: string; name: string }[]; tools: Opt[]; account_types: Opt[]; purposes: Opt[]; data_categories: Opt[]; closes_at: string; open: boolean };
type Tool = { tool: string; account_type: string; name?: string };

/** The no-login staff check-in (schematic D13, mockup Attestation): four short steps on a phone. */
export function PhoneAttestation() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['attest', token], queryFn: () => api.get<Info>(`/public/attest/${token}`), retry: false });
  const [step, setStep] = useState(1);
  const [who, setWho] = useState({ respondent_name: '', respondent_email: '', department_id: '' });
  const [none, setNone] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);
  const [purposes, setPurposes] = useState<string[]>([]);
  const [data, setData] = useState<string[]>([]);
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const [why, setWhy] = useState(false);

  if (q.isLoading) return <PhoneShell title="AI use check-in"><Loading /></PhoneShell>;
  if (q.error instanceof ApiError || !q.data) return <PhoneShell title="AI use check-in"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const info = q.data;
  if (!info.open) return <PhoneShell title={`${info.client_name} · AI use check-in`}><Alert tone="info">This check-in has closed. Thank you; nothing more is needed.</Alert></PhoneShell>;
  if (done) return <PhoneShell title={`${info.client_name} · AI use check-in`}><div className="stack"><h1 style={{ fontSize: 22 }}>Thank you</h1><p>Your answers have been recorded. If something changes, you can open the same link and answer again with the same email; your new answers replace the old ones.</p></div></PhoneShell>;

  const toggle = (list: string[], v: string, set: (x: string[]) => void) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const hasTool = (v: string) => tools.some((t) => t.tool === v);
  const setTool = (v: string, patch: Partial<Tool>) => setTools(tools.map((t) => (t.tool === v ? { ...t, ...patch } : t)));

  function next() {
    setErr(null);
    if (step === 1 && (!who.respondent_name.trim() || !who.department_id)) { setErr('Enter your name and choose your department.'); return; }
    if (step === 2 && !none && (!tools.length || tools.some((t) => !t.account_type))) { setErr('Choose the tools you use and which account, or tick "I don\'t use AI for work".'); return; }
    setStep(none && step === 2 ? 4 : step + 1);
  }
  async function submit() {
    setErr(null); setFe({});
    try {
      await api.post(`/public/attest/${token}`, { ...who, uses_ai: !none, tools_declared: none ? [] : tools, purposes: none ? [] : purposes, data_entered: none ? [] : data, policy_acknowledged: ack });
      setDone(true);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }

  return (
    <PhoneShell title={`${info.client_name} · AI use check-in`}>
      <div className="stack">
        <Progress value={(step / 4) * 100} label={`Step ${step} of 4`} />
        {err && <Alert tone="danger">{err}</Alert>}
        {step === 1 && (
          <>
            <h1 style={{ fontSize: 22, margin: 0 }}>About you</h1>
            <p className="small">This is not a test and nothing here is used to judge you. It helps {info.client_name} set safe rules for AI. <button type="button" className="link-btn small" onClick={() => setWhy(!why)}>How your answers are used</button></p>
            {why && <Alert tone="info">Your individual answers are seen only by the Chief AI Compliance Officer, the Data Protection Officer and the Futran auditors. Managers see department totals only, and only where at least three people have answered.</Alert>}
            <TextField label="Your name" value={who.respondent_name} onChange={(e) => setWho({ ...who, respondent_name: e.target.value })} autoComplete="name" error={fe.respondent_name} />
            <TextField label="Work email (optional)" type="email" value={who.respondent_email} onChange={(e) => setWho({ ...who, respondent_email: e.target.value })} help="Lets you update your answers later." autoComplete="email" error={fe.respondent_email} />
            <SelectField label="Department" value={who.department_id} onChange={(e) => setWho({ ...who, department_id: e.target.value })} placeholder="Choose…" options={info.departments.map((d) => ({ value: d.id, label: d.name }))} error={fe.department_id} />
          </>
        )}
        {step === 2 && (
          <>
            <h1 style={{ fontSize: 22, margin: 0 }}>Which AI tools do you use for work?</h1>
            {info.tools.map((t) => (
              <div key={t.value} className="card" style={{ padding: 12 }}>
                <Checkbox label={t.label} checked={hasTool(t.value)} disabled={none} onChange={(e) => setTools(e.target.checked ? [...tools, { tool: t.value, account_type: '' }] : tools.filter((x) => x.tool !== t.value))} />
                {hasTool(t.value) && (
                  <div className="stack-sm" style={{ marginTop: 8 }}>
                    {(t.value === 'in_app' || t.value === 'other') && <TextField label="Name of the tool or app" value={tools.find((x) => x.tool === t.value)?.name ?? ''} onChange={(e) => setTool(t.value, { name: e.target.value })} />}
                    <fieldset><legend className="small">Which account?</legend>
                      <div className="row" style={{ gap: 6 }}>{info.account_types.map((a) => <label key={a.value} className="radio-pill"><input type="radio" name={`acct-${t.value}`} checked={tools.find((x) => x.tool === t.value)?.account_type === a.value} onChange={() => setTool(t.value, { account_type: a.value })} />{a.label}</label>)}</div>
                    </fieldset>
                  </div>
                )}
              </div>
            ))}
            <Checkbox label="I don't use AI for work" checked={none} onChange={(e) => { setNone(e.target.checked); if (e.target.checked) setTools([]); }} />
          </>
        )}
        {step === 3 && (
          <>
            <h1 style={{ fontSize: 22, margin: 0 }}>What do you use it for?</h1>
            <fieldset><legend className="small">Tick all that apply</legend>
              <div className="stack-sm">{info.purposes.map((p) => <Checkbox key={p.value} label={p.label} checked={purposes.includes(p.value)} onChange={() => toggle(purposes, p.value, setPurposes)} />)}</div>
            </fieldset>
            <fieldset><legend className="small">What information goes into it?</legend>
              <div className="stack-sm">{info.data_categories.map((p) => <Checkbox key={p.value} label={p.label} checked={data.includes(p.value)} onChange={() => toggle(data, p.value, setData)} />)}</div>
            </fieldset>
          </>
        )}
        {step === 4 && (
          <>
            <h1 style={{ fontSize: 22, margin: 0 }}>AI use policy</h1>
            <div className="card" style={{ padding: 12 }}><p className="small" style={{ margin: 0 }}>{info.policy_text}</p><p className="small muted" style={{ margin: '8px 0 0' }}>Policy version {info.policy_version}</p></div>
            <Checkbox label="I have read the AI use policy" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          </>
        )}
        <div className="row" style={{ justifyContent: 'space-between' }}>
          {step > 1 ? <Button onClick={() => setStep(none && step === 4 ? 2 : step - 1)}>Back</Button> : <span />}
          {step < 4 ? <Button variant="primary" onClick={next}>{step === 2 ? 'Next: what you use it for' : 'Next'}</Button> : <Button variant="primary" onClick={submit} disabled={!ack}>Submit</Button>}
        </div>
      </div>
    </PhoneShell>
  );
}
