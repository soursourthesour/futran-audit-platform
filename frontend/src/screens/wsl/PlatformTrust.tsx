import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import type { SocControlRow, TrustPage } from '@/api/wsl';
import { Alert, Badge, Button, Card, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { trustHelp as H } from '@/help/wsl';
import '@/styles/wsl.css';

const STONE: Record<string, 'muted' | 'navy' | 'success' | 'warn' | 'default'> = { not_started: 'muted', in_progress: 'navy', implemented: 'success', tested: 'success', not_applicable: 'default' };

/** Futran Admin > Platform trust `/staff/admin/trust` (spec §21 F19): the SOC 2 readiness register and the platform's own
 *  AI features, registered in Futran's organization and audited with the same template. */
export function PlatformTrust() {
  const q = useQuery({ queryKey: ['platform-trust'], queryFn: () => api.get<TrustPage>('/staff/admin/trust') });
  const qc = useQueryClient();
  const [editing, setEditing] = useState<SocControlRow | 'new' | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const done = (d.summary.implemented ?? 0) + (d.summary.tested ?? 0);
  return (
    <div className="page">
      <PageHeader title="Platform trust" subtitle="SOC 2 Type II readiness for the Futran Audit Platform, and the platform's own AI features, registered and audited like a client's."
        actions={d.can_edit ? <Button variant="primary" onClick={() => setEditing('new')}>Add control</Button> : undefined} />
      {flash && <Alert tone="success">{flash}</Alert>}
      <div className="grid-tiles" style={{ marginTop: 8 }}>
        <div className="tile"><div className="label">Controls</div><div className="value">{d.summary.total}</div></div>
        <div className="tile"><div className="label">In place</div><div className="value">{done}</div></div>
        <div className="tile"><div className="label">In progress</div><div className="value">{d.summary.in_progress ?? 0}</div></div>
        <div className="tile"><div className="label">Not started</div><div className="value">{d.summary.not_started ?? 0}</div></div>
        <div className="tile"><div className="label">Review overdue</div><div className="value">{d.summary.review_overdue}</div></div>
      </div>
      <Card title="SOC 2 readiness register">
        <DataGrid label="SOC 2 controls" rows={d.controls} rowId={(c) => c.id} rowLabel={(c) => `${c.code} ${c.title}`}
          columns={[
            { key: 'code', header: 'Reference', value: (c) => c.code, width: '90px' },
            { key: 'title', header: 'Control', value: (c) => c.title, render: (c) => <><strong>{c.title}</strong>{c.description && <div className="small muted">{c.description}</div>}</> },
            { key: 'criterion', header: 'Criteria', value: (c) => c.criterion_label ?? c.criterion },
            { key: 'owner', header: 'Owner', value: (c) => c.owner ?? '', render: (c) => c.owner ?? <span className="muted">Not assigned</span> },
            { key: 'status', header: 'Status', value: (c) => c.status_label ?? c.status, render: (c) => <Badge tone={STONE[c.status]}>{c.status_label}</Badge> },
            { key: 'evidence', header: 'Evidence', value: (c) => c.evidence_link ?? '', render: (c) => (c.evidence_link ? (/^https?:\/\//i.test(c.evidence_link) ? <a href={c.evidence_link} target="_blank" rel="noreferrer noopener">Open</a> : c.evidence_link) : <span className="muted">—</span>) },
            { key: 'review', header: 'Last review', value: (c) => c.last_reviewed_on ?? '', render: (c) => <>{fmtDate(c.last_reviewed_on)}{c.review_overdue && <> <Badge tone="danger">Overdue</Badge></>}{c.next_review_on && !c.review_overdue && <div className="small muted">Next {fmtDate(c.next_review_on)}</div>}</> },
          ]}
          filters={[
            { key: 'criterion', label: 'Criteria', options: d.criteria, test: (c, v) => c.criterion === v },
            { key: 'status', label: 'Status', options: d.statuses, test: (c, v) => c.status === v },
          ]}
          search={{ label: 'Search controls', text: (c) => `${c.code} ${c.title} ${c.owner ?? ''}` }}
          selectable={d.can_edit}
          bulkActions={d.can_edit ? d.statuses.map((s) => ({ label: `Mark ${s.label.toLowerCase()}`, run: async (rows: SocControlRow[]) => { await Promise.all(rows.map((c) => api.patch(`/staff/admin/trust/controls/${c.id}`, { status: s.value }))); await qc.invalidateQueries({ queryKey: ['platform-trust'] }); setFlash(`${rows.length} controls updated.`); } })) : undefined}
          rowActions={d.can_edit ? (c) => [{ label: 'Edit', onSelect: () => setEditing(c) }] : undefined}
        />
      </Card>
      <Card title="The platform's own AI">
        <p className="small muted" style={{ marginTop: 0 }}>Each AI feature of the platform is an AI system in Futran's own register. Every suggestion it makes is accepted or rejected by a named person and logged.</p>
        <ul className="list-rows" style={{ margin: 0 }}>
          {d.ai_systems.map((s) => <li key={s.id} style={{ display: 'block' }}><strong>{s.reference} {s.name}</strong> <Badge tone={s.stage === 'live' ? 'success' : 'navy'}>{s.stage === 'live' ? 'Live' : s.stage === 'in_development' ? 'In development' : s.stage}</Badge>{s.risk_tier && <span className="small muted"> · Tier {s.risk_tier}</span>}<div className="small muted">{s.purpose}</div><div className="small muted">{s.ai_provider === 'anthropic' ? 'Anthropic' : s.ai_provider} · {s.model_name}</div></li>)}
        </ul>
      </Card>
      <Card title="Trust Center">
        {d.trust_center ? <p style={{ margin: 0 }}>Futran's public Trust Center page: <a href={d.trust_center.link} target="_blank" rel="noreferrer noopener">{d.trust_center.link}</a></p>
          : <p className="small muted" style={{ margin: 0 }}>Futran's public Trust Center page is published from the Trust Center module once it is set up for Futran's own organization. Items appear there only after they are approved.</p>}
      </Card>
      {editing && <ControlDialog control={editing === 'new' ? null : editing} d={d} onClose={() => setEditing(null)} onSaved={async (m) => { setEditing(null); await qc.invalidateQueries({ queryKey: ['platform-trust'] }); setFlash(m); }} />}
    </div>
  );
}

function ControlDialog({ control, d, onClose, onSaved }: { control: SocControlRow | null; d: TrustPage; onClose: () => void; onSaved: (m: string) => void }) {
  const [v, setV] = useState({ code: control?.code ?? '', criterion: control?.criterion ?? 'security', title: control?.title ?? '', description: control?.description ?? '', owner_id: control?.owner_id ?? '',
    status: control?.status ?? 'not_started', evidence_link: control?.evidence_link ?? '', last_reviewed_on: control?.last_reviewed_on ?? '', review_months: String(control?.review_months ?? 12), notes: control?.notes ?? '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null); setFe({});
    const body = { title: v.title, description: v.description, owner_id: v.owner_id || null, status: v.status, evidence_link: v.evidence_link, last_reviewed_on: v.last_reviewed_on || null, review_months: Number(v.review_months) || 12, notes: v.notes };
    try {
      if (control) await api.patch(`/staff/admin/trust/controls/${control.id}`, body);
      else await api.post('/staff/admin/trust/controls', { ...body, code: v.code, criterion: v.criterion });
      onSaved(control ? `${control.code} saved.` : `${v.code.toUpperCase()} added.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Dialog title={control ? `${control.code} ${control.title}` : 'Add control'} onClose={onClose} wide>
      <div className="stack">
        {!control && (
          <div className="grid-2">
            <TextField label="Reference *" help={H.code} value={v.code} onChange={(e) => setV({ ...v, code: e.target.value })} error={fe.code} maxLength={12} />
            <SelectField label="Criteria *" value={v.criterion} options={d.criteria} onChange={(e) => setV({ ...v, criterion: e.target.value })} error={fe.criterion} />
          </div>
        )}
        <TextField label="Control *" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} error={fe.title} maxLength={200} />
        <TextArea label="What it means here" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
        <div className="grid-2">
          <SelectField label="Owner" help={H.owner} value={v.owner_id} placeholder="Not assigned" options={d.people.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setV({ ...v, owner_id: e.target.value })} error={fe.owner_id} />
          <SelectField label="Status" help={H.status} value={v.status} options={d.statuses} onChange={(e) => setV({ ...v, status: e.target.value })} error={fe.status} />
        </div>
        <TextField label="Evidence" help={H.evidence} value={v.evidence_link} onChange={(e) => setV({ ...v, evidence_link: e.target.value })} error={fe.evidence_link} maxLength={500} />
        <div className="grid-2">
          <TextField label="Last review" help={H.reviewed} type="date" value={v.last_reviewed_on} onChange={(e) => setV({ ...v, last_reviewed_on: e.target.value })} error={fe.last_reviewed_on} />
          <TextField label="Review every (months)" help={H.months} type="number" min={1} max={36} value={v.review_months} onChange={(e) => setV({ ...v, review_months: e.target.value })} />
        </div>
        <TextArea label="Notes" help={H.notes} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} />
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
