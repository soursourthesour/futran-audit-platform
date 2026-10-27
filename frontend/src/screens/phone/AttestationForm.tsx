import { useState } from 'react';
import { errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Checkbox, FieldGroup, Progress, SelectField, TextField, WithHelp } from '@/components/ui';
import { phoneAttestationHelp as H } from '@/help/client';
import { attestationFormHelp as F } from '@/help/attestation';

export type Opt = { value: string; label: string };
export type ToolOpt = Opt & { kind: 'tool' | 'agent'; has_name?: boolean; needs_name?: boolean; account?: string };
export type AttestInfo = { client_name: string; policy_version: string; policy_text: string; departments: { id: string; name: string }[]; tools: ToolOpt[]; account_types: Opt[]; purposes: Opt[]; data_categories: Opt[]; closes_at: string; open: boolean };
export type Identity = { respondent_name: string; respondent_email: string; department_id: string | null };
type Tool = { tool: string; account_type: string; name?: string };

const nameLabel = (t: ToolOpt) => (t.value === 'in_app' ? 'Name of the tool or app' : t.kind === 'agent' ? 'Name of the agent' : 'Name of the tool');
const nameHelp = (t: ToolOpt) => (t.value === 'in_app' ? F.appName : t.value === 'in_house_agent' ? F.inHouseAgent : t.kind === 'agent' ? F.agentName : F.toolName);

/** The four check-in steps, shared by the no-login phone link and the in-app attestation. With `identity`, the
 * person is already known: name and email are not asked, and the department only when their account has none. */
