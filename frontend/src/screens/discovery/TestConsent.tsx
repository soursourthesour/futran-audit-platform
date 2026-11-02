import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Button, Card, Loading, TextField } from '@/components/ui';
import { PhoneShell } from '@/shells/Shells';
import { integrationsHelp as H } from '@/help/discovery';

type Info = { type: string; label: string; provider: 'microsoft' | 'google'; organization: string; scopes: string[] };

/** Test mode only: stands in for the Microsoft or Google consent page for an AI discovery connector. The answer is
 *  accepted only in the browser session, and from the person, that started the connection. */
export function ConnectorTestConsent() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const state = params.get('state') ?? '';
  const q = useQuery({ queryKey: ['connector-consent', state], queryFn: () => api.get<Info>(`/connectors/test-consent-info?state=${encodeURIComponent(state)}`), retry: false });
  const hint = params.get('login_hint') ?? '';
  const [domain, setDomain] = useState(hint.includes('@') ? hint.split('@')[1] : '');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function answer(approve: boolean) {
    if (busy || !q.data) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ redirect: string }>(`/connectors/oauth/${q.data.provider}/test`, { state, domain, approve });
      await qc.invalidateQueries();
      nav(r.redirect);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  if (q.isLoading) return <PhoneShell title="Sign in"><Loading /></PhoneShell>;
  if (!q.data) return <PhoneShell title="Sign in"><Alert tone="danger">{errorMessage(q.error)}</Alert></PhoneShell>;
  const i = q.data;
  return (
    <PhoneShell title={`${i.label} (test mode)`}>
      <Card>
        <div className="stack">
          <Alert tone="info">{H.testConsent}</Alert>
          <h1 style={{ fontSize: 22, margin: 0 }}>Allow read-only access for {i.organization}</h1>
          <p style={{ margin: 0 }}>The Futran Audit Platform asks to read, and only read:</p>
          <ul className="small" style={{ margin: 0 }}>{i.scopes.map((s) => <li key={s}><code>{s}</code></li>)}</ul>
          <TextField label="Your organisation’s domain *" help={H.testDomain} value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="yourcompany.com" />
          {err && <Alert tone="danger">{err}</Alert>}
          <Button variant="primary" block disabled={busy || !domain} onClick={() => answer(true)}>Accept</Button>
          <Button block disabled={busy} onClick={() => answer(false)}>Cancel</Button>
        </div>
      </Card>
    </PhoneShell>
  );
}
