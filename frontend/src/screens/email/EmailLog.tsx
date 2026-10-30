import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { type AdminEntry, type SendDetail, type SendRow, downloadBlob } from '@/api/mail';
import { Alert, Badge, Card, Dialog, EmptyState, Loading, PageHeader, SelectField, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import { emailHelp as H } from '@/help/email';
import './email.css';

type Sends = { sends: SendRow[]; templates: [string, string][]; groups: [string, string][] };
type Admin = { entries: AdminEntry[]; retention_years: number; categories: { value: string; label: string }[] };

const STATUS_TONE: Record<string, 'success' | 'warn' | 'danger' | 'muted' | 'navy'> = { completed: 'success', opened: 'navy', sent: 'muted', delivered: 'muted', bounced: 'danger', queued: 'warn' };
const STATUS_LABEL: Record<string, string> = { completed: 'Completed', opened: 'Opened link', sent: 'Sent', delivered: 'Delivered', bounced: 'Bounced', queued: 'Queued' };
const dash = (n: number, show: boolean) => (show ? n.toLocaleString() : '—');

/** E5 Email and admin log (/admin/log). Clients see their own; Futran sees its own and its engagements'. */
export function EmailLog() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [params] = useSearchParams();
  const clientId = params.get('client') ?? '';
  const [template, setTemplate] = useState('');
  const [group, setGroup] = useState('');
  const [days, setDays] = useState('30');
  const [category, setCategory] = useState('');
  const [open, setOpen] = useState<{ id: string; tab: 'message' | 'recipients' | 'replies' } | null>(params.get('send') ? { id: params.get('send')!, tab: 'recipients' } : null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const qsBase = clientId ? `client_id=${clientId}&` : '';
  const sends = useQuery({ queryKey: ['mail-log', clientId, template, group, days], queryFn: () => api.get<Sends>(`/mail/log/sends?${qsBase}days=${days}${template ? `&template=${template}` : ''}${group ? `&group=${group}` : ''}`) });
  const admin = useQuery({ queryKey: ['mail-admin-log', clientId, category], queryFn: () => api.get<Admin>(`/mail/log/admin?${qsBase}${category ? `category=${category}` : ''}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['mail-log'] });
  const isFutran = me?.organization.type === 'futran';

  async function act(fn: () => Promise<{ reminded?: number; resent?: number }>, kind: 'remind' | 'resend') {
    setMsg(null);
    try {
      const r = await fn();
      const n = kind === 'remind' ? r.reminded ?? 0 : r.resent ?? 0;
      setMsg({ tone: 'success', text: kind === 'remind' ? (n ? `Reminder sent to ${n} ${n === 1 ? 'person' : 'people'} who have not responded.` : 'Everyone has responded; no reminder was needed.') : (n ? `Sent again to ${n} bounced ${n === 1 ? 'address' : 'addresses'}.` : 'Nothing had bounced.') });
      await refresh();
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const remind = (s: SendRow) => act(() => api.post(`/mail/log/sends/${s.id}/remind`), 'remind');
  const resend = (s: SendRow) => act(() => api.post(`/mail/log/sends/${s.id}/resend-bounced`), 'resend');
  const exportRecipients = async (s: SendRow) => downloadBlob(await api.get<Blob>(`/mail/log/sends/${s.id}/export`), `${(s.template || 'email').replace(/[^A-Za-z0-9]+/g, '_')}_recipients.csv`);
  const groupSend = (s: SendRow) => s.kind === 'group' || s.kind === 'reminder';

  const columns: GridColumn<SendRow>[] = [
    { key: 'sent', header: 'Sent', value: (s) => s.sent_at, render: (s) => <>{fmtDateTime(s.sent_at)}{s.status === 'scheduled' && <div><Badge tone="warn">Scheduled</Badge></div>}{s.status === 'sending' && <div><Badge tone="navy">Sending</Badge></div>}{s.kind === 'reminder' && <div><Badge tone="muted">Reminder</Badge></div>}</> },
    { key: 'template', header: 'Template', value: (s) => s.template },
    { key: 'groups', header: 'Groups', value: (s) => s.groups.join(', '), render: (s) => (s.groups.length ? s.groups.join(', ') : <span className="muted">{s.kind === 'system' ? 'Direct' : '—'}</span>) },
    { key: 'mode', header: 'Delivery', value: (s) => s.mode_label },
    { key: 'recipients', header: 'Recipients', value: (s) => s.recipients, render: (s) => <span className="num">{s.recipients.toLocaleString()}</span> },
    { key: 'delivered', header: 'Delivered', value: (s) => s.delivered, render: (s) => <span className="num">{s.delivered.toLocaleString()}</span> },
    { key: 'bounced', header: 'Bounced', value: (s) => s.bounced, render: (s) => <span className="num">{s.bounced.toLocaleString()}</span> },
    { key: 'opened', header: 'Opened link', value: (s) => s.opened, render: (s) => <span className="num">{dash(s.opened, s.mode === 'personal' || s.mode === 'bcc')}</span> },
    { key: 'completed', header: 'Completed', value: (s) => s.completed, render: (s) => <span className="num">{dash(s.completed, s.mode === 'personal' || s.mode === 'bcc')}</span> },
    { key: 'replies', header: 'Replies', value: (s) => s.replies, render: (s) => <span className="num">{s.replies}</span> },
    { key: 'by', header: 'Sent by', value: (s) => s.sent_by },
  ];

  return (
    <div className="page">
      <PageHeader title="Email and admin log" subtitle={`Every email sent from the platform, with delivery and response counts, and every change to email, groups and sync.${isFutran ? ' Futran sees its own emails and those of its engagements.' : ' Futran sees the same log for its engagements.'}`} />
      <div className="stack">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <Card title="Emails sent">
          <div className="stack">
            <div className="log-filters">
              <SelectField label="Template" help={H.logTemplate} value={template} placeholder="All templates" onChange={(e) => setTemplate(e.target.value)} options={(sends.data?.templates ?? []).map(([v, l]) => ({ value: v, label: l }))} />
              <SelectField label="Group" help={H.logGroup} value={group} placeholder="All groups" onChange={(e) => setGroup(e.target.value)} options={(sends.data?.groups ?? []).map(([v, l]) => ({ value: v, label: l }))} />
              <SelectField label="Period" help={H.logPeriod} value={days} onChange={(e) => setDays(e.target.value)} options={[{ value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: '90', label: 'Last 90 days' }, { value: '365', label: 'Last 12 months' }, { value: '2555', label: 'Last 7 years' }]} />
            </div>
            {sends.isLoading ? <Loading /> : sends.error ? <Alert tone="danger">{errorMessage(sends.error)}</Alert> : (
              <DataGrid<SendRow>
                label="Emails sent"
                rows={sends.data!.sends}
                rowId={(s) => s.id}
                rowLabel={(s) => `${s.template} ${fmtDateTime(s.sent_at)}`}
                columns={columns}
                selectable
                bulkActions={[
                  { label: 'Remind non-responders', available: (rows) => rows.every(groupSend), run: async (rows) => { for (const s of rows) await remind(s); } },
                  { label: 'Resend bounced', run: async (rows) => { for (const s of rows) await resend(s); } },
                  { label: 'Export recipients', run: async (rows) => { for (const s of rows) await exportRecipients(s); } },
                ]}
                rowActions={(s) => [
                  { label: 'Open message', onSelect: () => setOpen({ id: s.id, tab: 'message' }) },
                  { label: 'See recipients and status', onSelect: () => setOpen({ id: s.id, tab: 'recipients' }) },
                  ...(groupSend(s) ? [{ label: "Remind people who haven't responded", onSelect: () => void remind(s) }] : []),
                  { label: 'Resend to bounced addresses', onSelect: () => void resend(s), disabled: !s.bounced },
                  { label: 'Open reply thread', onSelect: () => setOpen({ id: s.id, tab: 'replies' }) },
                  { label: 'Export', onSelect: () => void exportRecipients(s) },
                ]}
                emptyText="No emails in this period."
              />
            )}
            <p className="small muted" style={{ margin: 0 }}>Replies are read back from the sending mailbox and attached to the engagement. Opens are counted only from link clicks, never tracking pixels.</p>
          </div>
        </Card>
        <Card title="Admin log">
          <div className="stack">
            <div className="log-filters"><SelectField label="Show" help={H.logCategory} value={category} placeholder="All actions" onChange={(e) => setCategory(e.target.value)} options={admin.data?.categories ?? []} /></div>
            {admin.isLoading ? <Loading /> : !admin.data?.entries.length ? <EmptyState>No changes yet.</EmptyState> : (
              <div className="table-wrap" style={{ position: 'relative' }}>
                <table className="table">
                  <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th></tr></thead>
                  <tbody>{admin.data.entries.map((e) => <tr key={e.id}><td style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(e.at)}</td><td>{e.who}</td><td>{e.label}</td><td>{e.summary}</td></tr>)}</tbody>
                </table>
              </div>
            )}
            <p className="small muted" style={{ margin: 0 }}>The log cannot be edited or deleted. Kept for {admin.data?.retention_years ?? 7} years.</p>
          </div>
        </Card>
      </div>
      {open && <SendDialog id={open.id} tab={open.tab} onTab={(tab) => setOpen({ ...open, tab })} onClose={() => setOpen(null)} />}
    </div>
  );
}

function SendDialog({ id, tab, onTab, onClose }: { id: string; tab: 'message' | 'recipients' | 'replies'; onTab: (t: 'message' | 'recipients' | 'replies') => void; onClose: () => void }) {
  const q = useQuery({ queryKey: ['mail-send', id], queryFn: () => api.get<SendDetail>(`/mail/log/sends/${id}`) });
  const d = q.data;
  return (
    <Dialog title={d ? d.template : 'Email'} onClose={onClose} large>
      {q.isLoading ? <Loading /> : !d ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : (
        <div className="stack">
          <dl className="email-meta">
            <dt>Sent</dt><dd>{fmtDateTime(d.sent_at)} by {d.sent_by}</dd>
            <dt>From</dt><dd>{d.sender ?? '—'}</dd>
            <dt>Delivery</dt><dd>{d.mode_label}{d.subject_ref ? ` · reference ${d.subject_ref}` : ''}</dd>
            {d.steps && d.steps.length > 0 && <><dt>Expanded</dt><dd>{d.steps.map((s) => `${s.label} ${s.count < 0 ? '−' + Math.abs(s.count) : s.count}`).join(' · ')}</dd></>}
          </dl>
          <div className="tabs" role="tablist">
            {(['message', 'recipients', 'replies'] as const).map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? 'active' : ''} onClick={() => onTab(t)}>{t === 'message' ? 'Message' : t === 'recipients' ? `Recipients (${d.recipients.length})` : `Replies (${d.replies.length})`}</button>)}
          </div>
          {tab === 'message' && (
            <>
              <p style={{ margin: 0 }}><strong>{d.message.subject}</strong></p>
              {d.message.html ? <iframe className="mail-preview-frame" title="Message" sandbox="allow-popups" srcDoc={d.message.html} /> : <EmptyState>The message body is not stored for this email.</EmptyState>}
            </>
          )}
          {tab === 'recipients' && (
            <div className="table-wrap" style={{ position: 'relative' }}>
              <table className="table">
                <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Reminders</th></tr></thead>
                <tbody>{d.recipients.map((r) => <tr key={r.id}><td>{r.name ?? '—'}</td><td>{r.email}</td><td><Badge tone={STATUS_TONE[r.status] ?? 'muted'}>{STATUS_LABEL[r.status] ?? r.status}</Badge>{r.out_of_office && <> <Badge tone="warn">Out of office</Badge></>}{r.error && <div className="small muted">{r.error}</div>}</td><td className="num">{r.reminders_sent}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {tab === 'replies' && (d.replies.length === 0 ? <EmptyState>No replies yet. Replies to this email are read back from the sending mailbox.</EmptyState> : (
            <ul className="member-list">{d.replies.map((r) => <li key={r.id}><div className="who"><strong>{r.from}</strong><span className="small muted">{fmtDateTime(r.received_at)} · {r.kind === 'reply' ? 'Reply' : r.kind === 'bounce' ? 'Bounce' : 'Out of office'}</span><span className="small">{r.snippet}</span></div></li>)}</ul>
          ))}
        </div>
      )}
    </Dialog>
  );
}
