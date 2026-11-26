import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import '@/styles/wsl.css';

export type WebsiteKey = {
  id: string; name: string; key_prefix: string; allowed_origins: string[]; rate_limit_per_minute: number; status: 'active' | 'revoked';
  created_at: string | null; created_by: string | null; revoked_at: string | null; revoked_by: string | null; last_used_at: string | null;
};
type KeyList = { keys: WebsiteKey[]; default_rate_limit_per_minute: number };

const BASE = '/api/public/v1/library';

/** Administration > Website API keys `/admin/website-keys`. The Futran Admin creates the keys Futran's website uses to
 *  read the law library and the AI litigation tracker (published records only), copies each key once, and revokes it. */
export function WebsiteKeys() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['website-keys'], queryFn: () => api.get<KeyList>('/admin/website-keys') });
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['website-keys'] });
  async function revoke(rows: WebsiteKey[]) {
    setFlash(null);
    try {
      await Promise.all(rows.map((k) => api.post(`/admin/website-keys/${k.id}/revoke`)));
      await refresh();
      setFlash({ tone: 'success', text: rows.length === 1 ? `${rows[0].name} revoked. The website gets 401 with this key from now on.` : `${rows.length} keys revoked.` });
    } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  }
  return (
    <div className="page">
      <PageHeader title="Website API keys"
        subtitle="Keys for Futran's website to show the law library and the AI litigation tracker. The website sees published records only: no client, staff or sales information."
        actions={<Button variant="primary" onClick={() => setAdding(true)}>New website key</Button>} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <Card title="Keys">
        <p className="small muted" style={{ marginTop: 0 }}>The website calls <code>{BASE}</code> with the header <code>X-API-Key</code>. Keep the key on the website's server. A key with no allowed origins works from servers only; list an origin only for a key that must be used from the browser, where anyone can read it.</p>
        {d.keys.length === 0 ? <EmptyState>No website keys yet.</EmptyState> : (
          <DataGrid label="Website API keys" rows={d.keys} rowId={(k) => k.id} rowLabel={(k) => k.name}
            columns={[
              { key: 'name', header: 'Name', value: (k) => k.name, render: (k) => <><strong>{k.name}</strong><div className="small muted"><code>{k.key_prefix}…</code></div></> },
              { key: 'origins', header: 'Allowed origins', value: (k) => k.allowed_origins.join(' '), render: (k) => (k.allowed_origins.length ? <div className="wsl-chips">{k.allowed_origins.map((o) => <Badge key={o}>{o}</Badge>)}</div> : <span className="muted">Server only</span>) },
              { key: 'rate', header: 'Calls a minute', value: (k) => k.rate_limit_per_minute },
              { key: 'created', header: 'Created', value: (k) => k.created_at ?? '', render: (k) => <span className="small">{fmtDateTime(k.created_at)}{k.created_by && <div className="muted">{k.created_by}</div>}</span> },
              { key: 'used', header: 'Last used', value: (k) => k.last_used_at ?? '', render: (k) => (k.last_used_at ? fmtDateTime(k.last_used_at) : <span className="muted">Never</span>) },
              { key: 'status', header: 'Status', value: (k) => k.status, render: (k) => (k.status === 'active' ? <Badge tone="success">Active</Badge>
                : <><Badge tone="muted">Revoked</Badge><div className="small muted">{fmtDateTime(k.revoked_at)}{k.revoked_by ? ` by ${k.revoked_by}` : ''}</div></>) },
            ]}
            filters={[{ key: 'status', label: 'Status', options: [{ value: 'active', label: 'Active' }, { value: 'revoked', label: 'Revoked' }], test: (k, v) => k.status === v }]}
            search={{ label: 'Search keys', text: (k) => `${k.name} ${k.key_prefix} ${k.allowed_origins.join(' ')}` }}
            selectable
            bulkActions={[{ label: 'Revoke', danger: true, available: (rows) => rows.every((k) => k.status === 'active'),
              confirm: (rows) => `Revoke ${rows.length} key${rows.length === 1 ? '' : 's'}? The website stops getting data with ${rows.length === 1 ? 'it' : 'them'} at once.`, run: revoke }]}
            rowActions={(k) => (k.status === 'active' ? [{ label: 'Revoke', danger: true, onSelect: () => revoke([k]) }] : [])}
          />
        )}
      </Card>
      {adding && <NewKeyDialog defaultRate={d.default_rate_limit_per_minute} onClose={() => setAdding(false)}
        onCreated={(name, key) => { setAdding(false); refresh(); setCreated({ name, key }); }} />}
      {created && <KeyOnce {...created} onClose={() => setCreated(null)} />}
    </div>
  );
}

function NewKeyDialog({ defaultRate, onClose, onCreated }: { defaultRate: number; onClose: () => void; onCreated: (name: string, key: string) => void }) {
  const [f, setF] = useState({ name: '', origins: '', rate: String(defaultRate) });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setErrs({});
    try {
      const origins = f.origins.split(/[\s,]+/).map((o) => o.trim()).filter(Boolean);
      const r = await api.post<{ website_key: WebsiteKey; key: string }>('/admin/website-keys', { name: f.name, allowed_origins: origins, rate_limit_per_minute: Number(f.rate) || defaultRate });
      onCreated(r.website_key.name, r.key);
    } catch (e) { setErrs(fieldErrors(e)); setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Dialog title="New website key" onClose={onClose}>
      <div className="stack">
        <TextField label="Name *" hint="Which website or environment uses it, such as Futran website (production)." value={f.name} error={errs.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <TextArea label="Allowed origins" rows={3} hint="One per line, such as https://www.futransolutions.com. Leave empty for a key used from the website's server only (recommended)." value={f.origins} error={errs.allowed_origins} onChange={(e) => setF({ ...f, origins: e.target.value })} />
        <TextField label="Calls a minute" type="number" min={1} max={1200} value={f.rate} error={errs.rate_limit_per_minute} onChange={(e) => setF({ ...f, rate: e.target.value })} />
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy || !f.name.trim()} onClick={save}>{busy ? 'Creating…' : 'Create key'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function KeyOnce({ name, key, onClose }: { name: string; key: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog title={`Website key ${name} created`} onClose={onClose}>
      <div className="stack">
        <Alert tone="warn">This is the only time the key is shown. Copy it now and give it to the website team through your password manager.</Alert>
        <div className="wsl-secret"><code aria-label="Website API key">{key}</code><Button onClick={async () => { try { await navigator.clipboard.writeText(key); setCopied(true); } catch { setCopied(false); } }}>{copied ? 'Copied' : 'Copy'}</Button></div>
        <p className="small muted" style={{ margin: 0 }}>Send it as <code>X-API-Key: {key.slice(0, 12)}…</code> from the website's server. If the key is lost or exposed, revoke it and create a new one.</p>
        <div><Button variant="primary" onClick={onClose}>I have saved it</Button></div>
      </div>
    </Dialog>
  );
}
