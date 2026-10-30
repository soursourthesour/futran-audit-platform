import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid, type GridColumn, type GridRowAction } from '@/components/ui/DataGrid';
import { clientAlertHelp as H } from '@/help/monitoring';
import '@/styles/monitoring.css';

type Rule = { id: string; trigger: string; when_label: string; audience_label: string; client_groups: string[]; email_label: string; approval: string; approval_label: string; active: boolean; days_before: number[]; last_sent_at: string | null; last_sent_count: number };
type Send = { id: string; rule_id: string; organization_id: string; client_name: string; change_ref: string; headline: string; subject: string; systems: string[]; todo_count: number; status: string; sent_from: string; deadline: string | null; created_at: string; sent_at: string | null; approved_by_name: string | null };
type Group = { change_ref: string; headline: string; rule_id: string; approval: string | null; when_label: string; items: Send[] };
type Preview = Send & { subject: string; html: string; text: string; from: string; to: string[]; groups: string[]; fallback: boolean };
type Msg = { tone: 'success' | 'danger'; text: string } | null;

export function ClientAlerts() {
  const { data: me } = useMe();
  const canManage = hasRole(me ?? undefined, 'chief_auditor', 'admin');
  const rules = useQuery({ queryKey: ['alert-rules'], queryFn: () => api.get<{ rules: Rule[]; groups: string[]; approvals: { value: string; label: string }[] }>('/alerts/rules'), enabled: canManage });
  const queue = useQuery({ queryKey: ['alert-queue'], queryFn: () => api.get<{ groups: Group[] }>('/alerts/queue') });
  const qc = useQueryClient();
  const [msg, setMsg] = useState<Msg>(null);
  const [editRule, setEditRule] = useState<Rule | null>(null);
  const [history, setHistory] = useState<Rule | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [editSend, setEditSend] = useState<Send | null>(null);
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['alert-rules'] }); await qc.invalidateQueries({ queryKey: ['alert-queue'] }); };
  async function setActive(rows: Rule[], active: boolean) { await api.post('/alerts/rules/bulk', { ids: rows.map((r) => r.id), active }); await refresh(); }
  async function approve(ids: string[]) {
    const out = await api.post<{ sent: number }>('/alerts/sends/approve', { ids });
    await refresh();
    setMsg({ tone: 'success', text: `${out.sent} ${out.sent === 1 ? 'alert' : 'alerts'} sent. They are in the email log.` });
  }
  async function hold(ids: string[]) { const out = await api.post<{ held: number }>('/alerts/sends/hold', { ids }); await refresh(); setMsg({ tone: 'success', text: `${out.held} held.` }); }

  const ruleCols: GridColumn<Rule>[] = [
    { key: 'when', header: 'When this happens', value: (r) => r.when_label, render: (r) => <strong>{r.when_label}</strong> },
    { key: 'who', header: 'Who gets it', value: (r) => r.audience_label },
    { key: 'group', header: 'Client group', value: (r) => r.client_groups.join(', ') },
    { key: 'email', header: 'Email', value: (r) => r.email_label },
    { key: 'approval', header: 'Approval', value: (r) => r.approval_label },
    { key: 'status', header: 'Status', value: (r) => (r.active ? 'On' : 'Off'), render: (r) => <Badge tone={r.active ? 'success' : 'muted'}>{r.active ? 'On' : 'Off'}</Badge> },
    { key: 'last', header: 'Last sent', value: (r) => r.last_sent_at ?? '', render: (r) => (r.last_sent_at ? `${fmtDate(r.last_sent_at)} · ${r.last_sent_count} ${r.last_sent_count === 1 ? 'client' : 'clients'}` : '—') },
  ];
  const ruleActions = (r: Rule): GridRowAction[] => [
    { label: 'Edit rule', onSelect: () => setEditRule(r) },
    { label: r.active ? 'Pause' : 'Turn on', onSelect: () => setActive([r], !r.active) },
    { label: 'Send history', onSelect: () => setHistory(r) },
  ];
  const sendCols: GridColumn<Send>[] = [
    { key: 'client', header: 'Client', value: (s) => s.client_name, render: (s) => <strong>{s.client_name}</strong> },
    { key: 'systems', header: 'Affected AI systems', value: (s) => s.systems.join(', '), render: (s) => (s.systems.length ? s.systems.join(', ') : <span className="muted">None listed</span>) },
    { key: 'todos', header: 'To-dos', value: (s) => s.todo_count },
    { key: 'from', header: 'Sent from', value: (s) => s.sent_from },
    { key: 'status', header: 'Status', value: (s) => s.status, render: (s) => <Badge tone={s.status === 'held' ? 'muted' : 'warn'}>{s.status === 'held' ? 'Held' : 'Ready'}</Badge> },
  ];
  return (
    <div className="page">
      <PageHeader title="Automatic client alerts" subtitle="When a rule changes, a deadline nears or a relevant case appears, the platform emails each affected client with what changed and what to do. Sent from the client's own mailbox where connected, to the client's groups." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {canManage && (
        <Card title="Alert rules">
          {rules.isLoading || !rules.data ? <Loading /> : (
            <DataGrid label="Alert rules" rows={rules.data.rules} rowId={(r) => r.id} rowLabel={(r) => r.when_label} columns={ruleCols} selectable
              bulkActions={[{ label: 'Pause', run: (rows) => setActive(rows, false) }, { label: 'Turn on', run: (rows) => setActive(rows, true) }]}
              rowActions={ruleActions} />
          )}
        </Card>
      )}
      <h2 className="section-title">Waiting to send</h2>
      {queue.isLoading ? <Loading /> : !queue.data?.groups.length ? <Card><EmptyState>Nothing is waiting. Alerts that need approval appear here when a change is approved or a briefing is queued.</EmptyState></Card> : (
        queue.data.groups.map((g) => (
          <Card key={g.change_ref} title={<h3 className="card-title">{g.headline} <span className="small muted">({g.items.length} {g.items.length === 1 ? 'client' : 'clients'})</span></h3>}>
            <DataGrid label={`Waiting: ${g.headline}`} rows={g.items} rowId={(s) => s.id} rowLabel={(s) => s.client_name} columns={sendCols} selectable
              bulkActions={[{ label: 'Approve and send', run: (rows) => approve(rows.map((r) => r.id)) }, { label: 'Hold', run: (rows) => hold(rows.map((r) => r.id)) }]}
              rowActions={(s) => [
                { label: 'Preview email', onSelect: () => setPreview(s.id) },
                { label: 'Edit email', onSelect: () => setEditSend(s) },
                { label: 'Approve and send', onSelect: () => approve([s.id]).catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
                { label: 'Hold', onSelect: () => hold([s.id]).catch((e) => setMsg({ tone: 'danger', text: errorMessage(e) })) },
              ]} />
            <p className="small muted">{g.when_label}. Each client's email lists only its own affected systems and the to-dos from the requirement records.</p>
          </Card>
        ))
      )}
      {preview && <PreviewDialog id={preview} onClose={() => setPreview(null)} onApprove={async () => { await approve([preview]); setPreview(null); }} />}
      {editSend && <EditSend s={editSend} onClose={() => setEditSend(null)} onSaved={() => { setEditSend(null); refresh(); }} />}
      {editRule && rules.data && <EditRule r={editRule} groups={rules.data.groups} approvals={rules.data.approvals} onClose={() => setEditRule(null)} onSaved={() => { setEditRule(null); refresh(); }} />}
      {history && <HistoryDialog r={history} onClose={() => setHistory(null)} />}
    </div>
  );
}

