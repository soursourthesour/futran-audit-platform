import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useApiAdmin, type ApiClientRow, type Delivery, type WebhookRow } from '@/api/wsl';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, TextField, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { apiHelp as H } from '@/help/wsl';
import '@/styles/wsl.css';

const DTONE: Record<string, 'success' | 'warn' | 'danger' | 'muted' | 'navy'> = { delivered: 'success', pending: 'navy', retrying: 'warn', failed: 'danger', blocked: 'danger' };
const DLABEL: Record<string, string> = { delivered: 'Delivered', pending: 'Waiting', retrying: 'Retrying', failed: 'Failed', blocked: 'Blocked' };

/** Admin > API and webhooks `/admin/api` (spec §21 F17). The Client Admin creates API clients and webhooks for the
 *  organization's GRC tools; the CAICO reads. Secrets are shown once. */
export function ApiAdmin() {
  const q = useApiAdmin();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [addingHook, setAddingHook] = useState(false);
  const [secret, setSecret] = useState<{ title: string; label: string; value: string; note: string } | null>(null);
  const [log, setLog] = useState<WebhookRow | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['api-admin'] });
  const act = async (fn: () => Promise<unknown>, ok: string) => { setFlash(null); try { await fn(); await refresh(); setFlash({ tone: 'success', text: ok }); } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); } };
  const rotate = (c: ApiClientRow) => act(async () => {
    const r = await api.post<{ client_secret: string }>(`/admin/api/clients/${c.id}/rotate-secret`);
    setSecret({ title: `New secret for ${c.name}`, label: 'Client secret', value: r.client_secret, note: `${H.secret} Tokens issued with the old secret stop working now.` });
  }, `New secret issued for ${c.name}.`);
  const rotateHook = (h: WebhookRow) => act(async () => {
    const r = await api.post<{ signing_secret: string }>(`/admin/api/webhooks/${h.id}/rotate-secret`);
    setSecret({ title: 'New signing secret', label: 'Signing secret', value: r.signing_secret, note: H.signing });
  }, 'New signing secret issued.');
  return (
    <div className="page">
      <PageHeader title="API and webhooks" subtitle="Connect your GRC tools (ServiceNow, Archer and others) to the platform. API clients read and write your AI inventory, findings and remediation; webhooks tell your tools when something changes."
        actions={<Link className="btn" to="/admin/api/reference">API reference</Link>} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      <Card title="API clients" actions={d.can_manage ? <Button variant="primary" onClick={() => setAdding(true)}>New API client</Button> : undefined}>
        <p className="small muted" style={{ marginTop: 0 }}>Get a token with OAuth 2.0 client credentials at <code>{d.token_url}</code>, then call <code>{d.base_url}</code> with <code>Authorization: Bearer &lt;token&gt;</code>. Tokens last one hour. Every call is in your audit log.</p>
        {d.clients.length === 0 ? <EmptyState>No API clients yet.</EmptyState> : (
          <DataGrid label="API clients" rows={d.clients} rowId={(c) => c.id} rowLabel={(c) => c.name}
            columns={[
              { key: 'name', header: 'Name', value: (c) => c.name, render: (c) => <><strong>{c.name}</strong><div className="small muted"><code>{c.client_id}</code> · secret ends {c.secret_hint}</div></> },
              { key: 'scopes', header: 'Scopes', value: (c) => c.scopes.join(' '), render: (c) => <div className="wsl-chips">{c.scopes.map((s) => <Badge key={s}>{s}</Badge>)}</div> },
              { key: 'rate', header: 'Calls a minute', value: (c) => c.rate_limit_per_minute },
              { key: 'used', header: 'Last used', value: (c) => c.last_used_at ?? '', render: (c) => (c.last_used_at ? fmtDateTime(c.last_used_at) : <span className="muted">Never</span>) },
              { key: 'status', header: 'Status', value: (c) => c.status, render: (c) => <Badge tone={c.status === 'active' ? 'success' : 'muted'}>{c.status === 'active' ? 'Active' : 'Revoked'}</Badge> },
            ]}
            filters={[{ key: 'status', label: 'Status', options: [{ value: 'active', label: 'Active' }, { value: 'revoked', label: 'Revoked' }], test: (c, v) => c.status === v }]}
            search={{ label: 'Search API clients', text: (c) => `${c.name} ${c.client_id}` }}
            selectable={d.can_manage}
            bulkActions={d.can_manage ? [{ label: 'Revoke', danger: true, available: (rows) => rows.every((c) => c.status === 'active'), confirm: (rows) => `Revoke ${rows.length} API client${rows.length === 1 ? '' : 's'}? Their tokens stop working at once.`,
              run: (rows) => act(() => Promise.all(rows.map((c) => api.post(`/admin/api/clients/${c.id}/revoke`))), `${rows.length} revoked.`) }] : undefined}
            rowActions={d.can_manage ? (c) => (c.status === 'active' ? [
              { label: 'Issue a new secret', onSelect: () => rotate(c) },
              { label: 'Revoke', danger: true, onSelect: () => act(() => api.post(`/admin/api/clients/${c.id}/revoke`), `${c.name} revoked.`) },
            ] : []) : undefined}
          />
        )}
      </Card>
      <Card title="Webhooks" actions={d.can_manage ? <Button variant="primary" onClick={() => setAddingHook(true)}>Add webhook</Button> : undefined}>
        <p className="small muted" style={{ marginTop: 0 }}>{H.signing}</p>
        {d.webhooks.length === 0 ? <EmptyState>No webhooks yet.</EmptyState> : (
          <DataGrid label="Webhooks" rows={d.webhooks} rowId={(h) => h.id} rowLabel={(h) => h.url}
            columns={[
              { key: 'url', header: 'Address', value: (h) => h.url, render: (h) => <><span style={{ overflowWrap: 'anywhere' }}>{h.url}</span>{h.description && <div className="small muted">{h.description}</div>}</> },
              { key: 'events', header: 'Events', value: (h) => h.events.join(' '), render: (h) => <div className="wsl-chips">{h.events.map((e) => <Badge key={e}>{e}</Badge>)}</div> },
              { key: 'last', header: 'Last delivery', value: (h) => h.last_delivery?.created_at ?? '', render: (h) => (h.last_delivery ? <><Badge tone={DTONE[h.last_delivery.status]}>{DLABEL[h.last_delivery.status]}</Badge> <span className="small muted">{h.last_delivery.event} · {fmtDateTime(h.last_delivery.created_at)}</span></> : <span className="muted">None yet</span>) },
              { key: 'status', header: 'Status', value: (h) => h.status, render: (h) => <Badge tone={h.status === 'active' ? 'success' : 'muted'}>{h.status === 'active' ? 'Active' : 'Paused'}</Badge> },
            ]}
            rowActions={(h) => [
              { label: 'Delivery log', onSelect: () => setLog(h) },
              ...(d.can_manage ? [
                { label: 'Send a test delivery', onSelect: () => act(async () => { const r = await api.post<Delivery>(`/admin/api/webhooks/${h.id}/test`); if (r.status !== 'delivered') throw new Error(r.last_error ?? 'The test delivery failed.'); }, 'Test delivery sent.') },
                { label: h.status === 'active' ? 'Pause' : 'Resume', onSelect: () => act(() => api.patch(`/admin/api/webhooks/${h.id}`, { status: h.status === 'active' ? 'paused' : 'active' }), h.status === 'active' ? 'Webhook paused.' : 'Webhook resumed.') },
                { label: 'Issue a new signing secret', onSelect: () => rotateHook(h) },
                { label: 'Remove', danger: true, onSelect: () => act(() => api.post(`/admin/api/webhooks/${h.id}/remove`), 'Webhook removed.') },
              ] : []),
            ]}
          />
        )}
      </Card>
      {adding && <NewClientDialog scopes={d.scopes} onClose={() => setAdding(false)} onCreated={(name, value) => { setAdding(false); refresh(); setSecret({ title: `API client ${name} created`, label: 'Client secret', value, note: H.secret }); }} />}
      {addingHook && <NewHookDialog events={d.events} onClose={() => setAddingHook(false)} onCreated={(value) => { setAddingHook(false); refresh(); setSecret({ title: 'Webhook added', label: 'Signing secret', value, note: H.signing }); }} />}
      {secret && <SecretDialog {...secret} onClose={() => setSecret(null)} />}
      {log && <DeliveryLog hook={log} onClose={() => setLog(null)} />}
    </div>
  );
}

