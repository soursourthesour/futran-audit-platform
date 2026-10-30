import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { staffAlerts, type StaffAlert } from '@/api/monitoring';
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Loading, PageHeader, SelectField, WithHelp, fmtDateTime } from '@/components/ui';
import { staffAlertHelp as H } from '@/help/monitoring';
import '@/styles/monitoring.css';

type Setting = { scope: string; recipients_rule: string; cc_roles: string[]; when_rule: string; channels: string[]; remind_after_days: number | null; escalate_after_days: number | null };
const KIND: Record<string, [string, 'warn' | 'navy' | 'danger' | 'muted']> = { refresh_done: ['Action needed', 'warn'], review_reminder: ['Reminder', 'navy'], escalation: ['Escalation', 'danger'] };
const LABELS: Record<string, string> = { new_laws: 'New laws', amendments_dates: 'Amendments and dates', rules_guidance: 'New rules or guidance', enforcement: 'Enforcement actions', case_updates: 'Case updates' };

export function alertLine(a: StaffAlert): string {
  const parts = Object.entries(a.summary.counts ?? {}).filter(([, v]) => v).map(([k, v]) => `${LABELS[k] ?? k}: ${v}`);
  if (!parts.length) return `${a.summary.sources_read} sources read, no changes.`;
  return `${parts.join(' · ')}${a.summary.low_confidence ? ` · low confidence: ${a.summary.low_confidence}` : ''}`;
}

export function alertBadge(a: StaffAlert) {
  if (a.kind === 'refresh_done' && !a.needs_action) return <Badge tone="muted">{a.is_test ? 'Test' : 'Info'}</Badge>;
  const [label, tone] = KIND[a.kind];
  return <Badge tone={tone}>{label}</Badge>;
}

export function RefreshAlerts() {
  const { data: me } = useMe();
  const q = useQuery({ queryKey: ['staff-alerts'], queryFn: staffAlerts });
  const qc = useQueryClient();
  const canSet = hasRole(me ?? undefined, 'chief_auditor', 'admin');
  async function readAll() { await api.post('/staff/alerts/read-all'); await qc.invalidateQueries({ queryKey: ['staff-alerts'] }); }
  async function read(a: StaffAlert) { if (!a.read) { await api.post(`/staff/alerts/${a.id}/read`); await qc.invalidateQueries({ queryKey: ['staff-alerts'] }); } }
  return (
    <div className="page">
      <PageHeader title="Refresh alerts" subtitle="Every law or litigation refresh, scheduled or run by hand, ends with an alert to the Chief Auditor: in the app, by email, and as a reminder if changes wait too long." />
      <div className="split">
        <div className="main stack">
          <Card title="Alerts" actions={q.data?.unread ? <Button size="sm" onClick={readAll}>Mark all read</Button> : undefined}>
            {q.isLoading ? <Loading /> : !q.data?.items.length ? <EmptyState>No refresh alerts yet. They appear here, and under the bell, when a refresh finishes.</EmptyState> : (
              <ul className="alert-list">
                {q.data.items.map((a) => (
                  <li key={a.id} className={a.read ? '' : 'unread'}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <strong>{a.title}</strong>
                      <span className="row" style={{ gap: 6 }}>{alertBadge(a)}<span className="small muted">{fmtDateTime(a.at)}</span></span>
                    </div>
                    <p className="small" style={{ margin: '4px 0' }}>{alertLine(a)}</p>
                    <p className="small muted" style={{ margin: 0 }}>
                      {a.summary.clients_affected ? `${a.summary.clients_affected} ${a.summary.clients_affected === 1 ? 'client' : 'clients'} · ${a.summary.systems_affected} AI ${a.summary.systems_affected === 1 ? 'system' : 'systems'} affected` : 'No client affected'}
                      {a.waiting ? ` · ${a.waiting} still waiting` : ''}{a.is_copy ? ' · you were copied' : ''}{a.emailed ? ' · also emailed' : ''}
                    </p>
                    {!a.is_test && <Link className="btn btn-sm" to={a.link} onClick={() => read(a)}>{a.scope === 'litigation_refresh' ? 'Review case updates' : 'Review law changes'}</Link>}
                  </li>
                ))}
              </ul>
            )}
            <p className="small muted">Unread alerts that still need a review stay at the top until the changes are reviewed. No client sees any change until the Chief Auditor approves it.</p>
          </Card>
        </div>
        <div className="side stack">{canSet ? <SettingsCard /> : <Card title="Alert settings"><p className="small muted">The Chief Auditor and the Futran Admin set who gets these alerts.</p></Card>}</div>
      </div>
    </div>
  );
}

