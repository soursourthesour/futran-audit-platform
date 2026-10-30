import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { type Preview, type SendOptions, type SendRow, downloadBlob } from '@/api/mail';
import { Alert, Button, Card, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextField, WithHelp } from '@/components/ui';
import { emailHelp as H } from '@/help/email';
import { OptionCard } from './common';
import './email.css';

function frameDoc(html: string): string {
  const base = '<base target="_blank"><meta name="viewport" content="width=device-width, initial-scale=1"><style>table[width] { width: 100% !important; } td { overflow-wrap: anywhere; } body { margin: 0; }</style>';
  return /<head[^>]*>/i.test(html) ? html.replace(/<head([^>]*)>/i, `<head$1>${base}`) : `${base}${html}`;
}

/** E4 Send an email to groups (/send). Clients send to their own groups; Futran sends engagement emails (?client=). */
export function SendToGroups() {
  const { data: me } = useMe();
  const [params] = useSearchParams();
  const isFutran = me?.organization.type === 'futran';
  const [clientId, setClientId] = useState(params.get('client') ?? '');
  const clients = useQuery({ queryKey: ['clients-list', ''], queryFn: () => api.get<{ clients: { id: string; name: string }[] }>('/clients?q='), enabled: isFutran && !params.get('client') });
  if (!me) return <div className="page"><Loading /></div>;
  if (isFutran && !clientId) {
    return (
      <div className="page page-narrow">
        <PageHeader title="Send an email to groups" subtitle="Futran sends engagement emails to a client's groups. Choose the client." />
        <Card>{clients.isLoading ? <Loading /> : (
          <SelectField label="Client" help={H.groups} value="" placeholder="Choose a client…" onChange={(e) => setClientId(e.target.value)} options={(clients.data?.clients ?? []).map((c) => ({ value: c.id, label: c.name }))} />
        )}</Card>
      </div>
    );
  }
  return <SendForm clientId={isFutran ? clientId : undefined} />;
}

type Form = {
  template_key: string; sender: string; group_ids: string[]; exclude_group_ids: string[]; exclude_responded: boolean; department_ids: string[]; offices: string[];
  mode: 'personal' | 'bcc'; when: 'now' | 'tomorrow' | 'later'; at: string; reminders: string; link_days: number; subject: string;
};

