import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { systemHelp as S, vendorHelp as V } from '@/help/fieldwork';

type Person = { id: string; name: string } | null;
export type SystemRow = {
  id: string; reference_id: string; name: string; version: string | null; built_by: string | null; built_by_label: string; vendor_id: string | null; vendor: string | null;
  department_id: string | null; department: string | null; owner: Person; technical_owner: Person; use_cases: { id: string; name: string; tier: number | null }[];
  tools: { id: string; label: string }[]; assessment_depth: 'full' | 'light'; status: string; completion_pct: number; methodology_version: string | null; source: string;
  inherent: number | null; maturity: number | null; residual: number | null; rating: string | null; knockouts: string[];
  register_system: { id: string; reference: string; name: string } | null;
};
type RegisterOption = { id: string; reference: string; name: string; type_label: string; sourcing_label: string; stage_label: string; risk_tier: number | null; built_by: string | null; vendor_id: string | null; department_id: string | null; owner_user_id: string | null; linked_to: string | null };
type VendorRow = { id: string; legal_name: string; capability: string | null; personal_data_processed: boolean | null; baa_dpa_signed: boolean | null; last_risk_review: string | null; risk_level: 'H' | 'M' | 'L' | null };
type Request = { id: string; payload: Record<string, unknown>; reason: string; status: string; requested_by: Person; requested_at: string };
type Register = {
  client: { id: string; name: string }; audit_ref: string; stage: number; systems: SystemRow[]; unmapped_tier3: { id: string; name: string }[];
  use_case_options: { id: string; name: string; tier: number | null }[]; tool_options: { id: string; label: string }[]; vendors: VendorRow[];
  departments: { id: string; name: string }[]; people: { id: string; name: string }[]; pending_requests: Request[]; can_manage: boolean; can_approve_additions: boolean;
  register_options: RegisterOption[];
};

const BUILT_BY = [{ value: 'in_house', label: 'In-house' }, { value: 'vendor', label: 'Vendor' }, { value: 'open_source_customized', label: 'Open source (customized)' }, { value: 'hybrid', label: 'Hybrid' }];
const RATING_TONE: Record<string, 'danger' | 'warn' | 'navy' | 'muted'> = { Critical: 'danger', High: 'danger', Medium: 'warn', Low: 'muted' };
const yesNo = (v: boolean | null) => (v === null ? 'Not known' : v ? 'Yes' : 'No');

