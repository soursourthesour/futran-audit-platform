import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors, type FieldError } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, WithHelp } from '@/components/ui';
import { useCaseHelp as H } from '@/help/client';
import { tierHelp as T } from '@/help/fieldwork';
import { ACCOUNT_LABELS, STATUS_LABELS, tierBadge, useInventory } from './Inventory';

type Named = { id?: string; person_name: string; email: string; role_name?: string | null; oversight_role: string; has_account?: boolean; training_complete?: boolean | null; policy_acknowledged?: boolean | null; oversight_role_confirmed?: boolean | null; link_sent?: boolean };
type Usage = { role_name: string; headcount: string; frequency: string };
type Detail = { id: string; name: string; department_id: string; purpose: string | null; tool_ids: string[]; data_categories: string[]; decision_impact: string | null; status: string; proposed_tier: number | null; final_tier: number | null; final_tier_rationale: string | null; aedt_determination: string | null; returned_comment: string | null; tier_reason: string; usage: { role_name: string; headcount: number | null; frequency: string | null }[]; named_users: Named[] };
type Preview = { tier: number; label: string; reason: string };

const DATA = [{ value: 'pii', label: 'Personal information (PII)' }, { value: 'phi', label: 'Health information (PHI)' }, { value: 'client', label: 'Client or customer data' }, { value: 'confidential', label: 'Company confidential' }, { value: 'none', label: 'None of these' }];
const IMPACT = [{ value: 'none', label: 'No effect on decisions about people' }, { value: 'informs', label: 'Informs a decision a person makes' }, { value: 'consequential', label: 'Substantially assists or makes decisions on hiring, promotion, credit, housing, insurance or health' }];
const AEDT = [{ value: 'in_scope', label: 'In scope (AEDT under LL144)' }, { value: 'out_of_scope', label: 'Out of scope' }, { value: 'undetermined', label: 'Not yet determined' }];

export function UseCaseForm() {
  const { useCaseId, clientId: futranClient } = useParams();
  const { data: me } = useMe();
  const clientId = futranClient ?? me?.organization.id ?? '';
  const isFutran = !!futranClient;
  const inv = useInventory(clientId);
  const detail = useQuery({ queryKey: ['use-case', useCaseId], queryFn: () => api.get<Detail>(`/use-cases/${useCaseId}`), enabled: !!useCaseId });
  if (inv.isLoading || (useCaseId && detail.isLoading) || !inv.data) return <div className="page"><Loading /></div>;
  return <Form key={detail.data?.id ?? 'new'} clientId={clientId} isFutran={isFutran} uc={detail.data} canReview={hasRole(me ?? undefined, 'caico', 'dept_compliance_lead')} canTier={hasRole(me ?? undefined, 'auditor', 'chief_auditor')} />;
}

