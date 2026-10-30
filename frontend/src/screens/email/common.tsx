import { type ReactNode } from 'react';
import { Alert, Badge } from '@/components/ui';
import { type Connection, type Credentials, PROVIDER_LABEL, statusLabel } from '@/api/mail';

export function StatusBadge({ status }: { status: Connection['status'] }) {
  const s = statusLabel(status);
  return <Badge tone={s.tone}>{s.text}</Badge>;
}

export function Dns({ c }: { c: Connection }) {
  const one = (label: string, ok: boolean | null | undefined) => <Badge key={label} tone={ok === true ? 'success' : ok === false ? 'danger' : 'muted'}>{label}{ok === null || ok === undefined ? ' not checked' : ok ? '' : ' missing'}</Badge>;
  return <span className="mail-dns">{one('SPF', c.spf_ok)}{one('DKIM', c.dkim_ok)}{one('DMARC', c.dmarc_ok)}</span>;
}

/** What Futran IT registers before real mailboxes can connect. Shown when the client ID or secret is missing. */
export function RegisterHelp({ creds, who = 'futran' }: { creds: Credentials; who?: 'futran' | 'client' }) {
  const ms = creds.microsoft365;
  const g = creds.google;
  if (creds.test_mode) {
    return (
      <Alert tone="info">
        Test mode: connections use a simulated Microsoft 365 and Google Workspace, and every email stays in Admin › Outbox. Nothing leaves the platform.
        {(!ms.configured || !g.configured) && who === 'futran' && ' Real connections also need the app registrations described in the README.'}
      </Alert>
    );
  }
  if (ms.configured && g.configured) return null;
  if (who === 'client') {
    return (
      <Alert tone="warn">
        {[!ms.configured && 'Microsoft 365', !g.configured && 'Google Workspace'].filter(Boolean).join(' and ')} cannot be connected yet: Futran IT is still registering the platform with
        the provider. Until then your emails go out from Futran's mail service on your behalf, and nothing is lost. Your Futran team will tell you when it is ready.
      </Alert>
    );
  }
  return (
    <Alert tone="warn">
      <div className="stack-sm">
        <strong>Futran IT must register the platform before mailboxes can connect.</strong>
        <span>Until then every email goes out through the platform's own mail service (Admin › Outbox, or SMTP when it is set).</span>
        {!ms.configured && (
          <div>
            <strong>Microsoft 365</strong>
            <ol className="register-steps">
              <li>In the Microsoft Entra admin center, register a multitenant web app named "Futran Audit Platform".</li>
              <li>Add the redirect URI <span className="mail-code">{ms.redirect_uri}</span>.</li>
              <li>Add Microsoft Graph application permissions Mail.Send, Mail.ReadWrite, User.Read.All, Group.Read.All and GroupMember.Read.All, and delegated permissions offline_access, openid, email, User.Read, Mail.Send and Mail.ReadWrite.</li>
              <li>Create a client secret and set {ms.missing.map((m, i) => <span key={m}>{i ? ' and ' : ''}<span className="mail-code">{m}</span></span>)} in the platform's .env.</li>
            </ol>
          </div>
        )}
        {!g.configured && (
          <div>
            <strong>Google Workspace</strong>
            <ol className="register-steps">
              <li>In Google Cloud, enable the Gmail API and the Admin SDK API, and configure the OAuth consent screen.</li>
              <li>Create an OAuth client of type Web application with the redirect URI <span className="mail-code">{g.redirect_uri}</span>.</li>
              <li>Add the scopes gmail.send, gmail.modify (restricted), admin.directory.user.readonly, admin.directory.group.readonly and admin.directory.group.member.readonly.</li>
              <li>Set {g.missing.map((m, i) => <span key={m}>{i ? ' and ' : ''}<span className="mail-code">{m}</span></span>)} in the platform's .env. gmail.modify is restricted: Google must verify the app for outside organizations, unless each client's Workspace admin marks it as trusted.</li>
            </ol>
          </div>
        )}
      </div>
    </Alert>
  );
}

export function ProviderCard({ provider, conn, available, children, active }: { provider: 'microsoft365' | 'google'; conn: Connection; available: boolean; active: boolean; children?: ReactNode }) {
  return (
    <div className={`mail-card ${active ? 'active' : ''}`}>
      <h3>{PROVIDER_LABEL[provider]}</h3>
      <span className="small muted">{provider === 'microsoft365' ? 'Microsoft Graph' : 'Gmail API and Directory API'}</span>
      {active && conn.status === 'connected' && <span className="small muted">Connected{conn.mailbox_address ? ` as ${conn.mailbox_address}` : ''}{conn.consent_by ? ` · approved by ${conn.consent_by}` : ''}{conn.consent_at ? ` on ${new Date(conn.consent_at + 'Z').toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' })}` : ''}</span>}
      {active && <div><StatusBadge status={conn.status} /></div>}
      {!available && <span className="small muted">Not set up on this platform yet.</span>}
      {children}
    </div>
  );
}

export function OptionCard({ name, checked, onChange, title, children, disabled }: { name: string; checked: boolean; onChange: () => void; title: string; children: ReactNode; disabled?: boolean }) {
  return (
    <label className={`option-card ${checked ? 'checked' : ''}`}>
      <input type="radio" name={name} checked={checked} onChange={onChange} disabled={disabled} />
      <div><strong>{title}</strong><span>{children}</span></div>
    </label>
  );
}
