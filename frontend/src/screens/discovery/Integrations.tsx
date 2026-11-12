import { useRef, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useIntegrations, type ConnectorRow, type DiscoveredTool, type IntegrationsPage } from '@/api/discovery';
import { Alert, Badge, Button, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { FieldHelp } from '@/components/ui/FieldHelp';
import { integrationsHelp as H } from '@/help/discovery';
import './discovery.css';

const READS: Record<string, string> = {
  okta: 'SSO apps, OAuth apps',
  google_workspace: 'Third-party app tokens, Gemini use',
  microsoft_365: 'Copilot licences and usage',
  entra_id: 'Enterprise apps, app consents',
  expense_csv: 'Matched to the AI vendor list',
  casb_csv: 'CASB or proxy export, aggregated',
};
const STATUS_LABEL: Record<string, string> = { new: 'New', confirmed: 'In inventory', mapped: 'Mapped to tool', dismissed: 'Dismissed' };
const STATUS_TONE: Record<string, 'navy' | 'success' | 'muted' | 'warn'> = { new: 'warn', confirmed: 'success', mapped: 'success', dismissed: 'muted' };

/** A write button that cannot be pressed twice while its request runs. */
function useBusy(): [boolean, (fn: () => Promise<unknown>) => Promise<void>] {
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  return [busy, async (fn) => {
    if (running.current) return;
    running.current = true; setBusy(true);
    try { await fn(); } finally { running.current = false; setBusy(false); }
  }];
}

function connectorState(c: ConnectorRow): { tone: 'success' | 'muted' | 'danger' | 'navy'; label: string } {
  if (c.type === 'casb_csv' && c.status === 'not_connected') return { tone: 'muted', label: 'Optional' };
  if (c.status === 'connected') return { tone: 'success', label: c.type.endsWith('_csv') ? 'CSV uploaded' : 'Connected' };
  if (c.status === 'error') return { tone: 'danger', label: 'Needs attention' };
  if (c.status === 'consent_requested') return { tone: 'navy', label: 'Waiting for approval' };
  return { tone: 'muted', label: 'Not connected' };
}

/** Screen 30, Integrations and AI discovery. `/integrations` for the client (Client Admin works it, the CAICO reads it);
 *  `/clients/:clientId/integrations` is Futran's read-only view, with names for Tier 2–3 named-user checks. */
export function Integrations() {
  const { clientId } = useParams();
  const q = useIntegrations(clientId);
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(() => {
    const ok = params.get('connected'); const bad = params.get('error');
    return bad ? { tone: 'danger', text: bad } : ok ? { tone: 'success', text: 'Connected with read-only access. Run a sync to find AI tools.' } : null;
  });
  const [okta, setOkta] = useState(false);
  const [uploading, setUploading] = useState<ConnectorRow | null>(null);
  const [mapping, setMapping] = useState<DiscoveredTool | null>(null);
  const [dismissing, setDismissing] = useState<DiscoveredTool[] | null>(null);
  const [people, setPeople] = useState<DiscoveredTool | null>(null);
  const [disconnecting, setDisconnecting] = useState<ConnectorRow | null>(null);
  const [busy, guard] = useBusy();
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const focus = params.get('tool');
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['integrations'] }), qc.invalidateQueries({ queryKey: ['monitoring'] })]);
  const done = async (text: string) => { setFlash({ tone: 'success', text }); setOkta(false); setUploading(null); setMapping(null); setDismissing(null); setDisconnecting(null); await refresh(); };
  const fail = (e: unknown) => setFlash({ tone: 'danger', text: errorMessage(e) });

  const connect = (c: ConnectorRow) => guard(async () => {
    try { const r = await api.post<{ url: string }>(`/integrations/${c.type}/connect`, {}); window.location.assign(r.url); } catch (e) { fail(e); }
  });
  const sync = (c: ConnectorRow) => guard(async () => {
    try {
      const r = await api.post<{ status: string; tools_found: number; error: string | null }>(`/integrations/${c.type}/sync`);
      if (r.status === 'failed') { fail(new Error(`${c.label} sync failed: ${r.error}`)); await refresh(); } else await done(`${c.label} synced: ${r.tools_found} AI tool and department pair${r.tools_found === 1 ? '' : 's'}.`);
    } catch (e) { fail(e); }
  });
  const confirm = (rows: DiscoveredTool[]) => guard(async () => {
    try {
      if (rows.length === 1) await api.post(`/discovered-tools/${rows[0].id}/confirm`);
      else await api.post('/discovered-tools/bulk', { ids: rows.map((r) => r.id), action: 'confirm' });
      await done(rows.length === 1 ? `${rows[0].product} is in your AI inventory. ${rows[0].department_matched ? `The ${rows[0].department} compliance lead` : 'Your Chief AI Compliance Officer'} has been asked to add the use case.` : `${rows.length} tools added to your AI inventory. Department leads have been asked to add the use cases.`);
    } catch (e) { fail(e); }
  });

  const tile = (c: ConnectorRow): ReactNode => {
    const s = connectorState(c);
    const upload = c.type === 'expense_csv' || c.type === 'casb_csv';
    const available = c.type === 'okta' || upload || (c.type === 'google_workspace' ? d.credentials.google.available : d.credentials.microsoft.available);
    const help = { okta: H.okta, google_workspace: H.google, microsoft_365: H.microsoft, entra_id: H.microsoft, expense_csv: H.expense, casb_csv: H.casb }[c.type];
    const when = c.last_run ? `${c.last_run.kind === 'upload' ? 'uploaded' : 'synced'} ${fmtDate(c.last_run.at)}` : null;
    return (
      <article key={c.type} className="dsc-conn" aria-label={c.label}>
        <div className="dsc-conn-top"><strong>{c.label}</strong><Badge tone={s.tone}>{s.label}</Badge></div>
        <p className="small muted dsc-conn-reads">{READS[c.type]}{when ? ` · ${when}` : ''} <FieldHelp label={`About ${c.label}`}>{help}</FieldHelp></p>
        {c.error && <p className="small dsc-error">{c.error}</p>}
        {c.last_run?.status === 'failed' && c.last_run.error && c.last_run.error !== c.error && <p className="small dsc-error">{c.last_run.error}</p>}
        {d.can_manage && (
          <div className="row dsc-conn-actions">
            {upload ? <Button size="sm" onClick={() => setUploading(c)}>{c.status === 'connected' ? 'Upload new' : 'Upload CSV'}</Button>
              : c.status === 'connected' ? <><Button size="sm" disabled={busy} onClick={() => sync(c)}>Sync now</Button><Button size="sm" variant="ghost" onClick={() => setDisconnecting(c)}>Disconnect</Button></>
                : c.type === 'okta' ? <Button size="sm" variant="primary" onClick={() => setOkta(true)}>Connect</Button>
                  : <Button size="sm" variant="primary" disabled={busy || !available} onClick={() => connect(c)} title={available ? undefined : 'Futran IT has not set this connector up yet.'}>Connect</Button>}
          </div>
        )}
      </article>
    );
  };

  const declaredCell = (t: DiscoveredTool) => (t.declared ? <span>Yes</span> : <Badge tone={t.status === 'dismissed' ? 'muted' : 'danger'}>Undeclared</Badge>);
  const statusCell = (t: DiscoveredTool) => {
    if (t.status === 'new' && d.can_decide) {
      return <div className="row dsc-decide"><Button size="sm" variant="primary" disabled={busy} onClick={() => confirm([t])}>Confirm</Button><Button size="sm" onClick={() => setDismissing([t])}>Dismiss</Button></div>;
    }
    if (t.status === 'confirmed' || t.status === 'mapped') return <span className="stack-xs"><Badge tone="success">{t.system_reference ?? STATUS_LABEL[t.status]}</Badge>{t.matched_tool && <span className="small muted">{t.matched_tool.label}</span>}</span>;
    if (t.status === 'dismissed') return <span className="stack-xs"><Badge tone="muted">Dismissed</Badge>{t.dismiss_reason && <span className="small muted dsc-clamp">{t.dismiss_reason}</span>}</span>;
    return <Badge tone={STATUS_TONE[t.status]}>{STATUS_LABEL[t.status]}</Badge>;
  };
  const back = clientId ? [{ to: `/clients/${clientId}`, label: d.organization.name }, { label: 'AI discovery' }] : undefined;
  const undeclared = d.summary.undeclared;

  return (
    <div className="page dsc-page">
      <PageHeader title="Integrations and AI discovery" crumbs={back} subtitle={H.page} />
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      {clientId && <Alert tone="info">Read-only view of {d.organization.name}’s connectors and discovered tools. The client confirms, maps or dismisses each tool; dismissal reasons are shown below.</Alert>}
      <section aria-labelledby="dsc-conn-h" className="stack">
        <h2 id="dsc-conn-h" className="dsc-h2">Connections</h2>
        <div className="dsc-conns">{d.connectors.map(tile)}</div>
        {d.credentials.test_mode && !clientId && <p className="small muted" style={{ margin: 0 }}>Test mode: connections use the platform’s own consent page and sample data, and nothing leaves the platform.</p>}
      </section>
      <section className="card" aria-labelledby="dsc-tools-h">
        <div className="card-header dsc-tools-head">
          <h2 id="dsc-tools-h">Discovered AI tools · {d.tools.length}</h2>
          {undeclared > 0 && <span className="dsc-undeclared">{undeclared} not declared in attestation</span>}
        </div>
        <div className="card-body stack">
          {d.tools.length > 0 && !d.tools[0].attestation_exists && <Alert tone="warn">No attestation has been run yet, so every tool counts as undeclared until employees attest.</Alert>}
          <DataGrid<DiscoveredTool> label="Discovered AI tools" rows={d.tools} rowId={(t) => t.id} rowLabel={(t) => `${t.product}, ${t.department}`}
            selectable={d.can_decide} initialSort={{ key: 'declared', dir: 'asc' }}
            rowClassName={(t) => (t.id === focus ? 'dsc-focus' : undefined)}
            emptyText={d.can_manage ? 'No AI tools found yet. Connect a source or upload expense data.' : 'No AI tools found yet.'}
            search={{ label: 'Search tools', placeholder: 'Tool, vendor or department', text: (t) => `${t.product} ${t.vendor} ${t.department} ${t.category ?? ''}` }}
            filters={[
              { key: 'status', label: 'Status', options: Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label })), test: (t, v) => t.status === v },
              { key: 'declared', label: 'Declared', options: [{ value: 'yes', label: 'Declared' }, { value: 'no', label: 'Undeclared' }], test: (t, v) => t.declared === (v === 'yes') },
              { key: 'source', label: 'Source', options: d.connectors.map((c) => ({ value: c.type, label: c.label })), test: (t, v) => t.source === v },
            ]}
            columns={[
              { key: 'tool', header: 'Tool', value: (t) => t.product, render: (t) => <span className="stack-xs"><strong>{t.product}</strong><span className="small muted">{t.category ?? t.vendor}</span></span> },
              { key: 'signal', header: 'Signal', value: (t) => t.signal_label, render: (t) => <span className="small">{t.signal_label}</span> },
              { key: 'department', header: 'Department', value: (t) => t.department, render: (t) => <span>{t.department}{!t.department_matched && <span className="small muted"> (not in your department list)</span>}</span> },
              { key: 'users', header: 'Users', value: (t) => t.user_count, className: 'num' },
              { key: 'declared', header: 'Declared?', value: (t) => (t.declared ? 2 : t.status === 'dismissed' ? 1 : 0), render: declaredCell },
              { key: 'action', header: d.can_decide ? 'Action' : 'Status', value: (t) => t.status, render: statusCell, sortable: false },
            ]}
            rowActions={(t) => [
              ...(d.can_decide ? [
                { label: 'Confirm and add to inventory', disabled: t.status === 'confirmed' || t.status === 'mapped', onSelect: () => confirm([t]) },
                { label: 'Map to an inventory tool', disabled: d.ai_tools.length === 0, onSelect: () => setMapping(t) },
                { label: 'Dismiss', danger: true, disabled: t.status === 'dismissed', onSelect: () => setDismissing([t]) },
              ] : []),
              ...(d.can_view_people ? [{ label: 'Names for the named-user check', disabled: t.signal === 'traffic', onSelect: () => setPeople(t) }] : []),
            ]}
            bulkActions={d.can_decide ? [
              { label: 'Confirm', run: (rows) => confirm(rows), available: (rows) => rows.some((r) => r.status === 'new' || r.status === 'dismissed') },
              { label: 'Dismiss', danger: true, run: (rows) => setDismissing(rows) },
            ] : undefined} />
          <p className="small" style={{ margin: 0 }} id="dsc-where">
            <strong>Where confirmed tools go.</strong> Confirm adds the tool to the AI inventory as Unreviewed, with Discovery as its source and the account type the signal points to (company for single sign-on and licences, personal paid for expense claims, otherwise not known); if the inventory already has that vendor and product, the discovery is linked to that tool instead.
            {' '}It then shows in {clientId ? 'AI systems' : <Link to="/register?source=discovery">AI systems</Link>} as a tool or agent that came from Discovery, and the department’s compliance lead (or the Chief AI Compliance Officer, when no department or lead matches) is asked to add the use case.
            {' '}It is not added to the AI system register: it joins the register when the inventory is imported into it, unless the tool is marked Not approved.
            {' '}Map links the discovery to a tool already in the inventory; Dismiss adds nothing and needs a reason, which the Futran auditor sees. {H.declared}
          </p>
        </div>
      </section>
      <RunLog page={d} />
      {okta && <OktaDialog onClose={() => setOkta(false)} onDone={done} />}
      {uploading && <UploadDialog c={uploading} onClose={() => setUploading(null)} onDone={done} />}
      {mapping && <MapDialog t={mapping} tools={d.ai_tools} onClose={() => setMapping(null)} onDone={done} />}
      {dismissing && <DismissDialog rows={dismissing} onClose={() => setDismissing(null)} onDone={done} />}
      {disconnecting && <DisconnectDialog c={disconnecting} onClose={() => setDisconnecting(null)} onDone={done} />}
      {people && clientId && <PeopleDialog clientId={clientId} t={people} onClose={() => setPeople(null)} />}
      {!clientId && <p className="small muted">Your AI inventory and register in one list: <Link to="/register">AI systems</Link>. Checks that use these results: <Link to="/monitoring">Monitoring</Link>.</p>}
    </div>
  );
}