function Form({ clientId, uc, isFutran, canReview, canTier }: { clientId: string; uc?: Detail; isFutran: boolean; canReview: boolean; canTier: boolean }) {
  const inv = useInventory(clientId).data!;
  const nav = useNavigate();
  const qc = useQueryClient();
  const editable = !isFutran && (!uc || uc.status === 'draft' || uc.status === 'returned');
  const [f, setF] = useState({ name: uc?.name ?? '', department_id: uc?.department_id ?? inv.departments[0]?.id ?? '', purpose: uc?.purpose ?? '', tool_ids: uc?.tool_ids ?? [], data_categories: uc?.data_categories ?? [], decision_impact: uc?.decision_impact ?? '' });
  const [usage, setUsage] = useState<Usage[]>(uc?.usage.length ? uc.usage.map((u) => ({ role_name: u.role_name, headcount: u.headcount?.toString() ?? '', frequency: u.frequency ?? '' })) : [{ role_name: '', headcount: '', frequency: '' }]);
  const [named, setNamed] = useState<Named[]>(uc?.named_users ?? []);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<FieldError[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api.post<Preview>(`/clients/${clientId}/use-cases/tier-preview`, { decision_impact: f.decision_impact || null, data_categories: f.data_categories, tool_ids: f.tool_ids }).then(setPreview).catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(t);
  }, [clientId, f.decision_impact, f.data_categories, f.tool_ids]);

  const fe = Object.fromEntries(errs.map((e) => [e.field, e.message]));
  const toggle = (k: 'tool_ids' | 'data_categories', v: string) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] });
  const body = () => ({ ...f, usage: usage.filter((u) => u.role_name.trim()), named_users: named.filter((n) => n.person_name.trim()) });

  async function save(submit: boolean) {
    setErr(null); setErrs([]); setMsg(null);
    try {
      const saved = uc ? await api.put<Detail>(`/use-cases/${uc.id}`, body()) : await api.post<Detail>(`/clients/${clientId}/use-cases`, body());
      if (submit) await api.post(`/use-cases/${saved.id}/submit`);
      await qc.invalidateQueries();
      if (submit) nav('/inventory');
      else if (!uc) nav(`/inventory/${saved.id}`, { replace: true });
      else setMsg('Draft saved.');
    } catch (e) {
      setErr(errorMessage(e));
      setErrs((e as { errors?: FieldError[] }).errors ?? []);
    }
  }

  const tier = preview?.tier ?? uc?.proposed_tier ?? 1;
  const needNamed = tier >= 2;
  return (
    <div className="page">
      <PageHeader crumbs={[{ to: isFutran ? `/clients/${clientId}/inventory` : '/inventory', label: 'AI inventory' }, { label: uc ? uc.name : 'New use case' }]} title={uc ? uc.name : 'Add a use case'}
        actions={uc ? <Badge tone={STATUS_LABELS[uc.status]?.tone ?? 'muted'}>{STATUS_LABELS[uc.status]?.label}</Badge> : undefined} />
      {uc?.status === 'returned' && uc.returned_comment && <Alert tone="warn"><strong>Returned:</strong> {uc.returned_comment}</Alert>}
      {err && <Alert tone="danger">{err}{errs.length > 1 && <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{errs.map((e, i) => <li key={i}>{e.message}</li>)}</ul>}</Alert>}
      {msg && <Alert tone="success">{msg}</Alert>}
      <div className="split">
        <fieldset disabled={!editable} className="main stack">
          <Card title="What it is">
            <div className="stack">
              <TextField label="Use case name *" help={H.name} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={fe.name} placeholder="Résumé screening for NYC roles" />
              <SelectField label="Department *" help={H.department} value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })} options={inv.departments.map((d) => ({ value: d.id, label: d.name }))} error={fe.department_id} />
              <FieldGroup legend="AI tools used *" help={H.tools}>
                {inv.tools.length === 0 ? <p className="small muted">No tools yet. Add the tool from the inventory page first.</p> : <div className="grid-2">{inv.tools.map((t) => <Checkbox key={t.id} label={`${t.vendor} ${t.product} (${ACCOUNT_LABELS[t.account_type].toLowerCase()})`} checked={f.tool_ids.includes(t.id)} onChange={() => toggle('tool_ids', t.id)} />)}</div>}
                {fe.tool_ids && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{fe.tool_ids}</p>}
              </FieldGroup>
              <TextArea label="Purpose *" help={H.purpose} value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} placeholder="The ATS ranks applicants and recruiters review the top 20 before scheduling interviews." />
            </div>
          </Card>
          <Card title="Data and decisions">
            <div className="stack">
              <FieldGroup legend="Data entered into the tool *" help={H.data}><div className="grid-2">{DATA.map((x) => <Checkbox key={x.value} label={x.label} checked={f.data_categories.includes(x.value)} onChange={() => toggle('data_categories', x.value)} />)}</div></FieldGroup>
              <FieldGroup legend="How does the output affect people? *" help={H.impact}>
                <div className="stack-sm">{IMPACT.map((x) => <label key={x.value} className="radio-pill" style={{ justifyContent: 'flex-start' }}><input type="radio" name="impact" checked={f.decision_impact === x.value} onChange={() => setF({ ...f, decision_impact: x.value })} />{x.label}</label>)}</div>
                {fe.decision_impact && <p className="small" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{fe.decision_impact}</p>}
              </FieldGroup>
            </div>
          </Card>
          <Card title="Who uses it">
            <div className="stack">
              {usage.map((u, i) => (
                <div key={i} className="grid-2" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                  <TextField label="Role" help={H.role} value={u.role_name} onChange={(e) => setUsage(usage.map((x, j) => (j === i ? { ...x, role_name: e.target.value } : x)))} />
                  <TextField label="Headcount" help={H.headcount} inputMode="numeric" value={u.headcount} onChange={(e) => setUsage(usage.map((x, j) => (j === i ? { ...x, headcount: e.target.value } : x)))} />
                  <SelectField label="How often" help={H.frequency} value={u.frequency} onChange={(e) => setUsage(usage.map((x, j) => (j === i ? { ...x, frequency: e.target.value } : x)))} placeholder="Choose…" options={['daily', 'weekly', 'monthly', 'occasionally'].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))} />
                </div>
              ))}
              {editable && <div><Button size="sm" variant="ghost" onClick={() => setUsage([...usage, { role_name: '', headcount: '', frequency: '' }])}>Add another role</Button></div>}
              <h3 style={{ fontSize: 15, margin: '8px 0 0' }}><WithHelp help={H.namedUsers}>Named users</WithHelp> {needNamed ? <span className="small muted">· required for Tier {tier}</span> : <span className="small muted">· needed only for Tier 2 and 3</span>}</h3>
              {fe.named_users && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>{fe.named_users}</p>}
              {named.map((n, i) => (
                <div key={i} className="card" style={{ padding: 12 }}>
                  <div className="grid-2">
                    <TextField label="Name" help={H.personName} value={n.person_name} onChange={(e) => setNamed(named.map((x, j) => (j === i ? { ...x, person_name: e.target.value } : x)))} />
                    <TextField label="Work email" help={H.personEmail} type="email" value={n.email ?? ''} onChange={(e) => setNamed(named.map((x, j) => (j === i ? { ...x, email: e.target.value } : x)))} />
                    <TextField label={tier === 3 ? 'Human oversight role *' : 'Human oversight role'} help={H.oversightRole} value={n.oversight_role ?? ''} onChange={(e) => setNamed(named.map((x, j) => (j === i ? { ...x, oversight_role: e.target.value } : x)))} placeholder="Reviews the ranked list" />
                  </div>
                  {uc && n.id && (
                    <p className="small muted" style={{ margin: '6px 0 0' }}>
                      {n.has_account ? 'Has a platform account.' : n.link_sent ? 'Confirmation link sent.' : 'Link not sent yet.'}
                      {n.training_complete != null && <> Training: {n.training_complete ? 'yes' : 'no'} · Policy: {n.policy_acknowledged ? 'yes' : 'no'} · Oversight role: {n.oversight_role_confirmed ? 'confirmed' : 'not confirmed'}</>}
                    </p>
                  )}
                  {editable && <Button size="sm" variant="ghost" onClick={() => setNamed(named.filter((_, j) => j !== i))}>Remove</Button>}
                </div>
              ))}
              {editable && <div><Button size="sm" variant="ghost" onClick={() => setNamed([...named, { person_name: '', email: '', oversight_role: '' }])}>Add named user</Button></div>}
            </div>
          </Card>
          {editable && (
            <div className="row"><Button variant="primary" onClick={() => save(true)}>Submit to Department Lead</Button><Button onClick={() => save(false)}>Save draft</Button></div>
          )}
        </fieldset>
        <div className="side stack">
          <Card title="Proposed risk tier">
            <div className="stack-sm">
              <div style={{ fontSize: 20, fontWeight: 600 }}>{preview?.label ?? `Tier ${tier}`}</div>
              <p className="small" style={{ margin: 0 }}>{preview?.reason ?? uc?.tier_reason}</p>
              <p className="small muted" style={{ margin: 0 }}>The Futran auditor sets the final tier.</p>
            </div>
          </Card>
          {uc && uc.final_tier && <Card title="Final tier (Futran)"><div className="stack-sm">{tierBadge(uc.final_tier)}<p className="small" style={{ margin: 0 }}>{uc.final_tier_rationale}</p>{uc.aedt_determination && <p className="small muted" style={{ margin: 0 }}>AEDT: {AEDT.find((a) => a.value === uc.aedt_determination)?.label}</p>}</div></Card>}
          {uc && !isFutran && canReview && uc.status === 'submitted' && <ReviewCard id={uc.id} onDone={() => qc.invalidateQueries()} />}
          {uc && isFutran && canTier && uc.status !== 'draft' && uc.status !== 'returned' && <FinalTierCard uc={uc} onDone={() => qc.invalidateQueries()} />}
          {isFutran && <Link className="small" to={`/clients/${clientId}/inventory`}>Back to the inventory</Link>}
        </div>
      </div>
    </div>
  );
}

