import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, Loading, SelectField, TextField, fmtDateTime } from '@/components/ui';
import './aiConnection.css';

/* 11-03 F1: Platform settings › AI provider. One connection for the whole platform; only the Futran Admin changes it.
   The API key is sent once and never comes back: the server returns only its last four characters. */

type Provider = { id: string; label: string; needs_endpoint: boolean; models: string[]; key_help: string };
type Active = { source: 'connection' | 'environment' | 'demonstration' | null; provider: string | null; provider_label: string | null; model: string | null };
type Conn = {
  connected: boolean; provider: string | null; provider_label: string | null; model: string | null; endpoint: string | null; deployment: string | null;
  key_hint: string | null; key_unreadable: boolean; updated_at: string | null; last_test: { at: string; ok: boolean; message: string } | null;
  active: Active; demo_mode: boolean; stand_in: boolean; providers: Provider[]; can_manage: boolean;
};

const KEY = ['admin-ai-connection'];

const HELP = {
  provider: (
    <>
      The service every AI feature calls: law and case refresh, Draft with AI, the copilot, obligation extraction, customer questionnaires and
      Explain this question. One connection serves the whole platform. With nothing saved, the platform uses ANTHROPIC_API_KEY from the server's
      .env file if it is set, and otherwise (in test mode) its built-in demonstration model.
    </>
  ),
  model: 'The model name exactly as the provider writes it. The suggestions were current in November 2026; any newer name the provider offers works.',
  azureModel: 'The model behind the deployment, for the AI log. Leave blank to record the deployment name.',
  endpoint: 'The resource endpoint from the Azure portal (Keys and Endpoint), for example https://your-resource.openai.azure.com.',
  deployment: 'The deployment name in Azure AI Foundry. Requests go to this deployment.',
  key: (
    <>
      Stored encrypted on the server and never shown again; only its last four characters are kept as a reminder. The audit log records changes
      to the connection without the key. Leave blank to keep the saved key; a different provider needs its own key.
    </>
  ),
};

function inUse(a: Active): string {
  if (a.source === 'connection') return `${a.provider_label} · ${a.model} (saved below)`;
  if (a.source === 'environment') return `${a.provider_label} · ${a.model} (ANTHROPIC_API_KEY in the server's .env file)`;
  if (a.source === 'demonstration') return 'The built-in demonstration model (no AI provider connected)';
  return 'None. AI features are off until a provider is connected.';
}

