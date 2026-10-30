import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { type FutranMail, type Template, goToConsent } from '@/api/mail';
import { Alert, Button, Card, Checkbox, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDateTime } from '@/components/ui';
import { emailHelp as H } from '@/help/email';
import { Dns, ProviderCard, RegisterHelp } from './common';
import { GroupsManager } from './Groups';
import './email.css';

/** E1 Futran email and groups (/staff/admin/email). The Futran Admin connects AiAudit@futransolutions.com; the Chief
 *  Auditor and Auditors see it read-only. */
export function FutranEmail() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ['mail-futran'], queryFn: () => api.get<FutranMail>('/mail/futran') });
  const [form, setForm] = useState({ mailbox_address: '', send_as_name: '', reply_to_mode: 'mailbox', sync_interval_min: 15 });
  const [opts, setOpts] = useState<Record<string, boolean>>({});
  const [testTo, setTestTo] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(params.get('connected') ? { tone: 'success', text: 'The Futran mailbox is connected.' } : null);
  const [fe, setFe] = useState<Record<string, string>>({});
  useEffect(() => {
    const c = q.data?.connection;
    if (!c) return;
    setForm({ mailbox_address: c.mailbox_address ?? 'aiaudit@futransolutions.com', send_as_name: c.send_as_name ?? 'Futran Audit Platform', reply_to_mode: c.reply_to_mode ?? 'mailbox', sync_interval_min: c.sync_interval_min ?? 15 });
    const o = (c.options ?? {}) as Record<string, boolean>;
    setOpts({ save_activity: o.save_activity ?? true, sync_replies: o.sync_replies ?? true, track_bounces: o.track_bounces ?? true, calendar: !!o.calendar });
  }, [q.data]);
  useEffect(() => { if (params.get('connected')) { params.delete('connected'); setParams(params, { replace: true }); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const c = d.connection;
  const can = d.can_manage;
  const refresh = () => qc.invalidateQueries({ queryKey: ['mail-futran'] });

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null); setFe({});
    try { await fn(); if (ok) setMsg({ tone: 'success', text: ok }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); setFe(fieldErrors(e)); }
  }
  const connect = (provider: string) => run(async () => { const r = await api.post<{ url: string }>('/mail/futran/connect', { provider, mailbox_address: form.mailbox_address || 'aiaudit@futransolutions.com' }); goToConsent(r.url); });
  const active = c.provider;

  return (
    <div className="page">
      <PageHeader title="Futran email and groups" subtitle="Connect the Futran mailbox so invitations, approvals and evidence requests go out from it and replies come back into the right engagement. Groups expand to people only at the moment an email is sent." />
      <div className="stack">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <RegisterHelp creds={d.credentials} />
        <Card title="Mailbox connection">
          <div className="stack">
            <div className="mail-cards">
              {(['microsoft365', 'google'] as const).map((p) => (
                <ProviderCard key={p} provider={p} conn={c} active={active === p && c.status !== 'not_connected'} available={d.credentials[p].available}>
                  {can && d.credentials[p].available && !(active === p && c.status === 'connected') && <div><Button onClick={() => connect(p)}>{active && c.status === 'connected' ? 'Connect instead' : 'Connect'}</Button></div>}
                </ProviderCard>
              ))}
              <div className="mail-card"><h3>Other (SMTP and IMAP)</h3><span className="small muted">After the first release. SMTP set in .env is used while no mailbox is connected.</span></div>
            </div>
            {c.last_error && <Alert tone="danger">{c.last_error}</Alert>}
            <h3 style={{ margin: 0, fontSize: 16 }}>Send as</h3>
            <div className="mail-grid-4">
              <TextField label="From address" help={H.mailbox} value={form.mailbox_address} disabled={!can} onChange={(e) => setForm({ ...form, mailbox_address: e.target.value })} error={fe.mailbox_address} />
              <TextField label="Sender name" help={H.sendAsName} value={form.send_as_name} disabled={!can} onChange={(e) => setForm({ ...form, send_as_name: e.target.value })} />
              <SelectField label="Reply-to" help={H.replyTo} value={form.reply_to_mode} disabled={!can} onChange={(e) => setForm({ ...form, reply_to_mode: e.target.value })}
                options={[{ value: 'mailbox', label: 'Same mailbox' }, { value: 'chief_auditor', label: "Engagement's Chief Auditor" }]} />
              <SelectField label="Sync every" help={H.syncInterval} value={String(form.sync_interval_min)} disabled={!can} onChange={(e) => setForm({ ...form, sync_interval_min: Number(e.target.value) })}
                options={[{ value: '5', label: '5 minutes' }, { value: '15', label: '15 minutes' }, { value: '60', label: 'Hourly' }]} />
            </div>
            <fieldset className="stack-sm" style={{ border: 0, padding: 0, margin: 0 }} disabled={!can}>
              <legend className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Sync</legend>
              <Checkbox label="Save every sent email to the engagement's activity log" help={H.saveActivity} checked={!!opts.save_activity} onChange={(e) => setOpts({ ...opts, save_activity: e.target.checked })} />
              <Checkbox label="Bring replies back into the engagement, matched by the reference in the subject (for example [FAP-1042])" help={H.options} checked={!!opts.sync_replies} onChange={(e) => setOpts({ ...opts, sync_replies: e.target.checked })} />
              <Checkbox label="Track bounces and out-of-office replies" help={H.trackBounces} checked={!!opts.track_bounces} onChange={(e) => setOpts({ ...opts, track_bounces: e.target.checked })} />
              <Checkbox label="Read Futran staff calendars to suggest meeting times (after the first release)" checked={false} disabled onChange={() => undefined} />
            </fieldset>
            <div className="mail-note">
              Permissions granted: send mail, read and file replies in this mailbox only, read Futran users and groups. Domain checks: <Dns c={c} />
              {c.last_sync_at && <> · Last sync {fmtDateTime(c.last_sync_at)}</>}
            </div>
            {can && (
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <Button variant="primary" onClick={() => run(() => api.patch('/mail/futran/connection', { ...form, options: opts }), 'Saved.')}>Save settings</Button>
                <TextField label="Send a test to" help={H.testTo} value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="you@futransolutions.com" />
                <Button onClick={() => run(() => api.post('/mail/futran/test', { to: testTo }), 'Test email sent.')} disabled={c.status !== 'connected'}>Send a test email</Button>
                <Button onClick={() => run(() => api.post('/mail/futran/check-domain'), 'Domain checked.')} disabled={!c.domain}>Check SPF, DKIM and DMARC</Button>
                {c.status === 'connected' && <Button variant="danger" onClick={() => { if (window.confirm('Disconnect the Futran mailbox? Emails then go out through the platform\'s own mail service.')) void run(() => api.post('/mail/futran/disconnect'), 'Disconnected.'); }}>Disconnect</Button>}
              </div>
            )}
          </div>
        </Card>
        <Card title="Futran staff mailboxes">
          <div className="stack-sm">
            <p className="small muted" style={{ margin: 0 }}>Whether Futran staff connect their own mailbox when they first sign in. Mail they send from the platform then comes from their own address.</p>
            <UserSyncSetting value={d.per_user_sync} canSet={can} onSaved={refresh} />
          </div>
        </Card>
        <Card><GroupsManager owner="futran" title="Futran groups" /><p className="small muted" style={{ margin: '12px 0 0' }}>Groups live only in the Futran Audit Platform. They are not created in Microsoft 365 or Google. A rule-based group updates itself when someone joins, leaves or changes role.</p></Card>
        <FutranTemplates canEdit={can} />
      </div>
    </div>
  );
}

