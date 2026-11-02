import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { can, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { triggerHelp as H } from '@/help/regupdates';
import '@/styles/regupdates.css';

export type Trigger = {
  id: string; register_system_id: string; system_reference: string | null; system_name: string | null; type: string; type_label: string; source: string; source_label: string;
  detail: string | null; detected_at: string; status: string; reopened: { reference: string; sections: string[] }[]; resolution_note: string | null; resolved_by_name: string | null; resolved_at: string | null;
};
const STATUS: Record<string, { label: string; tone: 'warn' | 'navy' | 'success' | 'muted' }> = {
  open: { label: 'Open', tone: 'warn' }, in_progress: { label: 'In progress', tone: 'navy' }, resolved: { label: 'Reassessed', tone: 'success' }, dismissed: { label: 'Dismissed', tone: 'muted' },
};

function TriggerRow({ t, showSystem, canManage, onAct }: { t: Trigger; showSystem?: boolean; canManage: boolean; onAct: (t: Trigger, action: 'start' | 'resolve' | 'dismiss') => void }) {
  const open = t.status === 'open' || t.status === 'in_progress';
  return (
    <div className="ru-trigger">
      <div className="row"><Badge tone={STATUS[t.status]?.tone ?? 'muted'}>{STATUS[t.status]?.label ?? t.status}</Badge><strong>{t.type_label}</strong>
        {showSystem && <Link to={`/register/${t.register_system_id}`}>{t.system_reference} {t.system_name}</Link>}</div>
      {t.detail && <span>{t.detail}</span>}
      <span className="small muted">{t.source_label} · {fmtDate(t.detected_at)}{t.reopened.length > 0 && ` · sections ${t.reopened.flatMap((r) => r.sections).join(', ')} reopened in the audit`}</span>
      {t.resolution_note && <span className="small">{t.resolution_note}{t.resolved_by_name && ` (${t.resolved_by_name}, ${fmtDate(t.resolved_at)})`}</span>}
      {open && canManage && (
        <div className="row wrap">
          {t.status === 'open' && <Button size="sm" onClick={() => onAct(t, 'start')}>Start reassessment</Button>}
          <Button size="sm" variant="primary" onClick={() => onAct(t, 'resolve')}>Mark reassessed</Button>
          <Button size="sm" variant="ghost" onClick={() => onAct(t, 'dismiss')}>Dismiss</Button>
        </div>)}
    </div>
  );
}

function useAct(refresh: () => void) {
  const [closing, setClosing] = useState<{ t: Trigger; action: 'resolve' | 'dismiss' } | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  async function act(t: Trigger, action: 'start' | 'resolve' | 'dismiss') {
    if (action !== 'start') { setClosing({ t, action }); return; }
    try { await api.post(`/reassessment/${t.id}/start`, {}); refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const dialog = closing && <CloseDialog t={closing.t} action={closing.action} onClose={() => setClosing(null)} onDone={(text) => { setClosing(null); setMsg({ tone: 'success', text }); refresh(); }} />;
  return { act, dialog, msg };
}

function CloseDialog({ t, action, onClose, onDone }: { t: Trigger; action: 'resolve' | 'dismiss'; onClose: () => void; onDone: (m: string) => void }) {
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/reassessment/${t.id}/${action}`, { note }); onDone(action === 'resolve' ? 'Marked reassessed and added to the history log.' : 'Trigger dismissed.'); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title={action === 'resolve' ? `Mark reassessed: ${t.type_label}` : `Dismiss: ${t.type_label}`} onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <TextArea label={action === 'resolve' ? 'What was reassessed *' : 'Why no reassessment is needed *'} help={H.note} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>{action === 'resolve' ? 'Mark reassessed' : 'Dismiss'}</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** Reassessment triggers on one register system (R4 details). */
export function SystemTriggers({ systemId }: { systemId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['triggers', systemId], queryFn: () => api.get<{ rows: Trigger[]; can_manage: boolean; types: { value: string; label: string }[] }>(`/register/${systemId}/triggers`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ['triggers', systemId] }); qc.invalidateQueries({ queryKey: ['reassessment'] }); };
  const { act, dialog, msg } = useAct(refresh);
  const [raising, setRaising] = useState(false);
  const d = q.data;
  if (q.isError) return null;
  return (
    <Card title="Reassessment triggers" actions={d?.can_manage ? <Button size="sm" onClick={() => setRaising(true)}>Raise a trigger</Button> : undefined}>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!d ? <Loading /> : d.rows.length === 0 ? <EmptyState>No reassessment needed. Version, data, jurisdiction, population and vendor changes raise one automatically, as do failed monitoring checks, regulatory updates and 12 months since the last assessment.</EmptyState>
        : d.rows.map((t) => <TriggerRow key={t.id} t={t} canManage={d.can_manage} onAct={act} />)}
      {dialog}
      {raising && d && <RaiseDialog systemId={systemId} types={d.types} onClose={() => setRaising(false)} onDone={() => { setRaising(false); refresh(); }} />}
    </Card>
  );
}

function RaiseDialog({ systemId, types, onClose, onDone }: { systemId: string; types: { value: string; label: string }[]; onClose: () => void; onDone: () => void }) {
  const [type, setType] = useState(types[0]?.value ?? '');
  const [detail, setDetail] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api.post(`/register/${systemId}/triggers`, { type, detail }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog title="Raise a reassessment trigger" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="What changed *" help={H.type} value={type} onChange={(e) => setType(e.target.value)} options={types} />
        <TextField label="Detail" help={H.detail} value={detail} onChange={(e) => setDetail(e.target.value)} />
        <div className="row wrap"><Button variant="primary" disabled={busy} onClick={save}>Raise</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** Open reassessment triggers across the company, for the client home. Renders nothing when there are none. */
export function ReassessmentCard() {
  const { data: me } = useMe();
  const allowed = !!me && can(me, 'view_reassessment');
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['reassessment'], queryFn: () => api.get<{ rows: Trigger[] }>('/reassessment'), enabled: allowed });
  const { act, dialog, msg } = useAct(() => qc.invalidateQueries({ queryKey: ['reassessment'] }));
  if (!allowed || !q.data || q.data.rows.length === 0) return null;
  const manage = !!me && can(me, 'manage_reassessment');
  return (
    <Card title={`Reassessment needed · ${q.data.rows.length}`}>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {q.data.rows.map((t) => <TriggerRow key={t.id} t={t} showSystem canManage={manage} onAct={act} />)}
      {dialog}
    </Card>
  );
}