export function AIConnection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => api.get<Conn>('/admin/ai-connection') });
  const c = q.data;
  const [provider, setProvider] = useState('anthropic');
  const [model, setModel] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [deployment, setDeployment] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => {
    if (!c) return;
    setProvider(c.provider ?? 'anthropic');
    setModel(c.model ?? '');
    setEndpoint(c.endpoint ?? '');
    setDeployment(c.deployment ?? '');
    setApiKey('');
  }, [c?.provider, c?.model, c?.endpoint, c?.deployment, c?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const changed = (d: Conn) => { qc.setQueryData(KEY, d); qc.invalidateQueries({ queryKey: ['admin-settings'] }); };
  const save = useMutation({
    mutationFn: () => api.put<Conn>('/admin/ai-connection', { provider, model, api_key: apiKey || null, endpoint: endpoint || null, deployment: deployment || null }),
    onSuccess: (d) => { changed(d); setErrs({}); setMsg({ tone: 'success', text: `Saved. AI features now use ${d.provider_label} (${d.model}). Test the connection to check the key.` }); },
    onError: (e) => { setErrs(fieldErrors(e)); setMsg({ tone: 'danger', text: errorMessage(e) }); },
  });
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string; connection: Conn }>('/admin/ai-connection/test', {}),
    onSuccess: (r) => { changed(r.connection); setMsg({ tone: r.ok ? 'success' : 'danger', text: r.message }); },
    onError: (e) => setMsg({ tone: 'danger', text: errorMessage(e) }),
  });
  const remove = useMutation({
    mutationFn: () => api.delete<Conn>('/admin/ai-connection'),
    onSuccess: (d) => { changed(d); setConfirmRemove(false); setMsg({ tone: 'success', text: 'Removed. The saved key is deleted.' }); },
    onError: (e) => { setConfirmRemove(false); setMsg({ tone: 'danger', text: errorMessage(e) }); },
  });

  if (q.isError) return null; // not allowed to see platform settings
  if (q.isLoading || !c) return <Card title="AI provider"><Loading /></Card>;

  const p = c.providers.find((x) => x.id === provider) ?? c.providers[0];
  const azure = p.needs_endpoint;
  const sameProvider = c.connected && c.provider === provider;
  const dirty = !c.connected || provider !== c.provider || model !== (c.model ?? '') || endpoint !== (c.endpoint ?? '') || deployment !== (c.deployment ?? '') || apiKey !== '';
  const busy = save.isPending || test.isPending || remove.isPending;

  return (
    <Card title="AI provider">
      <div className="ai-conn">
        <p className="small muted">Choose the AI service, model and API key that every AI feature uses. One connection serves the whole platform.</p>
        <dl className="kv">
          <dt>In use now</dt><dd data-testid="ai-in-use">{inUse(c.active)}</dd>
          {c.connected && (
            <>
              <dt>Saved connection</dt>
              <dd>
                {c.provider_label} · {c.model}{c.deployment ? ` · deployment ${c.deployment}` : ''} · key {c.key_hint}
                {c.updated_at && <div className="small muted">Saved {fmtDateTime(c.updated_at)}</div>}
              </dd>
              <dt>Last test</dt>
              <dd>
                {c.last_test ? (
                  <>
                    {c.last_test.ok ? <Badge tone="success">Working</Badge> : <Badge tone="danger">Failed</Badge>} {fmtDateTime(c.last_test.at)}
                    <div className="small muted">{c.last_test.message}</div>
                  </>
                ) : 'Not tested yet'}
              </dd>
            </>
          )}
        </dl>
        {c.key_unreadable && <Alert tone="warn">The saved key cannot be read with the server's current secret key, so AI features are not using it. Enter the key again and save.</Alert>}
        {c.demo_mode && <Alert>This server runs with AI_CLIENT=fake, so AI features use the demonstration model whatever is saved here. Test connection still checks the saved provider.</Alert>}
        {c.stand_in && <Alert>This server runs with AI_PROVIDER_HTTP=fake (browser tests): a stand-in answers instead of the provider, and nothing leaves the server.</Alert>}
        {msg && <Alert tone={msg.tone} role={msg.tone === 'danger' ? 'alert' : 'status'}>{msg.text}</Alert>}

        {c.can_manage ? (
          <form className="ai-conn-form" autoComplete="off" onSubmit={(e) => { e.preventDefault(); setMsg(null); save.mutate(); }}>
            <SelectField label="Provider" help={HELP.provider} value={provider} error={errs.provider}
              onChange={(e) => { setProvider(e.target.value); setErrs({}); setModel(e.target.value === c.provider ? (c.model ?? '') : ''); }}
              options={c.providers.map((x) => ({ value: x.id, label: x.label }))} />
            <TextField label={azure ? 'Model (optional)' : 'Model'} help={azure ? HELP.azureModel : HELP.model} value={model} onChange={(e) => setModel(e.target.value)}
              list="ai-conn-models" placeholder={p.models[0]} error={errs.model} spellCheck={false} autoCapitalize="off" />
            <datalist id="ai-conn-models">{p.models.map((m) => <option key={m} value={m} />)}</datalist>
            {azure && (
              <>
                <TextField label="Endpoint" help={HELP.endpoint} value={endpoint} onChange={(e) => setEndpoint(e.target.value)} type="url" inputMode="url"
                  placeholder="https://your-resource.openai.azure.com" error={errs.endpoint} spellCheck={false} autoCapitalize="off" />
                <TextField label="Deployment" help={HELP.deployment} value={deployment} onChange={(e) => setDeployment(e.target.value)} error={errs.deployment}
                  spellCheck={false} autoCapitalize="off" />
              </>
            )}
            <TextField label="API key" help={HELP.key} hint={p.key_help} type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
              autoComplete="new-password" spellCheck={false} error={errs.api_key}
              placeholder={sameProvider ? `Leave blank to keep ${c.key_hint}` : 'Paste the API key'} />
            <div className="ai-conn-actions">
              <Button type="submit" variant="primary" disabled={!dirty || busy}>{save.isPending ? 'Saving…' : 'Save'}</Button>
              {c.connected && <Button onClick={() => { setMsg(null); test.mutate(); }} disabled={busy || dirty}>{test.isPending ? 'Testing…' : 'Test connection'}</Button>}
              {c.connected && <Button variant="danger" onClick={() => setConfirmRemove(true)} disabled={busy}>Remove</Button>}
            </div>
            {c.connected && dirty && <p className="small muted ai-conn-note">Save the changes before testing.</p>}
          </form>
        ) : (
          <p className="small">Only the Futran Admin changes the AI provider.</p>
        )}
        <p className="small muted ai-conn-note">
          Anthropic Claude runs through the platform's existing Anthropic connection. OpenAI, Azure OpenAI and Google Gemini have been tested only
          against simulated replies; their live calls are untested until the first real connection, so press Test connection after saving and run one
          small feature before relying on them. Law refresh with these providers marks every change low confidence for a second review, because they
          name the pages they read but not the passages.
        </p>
      </div>
      {confirmRemove && (
        <Dialog title="Remove the AI connection?" onClose={() => setConfirmRemove(false)}>
          <p>The saved API key is deleted. AI features then use ANTHROPIC_API_KEY from the server's .env file if it is set, otherwise the demonstration model in test mode, otherwise they are off.</p>
          <div className="ai-conn-actions">
            <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>{remove.isPending ? 'Removing…' : 'Remove connection'}</Button>
            <Button onClick={() => setConfirmRemove(false)}>Cancel</Button>
          </div>
        </Dialog>
      )}
    </Card>
  );
}
