import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Dialog, EmptyState, Loading, PageHeader, TextArea, TextField, fmtDateTime } from '@/components/ui';
import './serviceTemplates.css';

/** G-06 Service templates `/staff/admin/service-templates` (Release 2 B6). One template per engagement type; the
 *  Futran Admin maintains a draft and sends it; the Chief Auditor approves each version before use. The document
 *  templates screen (/admin/templates) is separate and unchanged. */
type Version = {
  id: string; template_id: string; version: string; status: string; status_label: string; sections_count: number; checklists_count: number; questions_count: number;
  catalog_codes: string[]; key_dates: { label: string; date: string; source?: string }[]; approved_by: string | null; approved_at: string | null; submitted_by: string | null;
  submitted_at: string | null; returned_note: string | null; change_note: string | null;
  sections?: { code: string; title: string; note?: string | null }[]; checklists?: { section?: string; code?: string; text: string; evidence?: boolean }[];
  question_codes?: string[]; questions?: { code: string; label: string }[]; deliverables?: string[]; default_stages?: string[]; report_template?: string | null;
};
type Row = {
  engagement_type: string; type_label: string; builtin: boolean; template: { id: string | null; name: string; content_owner: string | null; note: string | null } | null;
  latest: Version | null; in_use: Version | null; catalog_codes: string[]; status_label: string; versions: Version[];
};
type Library = { types: Row[]; can_manage: boolean; can_approve: boolean };
type Checklist = { items: { position: number; text: string | null }[]; note: string; can_edit: boolean };

const TONE: Record<string, 'success' | 'warn' | 'navy' | 'muted'> = { 'In use': 'success', 'In use (v0.6.1)': 'success', 'Awaiting Chief Auditor': 'warn', Draft: 'navy' };