function SendForm({ clientId }: { clientId?: string }) {
  const [params] = useSearchParams();
  const q = useQuery({ queryKey: ['mail-send-options', clientId ?? 'own'], queryFn: () => api.get<SendOptions>(`/mail/send/options${clientId ? `?client_id=${clientId}` : ''}`) });
  const [f, setF] = useState<Form | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPeople, setShowPeople] = useState(false);
  const [sent, setSent] = useState<SendRow | null>(null);
  useEffect(() => {
    if (!q.data || f) return;
    const o = q.data;
    const wanted = (params.get('groups') ?? '').split(',').filter(Boolean);
    const groups = wanted.length ? wanted.filter((id) => o.groups.some((g) => g.id === id)) : [];
    const key = params.get('template') && o.templates.some((t) => t.key === params.get('template')) ? params.get('template')! : (o.templates[0]?.key ?? '');
    const t = o.templates.find((x) => x.key === key);
    setF({ template_key: key, sender: o.senders[0]?.key ?? 'organization', group_ids: groups, exclude_group_ids: [], exclude_responded: params.get('exclude') === 'responded' || t?.purpose === 'attestation',
      department_ids: [], offices: [], mode: t?.default_mode ?? 'personal', when: 'now', at: '', reminders: '3,7', link_days: o.defaults.link_days, subject: '' });
  }, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const body = useMemo(() => f && ({
    client_id: clientId, template_key: f.template_key, sender: f.sender, group_ids: f.group_ids, exclude_group_ids: f.exclude_group_ids, exclude_responded: f.exclude_responded,
    department_ids: f.department_ids, offices: f.offices, mode: f.mode, reminder_days: f.reminders ? f.reminders.split(',').map(Number) : [], link_days: f.link_days, subject: f.subject || undefined,
  }), [f, clientId]);
  const preview = useQuery({ queryKey: ['mail-preview', body], queryFn: () => api.post<Preview>('/mail/send/preview', body), enabled: !!body && body.group_ids.length > 0, retry: false });
  if (q.isLoading || !f) return <div className="page">{q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />}</div>;
  const o = q.data!;
  const set = (patch: Partial<Form>) => setF({ ...f, ...patch });
  const groupName = (id: string) => o.groups.find((g) => g.id === id)?.name ?? 'Group';
  const t = o.templates.find((x) => x.key === f.template_key);
  const total = preview.data?.total ?? 0;
  const fromCampaign = params.get('from') === 'attestation';

  function scheduledAt(): string | undefined {
    if (f!.when === 'now') return undefined;
    if (f!.when === 'tomorrow') { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d.toISOString(); }
    return f!.at ? new Date(f!.at).toISOString() : undefined;
  }
  async function send() {
    setBusy(true); setMsg(null);
    try {
      const r = await api.post<SendRow>('/mail/send', { ...body, scheduled_at: scheduledAt() });
      setSent(r);
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  async function test() {
    setMsg(null);
    try { const r = await api.post<{ to: string }>('/mail/send/test', body); setMsg({ tone: 'success', text: `Test sent to ${r.to}.` }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function download() {
    downloadBlob(await api.post<Blob>('/mail/send/people.csv', body), 'recipients.csv');
  }
  const add = (list: 'group_ids' | 'exclude_group_ids', id: string) => id && !f[list].includes(id) && set({ [list]: [...f[list], id] } as Partial<Form>);
  const drop = (list: 'group_ids' | 'exclude_group_ids', id: string) => set({ [list]: f[list].filter((x) => x !== id) } as Partial<Form>);
  const sendLabel = f.when === 'now' ? `Send to ${total.toLocaleString()} ${total === 1 ? 'person' : 'people'}` : `Schedule for ${total.toLocaleString()} ${total === 1 ? 'person' : 'people'}`;

  if (sent) {
    return (
      <div className="page page-narrow">
        <PageHeader title={sent.status === 'scheduled' ? 'Email scheduled' : 'Email sent'} />
        <Card>
          <div className="stack">
            <Alert tone="success">{sent.template} {sent.status === 'scheduled' ? 'is scheduled for' : 'is going to'} {sent.recipients.toLocaleString()} {sent.recipients === 1 ? 'person' : 'people'}. {sent.queued > 0 && sent.status !== 'scheduled' ? `${sent.delivered.toLocaleString()} sent so far; the rest go out over the next few minutes to stay inside the provider's limits.` : ''}</Alert>
            <p className="small muted" style={{ margin: 0 }}>The recipient list is saved with the send, so the log shows exactly who was emailed even if the groups change later.</p>
            <div className="row"><Link className="btn btn-primary" to={`/admin/log?send=${sent.id}${clientId ? `&client=${clientId}` : ''}`}>Open in the email log</Link><Button onClick={() => { setSent(null); setF(null); }}>Send another</Button></div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader title="Send an email to groups" crumbs={fromCampaign ? [{ to: clientId ? `/clients/${clientId}/attestation` : '/attestation', label: 'Attestation campaign' }, { label: 'Send email' }] : undefined}
        subtitle={`Pick groups, not people. The platform expands them when you press Send, so the list is always current. Nobody sees anyone else's address.${o.engagement ? ` Engagement ${o.engagement.audit_ref}.` : ''}`}
        actions={<><Button onClick={test} disabled={!t}>Send a test to me</Button><Button onClick={() => set({ when: f.when === 'now' ? 'tomorrow' : 'now' })}>{f.when === 'now' ? 'Schedule' : 'Send now instead'}</Button><Button variant="primary" onClick={send} disabled={busy || !total || preview.isFetching}>{sendLabel}</Button></>} />
      {msg && <div style={{ marginBottom: 16 }}><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="send-layout">
        <div className="stack">
          <Card title="1 · What to send">
            <div className="grid-2">
              <SelectField label="Template *" help={H.template} value={f.template_key} onChange={(e) => { const nt = o.templates.find((x) => x.key === e.target.value); set({ template_key: e.target.value, mode: nt?.default_mode ?? f.mode, exclude_responded: nt?.purpose === 'attestation' ? f.exclude_responded : false }); }}
                options={o.templates.map((x) => ({ value: x.key, label: x.name }))} />
              <SelectField label="Send from" help={H.sender} value={f.sender} onChange={(e) => set({ sender: e.target.value })} options={o.senders.map((s) => ({ value: s.key, label: s.label }))} />
            </div>
            <TextField label="Subject" help={H.subject} value={f.subject} placeholder={t?.subject} onChange={(e) => set({ subject: e.target.value })} />
          </Card>
          <Card title="2 · Who gets it">
            <div className="stack">
              <FieldGroup legend="Send to groups *" help={H.groups}>
                <div className="chips">
                  {f.group_ids.map((id) => <span key={id} className="chip-x">{groupName(id)}<button type="button" onClick={() => drop('group_ids', id)} aria-label={`Remove ${groupName(id)}`}>×</button></span>)}
                  <select className="select" aria-label="Add a group" value="" onChange={(e) => add('group_ids', e.target.value)} style={{ width: 'auto', minWidth: 160 }}>
                    <option value="">Add a group…</option>
                    {o.groups.filter((g) => !f.group_ids.includes(g.id)).map((g) => <option key={g.id} value={g.id}>{g.name} ({g.member_count.toLocaleString()})</option>)}
                  </select>
                </div>
              </FieldGroup>
              <FieldGroup legend="Leave out" help={H.excludeGroups}>
                <div className="chips">
                  {t?.purpose === 'attestation' && (f.exclude_responded
                    ? <span className="chip-x muted">People who already responded<button type="button" onClick={() => set({ exclude_responded: false })} aria-label="Stop leaving out people who already responded">×</button></span>
                    : <Button size="sm" onClick={() => set({ exclude_responded: true })}>Leave out people who already responded</Button>)}
                  {f.exclude_group_ids.map((id) => <span key={id} className="chip-x muted">{groupName(id)}<button type="button" onClick={() => drop('exclude_group_ids', id)} aria-label={`Stop leaving out ${groupName(id)}`}>×</button></span>)}
                  <select className="select" aria-label="Leave out a group" value="" onChange={(e) => add('exclude_group_ids', e.target.value)} style={{ width: 'auto', minWidth: 160 }}>
                    <option value="">Leave out a group…</option>
                    {o.groups.filter((g) => !f.exclude_group_ids.includes(g.id)).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                </div>
              </FieldGroup>
              {(o.departments.length > 0 || o.offices.length > 0) && (
                <div className="grid-2">
                  {o.departments.length > 0 && <SelectField label="Only this department" help={H.departments} value={f.department_ids[0] ?? ''} placeholder="All departments" onChange={(e) => set({ department_ids: e.target.value ? [e.target.value] : [] })} options={o.departments.map((d) => ({ value: d.id, label: d.name }))} />}
                  {o.offices.length > 0 && <SelectField label="Only this office" help={H.offices} value={f.offices[0] ?? ''} placeholder="All offices" onChange={(e) => set({ offices: e.target.value ? [e.target.value] : [] })} options={o.offices.map((x) => ({ value: x, label: x }))} />}
                </div>
              )}
              <div className="expansion-box" aria-live="polite">
                <h3>Group expansion preview (updated at send time)</h3>
                {!f.group_ids.length ? <EmptyState>Add a group to see who would receive it.</EmptyState> : preview.isLoading ? <Loading label="Counting…" /> : preview.error ? <Alert tone="danger">{errorMessage(preview.error)}</Alert> : (
                  <>
                    <table className="expansion">
                      <tbody>
                        {preview.data!.steps.map((s, i) => (
                          <tr key={i} className={s.kind === 'total' ? 'total' : ''}><td>{s.label}</td><td>{s.kind === 'add' ? `+ ${s.count.toLocaleString()}` : s.count < 0 ? `− ${Math.abs(s.count).toLocaleString()}` : s.count.toLocaleString()}</td></tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="foot"><button type="button" className="link-btn" onClick={() => setShowPeople(true)}>See all {total.toLocaleString()} people</button><button type="button" className="link-btn" onClick={download}>Download list</button></div>
                  </>
                )}
              </div>
            </div>
          </Card>
          <Card title="3 · How it is delivered">
            <div className="stack">
              <OptionCard name="mode" checked={f.mode === 'personal'} onChange={() => set({ mode: 'personal' })} title="Personal link for each person (recommended for attestation)">
                One message per person, each with their own link. No sign-in. Lets you see who has and has not responded and send reminders only to them.
              </OptionCard>
              <OptionCard name="mode" checked={f.mode === 'bcc'} onChange={() => set({ mode: 'bcc' })} title="One message, everyone in BCC">
                Sent in batches of up to {o.defaults.batch_size} people in BCC. Everyone gets the same link and confirms their work email with a one-time code before filling in. Good for notices.
              </OptionCard>
              <div className="grid-3">
                <SelectField label="Send at" help={H.sendAt} value={f.when} onChange={(e) => set({ when: e.target.value as Form['when'] })} options={[{ value: 'now', label: 'Now' }, { value: 'tomorrow', label: 'Tomorrow 9:00 am' }, { value: 'later', label: 'Choose a time' }]} />
                <SelectField label="Reminders to people who haven't responded" help={H.reminders} value={f.reminders} onChange={(e) => set({ reminders: e.target.value })} options={[{ value: '3,7', label: 'After 3 and 7 days' }, { value: '5', label: 'After 5 days' }, { value: '', label: 'None' }]} />
                <SelectField label="Link expires" help={H.linkDays} value={String(f.link_days)} onChange={(e) => set({ link_days: Number(e.target.value) })} options={[{ value: '14', label: 'After 14 days' }, { value: '30', label: 'After 30 days' }]} />
              </div>
              {f.when === 'later' && <TextField label="Date and time" help={H.sendAt} type="datetime-local" value={f.at} onChange={(e) => set({ at: e.target.value })} />}
              <p className="small muted" style={{ margin: 0 }}>Sending is paced to stay inside Microsoft 365 and Google limits (about {o.pace_per_minute} messages a minute). Large sends are spread over several minutes.</p>
            </div>
          </Card>
        </div>
        <div className="send-preview">
          <h2 style={{ fontSize: 16, margin: '0 0 8px' }}><WithHelp help="What one recipient sees, with their own name and link filled in when it is sent.">Preview: what a recipient sees</WithHelp></h2>
          <Card>
            {preview.data ? (
              <div className="stack-sm">
                <div className="mail-preview-head"><span>From <b>{preview.data.message.from}</b></span><span>To <b>{preview.data.message.to}</b></span><span>Subject <b>{preview.data.message.subject}</b></span></div>
                <iframe className="mail-preview-frame" title="Email preview" sandbox="allow-popups" srcDoc={frameDoc(preview.data.message.html)} />
              </div>
            ) : <EmptyState>Choose a template and a group to preview the email.</EmptyState>}
          </Card>
          {t?.purpose === 'attestation' && <p className="small muted">The link opens the employee check-in on any phone. Answers go straight into the AI inventory as drafts.</p>}
        </div>
      </div>
      {showPeople && preview.data && (
        <Dialog title={`Who will receive it (${total.toLocaleString()})`} onClose={() => setShowPeople(false)} wide>
          <ul className="member-list">{preview.data.people.map((p) => <li key={p.id}><div className="who"><strong>{p.name}</strong><span className="small muted">{p.email}{p.department ? ` · ${p.department}` : ''}</span></div></li>)}</ul>
          {total > preview.data.people.length && <p className="small muted">Showing the first {preview.data.people.length}. Download the list to see everyone.</p>}
        </Dialog>
      )}
    </div>
  );
}