function ReviewCard({ id, onDone }: { id: string; onDone: () => void }) {
  const [comment, setComment] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function go(approve: boolean) {
    try { await api.post(`/use-cases/${id}/review`, { approve, comment }); onDone(); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card title="Department review">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <Button variant="primary" onClick={() => go(true)}>Approve</Button>
        <TextArea label="Or return with a comment" help={H.returnComment} value={comment} onChange={(e) => setComment(e.target.value)} />
        <Button onClick={() => go(false)} disabled={!comment.trim()}>Return</Button>
      </div>
    </Card>
  );
}

function FinalTierCard({ uc, onDone }: { uc: Detail; onDone: () => void }) {
  const [tier, setTier] = useState(String(uc.final_tier ?? uc.proposed_tier ?? 1));
  const [rationale, setRationale] = useState(uc.final_tier_rationale ?? '');
  const [aedt, setAedt] = useState(uc.aedt_determination ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    setErr(null); setFe({});
    try { await api.post(`/use-cases/${uc.id}/final-tier`, { tier: Number(tier), rationale, aedt_determination: aedt || null }); onDone(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Card title="Set the final tier">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Final tier" help={T.tier} value={tier} onChange={(e) => setTier(e.target.value)} options={[1, 2, 3].map((t) => ({ value: String(t), label: `Tier ${t}` }))} />
        <TextArea label="Rationale" help={T.rationale} value={rationale} onChange={(e) => setRationale(e.target.value)} error={fe.rationale} />
        <SelectField label="AEDT determination (NYC employment use)" help={T.aedt} value={aedt} onChange={(e) => setAedt(e.target.value)} placeholder="Not applicable" options={AEDT} />
        <Button variant="primary" onClick={save}>Save final tier</Button>
        <p className="small muted" style={{ margin: 0 }}>Raising the tier re-sends confirmation links to the named users.</p>
      </div>
    </Card>
  );
}