function RunLog({ page }: { page: IntegrationsPage }) {
  if (!page.runs.length) return null;
  return (
    <section className="card" aria-labelledby="dsc-runs-h">
      <div className="card-header"><h2 id="dsc-runs-h">Sync and upload log</h2></div>
      <div className="card-body">
        <DataGrid label="Sync and upload log" rows={page.runs} rowId={(r) => r.id} initialSort={{ key: 'at', dir: 'desc' }}
          columns={[
            { key: 'at', header: 'When', value: (r) => r.started_at, render: (r) => fmtDateTime(r.started_at) },
            { key: 'source', header: 'Source', value: (r) => r.connector },
            { key: 'kind', header: 'Run', value: (r) => r.kind, render: (r) => (r.kind === 'upload' ? `Upload${r.filename ? ` (${r.filename})` : ''}` : 'Sync') },
            { key: 'by', header: 'By', value: (r) => r.by },
            { key: 'result', header: 'Result', value: (r) => r.status, render: (r) => (r.status === 'failed' ? <span className="dsc-error small">{r.error ?? 'Failed'}</span> : <span className="small">{r.kind === 'upload' ? `${r.rows_matched} of ${r.rows_read} rows matched; ` : ''}{r.tools_found} tool and department pair{r.tools_found === 1 ? '' : 's'}</span>) },
          ]} />
      </div>
    </section>
  );
}

