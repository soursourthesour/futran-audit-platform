import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { type ClientMail, PROVIDER_LABEL, goToConsent } from '@/api/mail';
import { Alert, Badge, Button, Card, Checkbox, Dialog, Loading, PageHeader, SelectField, TextField, fmtDateTime } from '@/components/ui';
import { emailHelp as H } from '@/help/email';
import { OptionCard, ProviderCard, RegisterHelp } from './common';
import { ClientTemplates, UserSyncSetting } from './FutranEmail';
import './email.css';

const STEPS = ['Connect your email system', 'Choose the sender', 'Sync users and groups', 'Send a test'];

/** E2 Connect your email (/admin/email): the Client Admin's four-step onboarding. The CAICO sees it read-only. */
export function ClientEmailSetup() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: me } = useMe();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ['mail-client'], queryFn: () => api.get<ClientMail>('/mail/client') });
  const [sender, setSender] = useState({ sender_mode: 'own', mailbox_address: '', send_as_name: '', reply_to_mode: 'mailbox', futran_copy: 'audit' });
  const [dir, setDir] = useState({ sync_people: true, use_directory_groups: true, include_guests: false, schedule: 'daily', department_field: 'department', scope_group: '' });
  const [testTo, setTestTo] = useState('');
  const [it, setIt] = useState<{ email: string; provider: string } | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(params.get('connected') ? { tone: 'success', text: 'Access approved. Your email system is connected.' } : null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!q.data) return;
    const c = q.data.connection;
    setSender({ sender_mode: c.sender_mode ?? 'own', mailbox_address: c.mailbox_address ?? '', send_as_name: c.send_as_name ?? `${q.data.organization} AI Governance`, reply_to_mode: c.reply_to_mode ?? 'mailbox',
      futran_copy: String((c.options ?? {}).futran_copy ?? 'audit') });
    const d = q.data.directory;
    if (d) setDir({ sync_people: true, use_directory_groups: d.use_directory_groups, include_guests: d.include_guests, schedule: d.schedule, department_field: d.department_field, scope_group: d.scope_group ?? '' });
  }, [q.data]);
  useEffect(() => { if (me && !testTo) setTestTo(me.user.email); }, [me]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (params.get('connected')) { params.delete('connected'); setParams(params, { replace: true }); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const c = d.connection;
  const can = d.can_manage;
  const hasCaico = !!me?.roles.some((r) => r.role === 'caico');
  const connected = c.status === 'connected';
  const refresh = () => qc.invalidateQueries({ queryKey: ['mail-client'] });
  const done = [connected, connected ? !!c.mailbox_address && (c.onboarding_step ?? 1) >= 3 : sender.sender_mode === 'futran_on_behalf' && (c.onboarding_step ?? 1) >= 3, !!d.directory?.last_run_at, !!c.test_sent_at];
  const current = done.findIndex((x) => !x);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null); setFe({}); setBusy(true);
    try { await fn(); if (ok) setMsg({ tone: 'success', text: ok }); await refresh(); return true; } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); setFe(fieldErrors(e)); return false; } finally { setBusy(false); }
  }
  const connect = (provider: string) => run(async () => { const r = await api.post<{ url: string }>('/mail/client/connect', { provider, mailbox_address: sender.mailbox_address || null }); goToConsent(r.url); });
  const saveSender = () => api.patch('/mail/client/connection', { ...(sender.sender_mode === 'own' ? { mailbox_address: sender.mailbox_address, send_as_name: sender.send_as_name, reply_to_mode: sender.reply_to_mode } : {}),
    sender_mode: sender.sender_mode, options: { futran_copy: sender.futran_copy }, onboarding_step: 3 });
  const saveDirectory = () => api.post('/mail/client/directory', { schedule: dir.schedule, include_guests: dir.include_guests, use_directory_groups: dir.use_directory_groups, department_field: dir.department_field,
    scope_group: dir.scope_group || null, scope_group_name: d.directory?.groups.find((g) => g.id === dir.scope_group)?.name ?? null });
  async function saveAll(next: boolean) {
    const ok = await run(async () => {
      if (connected || sender.sender_mode === 'futran_on_behalf') await saveSender();
      if (connected) await saveDirectory();
      if (next) await api.post('/mail/client/finish');
    }, next ? undefined : 'Saved. You can finish later from Getting started.');
    if (ok && next) nav('/admin/groups');
  }

  return (
    <div className="page">
      <PageHeader title="Connect your email" subtitle="Requests to employees and department heads go out from your own email system, so people recognise the sender and the messages pass your filters. Set up once, during onboarding." />
      {msg && <div style={{ marginBottom: 16 }}><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="mail-onboard">
        <div className="mail-side">
          <Card>
            <div className="stack">
              <ol className="mail-steps" aria-label="Steps">
                {STEPS.map((s, i) => <li key={s} className={done[i] ? 'done' : i === current ? 'current' : ''} aria-current={i === current ? 'step' : undefined}><span className="n" aria-hidden="true">{done[i] ? '✓' : i + 1}</span><a href={`#step-${i + 1}`}>{s}</a>{done[i] && <span className="sr-only"> (done)</span>}</li>)}
              </ol>
              <div style={{ borderTop: '1px solid var(--line-soft)' }} />
              <p className="small muted" style={{ margin: 0 }}>Your IT admin may need to approve access once. We can send them the request.</p>
              {c.it_request_sent_at && <p className="small" style={{ margin: 0 }}>Request sent to {c.it_request_email} on {fmtDateTime(c.it_request_sent_at)}.</p>}
              {can && <Button onClick={() => setIt({ email: c.it_request_email ?? '', provider: c.provider ?? 'microsoft365' })} disabled={connected}>Email the request to IT</Button>}
            </div>
          </Card>
        </div>
        <div className="stack">
          <RegisterHelp creds={d.credentials} who="client" />
          {!can && <Alert tone="info">Your Client Admin sets this up. You can see the connection here.</Alert>}
          <Card className={`mail-section ${current === 0 ? 'current' : ''}`} title={<h2 id="step-1">1 · Your email system {connected && <Badge tone="success">Done</Badge>}</h2>}>
            <div className="stack">
              <div className="mail-cards">
                {(['microsoft365', 'google'] as const).map((p) => {
                  const mine = c.provider === p && c.status !== 'not_connected' && c.status !== 'disconnected';
                  return (
                    <ProviderCard key={p} provider={p} conn={c} active={mine} available={d.credentials[p].available}>
                      {can && d.credentials[p].available && !(mine && connected) && <div><Button variant={!connected && p === 'microsoft365' ? 'primary' : 'default'} onClick={() => connect(p)} disabled={busy}>{connected ? 'Connect instead' : mine ? 'Connect again' : 'Connect'}</Button></div>}
                    </ProviderCard>
                  );
                })}
              </div>
              {c.status === 'consent_requested' && <Alert tone="warn">Waiting for an administrator to approve access in {PROVIDER_LABEL[c.provider ?? 'microsoft365']}. This page updates once they do.</Alert>}
              {c.last_error && <Alert tone="danger">{c.last_error}</Alert>}
              <p className="small muted" style={{ margin: 0 }}>Access asked for: send mail from one chosen mailbox, read replies to messages we sent, read users, departments and groups. We never read anyone else's mailbox.</p>
            </div>
          </Card>
          <Card className={`mail-section ${current === 1 ? 'current' : ''}`} title={<h2 id="step-2">2 · Who the emails come from {done[1] && <Badge tone="success">Done</Badge>}</h2>}>
            <fieldset className="stack" disabled={!can} style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="sr-only">Who the emails come from</legend>
              <OptionCard name="sender" checked={sender.sender_mode === 'own'} onChange={() => setSender({ ...sender, sender_mode: 'own' })} title="From your own mailbox (recommended)">
                For example ai-governance@yourcompany.com, sent through your {PROVIDER_LABEL[c.provider ?? 'microsoft365']}. Employees see an internal sender.
              </OptionCard>
              <OptionCard name="sender" checked={sender.sender_mode === 'futran_on_behalf'} onChange={() => setSender({ ...sender, sender_mode: 'futran_on_behalf' })} title="From Futran on your behalf">
                {d.futran_sender ?? 'AiAudit@futransolutions.com'}, with “{d.organization}” in the name. Use this if IT cannot approve a mailbox yet.
              </OptionCard>
              {sender.sender_mode === 'own' && (
                <div className="mail-grid-4">
                  <TextField label="Mailbox to send from *" help={H.mailbox} value={sender.mailbox_address} onChange={(e) => setSender({ ...sender, mailbox_address: e.target.value })} error={fe.mailbox_address} placeholder="ai-governance@yourcompany.com" />
                  <TextField label="Sender name *" help={H.sendAsName} value={sender.send_as_name} onChange={(e) => setSender({ ...sender, send_as_name: e.target.value })} />
                  <SelectField label="Replies go to" help={H.replyTo} value={sender.reply_to_mode} onChange={(e) => setSender({ ...sender, reply_to_mode: e.target.value })}
                    options={[{ value: 'mailbox', label: 'Same mailbox (synced back)' }, { value: 'caico', label: 'Chief AI Compliance Officer' }]} />
                  <SelectField label="Copy Futran on replies?" help={H.futranCopy} value={sender.futran_copy} onChange={(e) => setSender({ ...sender, futran_copy: e.target.value })}
                    options={[{ value: 'audit', label: 'Only audit-related threads' }, { value: 'all', label: 'All' }, { value: 'none', label: 'No' }]} />
                </div>
              )}
              {sender.sender_mode === 'own' && !connected && <p className="small muted" style={{ margin: 0 }}>Connect your email system first. Until then emails come from Futran on your behalf.</p>}
              {can && <div><Button onClick={() => run(saveSender, 'Sender saved.')} disabled={busy || (sender.sender_mode === 'own' && !connected)}>Save sender</Button></div>}
            </fieldset>
          </Card>
          <Card className={`mail-section ${current === 2 ? 'current' : ''}`} title={<h2 id="step-3">3 · Sync users and groups {done[2] && <Badge tone="success">Done</Badge>}</h2>}>
            <fieldset className="stack" disabled={!can || !connected} style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="sr-only">Directory sync</legend>
              {!connected && <p className="small muted" style={{ margin: 0 }}>Available once your email system is connected.</p>}
              <Checkbox label={`Sync people from ${c.provider === 'google' ? 'Google Workspace' : 'Microsoft Entra ID'}`} help={H.syncPeople} checked={dir.sync_people} disabled onChange={() => undefined} />
              <Checkbox label="Let us use your directory groups as a source" help={H.directoryGroups} checked={dir.use_directory_groups} onChange={(e) => setDir({ ...dir, use_directory_groups: e.target.checked })} />
              <Checkbox label="Include guests and contractors" help={H.guests} checked={dir.include_guests} onChange={(e) => setDir({ ...dir, include_guests: e.target.checked })} />
              <div className="mail-grid-4">
                <SelectField label="Sync every" help={H.schedule} value={dir.schedule} onChange={(e) => setDir({ ...dir, schedule: e.target.value })}
                  options={[{ value: 'daily', label: 'Daily' }, { value: '6h', label: 'Every 6 hours' }, { value: 'weekly', label: 'Weekly' }]} />
                <SelectField label="Department comes from" help={H.departmentField} value={dir.department_field} onChange={(e) => setDir({ ...dir, department_field: e.target.value })}
                  options={[{ value: 'department', label: 'Directory field: department' }, { value: 'office', label: 'Directory field: office' }]} />
                <SelectField label="Only sync people in" help={H.scopeGroup} value={dir.scope_group} onChange={(e) => setDir({ ...dir, scope_group: e.target.value })} placeholder="Everyone"
                  options={(d.directory?.groups ?? []).map((g) => ({ value: g.id, label: `Directory group: ${g.name}` }))} />
                <SelectField label="When someone leaves" help={H.leavers} value="remove" onChange={() => undefined} options={[{ value: 'remove', label: 'Remove from groups; keep their answers' }]} />
              </div>
              {d.directory?.last_run_at ? (
                <div className="mail-note">
                  Last sync: {fmtDateTime(d.directory.last_run_at)} · <strong>{d.directory.people.toLocaleString()}</strong> people · {d.directory.joined} joined, {d.directory.left} left, {d.directory.changed} changed · <strong>{d.directory.groups.length}</strong> directory groups available
                  {(d.directory.report.unmatched_departments ?? []).length > 0 && <div className="small" style={{ marginTop: 6 }}>Departments in your directory that are not on the platform yet: {(d.directory.report.unmatched_departments ?? []).join(', ')}. Add them under People if they are in scope.</div>}
                </div>
              ) : connected ? <div className="mail-note">Not synced yet.</div> : null}
              {can && connected && <div className="row"><Button onClick={() => run(saveDirectory, 'Directory settings saved.')} disabled={busy}>Save settings</Button><Button variant="primary" onClick={() => run(async () => { await saveDirectory(); await api.post('/mail/client/directory/sync'); }, 'Directory synced.')} disabled={busy}>Sync now</Button></div>}
            </fieldset>
          </Card>
          <Card className={`mail-section ${current === 3 ? 'current' : ''}`} title={<h2 id="step-4">4 · Send a test {done[3] && <Badge tone="success">Done</Badge>}</h2>}>
            <div className="stack">
              {c.test_sent_at && <p className="small" style={{ margin: 0 }}>Last test sent to {c.test_sent_to} on {fmtDateTime(c.test_sent_at)}.</p>}
              <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 220 }}><TextField label="Send a test to" help={H.testTo} type="email" value={testTo} disabled={!can} onChange={(e) => setTestTo(e.target.value)} error={fe.to} /></div>
                {can && <Button onClick={() => run(() => api.post('/mail/client/test', { to: testTo }), `Test email sent to ${testTo}.`)} disabled={busy}>Send test</Button>}
              </div>
              {d.can_set_user_sync && (
                <div className="stack-sm">
                  <p className="small muted" style={{ margin: 0 }}>Your users can also connect their own mailbox at first sign-in, so mail they send from the platform comes from their own address.</p>
                  <UserSyncSetting value={d.per_user_sync} canSet onSaved={refresh} />
                </div>
              )}
              {can && (
                <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                  <Button onClick={() => saveAll(false)} disabled={busy}>Save and finish later</Button>
                  <Button variant="primary" onClick={() => saveAll(true)} disabled={busy}>Save and continue to groups</Button>
                </div>
              )}
              {can && connected && <div><Button variant="ghost" size="sm" onClick={() => { if (window.confirm('Disconnect your email system? Emails then come from Futran on your behalf.')) void run(() => api.post('/mail/client/disconnect'), 'Disconnected.'); }}>Disconnect</Button></div>}
            </div>
          </Card>
          <ClientTemplates canEdit={can || hasCaico} />
        </div>
      </div>
      {it && (
        <Dialog title="Email the request to IT" onClose={() => setIt(null)}>
          <div className="stack">
            <p className="small muted" style={{ margin: 0 }}>Your IT administrator gets an email with a link to approve access once. The link expires in 7 days.</p>
            <TextField label="IT administrator's email *" help={H.itEmail} type="email" value={it.email} onChange={(e) => setIt({ ...it, email: e.target.value })} error={fe.email} />
            <SelectField label="Email system" help={H.provider} value={it.provider} onChange={(e) => setIt({ ...it, provider: e.target.value })} options={[{ value: 'microsoft365', label: 'Microsoft 365' }, { value: 'google', label: 'Google Workspace' }]} />
            <div className="row"><Button variant="primary" onClick={async () => { const ok = await run(() => api.post('/mail/client/request-it', it), `Request sent to ${it.email}.`); if (ok) setIt(null); }} disabled={busy}>Send the request</Button><Button onClick={() => setIt(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