export function AttestationSteps({ info, identity, onSubmit, headingLevel = 1 }: { info: AttestInfo; identity?: Identity; onSubmit: (payload: Record<string, unknown>) => Promise<void>; headingLevel?: 1 | 2 }) {
  const [step, setStep] = useState(1);
  const [who, setWho] = useState({ respondent_name: identity?.respondent_name ?? '', respondent_email: identity?.respondent_email ?? '', department_id: identity?.department_id ?? '' });
  const [none, setNone] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);
  const [purposes, setPurposes] = useState<string[]>([]);
  const [purposeOther, setPurposeOther] = useState('');
  const [data, setData] = useState<string[]>([]);
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [why, setWhy] = useState(false);
  const [busy, setBusy] = useState(false);
  const Hn = headingLevel === 1 ? 'h1' : 'h2';
  const Sub = headingLevel === 1 ? 'h2' : 'h3';
  const deptName = info.departments.find((d) => d.id === identity?.department_id)?.name;

  const toggle = (list: string[], v: string, set: (x: string[]) => void) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const hasTool = (v: string) => tools.some((t) => t.tool === v);
  const setTool = (v: string, patch: Partial<Tool>) => setTools(tools.map((t) => (t.tool === v ? { ...t, ...patch } : t)));
  const spec = (v: string) => info.tools.find((t) => t.value === v);

  function next() {
    setErr(null);
    if (step === 1 && (!who.respondent_name.trim() || !who.department_id)) { setErr(identity ? 'Choose your department.' : 'Enter your name and choose your department.'); return; }
    if (step === 2 && !none) {
      if (!tools.length || tools.some((t) => !t.account_type)) { setErr('Choose the tools and agents you use and which account, or tick "I don\'t use AI for work".'); return; }
      const unnamed = tools.find((t) => spec(t.tool)?.needs_name && !(t.name ?? '').trim());
      if (unnamed) { setErr(`Give the name for "${spec(unnamed.tool)?.label}".`); return; }
    }
    if (step === 3 && purposes.includes('other') && !purposeOther.trim()) { setErr('Say what else you use AI for.'); setFe({ purpose_other: 'Say what else you use AI for.' }); return; }
    setFe({});
    setStep(none && step === 2 ? 4 : step + 1);
  }
  async function submit() {
    setErr(null); setFe({}); setBusy(true);
    try {
      await onSubmit({ ...who, uses_ai: !none, tools_declared: none ? [] : tools, purposes: none ? [] : purposes, purpose_other: !none && purposes.includes('other') ? purposeOther.trim() : '', data_entered: none ? [] : data, policy_acknowledged: ack });
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }

  const toolCard = (t: ToolOpt) => {
    const mine = tools.find((x) => x.tool === t.value);
    return (
      <div key={t.value} className="card" style={{ padding: 12 }}>
        <Checkbox label={t.label} checked={hasTool(t.value)} disabled={none} onChange={(e) => setTools(e.target.checked ? [...tools, { tool: t.value, account_type: t.account ?? '' }] : tools.filter((x) => x.tool !== t.value))} />
        {mine && (
          <div className="stack-sm" style={{ marginTop: 8 }}>
            {t.has_name && <TextField label={nameLabel(t)} help={nameHelp(t)} required={t.needs_name} maxLength={80} value={mine.name ?? ''} onChange={(e) => setTool(t.value, { name: e.target.value })} />}
            {!t.account && (
              <FieldGroup legend="Which account?" legendClassName="small" help={H.account}>
                <div className="row" style={{ gap: 6 }}>{info.account_types.map((a) => <label key={a.value} className="radio-pill"><input type="radio" name={`acct-${t.value}`} checked={mine.account_type === a.value} onChange={() => setTool(t.value, { account_type: a.value })} />{a.label}</label>)}</div>
              </FieldGroup>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="stack">
      <Progress value={(step / 4) * 100} label={`Step ${step} of 4`} />
      {err && <Alert tone="danger">{err}</Alert>}
      {step === 1 && (
        <>
          <Hn style={{ fontSize: 22, margin: 0 }}>About you</Hn>
          <p className="small">This is not a test and nothing here is used to judge you. It helps {info.client_name} set safe rules for AI. <button type="button" className="link-btn small" onClick={() => setWhy(!why)}>How your answers are used</button></p>
          {why && <Alert tone="info">Your individual answers are seen only by the Chief AI Compliance Officer, the Data Protection Officer and the Futran auditors. Managers see department totals only, and only where at least three people have answered.</Alert>}
          {identity ? (
            <>
              <FieldGroup legend="Answering as" legendClassName="small" help={F.identity}>
                <p style={{ margin: 0 }}><strong>{identity.respondent_name}</strong> · {identity.respondent_email}{deptName ? ` · ${deptName}` : ''}</p>
              </FieldGroup>
              {!identity.department_id && <SelectField label="Department" help={H.department} value={who.department_id} onChange={(e) => setWho({ ...who, department_id: e.target.value })} placeholder="Choose…" options={info.departments.map((d) => ({ value: d.id, label: d.name }))} error={fe.department_id} />}
            </>
          ) : (
            <>
              <TextField label="Your name" help={H.name} value={who.respondent_name} onChange={(e) => setWho({ ...who, respondent_name: e.target.value })} autoComplete="name" error={fe.respondent_name} />
              <TextField label="Work email (optional)" type="email" value={who.respondent_email} onChange={(e) => setWho({ ...who, respondent_email: e.target.value })} help={H.email} autoComplete="email" error={fe.respondent_email} />
              <SelectField label="Department" help={H.department} value={who.department_id} onChange={(e) => setWho({ ...who, department_id: e.target.value })} placeholder="Choose…" options={info.departments.map((d) => ({ value: d.id, label: d.name }))} error={fe.department_id} />
            </>
          )}
        </>
      )}
      {step === 2 && (
        <>
          <Hn style={{ fontSize: 22, margin: 0 }}><WithHelp help={F.tools} label="AI tools and agents you use">Which AI tools and agents do you use for work?</WithHelp></Hn>
          <Sub style={{ fontSize: 16, margin: '4px 0 0' }}>AI tools</Sub>
          {info.tools.filter((t) => t.kind !== 'agent').map(toolCard)}
          <Sub style={{ fontSize: 16, margin: '8px 0 0' }}><WithHelp help={F.agents} label="AI agents">AI agents (tools that take actions for you)</WithHelp></Sub>
          {info.tools.filter((t) => t.kind === 'agent').map(toolCard)}
          <Checkbox label="I don't use AI for work" help={H.none} checked={none} onChange={(e) => { setNone(e.target.checked); if (e.target.checked) setTools([]); }} />
        </>
      )}
      {step === 3 && (
        <>
          <Hn style={{ fontSize: 22, margin: 0 }}>What do you use it for?</Hn>
          <FieldGroup legend="Tick all that apply" legendClassName="small" help={H.purposes}>
            <div className="stack-sm">{info.purposes.map((p) => <Checkbox key={p.value} label={p.label} checked={purposes.includes(p.value)} onChange={() => toggle(purposes, p.value, setPurposes)} />)}</div>
          </FieldGroup>
          {purposes.includes('other') && <TextField label="What else?" help={F.purposeOther} required maxLength={200} value={purposeOther} onChange={(e) => setPurposeOther(e.target.value)} error={fe.purpose_other} />}
          <FieldGroup legend="What information goes into it?" legendClassName="small" help={H.data}>
            <div className="stack-sm">{info.data_categories.map((p) => <Checkbox key={p.value} label={p.label} checked={data.includes(p.value)} onChange={() => toggle(data, p.value, setData)} />)}</div>
          </FieldGroup>
        </>
      )}
      {step === 4 && (
        <>
          <Hn style={{ fontSize: 22, margin: 0 }}>AI use policy</Hn>
          <div className="card" style={{ padding: 12 }}><p className="small" style={{ margin: 0 }}>{info.policy_text}</p><p className="small muted" style={{ margin: '8px 0 0' }}>Policy version {info.policy_version}</p></div>
          <Checkbox label="I have read the AI use policy" help={H.policy} checked={ack} onChange={(e) => setAck(e.target.checked)} />
        </>
      )}
      <div className="row" style={{ justifyContent: 'space-between' }}>
        {step > 1 ? <Button onClick={() => setStep(none && step === 4 ? 2 : step - 1)}>Back</Button> : <span />}
        {step < 4 ? <Button variant="primary" onClick={next}>{step === 2 ? 'Next: what you use it for' : 'Next'}</Button> : <Button variant="primary" onClick={submit} disabled={!ack || busy}>Submit</Button>}
      </div>
    </div>
  );
}