function useSubmit(onDone: (m: string) => void | Promise<void>) {
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, guard] = useBusy();
  const run = (fn: () => Promise<string>) => guard(async () => {
    setErr(null); setFe({});
    try { await onDone(await fn()); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  });
  return { err, fe, busy, run };
}

function OktaDialog({ onClose, onDone }: { onClose: () => void; onDone: (m: string) => void }) {
  const [v, setV] = useState({ domain: '', client_id: '', client_secret: '' });
  const s = useSubmit(onDone);
  return (
    <Dialog title="Connect Okta" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void s.run(async () => { await api.post('/integrations/okta/credentials', v); return 'Okta connected with read-only access. Run a sync to find AI tools.'; }); }}>
        <p className="small" style={{ margin: 0 }}>{H.okta}</p>
        {s.err && <Alert tone="danger">{s.err}</Alert>}
        <TextField label="Okta domain *" help={H.oktaDomain} value={v.domain} onChange={(e) => setV({ ...v, domain: e.target.value })} error={s.fe.domain} autoComplete="off" />
        <TextField label="Client ID *" help={H.oktaClientId} value={v.client_id} onChange={(e) => setV({ ...v, client_id: e.target.value })} error={s.fe.client_id} autoComplete="off" />
        <TextField label="Client secret *" help={H.oktaSecret} type="password" value={v.client_secret} onChange={(e) => setV({ ...v, client_secret: e.target.value })} error={s.fe.client_secret} autoComplete="new-password" />
        <div className="row"><Button type="submit" variant="primary" disabled={s.busy}>Connect</Button><Button type="button" onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

