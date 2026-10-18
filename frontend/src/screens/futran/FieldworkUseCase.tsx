import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate } from '@/components/ui';

export type FindingRow = {
  id: string; ref: string; title: string; severity: string; status: string; description: string | null; recommended_remediation: string | null; control_refs: string[];
  use_case_ids: string[]; use_cases: string[]; ai_system_id: string | null; system: string | null; null_compliance_flag: boolean; author: string | null; author_id?: string | null; review_comment?: string | null;
  template_section: string | null; proposed_owner: string | null; approved_by: string | null;
};
type EvidenceReq = { id: string; ref: string; description: string; status: string; due_date: string; answer: string | null; owner: string | null; files: { id: string; filename: string }[]; overdue: boolean; waived_reason?: string | null };
type View = {
  use_case: { id: string; name: string; department: string | null; purpose: string | null; data_categories: string[]; decision_impact: string | null; proposed_tier: number | null; final_tier: number | null; final_tier_rationale: string | null; aedt_determination: string | null; status: string; submitted_by: string | null };
  named_users: { count: number; not_trained: number; unconfirmed: number }; systems: { id: string; reference_id: string; name: string }[];
  evidence_requests: EvidenceReq[]; findings: FindingRow[];
  null_compliance: { applies: boolean; message: string | null; systems: string[]; suggested_finding: Partial<FindingRow> | null };
  control_options: string[]; client_id: string; audit_ref: string; stage: number;
};

export const SEVERITIES = [{ value: 'critical', label: 'Critical' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }, { value: 'observation', label: 'Observation' }];
export const SEV_TONE: Record<string, 'danger' | 'warn' | 'navy' | 'muted'> = { critical: 'danger', high: 'danger', medium: 'warn', low: 'navy', observation: 'muted' };
const ER_TONE: Record<string, 'warn' | 'success' | 'muted'> = { outstanding: 'warn', received: 'success', answered: 'success', waived: 'muted' };
const DATA: Record<string, string> = { pii: 'Personal information', phi: 'Health information', client: 'Client data', confidential: 'Confidential business data', none: 'No sensitive data' };