function PreviewDialog({ id, onClose, onApprove }: { id: string; onClose: () => void; onApprove: () => Promise<void> }) {
  const q = useQuery({ queryKey: ['alert-preview', id], queryFn: () => api.get<Preview>(`/alerts/sends/${id}/preview`) });
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title={q.data ? `Preview: ${q.data.client_name}` : 'Preview'} onClose={onClose} large>
      {!q.data ? <Loading /> : (
        <div className="stack">
          {err && <Alert tone="danger">{err}</Alert>}
          <dl className="kv">
            <dt>From</dt><dd>{q.data.from}</dd>
            <dt>To</dt><dd>{q.data.fallback ? `${q.data.to.join(', ')} (the client group is empty, so the Chief AI Compliance Officer)` : `${q.data.groups.join(', ')} (${q.data.to.length} ${q.data.to.length === 1 ? 'person' : 'people'})`}</dd>
            <dt>Subject</dt><dd>{q.data.subject}</dd>
          </dl>
          <iframe title="Email preview" className="email-frame" srcDoc={q.data.html} sandbox="" />
          <div className="row"><Button variant="primary" onClick={() => onApprove().catch((e) => setErr(errorMessage(e)))}>Approve and send</Button><Button onClick={onClose}>Close</Button></div>
        </div>
      )}
    </Dialog>
  );
}