function UploadDialog({ c, onClose, onDone }: { c: ConnectorRow; onClose: () => void; onDone: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const s = useSubmit(onDone);
  return (
    <Dialog title={c.type === 'expense_csv' ? 'Upload expense data' : 'Upload network logs'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void s.run(async () => {
          if (!file) throw new Error('Choose the CSV file.');
          const form = new FormData(); form.append('file', file);
          const r = await api.upload<{ rows_read: number; rows_matched: number; tools_found: number }>(`/integrations/${c.type}/upload`, form);
          return `${file.name}: ${r.rows_read} rows read, ${r.rows_matched} matched to AI vendors, ${r.tools_found} tool and department pair${r.tools_found === 1 ? '' : 's'}. The file was not kept.`;
        });
      }}>
        <p className="small" style={{ margin: 0 }}>{c.type === 'expense_csv' ? H.expense : H.casb}</p>
        {s.err && <Alert tone="danger">{s.err}</Alert>}
        <div className="field">
          <label htmlFor="dsc-file">CSV file * <FieldHelp label="About the file">{H.file}</FieldHelp></label>
          <input id="dsc-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          {s.fe.file && <div className="field-error">{s.fe.file}</div>}
        </div>
        <div className="row"><Button type="submit" variant="primary" disabled={s.busy || !file}>Upload</Button><Button type="button" onClick={onClose}>Cancel</Button></div>
      </form>
    </Dialog>
  );
}

