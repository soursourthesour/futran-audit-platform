import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, EmptyState, FieldHelp, Loading, SelectField, TextField, fmtDateTime } from '@/components/ui';

/* 11-03 C12: the AI model list behind the register's "Model or algorithm" field. Kept by the Futran Admin; the
   monthly check proposes additions (AI connected) or reminds the admin to review. Nothing changes without a person. */

type Model = { id: string; name: string; active: boolean; origin: string };
type Vendor = { id: string; code: string; name: string; active: boolean; source_url: string | null; models: Model[] };
type Proposal = { id: string; vendor_name: string; model_name: string; reason: string | null; source_url: string | null; created_at: string };
type Page = { vendors: Vendor[]; proposals: Proposal[]; last_check: { at: string; mode: string; proposals: number; error: string | null } | null };

const MODE: Record<string, string> = { ai: 'AI check', reminder: 'Reminder only (no AI connected)', failed: 'AI check failed', manual: 'Run by hand' };

export function ModelCatalogue({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['admin-model-catalogue'], queryFn: () => api.get<Page>('/admin/model-catalogue') });
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [vendorName, setVendorName] = useState('');
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState('');
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin-model-catalogue'] });
  async function act(fn: () => Promise<unknown>, ok: string) {
    if (busy) return;
    setBusy(true); setFlash(null);
    try { await fn(); await refresh(); setFlash({ tone: 'success', text: ok }); } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const p = q.data;
  const shown = filter ? p.vendors.filter((v) => v.id === filter) : p.vendors;
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>
        The vendors and models offered in a client's AI system register under Model or algorithm. A client can still choose Other; what it types is kept for that client only.
        Once a month the platform checks the list: with an AI provider connected it proposes additions for you to accept or reject; without one it reminds you to review the list.
        Nothing changes here until a person accepts it.
      </p>
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <Card title="Proposed additions" actions={canEdit ? <Button size="sm" disabled={busy} onClick={() => act(() => api.post('/admin/model-catalogue/check'), 'The check has run.')}>Check now</Button> : undefined}>
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>
            {p.last_check ? <>Last check {fmtDateTime(p.last_check.at)}: {MODE[p.last_check.mode] ?? p.last_check.mode}{p.last_check.mode === 'ai' ? `, ${p.last_check.proposals} proposed` : ''}{p.last_check.error ? ` (${p.last_check.error})` : ''}.</> : 'No check has run yet. The first runs with the daily jobs at the start of next month.'}
          </p>
          {p.proposals.length === 0 ? <EmptyState>Nothing waiting for a decision.</EmptyState> : (
            <ul className="mc-list" aria-label="Proposed additions">
              {p.proposals.map((x) => (
                <li key={x.id}>
                  <div className="mc-text"><strong>{x.model_name}</strong> <span className="small muted">· {x.vendor_name}</span>
                    {x.reason && <div className="small">{x.reason}</div>}
                    {x.source_url && <div className="small"><a href={x.source_url} target="_blank" rel="noreferrer">Source</a></div>}
                  </div>
                  {canEdit && <div className="row mc-act">
                    <Button size="sm" variant="primary" disabled={busy} aria-label={`Accept ${x.model_name}`} onClick={() => act(() => api.post(`/admin/model-catalogue/proposals/${x.id}/decide`, { accept: true }), `${x.model_name} was added.`)}>Accept</Button>
                    <Button size="sm" variant="ghost" disabled={busy} aria-label={`Reject ${x.model_name}`} onClick={() => act(() => api.post(`/admin/model-catalogue/proposals/${x.id}/decide`, { accept: false }), `${x.model_name} was not added.`)}>Reject</Button>
                  </div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
      <Card title="Vendors and models">
        <div className="stack">
          <div className="grid-2">
            <SelectField label="Show" value={filter} placeholder="All vendors" onChange={(e) => setFilter(e.target.value)} options={p.vendors.map((v) => ({ value: v.id, label: v.name }))} />
            {canEdit && (
              <form className="mc-add" onSubmit={(e) => { e.preventDefault(); if (vendorName.trim()) void act(async () => { await api.post('/admin/model-catalogue/vendors', { name: vendorName }); setVendorName(''); }, `${vendorName.trim()} was added.`); }}>
                <TextField label="Add a vendor" value={vendorName} onChange={(e) => setVendorName(e.target.value)} placeholder="Vendor name" />
                <Button type="submit" disabled={busy || !vendorName.trim()}>Add</Button>
              </form>
            )}
          </div>
          {shown.map((v) => (
            <section key={v.id} className="mc-vendor" aria-label={v.name}>
              <div className="mc-head">
                <h3>{v.name}{!v.active && <> <Badge tone="muted">Not offered</Badge></>}</h3>
                <span className="small muted">Saved as {v.code}{v.source_url && <> · <a href={v.source_url} target="_blank" rel="noreferrer">Vendor's model list</a></>}</span>
                {canEdit && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.patch(`/admin/model-catalogue/vendors/${v.id}`, { active: !v.active }), v.active ? `${v.name} is no longer offered.` : `${v.name} is offered again.`)}>{v.active ? 'Stop offering' : 'Offer again'}</Button>}
              </div>
              <ul className="mc-models">
                {v.models.map((m) => (
                  <li key={m.id} className={m.active ? '' : 'mc-off'}>
                    <span>{m.name}{m.origin === 'proposal' && <span className="small muted"> · added from a proposal</span>}{!m.active && <span className="small muted"> · not offered</span>}</span>
                    {canEdit && <button type="button" className="linklike small" disabled={busy} aria-label={`${m.active ? 'Stop offering' : 'Offer again'} ${m.name}`}
                      onClick={() => act(() => api.patch(`/admin/model-catalogue/models/${m.id}`, { active: !m.active }), m.active ? `${m.name} is no longer offered.` : `${m.name} is offered again.`)}>{m.active ? 'Stop offering' : 'Offer again'}</button>}
                  </li>
                ))}
              </ul>
              {canEdit && (
                <form className="mc-add" onSubmit={(e) => { e.preventDefault(); const name = (adding[v.id] ?? '').trim(); if (name) void act(async () => { await api.post('/admin/model-catalogue/models', { vendor_id: v.id, name }); setAdding((x) => ({ ...x, [v.id]: '' })); }, `${name} was added to ${v.name}.`); }}>
                  <TextField label={`Add a model to ${v.name}`} value={adding[v.id] ?? ''} onChange={(e) => setAdding((x) => ({ ...x, [v.id]: e.target.value }))} placeholder="Model name as the vendor gives it" />
                  <Button type="submit" disabled={busy || !(adding[v.id] ?? '').trim()}>Add</Button>
                  <FieldHelp label={`Add a model to ${v.name}`}>Use the name on the vendor's own model list. A model that is no longer sold can be marked Stop offering; systems that use it keep it.</FieldHelp>
                </form>
              )}
            </section>
          ))}
        </div>
      </Card>
      <style>{`
        .mc-list, .mc-models { list-style: none; margin: 0; padding: 0; }
        .mc-list li { display: flex; gap: 12px; align-items: center; justify-content: space-between; padding: 10px 0; border-top: 1px solid var(--line-soft); }
        .mc-list li:first-child { border-top: 0; }
        .mc-text { min-width: 0; overflow-wrap: anywhere; }
        .mc-act { flex: none; gap: 6px; }
        .mc-vendor { border-top: 1px solid var(--line-soft); padding-top: 14px; }
        .mc-head { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; }
        .mc-head h3 { margin: 0; font-size: 16px; }
        .mc-models { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 0 16px; margin: 8px 0; }
        .mc-models li { display: flex; justify-content: space-between; gap: 8px; align-items: center; min-height: 44px; border-bottom: 1px dashed var(--line-soft); }
        .mc-models li .linklike { min-height: 44px; }
        .mc-off { color: var(--muted); }
        .mc-add { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; }
        .mc-add .field { flex: 1 1 220px; margin: 0; }
        @media (max-width: 600px) { .mc-list li { flex-direction: column; align-items: stretch; } .mc-act .btn { flex: 1 1 auto; } }
      `}</style>
    </div>
  );
}