export function ServiceTemplates() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'assurance' ? 'assurance' : 'library';
  const q = useQuery({ queryKey: ['service-templates'], queryFn: () => api.get<Library>('/service-templates') });
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['service-templates'] });
  const start = async (r: Row) => {
    try { const v = await api.post<Version>(`/service-templates/${r.template?.id}/versions`); await refresh(); setOpen(v.id); setFlash({ tone: 'success', text: `${r.template?.name} ${v.version} started as a draft.` }); } catch (e) { setFlash({ tone: 'danger', text: errorMessage(e) }); }
  };
  return (
    <div className="page st-page">
      <PageHeader title="Service templates" subtitle="One template per engagement type. The Chief Auditor approves each version before use." />
      <nav className="tabs" aria-label="Service template sections">
        <button type="button" className={tab === 'library' ? 'active' : ''} aria-current={tab === 'library' ? 'page' : undefined} onClick={() => setParams({})}>Engagement types</button>
        <button type="button" className={tab === 'assurance' ? 'active' : ''} aria-current={tab === 'assurance' ? 'page' : undefined} onClick={() => setParams({ tab: 'assurance' })}>Agent Assure check list</button>
      </nav>
      {flash && <Alert tone={flash.tone}>{flash.text}</Alert>}
      {tab === 'library' ? (
        <section className="card">
          <div className="card-body stack">
            <div className="table-wrap"><table className="table" aria-label="Service templates">
              <thead><tr><th>Engagement type</th><th>Template</th><th>Version</th><th>Sections · checklists</th><th>Catalog codes</th><th>Content owner</th><th>Status</th><th /></tr></thead>
              <tbody>{d.types.map((r) => {
                const v = r.latest;
                return (
                  <tr key={r.engagement_type}>
                    <td><code className="small">{r.engagement_type}</code><div className="small muted">{r.type_label}</div></td>
                    <td>{r.template?.name ?? '—'}{r.template?.note && <div className="small muted st-note">{r.template.note}</div>}</td>
                    <td>{r.builtin ? (r.engagement_type === 'initial_assessment' ? '1.0 + 5.1a' : '1.0') : v?.version ?? '—'}</td>
                    <td className="small">{r.builtin ? 'Question bank' : v ? `${v.sections_count} · ${v.checklists_count}${v.questions_count ? ` · ${v.questions_count} questions` : ''}` : '—'}</td>
                    <td className="small">{r.catalog_codes.join(', ') || '—'}</td>
                    <td className="small">{r.template?.content_owner ?? '—'}</td>
                    <td><Badge tone={TONE[r.status_label] ?? 'muted'}>{r.status_label}</Badge>{r.in_use && r.latest && r.in_use.id !== r.latest.id && <div className="small muted">{r.in_use.version} in use</div>}</td>
                    <td className="st-actions">{v && <Button size="sm" onClick={() => setOpen(v.id)}>Open</Button>}
                      {!r.builtin && r.template?.id && d.can_manage && (!v || v.status === 'approved') && <Button size="sm" onClick={() => start(r)}>{v ? 'New version' : 'Start a version'}</Button>}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
            <p className="small" style={{ margin: 0 }}><strong>Exports available on any signed report.</strong> Board readout pack (A-13): one-page summary, heat map, top 5 findings and roadmap, as PDF from the final report screen. PowerPoint is not produced: the platform has no PowerPoint library.</p>
          </div>
        </section>
      ) : <AssureChecklist />}
      {open && <VersionDialog id={open} lib={d} onClose={() => setOpen(null)} onDone={async (m) => { setFlash({ tone: 'success', text: m }); await refresh(); }} />}
    </div>
  );
}

const lines = (xs?: string[]) => (xs ?? []).join('\n');
const split = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean);

function VersionDialog({ id, lib, onClose, onDone }: { id: string; lib: Library; onClose: () => void; onDone: (m: string) => void }) {
  const q = useQuery({ queryKey: ['service-template-version', id], queryFn: () => api.get<Version>(`/service-template-versions/${id}`) });
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Record<string, string> | null>(null);
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  if (q.isLoading) return <Dialog title="Service template" onClose={onClose}><Loading /></Dialog>;
  if (!q.data) return <Dialog title="Service template" onClose={onClose}><Alert tone="danger">{errorMessage(q.error)}</Alert></Dialog>;
  const v = q.data;
  const row = lib.types.find((r) => r.template?.id === v.template_id);
  const draft = v.status === 'draft';
  const act = async (fn: () => Promise<unknown>, m: string) => {
    setErr(null);
    try { await fn(); await qc.invalidateQueries({ queryKey: ['service-template-version', id] }); onDone(m); setEdit(null); setNote(''); } catch (e) { setErr(errorMessage(e)); }
  };
  const begin = () => setEdit({
    sections: (v.sections ?? []).map((s) => `${s.code} | ${s.title}${s.note ? ` | ${s.note}` : ''}`).join('\n'),
    checklists: (v.checklists ?? []).map((c) => `${c.section ?? ''} | ${c.code ?? ''} | ${c.text}`).join('\n'),
    question_codes: lines(v.question_codes), deliverables: lines(v.deliverables), default_stages: lines(v.default_stages), catalog_codes: lines(v.catalog_codes),
    report_template: v.report_template ?? '', change_note: v.change_note ?? '',
  });
  const save = () => edit && act(() => api.put(`/service-template-versions/${v.id}`, {
    sections: split(edit.sections).map((l) => { const [code, title, n] = l.split('|').map((x) => x.trim()); return { code, title: title ?? code, note: n || null }; }),
    checklists: split(edit.checklists).map((l) => { const p = l.split('|').map((x) => x.trim()); return p.length >= 3 ? { section: p[0], code: p[1], text: p.slice(2).join(' | '), evidence: true } : { text: l, evidence: true }; }),
    question_codes: split(edit.question_codes), deliverables: split(edit.deliverables), default_stages: split(edit.default_stages), catalog_codes: split(edit.catalog_codes),
    report_template: edit.report_template, change_note: edit.change_note,
  }), 'Draft saved.');
  return (
    <Dialog title={`${row?.template?.name ?? 'Service template'} · ${v.version}`} onClose={onClose} large>
      <div className="stack">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><Badge tone={v.status === 'approved' ? 'success' : v.status === 'awaiting_approval' ? 'warn' : 'navy'}>{v.status_label}</Badge>
          <span className="small muted">{row?.type_label}{row?.template?.content_owner ? ` · content owner ${row.template.content_owner}` : ''}</span>
          {v.approved_by && <span className="small muted">Approved by {v.approved_by} {fmtDateTime(v.approved_at)}</span>}</div>
        {err && <Alert tone="danger">{err}</Alert>}
        {v.returned_note && draft && <Alert tone="warn">Returned by the Chief Auditor: {v.returned_note}</Alert>}
        {edit ? (
          <div className="stack">
            <TextArea label="Sections (one per line: code | title | note)" rows={5} value={edit.sections} onChange={(e) => setEdit({ ...edit, sections: e.target.value })} />
            <TextArea label="Checklist items (one per line: section | code | text)" rows={8} value={edit.checklists} onChange={(e) => setEdit({ ...edit, checklists: e.target.value })} />
            <TextArea label="Question bank questions (codes, one per line)" hint="Read through the question bank, for example 9.2.01." rows={3} value={edit.question_codes} onChange={(e) => setEdit({ ...edit, question_codes: e.target.value })} />
            <div className="grid-2">
              <TextArea label="Deliverables (one per line)" rows={3} value={edit.deliverables} onChange={(e) => setEdit({ ...edit, deliverables: e.target.value })} />
              <TextArea label="Default stages (one per line)" rows={3} value={edit.default_stages} onChange={(e) => setEdit({ ...edit, default_stages: e.target.value })} />
              <TextArea label="Catalog codes (one per line)" rows={3} value={edit.catalog_codes} onChange={(e) => setEdit({ ...edit, catalog_codes: e.target.value })} />
              <TextField label="Report template" value={edit.report_template} onChange={(e) => setEdit({ ...edit, report_template: e.target.value })} />
            </div>
            <TextField label="What changed" value={edit.change_note} onChange={(e) => setEdit({ ...edit, change_note: e.target.value })} />
            <div className="row"><Button variant="primary" onClick={save}>Save draft</Button><Button onClick={() => setEdit(null)}>Cancel</Button></div>
          </div>
        ) : (
          <div className="stack">
            {v.key_dates.length > 0 && <p className="small" style={{ margin: 0 }}><strong>Key dates:</strong> {v.key_dates.map((k) => `${k.label} ${k.date}${k.source ? ` (${k.source})` : ''}`).join('; ')}</p>}
            <div className="st-cols">
              <div><h3 className="st-h3">Sections</h3>{(v.sections ?? []).length ? <ul className="st-list">{v.sections!.map((s) => <li key={s.code}><strong>{s.title}</strong>{s.note && <div className="small muted">{s.note}</div>}</li>)}</ul> : <EmptyState>None</EmptyState>}</div>
              <div><h3 className="st-h3">Checklists</h3>{(v.checklists ?? []).length ? <ul className="st-list">{v.checklists!.map((c, i) => <li key={i} className="small">{c.text}{c.evidence && <span className="muted"> · evidence</span>}</li>)}</ul> : <EmptyState>None</EmptyState>}</div>
            </div>
            {(v.questions ?? []).length > 0 && <div><h3 className="st-h3">Question bank questions</h3><ul className="st-list">{v.questions!.map((x) => <li key={x.code} className="small"><code>{x.code}</code> {x.label}</li>)}</ul></div>}
            <p className="small" style={{ margin: 0 }}><strong>Deliverables:</strong> {(v.deliverables ?? []).join('; ') || '—'} · <strong>Default stages:</strong> {(v.default_stages ?? []).join(' → ') || '—'} · <strong>Report template:</strong> {v.report_template || '—'} · <strong>Catalog codes:</strong> {v.catalog_codes.join(', ') || '—'}</p>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
              {draft && lib.can_manage && <><Button onClick={begin}>Edit draft</Button><Button variant="primary" onClick={() => act(() => api.post(`/service-template-versions/${v.id}/submit`), `${v.version} sent to the Chief Auditor for approval.`)}>Send for approval</Button></>}
              {v.status === 'awaiting_approval' && lib.can_approve && <>
                <TextField label="Note (needed to return it)" value={note} onChange={(e) => setNote(e.target.value)} />
                <Button variant="primary" onClick={() => act(() => api.post(`/service-template-versions/${v.id}/approve`, { note }), `${v.version} approved. It is now the version in use.`)}>Approve for use</Button>
                <Button onClick={() => act(() => api.post(`/service-template-versions/${v.id}/return`, { note }), `${v.version} returned to the Futran Admin.`)}>Return</Button></>}
              {v.status === 'awaiting_approval' && !lib.can_approve && <span className="small muted">Waiting for the Chief Auditor.</span>}
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}

function AssureChecklist() {
  const q = useQuery({ queryKey: ['assurance-checklist'], queryFn: () => api.get<Checklist>('/assurance/checklist') });
  const qc = useQueryClient();
  const [items, setItems] = useState<Record<number, string> | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const cur = items ?? Object.fromEntries(d.items.map((i) => [i.position, i.text ?? '']));
  return (
    <section className="card">
      <div className="card-header"><h2>Agent Assure 15-point pre-deploy check</h2></div>
      <div className="card-body stack">
        <Alert tone="info">{d.note}</Alert>
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <ol className="st-points">{d.items.map((i) => (
          <li key={i.position}>{d.can_edit
            ? <input aria-label={`Check point ${i.position}`} className="st-input" placeholder="Not supplied yet" value={cur[i.position] ?? ''} onChange={(e) => setItems({ ...cur, [i.position]: e.target.value })} />
            : (i.text ?? <span className="muted">Not supplied yet</span>)}</li>
        ))}</ol>
        {d.can_edit && <div className="row"><Button variant="primary" disabled={!items} onClick={async () => {
          try { await api.put('/assurance/checklist', { items: Object.entries(cur).map(([p, t]) => ({ position: Number(p), text: t })) }); setItems(null); await qc.invalidateQueries({ queryKey: ['assurance-checklist'] }); setMsg({ tone: 'success', text: 'Check list saved. New Agent Assure records use these points.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
        }}>Save check list</Button></div>}
      </div>
    </section>
  );
}