export function UserSyncSetting({ value, canSet, onSaved }: { value: string; canSet: boolean; onSaved: () => void }) {
  const [v, setV] = useState(value);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setV(value), [value]);
  return (
    <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
      <SelectField label="Personal mailbox at first sign-in" help={H.perUserSync} value={v} disabled={!canSet} onChange={(e) => setV(e.target.value)}
        options={[{ value: 'required', label: 'Required' }, { value: 'optional', label: 'Optional' }, { value: 'off', label: 'Off' }]} />
      {canSet && <Button onClick={async () => { setErr(null); try { await api.patch('/mail/settings', { per_user_sync: v }); onSaved(); } catch (e) { setErr(errorMessage(e)); } }} disabled={v === value}>Save</Button>}
      {err && <Alert tone="danger">{err}</Alert>}
    </div>
  );
}

function FutranTemplates({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['mail-templates', 'futran'], queryFn: () => api.get<Template[]>('/mail/templates') });
  const [edit, setEdit] = useState<Template | null>(null);
  return (
    <Card title="Email templates">
      {q.isLoading ? <Loading /> : (
        <div className="table-wrap" style={{ position: 'relative' }}>
          <table className="table">
            <thead><tr><th>Template</th><th>Default delivery</th><th>Version</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {(q.data ?? []).map((t) => (
                <tr key={t.id}><td><strong>{t.name}</strong><div className="small muted">{t.subject}</div></td><td>{t.default_mode === 'personal' ? 'Personal link' : 'BCC'}</td><td>{t.version}</td>
                  <td>{canEdit && t.can_edit && <Button size="sm" onClick={() => setEdit(t)}>Edit</Button>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && <TemplateDialog t={edit} onClose={() => setEdit(null)} onSaved={async () => { setEdit(null); await qc.invalidateQueries({ queryKey: ['mail-templates'] }); }} />}
    </Card>
  );
}

export function TemplateDialog({ t, onClose, onSaved }: { t: Template; onClose: () => void; onSaved: () => void }) {
  const [subject, setSubject] = useState(t.subject);
  const [body, setBody] = useState(t.body);
  const [mode, setMode] = useState(t.default_mode);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title={`Edit template: ${t.name}`} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>Saving makes version {t.version + 1}. Emails already sent keep the version they used. Merge fields: [First name], [Name], [Department], [Link], [Due date], [Sender name], [Organization]. Put [Link] on its own line for the button.</p>
        <TextField label="Subject" help={H.subject} value={subject} onChange={(e) => setSubject(e.target.value)} />
        <SelectField label="Default delivery" help={H.mode} value={mode} onChange={(e) => setMode(e.target.value as 'personal' | 'bcc')} options={[{ value: 'personal', label: 'Personal link' }, { value: 'bcc', label: 'BCC with a shared link' }]} />
        <TextArea label="Message" help={H.template} value={body} onChange={(e) => setBody(e.target.value)} rows={12} />
        <div className="row"><Button variant="primary" onClick={async () => { setErr(null); try { await api.put(`/mail/templates/${t.id}`, { subject, body, default_mode: mode }); onSaved(); } catch (e) { setErr(errorMessage(e)); } }}>Save version {t.version + 1}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** The client's templates (E2): Futran's defaults, and the client's own copies it can edit (spec §26.6). */
export function ClientTemplates({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['mail-templates', 'client'], queryFn: () => api.get<Template[]>('/mail/templates') });
  const [edit, setEdit] = useState<Template | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function copy(t: Template) {
    setErr(null);
    try { const c = await api.post<Template>(`/mail/templates/${t.key}/copy`); await qc.invalidateQueries({ queryKey: ['mail-templates'] }); setEdit({ ...c, can_edit: true }); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Card title="Email templates">
      <div className="stack-sm">
        <p className="small muted" style={{ margin: 0 }}>Futran ships these templates. Make your own copy to change the wording; every change is kept as a new version and earlier emails keep the version they used.</p>
        {err && <Alert tone="danger">{err}</Alert>}
        {q.isLoading ? <Loading /> : (
          <div className="table-wrap" style={{ position: 'relative' }}>
            <table className="table">
              <thead><tr><th>Template</th><th>Whose</th><th>Version</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {(q.data ?? []).map((t) => (
                  <tr key={t.id}><td><strong>{t.name}</strong><div className="small muted">{t.subject}</div></td><td>{t.owner === 'client' ? 'Your copy' : 'Futran default'}</td><td>{t.version}</td>
                    <td>{canEdit && (t.owner === 'client' ? <Button size="sm" onClick={() => setEdit(t)}>Edit</Button> : <Button size="sm" onClick={() => copy(t)}>Make our copy</Button>)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {edit && <TemplateDialog t={edit} onClose={() => setEdit(null)} onSaved={async () => { setEdit(null); await qc.invalidateQueries({ queryKey: ['mail-templates'] }); }} />}
    </Card>
  );
}