function SecretDialog({ title, label, value, note, onClose }: { title: string; label: string; value: string; note: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog title={title} onClose={onClose}>
      <div className="stack">
        <Alert tone="warn">This is the only time the {label.toLowerCase()} is shown.</Alert>
        <div className="wsl-secret"><code aria-label={label}>{value}</code><Button onClick={async () => { try { await navigator.clipboard.writeText(value); setCopied(true); } catch { setCopied(false); } }}>{copied ? 'Copied' : 'Copy'}</Button></div>
        <p className="small muted" style={{ margin: 0 }}>{note}</p>
        <div><Button variant="primary" onClick={onClose}>I have saved it</Button></div>
      </div>
    </Dialog>
  );
}

function NewClientDialog({ scopes, onClose, onCreated }: { scopes: { code: string; label: string }[]; onClose: () => void; onCreated: (name: string, secret: string) => void }) {
  const [name, setName] = useState('');
  const [chosen, setChosen] = useState<string[]>([]);
  const [rate, setRate] = useState('60');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    try {
      const r = await api.post<{ client: ApiClientRow; client_secret: string }>('/admin/api/clients', { name, scopes: chosen, rate_limit_per_minute: Number(rate) || 60 });
      onCreated(r.client.name, r.client_secret);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Dialog title="New API client" onClose={onClose} wide>
      <div className="stack">
        <TextField label="Name *" help={H.name} value={name} onChange={(e) => setName(e.target.value)} error={fe.name} maxLength={120} />
        <FieldGroup legend="Scopes *" help={H.scopes}>
          <div className="wsl-scopes">{scopes.map((s) => <Checkbox key={s.code} label={<><code>{s.code}</code> <span className="small muted">{s.label}</span></>} checked={chosen.includes(s.code)} onChange={(e) => setChosen(e.target.checked ? [...chosen, s.code] : chosen.filter((x) => x !== s.code))} />)}</div>
          {fe.scopes && <span className="error">{fe.scopes}</span>}
        </FieldGroup>
        <TextField label="Calls a minute" help={H.rate} type="number" min={1} max={600} value={rate} onChange={(e) => setRate(e.target.value)} error={fe.rate_limit_per_minute} />
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy || !name.trim() || chosen.length === 0} onClick={save}>{busy ? 'Creating…' : 'Create and show secret'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function NewHookDialog({ events, onClose, onCreated }: { events: { code: string; label: string }[]; onClose: () => void; onCreated: (secret: string) => void }) {
  const [url, setUrl] = useState('https://');
  const [chosen, setChosen] = useState<string[]>(events.map((e) => e.code));
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    try {
      const r = await api.post<{ signing_secret: string }>('/admin/api/webhooks', { url, events: chosen, description });
      onCreated(r.signing_secret);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Dialog title="Add webhook" onClose={onClose} wide>
      <div className="stack">
        <TextField label="Address *" help={H.url} type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} error={fe.url} />
        <TextField label="Description" help="What receives these events, for example the ServiceNow integration hub." value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
        <FieldGroup legend="Events *" help={H.events}>
          {events.map((e) => <Checkbox key={e.code} label={<><code>{e.code}</code> <span className="small muted">{e.label}</span></>} checked={chosen.includes(e.code)} onChange={(x) => setChosen(x.target.checked ? [...chosen, e.code] : chosen.filter((c) => c !== e.code))} />)}
          {fe.events && <span className="error">{fe.events}</span>}
        </FieldGroup>
        {err && !fe.url && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy || chosen.length === 0} onClick={save}>{busy ? 'Adding…' : 'Add and show signing secret'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DeliveryLog({ hook, onClose }: { hook: WebhookRow; onClose: () => void }) {
  const q = useQuery({ queryKey: ['webhook-log', hook.id], queryFn: () => api.get<{ rows: Delivery[] }>(`/admin/api/webhooks/${hook.id}/deliveries`) });
  const rows = q.data?.rows ?? null;
  const err = q.error ? errorMessage(q.error) : null;
  return (
    <Dialog title="Delivery log" onClose={onClose} large>
      <div className="stack">
        <p className="small muted" style={{ margin: 0, overflowWrap: 'anywhere' }}>{hook.url}</p>
        {err && <Alert tone="danger">{err}</Alert>}
        {rows === null && !err ? <Loading /> : rows && rows.length === 0 ? <EmptyState>No deliveries yet.</EmptyState> : rows && (
          <DataGrid label="Deliveries" rows={rows} rowId={(r) => r.id}
            columns={[
              { key: 'at', header: 'Created', value: (r) => r.created_at, render: (r) => fmtDateTime(r.created_at) },
              { key: 'event', header: 'Event', value: (r) => r.event },
              { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <Badge tone={DTONE[r.status]}>{DLABEL[r.status]}</Badge> },
              { key: 'tries', header: 'Attempts', value: (r) => r.attempts },
              { key: 'code', header: 'Response', value: (r) => r.last_status_code ?? '', render: (r) => r.last_status_code ?? '—' },
              { key: 'detail', header: 'Detail', value: (r) => r.last_error ?? '', render: (r) => r.last_error ?? (r.next_attempt_at ? `Next try ${fmtDateTime(r.next_attempt_at)}` : r.delivered_at ? `Delivered ${fmtDateTime(r.delivered_at)}` : '—') },
            ]}
            filters={[{ key: 'status', label: 'Status', options: Object.entries(DLABEL).map(([value, label]) => ({ value, label })), test: (r, v) => r.status === v }]}
          />
        )}
      </div>
    </Dialog>
  );
}
