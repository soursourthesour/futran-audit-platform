import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import type { PolicyDoc } from '@/api/wsi';
import { Alert, Badge, Button, Checkbox, Dialog, FieldGroup, Loading, PageHeader, TextArea, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { policyHelp as H } from '@/help/wsi';
import './wsi.css';

type Row = PolicyDoc & { client_id: string; client_name: string; review_note: string | null };

/** Futran `/client-policies`: client policies Futran was asked to review or has tailored. The Chief Auditor records who
 *  at Futran wrote or tailored each one; those people cannot be Lead Auditor on a later audit of that client. */
export function FutranPolicies() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['futran-policies'], queryFn: () => api.get<{ policies: Row[]; people: { id: string; name: string }[]; can: { record: boolean } }>('/futran/policies') });
  const [editing, setEditing] = useState<Row | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const { data: me } = useMe();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const removed = editing ? editing.futran_team.filter((t) => !chosen.includes(t.id)) : [];
  const self = me?.user.id;
  return (
    <div className="page">
      <PageHeader title="Client policy reviews" subtitle="Policies clients asked Futran to review or tailor. Record the Futran team that worked on each one: the independence rule stops them leading a later audit of that client." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <section className="card"><div className="card-body">
        <DataGrid label="Client policies" rows={d.policies} rowId={(p) => p.id} rowLabel={(p) => `${p.client_name}: ${p.title}`} emptyText="No client has asked Futran to review a policy."
          search={{ label: 'Search', text: (p) => `${p.client_name} ${p.title}` }}
          columns={[
            { key: 'client', header: 'Client', value: (p) => p.client_name },
            { key: 'policy', header: 'Policy', value: (p) => p.title, render: (p) => <><strong>{p.title}</strong><div className="small muted">Version {p.version_no} · {p.status_label}</div>{p.review_note && <div className="small">“{p.review_note}”</div>}</> },
            { key: 'asked', header: 'Review requested', value: (p) => p.futran_review_requested_at ?? '', render: (p) => fmtDate(p.futran_review_requested_at) },
            { key: 'team', header: 'Futran team', value: (p) => p.futran_team.map((t) => t.name).join(', '), render: (p) => p.futran_team.length ? p.futran_team.map((t) => <Badge key={t.id} tone="navy">{t.name}</Badge>) : <span className="muted">Not recorded</span> },
          ]}
          rowActions={(p) => [
            { label: 'Record Futran team', disabled: !d.can.record, onSelect: () => { setEditing(p); setChosen(p.futran_team.map((t) => t.id)); setReason(''); } },
            { label: 'Download PDF', onSelect: () => { window.location.href = `/api/v1/futran/policies/${p.id}/pdf`; } },
          ]} />
      </div></section>
      {editing && (
        <Dialog title={`Futran team for ${editing.client_name}: ${editing.title}`} onClose={() => setEditing(null)}>
          <div className="stack">
            <FieldGroup legend="Who wrote or tailored this policy" help={H.futranTeam} className="stack-sm">
              {d.people.map((u) => {
                const locked = u.id === self && !!editing.futran_team.find((t) => t.id === u.id);
                return <Checkbox key={u.id} label={locked ? `${u.name} (you cannot remove yourself; another Chief Auditor can)` : u.name} checked={chosen.includes(u.id)} disabled={locked}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, u.id] : chosen.filter((x) => x !== u.id))} />;
              })}
            </FieldGroup>
            {removed.length > 0 && <TextArea label={`Why remove ${removed.map((t) => t.name).join(', ')}`} help="Removing someone from the authors lets them lead a later audit of this client. The reason is kept in the audit log." rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
            <div className="row"><Button variant="primary" disabled={busy || (removed.length > 0 && !reason.trim())} onClick={async () => { setBusy(true); try { await api.put(`/futran/policies/${editing.id}/team`, { user_ids: chosen, reason: reason.trim() || null }); setMsg({ tone: 'success', text: 'Futran team recorded.' }); setEditing(null); await qc.invalidateQueries({ queryKey: ['futran-policies'] }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); } }}>Save</Button><Button onClick={() => setEditing(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