/** Screen 16: the auditor's fieldwork on one use case. */
export function FieldworkUseCase() {
  const { useCaseId = '' } = useParams();
  const key = ['fieldwork', useCaseId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<View>(`/use-cases/${useCaseId}/fieldwork`) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [asking, setAsking] = useState(false);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const u = d.use_case;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  return (
    <div className="page">
      <PageHeader title={u.name} crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${d.client_id}`, label: d.audit_ref }, { to: `/clients/${d.client_id}/inventory`, label: 'AI inventory' }, { label: u.name }]}
        subtitle={`${u.department ?? ''} · stage ${d.stage} fieldwork${d.systems.length ? ` · ${d.systems.map((s) => s.reference_id).join(', ')}` : ''}`}
        actions={u.proposed_tier ? <Badge tone={u.proposed_tier === 3 ? 'danger' : 'warn'}>Client proposed Tier {u.proposed_tier}</Badge> : undefined} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <FinalTier useCaseId={useCaseId} u={u} onDone={(t) => { setMsg({ tone: 'success', text: t }); refresh(); }} />
          <Card title="Evidence requests" actions={<Button size="sm" onClick={() => setAsking(true)}>Request evidence</Button>}>
            {d.evidence_requests.length === 0 ? <p className="small muted" style={{ margin: 0 }}>Nothing requested yet.</p> : (
              <ul className="list-rows">
                {d.evidence_requests.map((r) => (
                  <li key={r.id}>
                    <div><span className="small muted">{r.ref}</span> {r.description}{r.answer && <div className="small muted">Answer: {r.answer}</div>}{r.files.length > 0 && <div className="small">{r.files.map((f) => <a key={f.id} href={fileUrl(f.id)} style={{ marginRight: 8 }}>{f.filename}</a>)}</div>}</div>
                    <span className="small" style={{ whiteSpace: 'nowrap', color: r.overdue ? 'var(--danger)' : undefined }}><Badge tone={ER_TONE[r.status]}>{r.status === 'outstanding' ? `Outstanding · due ${fmtDate(r.due_date)}` : r.status === 'received' ? `Received · ${r.files.length} file${r.files.length === 1 ? '' : 's'}` : r.status[0].toUpperCase() + r.status.slice(1)}</Badge></span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {d.findings.length > 0 && (
            <Card title="Findings for this use case">
              <ul className="list-rows">{d.findings.map((f) => <li key={f.id}><span><strong>{f.ref}</strong> {f.title}</span><span><Badge tone={SEV_TONE[f.severity]}>{f.severity}</Badge> <span className="small muted">{f.status}</span></span></li>)}</ul>
            </Card>
          )}
          <FindingForm clientId={d.client_id} controls={d.control_options} initial={{ use_case_ids: [u.id], ai_system_id: d.systems[0]?.id ?? null }} key={JSON.stringify(d.null_compliance.suggested_finding)} onDone={(t) => { setMsg({ tone: 'success', text: t }); refresh(); }} prefill={null} />
        </div>
        <div className="side stack">
          {d.null_compliance.applies && (
            <div className="card nc-panel">
              <div className="small" style={{ fontWeight: 600 }}>Data sufficiency check</div>
              <h3 style={{ margin: '2px 0 6px' }}>Null-compliance risk</h3>
              <p className="small" style={{ margin: 0 }}>{d.null_compliance.message}</p>
              {d.null_compliance.suggested_finding && <NcDraft clientId={d.client_id} draft={d.null_compliance.suggested_finding} onDone={(t) => { setMsg({ tone: 'success', text: t }); refresh(); }} />}
            </div>
          )}
          <Card title="From the client's inventory">
            <dl className="kv-stacked">
              <dt>Purpose</dt><dd>{u.purpose ?? '—'}</dd>
              <dt>Data</dt><dd>{u.data_categories.map((c) => DATA[c] ?? c).join(', ') || '—'}</dd>
              <dt>Named users</dt><dd>{d.named_users.count} {d.named_users.count === 1 ? 'person' : 'people'}{d.named_users.not_trained ? ` · ${d.named_users.not_trained} not trained` : ''}{d.named_users.unconfirmed ? ` · ${d.named_users.unconfirmed} not confirmed` : ''}</dd>
              <dt>Submitted by</dt><dd>{u.submitted_by ?? '—'}{u.status === 'dept_approved' ? ' · approved by Department Lead' : ''}</dd>
            </dl>
            {d.systems.map((s) => <p key={s.id} className="small" style={{ marginBottom: 0 }}><Link to={`/systems/${s.id}/assess`}>{s.reference_id} {s.name}: assessment</Link></p>)}
          </Card>
        </div>
      </div>
      {asking && <RequestEvidence useCaseId={useCaseId} onClose={() => setAsking(false)} onDone={() => { setAsking(false); setMsg({ tone: 'success', text: 'Request sent to the client.' }); refresh(); }} />}
    </div>
  );
}

function FinalTier({ useCaseId, u, onDone }: { useCaseId: string; u: View['use_case']; onDone: (t: string) => void }) {
  const [tier, setTier] = useState(String(u.final_tier ?? u.proposed_tier ?? ''));
  const [aedt, setAedt] = useState(u.aedt_determination ?? '');
  const [rationale, setRationale] = useState(u.final_tier_rationale ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    setErr(null); setFe({});
    try { await api.post(`/use-cases/${useCaseId}/final-tier`, { tier: Number(tier), rationale, aedt_determination: aedt || null }); onDone('Final tier saved.'); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Card title="Final risk tier">
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <SelectField label="Tier set by auditor" value={tier} placeholder="Choose" onChange={(e) => setTier(e.target.value)} options={[{ value: '3', label: 'Tier 3 · High-risk' }, { value: '2', label: 'Tier 2 · Elevated' }, { value: '1', label: 'Tier 1 · Baseline' }]} error={fe.tier} />
          <SelectField label="LL144 AEDT determination" value={aedt} placeholder="Not assessed" onChange={(e) => setAedt(e.target.value)} options={[{ value: 'in_scope', label: 'AEDT: in scope' }, { value: 'out_of_scope', label: 'Not an AEDT' }, { value: 'undetermined', label: 'Undetermined' }]} error={fe.aedt_determination} />
        </div>
        <TextArea label="Rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} error={fe.rationale} />
        <div><Button onClick={save}>Save final tier</Button></div>
      </div>
    </Card>
  );
}

function RequestEvidence({ useCaseId, onClose, onDone }: { useCaseId: string; onClose: () => void; onDone: () => void }) {
  const [description, setDescription] = useState('');
  const [due, setDue] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    try { await api.post(`/use-cases/${useCaseId}/evidence-requests`, { description, due_date: due }); onDone(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title="Request evidence" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label="What you need" value={description} onChange={(e) => setDescription(e.target.value)} error={fe.description} />
        <TextField label="Due date" type="date" value={due} onChange={(e) => setDue(e.target.value)} error={fe.due_date} />
        <p className="small muted" style={{ margin: 0 }}>Sent to the use case's Department Lead (or the Chief AI Compliance Officer), with a reminder 3 days before it is due.</p>
        <div className="row"><Button variant="primary" onClick={save}>Send request</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function NcDraft({ clientId, draft, onDone }: { clientId: string; draft: Partial<FindingRow>; onDone: (t: string) => void }) {
  const [err, setErr] = useState<string | null>(null);
  async function create() {
    try { const f = await api.post<FindingRow>(`/clients/${clientId}/findings`, draft); onDone(`Draft finding ${f.ref} created. Review it, then submit it.`); } catch (e) { setErr(errorMessage(e)); }
  }
  return <div style={{ marginTop: 10 }}>{err && <Alert tone="danger">{err}</Alert>}<Button size="sm" onClick={create}>Create draft finding</Button></div>;
}

export function FindingForm({ clientId, controls, initial, prefill, onDone, existing }: { clientId: string; controls: string[]; initial: Partial<FindingRow>; prefill: Partial<FindingRow> | null; onDone: (t: string) => void; existing?: FindingRow }) {
  const src = existing ?? prefill ?? {};
  const [f, setF] = useState({ title: src.title ?? '', severity: src.severity ?? 'medium', control: (src.control_refs ?? [])[0] ?? '', description: src.description ?? '', recommended_remediation: src.recommended_remediation ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save(submit: boolean) {
    setErr(null); setFe({});
    const body = { ...initial, title: f.title, severity: f.severity, control_refs: f.control ? [f.control] : [], description: f.description, recommended_remediation: f.recommended_remediation };
    try {
      const out = existing ? await api.patch<FindingRow>(`/findings/${existing.id}`, body) : await api.post<FindingRow>(`/clients/${clientId}/findings`, body);
      if (submit) await api.post(`/findings/${out.id}/submit`);
      if (!existing) setF({ title: '', severity: 'medium', control: '', description: '', recommended_remediation: '' });
      onDone(submit ? `${out.ref} submitted for approval.` : `${out.ref} saved as a draft.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Card title={existing ? `${existing.ref} · edit finding` : 'Draft finding'}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {existing?.review_comment && <Alert tone="warn">Returned: {existing.review_comment}</Alert>}
        <TextField label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} error={fe.title} />
        <div className="grid-2">
          <SelectField label="Severity" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} options={SEVERITIES} error={fe.severity} />
          <SelectField label="Control reference" value={f.control} placeholder="None" onChange={(e) => setF({ ...f, control: e.target.value })} options={[...new Set([...(f.control ? [f.control] : []), ...controls])].map((c) => ({ value: c, label: c }))} />
        </div>
        <TextArea label="Description (condition, criteria, cause, effect)" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        <TextArea label="Recommended action" value={f.recommended_remediation} onChange={(e) => setF({ ...f, recommended_remediation: e.target.value })} />
        <div className="row" style={{ gap: 8 }}><Button variant="primary" onClick={() => save(true)}>Submit to Chief Auditor</Button><Button onClick={() => save(false)}>Save draft</Button></div>
      </div>
    </Card>
  );
}
