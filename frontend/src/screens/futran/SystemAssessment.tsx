import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, ButtonLink, Card, Loading, PageHeader, TextField, fileUrl } from '@/components/ui';
import { QuestionCard, type DraftFinding, type FileRef, type QuestionView, type SaveBody } from '@/components/QuestionCard';

export type Section = { code: string; title: string; answered: number; applicable: number; note?: string | null };
type ChecklistRow = { code: string; section: string; section_title: string; text: string; maturity_domain: string; pending_review: boolean; confirmed: boolean; evidence: FileRef[]; auditor_note: string | null };
export type Assessment = {
  target: { engagement_id: string; client_id: string; audit_ref: string; client: string; system: { id: string; reference_id: string; name: string; built_by: string | null; assessment_depth: string; status: string } | null };
  sections: Section[]; questions: QuestionView[]; completion: { answered: number; applicable: number; pct: number }; locked: boolean;
  checklists?: ChecklistRow[]; draft_findings?: DraftFinding[]; evidence_files?: FileRef[];
};

const BUILT: Record<string, string> = { in_house: 'in-house', vendor: 'vendor', open_source_customized: 'open source (customised)', hybrid: 'hybrid' };

/** Futran view of one system's assessment (or, with no systemId, the engagement-level §4 questions). */
export function SystemAssessment() {
  const { systemId, clientId } = useParams();
  const base = systemId ? `/systems/${systemId}` : `/clients/${clientId}`;
  const key = ['assessment', base];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Assessment>(`${base}/assessment`) });
  const [section, setSection] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const s = d.target.system;
  const checklistSections = [...new Set((d.checklists ?? []).map((c) => c.section))];
  const nav = [...d.sections.map((x) => ({ key: x.code, label: `§${x.code} ${x.title}`, count: `${x.answered}/${x.applicable}` })),
    ...(checklistSections.length ? [{ key: 'checklists', label: `Checklists ${checklistSections.join(', ')}`, count: `${(d.checklists ?? []).filter((c) => c.confirmed).length}/${(d.checklists ?? []).length}` }] : []),
    { key: 'drafts', label: 'Draft findings', count: String(d.draft_findings?.length ?? 0) }];
  const current = section ?? d.sections[0]?.code ?? 'checklists';
  const sec = d.sections.find((x) => x.code === current);
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const save = (code: string) => async (body: SaveBody) => { await api.put(`${base}/responses/${code}`, body); await refresh(); };
  const verify = async (id: string) => { await api.post(`/responses/${id}/verify`); await refresh(); };
  const upload = async (file: File) => { const form = new FormData(); form.append('file', file); const f = await api.upload<FileRef>(`${base}/evidence`, form); await refresh(); return f; };
  async function verifySection() {
    setMsg(null);
    try { const r = await api.post<{ verified: number }>(`${base}/sections/${current}/verify`); await refresh(); setMsg({ tone: 'success', text: `${r.verified} answers verified.` }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const idx = nav.findIndex((n) => n.key === current);
  const next = nav[idx + 1];
  return (
    <div className="page">
      <PageHeader title={s ? s.name : 'Governance and accountability (§4)'}
        crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${d.target.client_id}`, label: `${d.target.client} · ${d.target.audit_ref}` }, { to: `/clients/${d.target.client_id}/systems`, label: 'AI systems' }, { label: s ? s.reference_id : '§4' }]}
        subtitle={s ? <>Built by {s.built_by ? BUILT[s.built_by] : <strong>not set — choose it on the systems register to see the right questions</strong>} · {s.assessment_depth} assessment · Template v1.0 + Addendum 5.1a{s.built_by === 'vendor' ? ' · Vendor assurance replaces §6.1 and §6.3' : ''}</> : 'Engagement-level questions shared by every system.'}
        actions={<><span className="small muted">{d.completion.answered}/{d.completion.applicable} answered · {d.completion.pct}%</span>{s && <ButtonLink to={`/systems/${s.id}/score`}>View risk score</ButtonLink>}</>} />
      {d.locked && <Alert tone="info">This assessment is locked. Answers can no longer change.</Alert>}
      {(d.draft_findings?.length ?? 0) > 0 && current !== 'drafts' && (
        <Alert tone="warn"><div className="row" style={{ justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}><span><strong>{d.draft_findings!.length} draft finding{d.draft_findings!.length === 1 ? '' : 's'}</strong> raised by answers. Keep or dismiss each one.</span><Button size="sm" onClick={() => setSection('drafts')}>Review</Button></div></Alert>
      )}
      <div className="assess" style={{ marginTop: 16 }}>
        <nav className="assess-nav" aria-label="Sections">
          {nav.map((n) => <button key={n.key} type="button" aria-current={n.key === current} onClick={() => { setSection(n.key); setMsg(null); }}><span>{n.label}</span><span className="count">{n.count}</span></button>)}
        </nav>
        <div>
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          {sec && (
            <>
              <h2 style={{ margin: '0 0 8px' }}>§{sec.code} {sec.title}</h2>
              {sec.note && <div className="intern-note" style={{ marginBottom: 12 }}><strong>Intern note:</strong> {sec.note}</div>}
              {d.questions.filter((x) => x.sub_section === current).map((x) => (
                <QuestionCard key={x.id} q={x} futran locked={d.locked} evidenceFiles={d.evidence_files ?? []} drafts={d.draft_findings ?? []} onSave={save(x.code)} onVerify={verify} onUpload={upload} />
              ))}
            </>
          )}
          {current === 'checklists' && <Checklists base={base} rows={d.checklists ?? []} files={d.evidence_files ?? []} locked={d.locked} onUpload={upload} onDone={refresh} />}
          {current === 'drafts' && <Drafts rows={d.draft_findings ?? []} onDone={refresh} />}
          <div className="row" style={{ justifyContent: 'space-between', marginTop: 16 }}>
            <span />
            <div className="row" style={{ gap: 8 }}>
              {sec && !d.locked && <Button onClick={verifySection}>Mark section verified</Button>}
              {next && <Button variant="primary" onClick={() => { setSection(next.key); setMsg(null); window.scrollTo(0, 0); }}>Next: {next.label}</Button>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Checklists({ base, rows, files, locked, onUpload, onDone }: { base: string; rows: ChecklistRow[]; files: FileRef[]; locked: boolean; onUpload: (f: File) => Promise<FileRef>; onDone: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [linking, setLinking] = useState<Record<string, string[]>>({});
  async function tick(c: ChecklistRow, confirmed: boolean) {
    setErr(null);
    try { await api.put(`${base}/checklist/${c.code}`, { confirmed, evidence_ids: linking[c.code] ?? c.evidence.map((f) => f.id) }); onDone(); } catch (e) { setErr(`${c.code}: ${errorMessage(e)}`); }
  }
  const groups = [...new Set(rows.map((r) => r.section))];
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>Tick an item only once you have seen the evidence. Each tick needs at least one linked file.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      {groups.map((g) => (
        <Card key={g} title={`Checklist ${g} · ${rows.find((r) => r.section === g)?.section_title}`}>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {rows.filter((r) => r.section === g).map((c) => {
              const linked = linking[c.code] ?? c.evidence.map((f) => f.id);
              return (
                <li key={c.code} style={{ padding: '10px 0', borderTop: '1px solid var(--line-soft)' }} className="stack-sm">
                  <div className="row" style={{ justifyContent: 'space-between', gap: 12 }}>
                    <label className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
                      <input type="checkbox" checked={c.confirmed} disabled={locked} onChange={(e) => tick(c, e.target.checked)} style={{ marginTop: 4 }} />
                      <span><span className="small muted">{c.code}</span> {c.text}{c.pending_review && <> <Badge tone="muted">Awaiting Futran review</Badge></>}</span>
                    </label>
                    <span className="small muted" style={{ whiteSpace: 'nowrap' }}>{linked.length ? `${linked.length} file${linked.length === 1 ? '' : 's'}` : 'No evidence'}</span>
                  </div>
                  {!locked && (
                    <div className="small row" style={{ gap: 8, flexWrap: 'wrap', paddingLeft: 26 }}>
                      {linked.map((id) => <span key={id} className="chip"><a href={fileUrl(id)}>{files.find((f) => f.id === id)?.filename ?? 'file'}</a></span>)}
                      <select className="select" style={{ maxWidth: 240 }} value="" aria-label={`Link evidence to ${c.code}`} onChange={(e) => e.target.value && setLinking({ ...linking, [c.code]: [...linked, e.target.value] })}>
                        <option value="">Link evidence…</option>
                        {files.filter((f) => !linked.includes(f.id)).map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
                      </select>
                      <label className="linklike">Upload<input type="file" hidden onChange={async (e) => { const file = e.target.files?.[0]; if (file) { try { const f = await onUpload(file); setLinking({ ...linking, [c.code]: [...linked, f.id] }); } catch (ex) { setErr(errorMessage(ex)); } } }} /></label>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function Drafts({ rows, onDone }: { rows: DraftFinding[]; onDone: () => void }) {
  const [reason, setReason] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function act(d: DraftFinding, dismiss: boolean) {
    setErr(null);
    try { await api.post(`/draft-findings/${d.id}/${dismiss ? 'dismiss' : 'confirm'}`, dismiss ? { reason: reason[d.id] ?? '' } : undefined); onDone(); } catch (e) { setErr(`${d.ref}: ${errorMessage(e)}`); }
  }
  if (!rows.length) return <Card title="Draft findings"><p className="small muted" style={{ margin: 0 }}>No draft findings. Answers that match a finding rule raise one here; the client never sees them.</p></Card>;
  return (
    <Card title="Draft findings">
      {err && <Alert tone="danger">{err}</Alert>}
      <p className="small muted">Raised automatically by answers. Keep the ones that stand; dismiss the rest with a reason. The client never sees drafts.</p>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.map((d) => (
          <li key={d.id} style={{ padding: '10px 0', borderTop: '1px solid var(--line-soft)' }} className="stack-sm">
            <div><strong>{d.ref}</strong> · {d.title} <Badge tone={d.severity === 'high' || d.severity === 'critical' ? 'danger' : 'warn'}>{d.severity}</Badge> <span className="small muted">from {d.question_code}{d.not_yet_in_place ? ' (not yet in place)' : ''}</span>{d.confirmed && <> <Badge tone="success">Kept</Badge></>}</div>
            <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 220 }}><TextField label="Reason to dismiss" value={reason[d.id] ?? ''} onChange={(e) => setReason({ ...reason, [d.id]: e.target.value })} /></div>
              {!d.confirmed && <Button variant="primary" onClick={() => act(d, false)}>Keep</Button>}
              <Button onClick={() => act(d, true)}>Dismiss</Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
