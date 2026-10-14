import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, ButtonLink, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';

export type Tool = { id: string; vendor: string; product: string; plan: string | null; account_type: string; sso: boolean | null; training_on_inputs: string; retention_terms: string | null; approval_status: string; source: string; declared_count: number | null };
export type UseCaseRow = { id: string; name: string; department_id: string; department: string | null; status: string; tools: string[]; tool_ids: string[]; proposed_tier: number | null; final_tier: number | null; final_tier_rationale: string | null; aedt_determination: string | null; returned_comment: string | null };
export type InventoryData = { tools: Tool[]; use_cases: UseCaseRow[]; tiers: Record<string, number>; departments: { id: string; name: string }[]; is_futran: boolean };

export const ACCOUNT_LABELS: Record<string, string> = { enterprise: 'Company (enterprise)', team: 'Company (team plan)', personal_paid: 'Personal, paid', personal_free: 'Personal, free', unknown: 'Not known' };
export const STATUS_LABELS: Record<string, { label: string; tone: 'muted' | 'navy' | 'success' | 'warn' }> = { draft: { label: 'Draft', tone: 'muted' }, submitted: { label: 'Submitted', tone: 'navy' }, dept_approved: { label: 'Dept approved', tone: 'success' }, returned: { label: 'Returned', tone: 'warn' } };

export function useInventory(clientId: string) {
  return useQuery({ queryKey: ['inventory', clientId], queryFn: () => api.get<InventoryData>(`/clients/${clientId}/inventory`), enabled: !!clientId });
}

export function tierBadge(t: number | null) {
  if (!t) return <span className="muted">—</span>;
  return <Badge tone={t === 3 ? 'danger' : t === 2 ? 'warn' : 'muted'}>Tier {t}</Badge>;
}

export function Inventory() {
  const { data: me } = useMe();
  return <InventoryView clientId={me?.organization.id ?? ''} />;
}

export function FutranInventory() {
  const { clientId = '' } = useParams();
  return <InventoryView clientId={clientId} />;
}

function InventoryView({ clientId }: { clientId: string }) {
  const q = useInventory(clientId);
  const [addingTool, setAddingTool] = useState(false);
  if (q.isLoading || !q.data) return <div className="page"><Loading /></div>;
  const d = q.data;
  const base = d.is_futran ? `/clients/${clientId}/inventory` : '/inventory';
  return (
    <div className="page">
      <PageHeader title="AI inventory" subtitle="Every AI tool in use and what people use it for. The proposed tier is calculated from the answers; Futran sets the final tier."
        actions={!d.is_futran ? <><Button onClick={() => setAddingTool(true)}>Add tool</Button><ButtonLink to="/inventory/new" variant="primary">Add use case</ButtonLink></> : undefined} />
      <div className="split">
        <div className="main">
          <Card title={`Use cases · ${d.use_cases.length}`} actions={<span className="small muted">Tier 3: {d.tiers['3'] ?? 0} · Tier 2: {d.tiers['2'] ?? 0} · Tier 1: {d.tiers['1'] ?? 0}</span>}>
            {d.use_cases.length === 0 ? <EmptyState>No use cases yet.{!d.is_futran && ' Add one for each way your team uses an AI tool.'}</EmptyState> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Use case</th><th>Department</th><th>Tool · account</th><th>Proposed</th><th>Final</th><th>Status</th></tr></thead>
                <tbody>{d.use_cases.map((u) => (
                  <tr key={u.id}>
                    <td><Link to={`${base}/${u.id}`}><strong>{u.name}</strong></Link>{u.returned_comment && u.status === 'returned' && <div className="small" style={{ color: 'var(--warn)' }}>{u.returned_comment}</div>}</td>
                    <td>{u.department}</td><td className="small">{u.tools.join(', ')}</td>
                    <td>{tierBadge(u.proposed_tier)}</td><td>{tierBadge(u.final_tier)}</td>
                    <td><Badge tone={STATUS_LABELS[u.status]?.tone ?? 'muted'}>{STATUS_LABELS[u.status]?.label ?? u.status}</Badge></td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
        </div>
        <div className="side">
          <Card title={`Tools · ${d.tools.length}`}>
            {d.tools.length === 0 ? <EmptyState>Tools appear here from the attestation answers, or add them yourself.</EmptyState> : (
              <ul className="small" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {d.tools.map((t) => (
                  <li key={t.id} style={{ padding: '8px 0', borderTop: '1px solid var(--line-soft)' }}>
                    <strong>{t.vendor} {t.product}</strong>
                    <div className="muted">{ACCOUNT_LABELS[t.account_type]}{t.declared_count ? ` · declared by ${t.declared_count}` : ''}{t.training_on_inputs === 'unknown' ? ' · training on inputs not known' : ''}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
      {addingTool && <AddTool clientId={clientId} onClose={() => setAddingTool(false)} />}
    </div>
  );
}

function AddTool({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ vendor: '', product: '', plan: '', account_type: 'enterprise', training_on_inputs: 'unknown', retention_terms: '' });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save(e: FormEvent) {
    e.preventDefault();
    try { await api.post(`/clients/${clientId}/tools`, f); await qc.invalidateQueries({ queryKey: ['inventory', clientId] }); onClose(); } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  return (
    <Dialog title="Add an AI tool" onClose={onClose}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="grid-2">
          <TextField label="Vendor" value={f.vendor} onChange={(e) => setF({ ...f, vendor: e.target.value })} error={fe.vendor} placeholder="Workday" />
          <TextField label="Product" value={f.product} onChange={(e) => setF({ ...f, product: e.target.value })} error={fe.product} placeholder="Recruiting AI" />
        </div>
        <SelectField label="Account type" value={f.account_type} onChange={(e) => setF({ ...f, account_type: e.target.value })} options={Object.entries(ACCOUNT_LABELS).map(([value, label]) => ({ value, label }))} />
        <SelectField label="Does the vendor train its models on what you enter?" value={f.training_on_inputs} onChange={(e) => setF({ ...f, training_on_inputs: e.target.value })} options={[{ value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }, { value: 'unknown', label: 'Not known' }]} />
        <TextField label="Plan" value={f.plan} onChange={(e) => setF({ ...f, plan: e.target.value })} />
        <TextArea label="Data retention terms" value={f.retention_terms} onChange={(e) => setF({ ...f, retention_terms: e.target.value })} />
        <div className="row"><Button type="submit" variant="primary">Add tool</Button><Button onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}