export function SystemsRegister() {
  const { clientId = '' } = useParams();
  const q = useQuery({ queryKey: ['systems', clientId], queryFn: () => api.get<Register>(`/clients/${clientId}/systems`) });
  const [adding, setAdding] = useState<string[] | null>(null);
  const [editing, setEditing] = useState<SystemRow | null>(null);
  const [vendor, setVendor] = useState<VendorRow | 'new' | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const full = d.systems.filter((s) => s.assessment_depth === 'full').length;
  const byBuild = BUILT_BY.map((b) => [b.label.toLowerCase(), d.systems.filter((s) => s.built_by === b.value).length] as const).filter(([, n]) => n);
  const rated = d.systems.filter((s) => s.rating);
  const order = ['Critical', 'High', 'Medium', 'Low'];
  const top = rated.sort((a, b) => order.indexOf(a.rating!) - order.indexOf(b.rating!))[0];
  const completion = d.systems.length ? Math.round(d.systems.reduce((n, s) => n + s.completion_pct, 0) / d.systems.length) : 0;
  return (
    <div className="page">
      <PageHeader title="AI systems in scope" crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client.name} · ${d.audit_ref}` }, { label: 'AI systems' }]}
        subtitle="Template §3–9 per system. Tier 3 use cases get a full assessment and Tier 2 a light one (§3, §5, §7.2, §9). The engagement rating follows the highest system rating."
        actions={<><Link to={`/clients/${clientId}/assessment`} className="btn">§4 governance questions</Link>{d.can_manage && <Button variant="primary" onClick={() => setAdding([])}>Add system</Button>}</>} />
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="grid-tiles" style={{ margin: '16px 0 24px' }}>
        <div className="tile"><div className="label">Systems in scope</div><div className="value">{d.systems.length}</div><div className="hint">{full} full · {d.systems.length - full} light</div></div>
        <div className="tile"><div className="label">Built by</div><div className="value" style={{ fontSize: 20 }}>{byBuild.length ? byBuild.map(([l, n]) => `${n} ${l}`).join(' · ') : '—'}</div><div className="hint">{d.systems.filter((s) => !s.built_by).length ? `${d.systems.filter((s) => !s.built_by).length} not set yet` : ' '}</div></div>
        <div className="tile"><div className="label">Engagement rating so far</div><div className="value">{top?.rating ?? '—'}</div><div className="hint">{top ? `from ${top.name}` : 'no system scored yet'}</div></div>
        <div className="tile"><div className="label">Assessment completion</div><div className="value">{completion}%</div><div className="hint">average across systems</div></div>
      </div>
      {d.unmapped_tier3.length > 0 && (
        <Alert tone="warn">
          <div className="row" style={{ justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div><strong>{d.unmapped_tier3.length === 1 ? '1 Tier 3 use case is' : `${d.unmapped_tier3.length} Tier 3 use cases are`} not mapped to a system</strong>
              <div className="small">{d.unmapped_tier3.map((u) => u.name).join(', ')}. Every Tier 3 use case needs a full assessment.</div></div>
            {d.can_manage && <Button size="sm" onClick={() => setAdding(d.unmapped_tier3.map((u) => u.id))}>Map use case</Button>}
          </div>
        </Alert>
      )}
      {d.pending_requests.length > 0 && <PendingRequests clientId={clientId} d={d} onDone={setFlash} />}
      <Card title="Systems">
        {d.systems.length === 0 ? <EmptyState>No systems yet. Add one for each Tier 3 use case, and for the Tier 2 use cases you select.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>System</th><th>Built by</th><th>Depth</th><th>Complete</th><th>Inherent</th><th>Maturity</th><th>Residual · rating</th><th>Knock-outs</th></tr></thead>
            <tbody>{d.systems.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/systems/${s.id}/assess`}><strong>{s.name}</strong></Link>
                  {d.can_manage && <> <button type="button" className="linklike small" onClick={() => setEditing(s)}>Edit</button></>}
                  <div className="small muted">{[s.reference_id, s.department, s.use_cases.some((u) => u.tier === 3) ? 'from Tier 3 use case' : s.source === 'wizard' ? 'listed at initiation' : null, s.register_system ? `client register ${s.register_system.reference}` : null].filter(Boolean).join(' · ')}</div>
                </td>
                <td>{s.built_by ? s.built_by_label : <span className="muted">Not set</span>}{s.vendor && <div className="small muted">{s.vendor}</div>}</td>
                <td><Badge tone={s.assessment_depth === 'full' ? 'navy' : 'muted'}>{s.assessment_depth === 'full' ? 'Full' : 'Light'}</Badge></td>
                <td>{s.completion_pct}%</td>
                <td>{s.inherent ?? '—'}</td>
                <td>{s.maturity ?? '—'}</td>
                <td>{s.rating ? <><span>{Math.round(s.residual ?? 0)} · </span><Badge tone={RATING_TONE[s.rating] ?? 'muted'}>{s.rating}</Badge></> : <span className="muted">Scoring pending</span>}</td>
                <td className="small">{s.knockouts.length ? s.knockouts.join(', ') : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      <div style={{ height: 24 }} />
      <Card title="AI vendor register (§9.1)" actions={d.can_manage ? <Button size="sm" onClick={() => setVendor('new')}>Add vendor</Button> : undefined}>
        {d.vendors.length === 0 ? <EmptyState>No vendors yet.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Vendor</th><th>Capability</th><th>Personal data</th><th>BAA / DPA signed</th><th>Last risk review</th><th>Risk</th></tr></thead>
            <tbody>{d.vendors.map((v) => (
              <tr key={v.id}>
                <td>{d.can_manage ? <button type="button" className="linklike" onClick={() => setVendor(v)}><strong>{v.legal_name}</strong></button> : <strong>{v.legal_name}</strong>}</td>
                <td className="small">{v.capability ?? '—'}</td><td>{yesNo(v.personal_data_processed)}</td><td>{yesNo(v.baa_dpa_signed)}</td>
                <td>{v.last_risk_review ? fmtDate(v.last_risk_review) : '—'}</td>
                <td>{v.risk_level ? <Badge tone={v.risk_level === 'H' ? 'danger' : v.risk_level === 'M' ? 'warn' : 'muted'}>{{ H: 'High', M: 'Medium', L: 'Low' }[v.risk_level]}</Badge> : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      {adding && <AddSystem clientId={clientId} d={d} preselected={adding} onClose={() => setAdding(null)} onDone={(m) => { setAdding(null); setFlash(m); }} />}
      {editing && <EditSystem clientId={clientId} d={d} s={editing} onClose={() => setEditing(null)} />}
      {vendor && <VendorDialog clientId={clientId} v={vendor === 'new' ? null : vendor} onClose={() => setVendor(null)} />}
    </div>
  );
}

function UseCasePicker({ d, value, onChange }: { d: Register; value: string[]; onChange: (v: string[]) => void }) {
  if (!d.use_case_options.length) return <p className="small muted" style={{ margin: 0 }}>No Tier 2 or Tier 3 use cases in the inventory yet.</p>;
  return (
    <FieldGroup legend="Use cases this system covers" help={S.useCases}>
      <div className="stack-sm">{d.use_case_options.map((u) => (
        <Checkbox key={u.id} label={<>{u.name} <span className="muted small">Tier {u.tier}</span></>} checked={value.includes(u.id)} onChange={(e) => onChange(e.target.checked ? [...value, u.id] : value.filter((x) => x !== u.id))} />
      ))}</div>
    </FieldGroup>
  );
}

function AddSystem({ clientId, d, preselected, onClose, onDone }: { clientId: string; d: Register; preselected: string[]; onClose: () => void; onDone: (m: string) => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: '', built_by: '', vendor_id: '', register_system_id: '', use_case_ids: preselected, reason: preselected.length ? 'Tier 3 use case found in discovery.' : '' });
  const regOpts = (d.register_options ?? []).filter((o) => !o.linked_to);
  function pickRegister(id: string) {
    const o = d.register_options.find((x) => x.id === id);
    setF({ ...f, register_system_id: id, ...(o ? { name: o.name, built_by: o.built_by ?? f.built_by, vendor_id: o.vendor_id ?? f.vendor_id, reason: f.reason || `In the client's AI system register as ${o.reference}.` } : {}) });
  }
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post(`/clients/${clientId}/systems`, { ...f, vendor_id: f.vendor_id || null, built_by: f.built_by || null, register_system_id: f.register_system_id || null });
      await qc.invalidateQueries({ queryKey: ['systems', clientId] });
      onDone('Sent to the Engagement Manager for approval. The system appears here once approved.');
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title="Add a system to the scope" onClose={onClose} wide>
      <form className="stack" onSubmit={save} noValidate>
        <p className="small muted" style={{ margin: 0 }}>Adding a system after initiation needs the Engagement Manager's approval (template §1.3).</p>
        {err && <Alert tone="danger">{err}</Alert>}
        {regOpts.length > 0 && (
          <SelectField label="Start from the client's AI system register" help="Copies the system's name, who built it, vendor, department and owner from the client's register, and links the two so its bias tests and history show on the assessment." value={f.register_system_id} placeholder="Not from the register" onChange={(e) => pickRegister(e.target.value)}
            options={regOpts.map((o) => ({ value: o.id, label: `${o.reference} · ${o.name} · ${o.type_label} · ${o.stage_label}${o.risk_tier ? ` · Tier ${o.risk_tier}` : ''}` }))} error={fe.register_system_id} />
        )}
        <UseCasePicker d={d} value={f.use_case_ids} onChange={(v) => setF({ ...f, use_case_ids: v })} />
        {fe.use_case_ids && <div className="small" style={{ color: "var(--danger)" }}>{fe.use_case_ids}</div>}
        <TextField label="System name" help={S.name} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={fe.name} />
        <div className="grid-2">
          <SelectField label="Built by" help={S.builtBy} value={f.built_by} placeholder="Choose" onChange={(e) => setF({ ...f, built_by: e.target.value })} options={BUILT_BY} error={fe.built_by} />
          <SelectField label="Vendor" help={S.vendor} value={f.vendor_id} placeholder="None" onChange={(e) => setF({ ...f, vendor_id: e.target.value })} options={d.vendors.map((v) => ({ value: v.id, label: v.legal_name }))} error={fe.vendor_id} />
        </div>
        <TextArea label="Reason for adding it" help={S.reason} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} error={fe.reason} />
        <div className="row"><Button type="submit" variant="primary">Send for approval</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

function EditSystem({ clientId, d, s, onClose }: { clientId: string; d: Register; s: SystemRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    name: s.name, version: s.version ?? '', built_by: s.built_by ?? '', vendor_id: s.vendor_id ?? '', department_id: s.department_id ?? '', owner_user_id: s.owner?.id ?? '',
    technical_owner_user_id: s.technical_owner?.id ?? '', use_case_ids: s.use_cases.map((u) => u.id), tool_ids: s.tools.map((t) => t.id), assessment_depth: s.assessment_depth,
  });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const people = d.people.map((p) => ({ value: p.id, label: p.name }));
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const body = { ...f, built_by: f.built_by || null, vendor_id: f.vendor_id || null, department_id: f.department_id || null, owner_user_id: f.owner_user_id || null, technical_owner_user_id: f.technical_owner_user_id || null };
      await api.patch(`/systems/${s.id}`, body);
      await qc.invalidateQueries({ queryKey: ['systems', clientId] });
      onClose();
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title={`${s.reference_id} · ${s.name}`} onClose={onClose} wide>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="System name" help={S.name} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} error={fe.name} />
          <TextField label="Version" help={S.version} value={f.version} onChange={(e) => setF({ ...f, version: e.target.value })} error={fe.version} />
          <SelectField label="Built by" help={S.builtBy} value={f.built_by} placeholder="Not set" onChange={(e) => setF({ ...f, built_by: e.target.value })} options={BUILT_BY} error={fe.built_by} />
          <SelectField label="Vendor" help={S.vendor} value={f.vendor_id} placeholder="None" onChange={(e) => setF({ ...f, vendor_id: e.target.value })} options={d.vendors.map((v) => ({ value: v.id, label: v.legal_name }))} error={fe.vendor_id} />
          <SelectField label="Department" help={S.department} value={f.department_id} placeholder="Not set" onChange={(e) => setF({ ...f, department_id: e.target.value })} options={d.departments.map((x) => ({ value: x.id, label: x.name }))} error={fe.department_id} />
          <SelectField label="Assessment depth" help={S.depth} value={f.assessment_depth} onChange={(e) => setF({ ...f, assessment_depth: e.target.value as 'full' | 'light' })} options={[{ value: 'full', label: 'Full (§3–9)' }, { value: 'light', label: 'Light (§3, §5, §7.2, §9)' }]} />
          <SelectField label="Business owner" help={S.owner} value={f.owner_user_id} placeholder="Not set" onChange={(e) => setF({ ...f, owner_user_id: e.target.value })} options={people} error={fe.owner_user_id} />
          <SelectField label="Technical owner" help={S.technicalOwner} value={f.technical_owner_user_id} placeholder="Not set" onChange={(e) => setF({ ...f, technical_owner_user_id: e.target.value })} options={people} error={fe.technical_owner_user_id} />
        </div>
        <UseCasePicker d={d} value={f.use_case_ids} onChange={(v) => setF({ ...f, use_case_ids: v })} />
        {fe.use_case_ids && <div className="small" style={{ color: "var(--danger)" }}>{fe.use_case_ids}</div>}
        {d.tool_options.length > 0 && (
          <FieldGroup legend="Tools" help={S.tools}><div className="stack-sm">{d.tool_options.map((t) => (
            <Checkbox key={t.id} label={t.label} checked={f.tool_ids.includes(t.id)} onChange={(e) => setF({ ...f, tool_ids: e.target.checked ? [...f.tool_ids, t.id] : f.tool_ids.filter((x) => x !== t.id) })} />
          ))}</div></FieldGroup>
        )}
        <div className="row"><Button type="submit" variant="primary">Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

function PendingRequests({ clientId, d, onDone }: { clientId: string; d: Register; onDone: (m: string) => void }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const ucName = (id: string) => d.use_case_options.find((u) => u.id === id)?.name ?? 'use case';
  async function decide(id: string, approve: boolean) {
    setErr(null);
    try {
      await api.post(`/system-requests/${id}/decide`, { approve, comment: comment[id] ?? '' });
      await qc.invalidateQueries({ queryKey: ['systems', clientId] });
      onDone(approve ? 'System added to the scope.' : 'Request declined. The auditor has been told.');
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card title="Scope additions awaiting approval" className="stack">
      {err && <Alert tone="danger">{err}</Alert>}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {d.pending_requests.map((r) => {
          const ids = (r.payload.use_case_ids as string[] | undefined) ?? [];
          const name = (r.payload.name as string) || ids.map(ucName).join(', ');
          return (
            <li key={r.id} style={{ padding: '10px 0', borderTop: '1px solid var(--line-soft)' }} className="stack-sm">
              <div><strong>{name}</strong> <span className="small muted">requested by {r.requested_by?.name} on {fmtDate(r.requested_at)}</span></div>
              <div className="small">{r.reason}</div>
              {d.can_approve_additions ? (
                <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 220 }}><TextField label="Comment (needed to decline)" help={S.declineComment} value={comment[r.id] ?? ''} onChange={(e) => setComment({ ...comment, [r.id]: e.target.value })} /></div>
                  <Button variant="primary" onClick={() => decide(r.id, true)}>Approve</Button><Button onClick={() => decide(r.id, false)}>Decline</Button>
                </div>
              ) : <div className="small muted">Waiting for the Engagement Manager.</div>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function VendorDialog({ clientId, v, onClose }: { clientId: string; v: VendorRow | null; onClose: () => void }) {
  const qc = useQueryClient();
  const tri = (b: boolean | null) => (b === null ? '' : b ? 'yes' : 'no');
  const [f, setF] = useState({ legal_name: v?.legal_name ?? '', capability: v?.capability ?? '', personal_data_processed: tri(v?.personal_data_processed ?? null), baa_dpa_signed: tri(v?.baa_dpa_signed ?? null), last_risk_review: v?.last_risk_review ?? '', risk_level: v?.risk_level ?? '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const toBool = (s: string) => (s === '' ? null : s === 'yes');
  const yn = [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }];
  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { ...f, personal_data_processed: toBool(f.personal_data_processed), baa_dpa_signed: toBool(f.baa_dpa_signed), last_risk_review: f.last_risk_review || null, risk_level: f.risk_level || null };
    try {
      if (v) await api.patch(`/vendors/${v.id}`, body); else await api.post(`/clients/${clientId}/vendors`, body);
      await qc.invalidateQueries({ queryKey: ['systems', clientId] });
      onClose();
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title={v ? v.legal_name : 'Add a vendor'} onClose={onClose}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Legal name" help={V.legalName} value={f.legal_name} onChange={(e) => setF({ ...f, legal_name: e.target.value })} error={fe.legal_name} />
        <TextField label="AI capability supplied" help={V.capability} value={f.capability} onChange={(e) => setF({ ...f, capability: e.target.value })} error={fe.capability} />
        <div className="grid-2">
          <SelectField label="Processes personal data" help={V.personalData} value={f.personal_data_processed} placeholder="Not known" onChange={(e) => setF({ ...f, personal_data_processed: e.target.value })} options={yn} />
          <SelectField label="BAA or DPA signed" help={V.agreement} value={f.baa_dpa_signed} placeholder="Not known" onChange={(e) => setF({ ...f, baa_dpa_signed: e.target.value })} options={yn} />
          <TextField label="Last risk review" help={V.lastReview} type="date" value={f.last_risk_review} onChange={(e) => setF({ ...f, last_risk_review: e.target.value })} error={fe.last_risk_review} />
          <SelectField label="Risk level" help={V.riskLevel} value={f.risk_level} placeholder="Not assessed" onChange={(e) => setF({ ...f, risk_level: e.target.value })} options={[{ value: 'H', label: 'High' }, { value: 'M', label: 'Medium' }, { value: 'L', label: 'Low' }]} error={fe.risk_level} />
        </div>
        <div className="row"><Button type="submit" variant="primary">Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}