function MapDialog({ t, tools, onClose, onDone }: { t: DiscoveredTool; tools: { id: string; label: string }[]; onClose: () => void; onDone: (m: string) => void }) {
  const [id, setId] = useState(t.matched_tool?.id ?? '');
  const s = useSubmit(onDone);
  return (
    <Dialog title={`Map ${t.product} to an inventory tool`} onClose={onClose}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>{H.map}</p>
        {s.err && <Alert tone="danger">{s.err}</Alert>}
        <SelectField label="Inventory tool *" help={H.mapTool} placeholder="Choose a tool" options={tools.map((x) => ({ value: x.id, label: x.label }))} value={id} onChange={(e) => setId(e.target.value)} error={s.fe.ai_tool_id} />
        <div className="row"><Button variant="primary" disabled={s.busy || !id} onClick={() => s.run(async () => { await api.post(`/discovered-tools/${t.id}/map`, { ai_tool_id: id }); return `${t.product} (${t.department}) is mapped to ${tools.find((x) => x.id === id)?.label}.`; })}>Map</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DismissDialog({ rows, onClose, onDone }: { rows: DiscoveredTool[]; onClose: () => void; onDone: (m: string) => void }) {
  const [reason, setReason] = useState('');
  const s = useSubmit(onDone);
  const title = rows.length === 1 ? `Dismiss ${rows[0].product}` : `Dismiss ${rows.length} tools`;
  return (
    <Dialog title={title} onClose={onClose}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>{rows.map((r) => `${r.product} (${r.department})`).join(', ')}</p>
        {s.err && <Alert tone="danger">{s.err}</Alert>}
        <TextArea label="Reason *" help={H.reason} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} error={s.fe.reason} />
        <p className="small muted" style={{ margin: 0 }}>{H.dismiss}</p>
        <div className="row"><Button variant="danger" disabled={s.busy} onClick={() => s.run(async () => {
          if (rows.length === 1) await api.post(`/discovered-tools/${rows[0].id}/dismiss`, { reason });
          else await api.post('/discovered-tools/bulk', { ids: rows.map((r) => r.id), action: 'dismiss', reason });
          return rows.length === 1 ? `${rows[0].product} dismissed. The reason is kept for the Futran auditor.` : `${rows.length} tools dismissed.`;
        })}>Dismiss</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function DisconnectDialog({ c, onClose, onDone }: { c: ConnectorRow; onClose: () => void; onDone: (m: string) => void }) {
  const s = useSubmit(onDone);
  const ms = c.type === 'entra_id' || c.type === 'microsoft_365';
  return (
    <Dialog title={`Disconnect ${c.label}`} onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0 }}>The stored sign-in is deleted and no further syncs run. Tools already discovered stay on this page with your decisions.</p>
        {ms && <p className="small" style={{ margin: 0 }}>To withdraw the consent itself, remove the Futran discovery app under Enterprise applications in Microsoft Entra ID.</p>}
        {s.err && <Alert tone="danger">{s.err}</Alert>}
        <div className="row"><Button variant="danger" disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/integrations/${c.type}/disconnect`); return `${c.label} disconnected; the stored sign-in was deleted.`; })}>Disconnect</Button><Button onClick={onClose}>Keep it</Button></div>
      </div>
    </Dialog>
  );
}

function PeopleDialog({ clientId, t, onClose }: { clientId: string; t: DiscoveredTool; onClose: () => void }) {
  const [state, setState] = useState<{ people?: { name: string | null; email: string | null }[]; err?: string } | null>(null);
  const [busy, guard] = useBusy();
  return (
    <Dialog title={`People behind ${t.product} (${t.department})`} onClose={onClose}>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>{H.people}</p>
        {!state && <Button variant="primary" disabled={busy} onClick={() => guard(async () => {
          try { setState({ people: (await api.get<{ people: { name: string | null; email: string | null }[] }>(`/clients/${clientId}/discovered-tools/${t.id}/people`)).people }); } catch (e) { setState({ err: errorMessage(e) }); }
        })}>Show names</Button>}
        {state?.err && <Alert tone="warn">{state.err}</Alert>}
        {state?.people && (state.people.length ? <ul className="dsc-people">{state.people.map((p, i) => <li key={i}>{p.name ?? p.email}{p.name && p.email ? <span className="small muted"> · {p.email}</span> : null}</li>)}</ul> : <p className="small">No names were recorded for this tool.</p>)}
      </div>
    </Dialog>
  );
}