function SettingsCard() {
  const q = useQuery({ queryKey: ['staff-alert-settings'], queryFn: () => api.get<{ settings: Setting[]; chief_auditors: { id: string; name: string }[] }>('/staff/alerts/settings') });
  const [scope, setScope] = useState('law_refresh');
  const [s, setS] = useState<Setting | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const qc = useQueryClient();
  useEffect(() => { setS(q.data?.settings.find((x) => x.scope === scope) ?? null); }, [q.data, scope]);
  if (q.isLoading || !s) return <Card title="Alert settings"><Loading /></Card>;
  const n = q.data?.chief_auditors.length ?? 0;
  const how = s.channels.length === 2 ? 'both' : s.channels[0];
  async function save() {
    setMsg(null);
    try {
      await api.put(`/staff/alerts/settings/${scope}`, s);
      await qc.invalidateQueries({ queryKey: ['staff-alert-settings'] });
      setMsg({ tone: 'success', text: 'Settings saved.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  async function test() {
    setMsg(null);
    try {
      await api.post('/staff/alerts/test', { scope });
      await qc.invalidateQueries({ queryKey: ['staff-alerts'] });
      setMsg({ tone: 'success', text: 'Test alert sent to you.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const cc = (role: string, on: boolean) => setS({ ...s, cc_roles: on ? [...s.cc_roles.filter((r) => r !== role), role] : s.cc_roles.filter((r) => r !== role) });
  return (
    <Card title="Alert settings">
      <div className="stack">
        <div className="pills" role="tablist" aria-label="Which refresh">
          <button type="button" role="tab" className="pill" aria-selected={scope === 'law_refresh'} onClick={() => setScope('law_refresh')}>Law refresh</button>
          <button type="button" role="tab" className="pill" aria-selected={scope === 'litigation_refresh'} onClick={() => setScope('litigation_refresh')}>Litigation refresh</button>
        </div>
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.recipients}>Alert goes to</WithHelp></legend>
          <label className="check"><input type="radio" name="rec" checked={s.recipients_rule === 'all_chief_auditors'} onChange={() => setS({ ...s, recipients_rule: 'all_chief_auditors' })} /><span>All Chief Auditors ({n})</span></label>
          <label className="check"><input type="radio" name="rec" checked={s.recipients_rule === 'runner'} onChange={() => setS({ ...s, recipients_rule: 'runner' })} /><span>The Chief Auditor who ran the refresh</span></label>
        </fieldset>
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.copy}>Copy</WithHelp></legend>
          <Checkbox label="QA Reviewer" help={H.ccQa} checked={s.cc_roles.includes('qa_reviewer')} onChange={(e) => cc('qa_reviewer', e.target.checked)} />
          <Checkbox label="Futran Admin" help={H.ccAdmin} checked={s.cc_roles.includes('admin')} onChange={(e) => cc('admin', e.target.checked)} />
        </fieldset>
        <SelectField label="When" help={H.when} value={s.when_rule} onChange={(e) => setS({ ...s, when_rule: e.target.value })}
          options={[{ value: 'every', label: 'Every refresh' }, { value: 'changes', label: 'Only with changes' }, { value: 'high_impact', label: 'Only high impact or low confidence' }]} />
        <SelectField label="How" help={H.how} value={how} onChange={(e) => setS({ ...s, channels: e.target.value === 'both' ? ['in_app', 'email'] : [e.target.value] })}
          options={[{ value: 'both', label: 'In the app and by email' }, { value: 'in_app', label: 'In the app only' }, { value: 'email', label: 'Email only' }]} />
        <SelectField label="Remind if not reviewed after" help={H.remind} value={String(s.remind_after_days ?? 3)} onChange={(e) => setS({ ...s, remind_after_days: Number(e.target.value) })}
          options={[3, 5, 7].map((d) => ({ value: String(d), label: `${d} days` }))} />
        <SelectField label="Escalate after" help={H.escalate} value={s.escalate_after_days ? String(s.escalate_after_days) : 'never'} onChange={(e) => setS({ ...s, escalate_after_days: e.target.value === 'never' ? null : Number(e.target.value) })}
          options={[{ value: '7', label: '7 days' }, { value: '14', label: '14 days' }, { value: 'never', label: 'Never' }]} />
        <p className="small muted" style={{ margin: 0 }}>Each alert, reminder and escalation is written to the email log and the admin log.</p>
        <div className="row wrap"><Button onClick={test}>Send a test alert</Button><Button variant="primary" onClick={save}>Save settings</Button></div>
      </div>
    </Card>
  );
}