function EditSend({ s, onClose, onSaved }: { s: Send; onClose: () => void; onSaved: () => void }) {
  const [subject, setSubject] = useState(s.subject);
  const [intro, setIntro] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() { setErr(null); try { await api.patch(`/alerts/sends/${s.id}`, { subject, intro }); onSaved(); } catch (e) { setErr(errorMessage(e)); } }
  return (
    <Dialog title={`Edit email: ${s.client_name}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextField label="Subject" help={H.subject} value={subject} onChange={(e) => setSubject(e.target.value)} />
        <TextArea label="Opening paragraph" help={H.intro} value={intro} onChange={(e) => setIntro(e.target.value)} rows={3} />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function EditRule({ r, groups, approvals, onClose, onSaved }: { r: Rule; groups: string[]; approvals: { value: string; label: string }[]; onClose: () => void; onSaved: () => void }) {
  const [g, setG] = useState<string[]>(r.client_groups);
  const [approval, setApproval] = useState(r.approval);
  const [label, setLabel] = useState(r.email_label);
  const [err, setErr] = useState<string | null>(null);
  async function save() { setErr(null); try { await api.patch(`/alerts/rules/${r.id}`, { client_groups: g, approval, email_label: label }); onSaved(); } catch (e) { setErr(errorMessage(e)); } }
  return (
    <Dialog title={`Edit rule: ${r.when_label}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <fieldset className="stack-sm"><legend>Client groups</legend>{groups.map((x) => <Checkbox key={x} label={x} help={x === groups[0] ? H.groups : undefined} checked={g.includes(x)} onChange={(e) => setG(e.target.checked ? [...g, x] : g.filter((y) => y !== x))} />)}</fieldset>
        <SelectField label="Approval" help={H.approval} value={approval} onChange={(e) => setApproval(e.target.value)} options={approvals} />
        <TextField label="Email" help={H.emailLabel} value={label} onChange={(e) => setLabel(e.target.value)} />
        <div className="row"><Button variant="primary" disabled={!g.length} onClick={save}>Save rule</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function HistoryDialog({ r, onClose }: { r: Rule; onClose: () => void }) {
  const q = useQuery({ queryKey: ['alert-history', r.id], queryFn: () => api.get<Send[]>(`/alerts/rules/${r.id}/history`) });
  return (
    <Dialog title={`Send history: ${r.when_label}`} onClose={onClose} large>
      {!q.data ? <Loading /> : !q.data.length ? <EmptyState>Nothing sent under this rule yet.</EmptyState> : (
        <div className="table-wrap"><table className="table"><thead><tr><th>Client</th><th>Alert</th><th>Status</th><th>Sent</th><th>Approved by</th></tr></thead>
          <tbody>{q.data.map((s) => <tr key={s.id}><td>{s.client_name}</td><td style={{ whiteSpace: 'normal' }}>{s.subject}</td><td>{s.status}</td><td>{s.sent_at ? fmtDateTime(s.sent_at) : '—'}</td><td>{s.approved_by_name ?? (s.sent_at ? 'Automatic' : '—')}</td></tr>)}</tbody></table></div>
      )}
    </Dialog>
  );
}
