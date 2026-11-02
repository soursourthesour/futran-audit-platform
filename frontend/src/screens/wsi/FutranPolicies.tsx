import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import type { PolicyDoc } from '@/api/wsi';
import { Alert, Badge, Button, Checkbox, Dialog, FieldGroup, Loading, PageHeader, fmtDate } from '@/components/ui';
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
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
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
            { label: 'Record Futran team', disabled: !d.can.record, onSelect: () => { setEditing(p); setChosen(p.futran_team.map((t) => t.id)); } },
            { label: 'Download PDF', onSelect: () => { window.location.href = `/api/v1/futran/policies/${p.id}/pdf`; } },
          ]} />
      </div></section>
      {editing && (
        <Dialog title={`Futran team for ${editing.client_name}: ${editing.title}`} onClose={() => setEditing(null)}>
          <div className="stack">
            <FieldGroup legend="Who wrote or tailored this policy" help={H.futranTeam} className="stack-sm">
              {d.people.map((u) => <Checkbox key={u.id} label={u.name} checked={chosen.includes(u.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, u.id] : chosen.filter((x) => x !== u.id))} />)}
            </FieldGroup>
            <div className="row"><Button variant="primary" disabled={busy} onClick={async () => { setBusy(true); try { await api.put(`/futran/policies/${editing.id}/team`, { user_ids: chosen }); setMsg({ tone: 'success', text: 'Futran team recorded.' }); setEditing(null); await qc.invalidateQueries({ queryKey: ['futran-policies'] }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); } }}>Save</Button><Button onClick={() => setEditing(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
