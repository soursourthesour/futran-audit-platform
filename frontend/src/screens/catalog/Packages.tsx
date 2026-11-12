import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '@/api/client';
import { money, PRICE_LABEL, SELL_LABEL, type Package } from '@/api/catalog';
import { Alert, Badge, Button, Card, Loading, TextArea, TextField } from '@/components/ui';
import { CatalogShell, useGrid } from './CatalogShell';

type Draft = { name: string; description: string; lines: { code: string; qty: number }[] };

/** SM-14 Packages tab: the package templates the Estimator and Proposal builder start from (Futran Admin, Price List Owners). */
export function Packages() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['catalog-packages'], queryFn: () => api.get<{ items: Package[]; can_manage: boolean }>('/catalog/packages') });
  const { data: g } = useGrid(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [add, setAdd] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const items = (g?.items ?? []).filter((i) => i.sellable_status !== 'roadmap');
  function start(p: Package) {
    setEditing(p.id);
    setDraft({ name: p.name, description: p.description ?? '', lines: p.lines.map((l) => ({ code: l.code, qty: l.qty })) });
    setAdd('');
  }
  async function save(p: Package) {
    try {
      await api.put(`/catalog/packages/${p.id}`, draft);
      setEditing(null); setDraft(null);
      setMsg({ tone: 'success', text: `${draft!.name} saved.` });
      await qc.invalidateQueries({ queryKey: ['catalog-packages'] });
      await qc.invalidateQueries({ queryKey: ['catalog'] });
    } catch (e) { setMsg({ tone: 'danger', text: e instanceof ApiError && e.errors.length ? e.errors.map((x) => x.message).join(' ') : errorMessage(e) }); }
  }
  return (
    <CatalogShell tab="packages">
      <p className="muted">Packages are the starting lines for an estimate or proposal. Reps change quantities and prices for each client; the package and the master price list stay as they are.</p>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!q.data ? <Loading /> : (
        <div className="package-grid">
          {q.data.items.map((p) => {
            const isEditing = editing === p.id && draft;
            const total = p.lines.reduce((n, l) => n + (l.list_price ?? 0) * l.qty * (l.billing === 'quarterly' ? 4 : l.billing === 'monthly' ? 12 : 1), 0);
            return (
              <Card key={p.id} title={<h2>{p.name}{p.is_starter && <span className="small muted"> · starter</span>}</h2>}
                actions={q.data!.can_manage && !isEditing ? <Button size="sm" onClick={() => start(p)}>Edit</Button> : undefined}>
                {isEditing ? (
                  <div className="stack-sm">
                    <TextField label="Name" value={draft!.name} onChange={(e) => setDraft({ ...draft!, name: e.target.value })} />
                    <TextArea label="Description" rows={2} value={draft!.description} onChange={(e) => setDraft({ ...draft!, description: e.target.value })} />
                    <table className="table compact" aria-label={`Lines in ${p.name}`}>
                      <thead><tr><th>Code</th><th>Item</th><th>Qty</th><th><span className="sr-only">Remove</span></th></tr></thead>
                      <tbody>
                        {draft!.lines.map((l, i) => (
                          <tr key={l.code}>
                            <td>{l.code}</td><td>{g?.items.find((x) => x.code === l.code)?.name ?? '—'}</td>
                            <td><input aria-label={`Quantity of ${l.code}`} className="qty-input" inputMode="numeric" value={l.qty}
                              onChange={(e) => setDraft({ ...draft!, lines: draft!.lines.map((x, j) => (j === i ? { ...x, qty: Number(e.target.value) || 0 } : x)) })} /></td>
                            <td><Button size="sm" variant="ghost" aria-label={`Remove ${l.code}`} onClick={() => setDraft({ ...draft!, lines: draft!.lines.filter((_, j) => j !== i) })}>×</Button></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="row">
                      <label className="field-inline">Add item<select value={add} onChange={(e) => setAdd(e.target.value)} aria-label="Item to add to the package">
                        <option value="">Choose…</option>
                        {items.filter((i) => !draft!.lines.some((l) => l.code === i.code)).map((i) => <option key={i.code} value={i.code}>{i.code} · {i.name}</option>)}
                      </select></label>
                      <Button size="sm" disabled={!add} onClick={() => { setDraft({ ...draft!, lines: [...draft!.lines, { code: add, qty: 1 }] }); setAdd(''); }}>Add</Button>
                    </div>
                    <p className="small muted">Roadmap items can't go in a package; they are not sellable with a price.</p>
                    <div className="row"><Button variant="primary" onClick={() => save(p)}>Save package</Button><Button onClick={() => { setEditing(null); setDraft(null); }}>Cancel</Button></div>
                  </div>
                ) : (
                  <div className="stack-sm">
                    {p.description && <p className="muted">{p.description}</p>}
                    {p.lines.length === 0 ? <p className="muted small">No lines.</p> : (
                      <table className="table compact" aria-label={`Lines in ${p.name}`}>
                        <thead><tr><th>Code</th><th>Item</th><th>Qty</th><th>List</th><th>Status</th></tr></thead>
                        <tbody>{p.lines.map((l) => (
                          <tr key={l.code}>
                            <td>{l.code}</td><td>{l.name ?? '—'}</td><td>{l.qty}</td><td className="num">{money(l.list_price)}</td>
                            <td>{l.problem ? <Badge tone="danger">{l.problem}</Badge> : <span className="small">{PRICE_LABEL[l.price_status ?? ''] ?? ''} · {SELL_LABEL[l.sellable_status ?? ''] ?? ''}</span>}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    )}
                    {p.lines.length > 0 && <p className="small">Year-1 value at list: <strong>{money(total)}</strong></p>}
                    {p.updated_by && <p className="small muted">Last changed by {p.updated_by}.</p>}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </CatalogShell>
  );
}
