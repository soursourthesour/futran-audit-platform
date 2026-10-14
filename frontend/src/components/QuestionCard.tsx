import { useState } from 'react';
import { errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Checkbox, SelectField, TextArea, TextField, fileUrl } from '@/components/ui';

export type Option = { value: string; label: string };
export type FileRef = { id: string; filename: string };
export type ClientResponse = { value: unknown; status: string; na_reason: string | null; detail: string | null; evidence: FileRef[] };
export type FutranResponse = ClientResponse & {
  id: string; source_person_name: string | null; source_person_title: string | null; answered_by: string | null; answered_side: 'client' | 'futran' | null; answered_at: string | null;
  verified: boolean; verified_by: string | null; client_value: unknown; client_status: string | null; client_detail: string | null; client_na_reason: string | null;
};
export type QuestionView = {
  id: string; code: string; section: string; sub_section: string; section_title: string; label: string; help_text: string | null; type: string; options: Option[] | null;
  detail_label: string | null; required: boolean; respondent: 'client' | 'auditor'; evidence_required: boolean; response: ClientResponse | FutranResponse | null;
};
export type DraftFinding = { id: string; finding_id: string; ref: string; title: string; severity: string; question_code: string; not_yet_in_place: boolean; confirmed: boolean };
export type SaveBody = { value: unknown; status: string; na_reason?: string; detail?: string; evidence_ids?: string[]; source_person_name?: string; source_person_title?: string; verified?: boolean };

const SEVERITY_TONE: Record<string, 'danger' | 'warn' | 'navy' | 'muted'> = { critical: 'danger', high: 'danger', medium: 'warn', low: 'navy', observation: 'muted' };
const CHOICE_TYPES = new Set(['single', 'yes_no', 'yes_no_unknown']);

export function displayValue(q: QuestionView, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const label = (x: unknown) => q.options?.find((o) => o.value === String(x))?.label ?? String(x);
  if (Array.isArray(v)) return v.map(label).join(', ');
  if (typeof v === 'object') { const p = v as { name?: string; title?: string }; return [p.name, p.title].filter(Boolean).join(' · '); }
  return label(v);
}

function ValueInput({ q, value, onChange, error, disabled }: { q: QuestionView; value: unknown; onChange: (v: unknown) => void; error?: string; disabled?: boolean }) {
  const opts = q.options ?? [];
  if (CHOICE_TYPES.has(q.type)) {
    if (opts.length <= 4) {
      return (
        <fieldset disabled={disabled}>
          <legend className="sr-only">{q.label}</legend>
          <div className="row" role="radiogroup" style={{ gap: 6, flexWrap: 'wrap' }}>
            {opts.map((o) => <label key={o.value} className="radio-pill"><input type="radio" name={q.id} checked={value === o.value} onChange={() => onChange(o.value)} />{o.label}</label>)}
          </div>
          {error && <div className="small" style={{ color: 'var(--danger)' }}>{error}</div>}
        </fieldset>
      );
    }
    return <SelectField label="Answer" value={(value as string) ?? ''} placeholder="Choose" options={opts} onChange={(e) => onChange(e.target.value)} error={error} disabled={disabled} />;
  }
  if (q.type === 'multi') {
    const list = Array.isArray(value) ? (value as string[]) : [];
    return (
      <fieldset disabled={disabled}>
        <legend className="sr-only">{q.label}</legend>
        <div className="grid-2">{opts.map((o) => <Checkbox key={o.value} label={o.label} checked={list.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...list, o.value] : list.filter((x) => x !== o.value))} />)}</div>
        {error && <div className="small" style={{ color: 'var(--danger)' }}>{error}</div>}
      </fieldset>
    );
  }
  if (q.type === 'person') {
    const p = (value as { name?: string; title?: string } | null) ?? {};
    return (
      <div className="grid-2">
        <TextField label="Name" value={p.name ?? ''} onChange={(e) => onChange({ ...p, name: e.target.value })} error={error} disabled={disabled} />
        <TextField label="Job title" value={p.title ?? ''} onChange={(e) => onChange({ ...p, title: e.target.value })} disabled={disabled} />
      </div>
    );
  }
  if (q.type === 'long_text') return <TextArea label="Answer" value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} error={error} disabled={disabled} />;
  const type = q.type === 'date' ? 'date' : q.type === 'number' || q.type === 'percent' ? 'number' : 'text';
  return <TextField label={q.type === 'percent' ? 'Answer (%)' : 'Answer'} type={type} value={(value as string | number | undefined) ?? ''} onChange={(e) => onChange(e.target.value)} error={error} disabled={disabled} />;
}

/** One question with the template's golden rules: N/A needs a reason, "we plan to" is saved as not yet in place,
 * and an auditor's verified interview answer names its source person. */
export function QuestionCard({ q, futran, locked, evidenceFiles, drafts, onSave, onVerify, onUpload }: {
  q: QuestionView; futran: boolean; locked: boolean; evidenceFiles: FileRef[]; drafts: DraftFinding[];
  onSave: (body: SaveBody) => Promise<void>; onVerify?: (responseId: string) => Promise<void>; onUpload?: (file: File) => Promise<FileRef>;
}) {
  const r = q.response as FutranResponse | ClientResponse | null;
  const fr = futran ? (r as FutranResponse | null) : null;
  const [value, setValue] = useState<unknown>(r?.value ?? null);
  const [status, setStatus] = useState<string>(r?.status && r.status !== 'unanswered' ? r.status : 'answered');
  const [naReason, setNaReason] = useState(r?.na_reason ?? '');
  const [detail, setDetail] = useState(r?.detail ?? '');
  const [evidence, setEvidence] = useState<string[]>((r?.evidence ?? []).map((f) => f.id));
  const [src, setSrc] = useState({ name: fr?.source_person_name ?? '', title: fr?.source_person_title ?? '' });
  const [verified, setVerified] = useState<boolean>(fr?.verified ?? false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const answered = !!r && r.status !== 'unanswered';
  const clientDiffers = fr && fr.client_status && (JSON.stringify(fr.client_value) !== JSON.stringify(fr.value) || fr.client_status !== fr.status);
  const myDrafts = drafts.filter((d) => d.question_code === q.code);

  async function save() {
    setErr(null); setFe({}); setSaved(false); setBusy(true);
    const body: SaveBody = { value: status === 'na' ? null : value, status, na_reason: status === 'na' ? naReason : undefined, detail: detail || undefined, evidence_ids: evidence };
    if (futran) Object.assign(body, { source_person_name: src.name, source_person_title: src.title, verified });
    try { await onSave(body); setSaved(true); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  async function upload(file: File) {
    if (!onUpload) return;
    try { const f = await onUpload(file); setEvidence((ev) => [...ev, f.id]); } catch (e) { setErr(errorMessage(e)); }
  }

  return (
    <div className="card question-card" id={`q-${q.code}`}>
      <div className="row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div className="small muted">{q.code}{q.required ? ' · Required' : ''}{futran && q.respondent === 'auditor' ? ' · Auditor only' : ''}{q.evidence_required ? ' · Evidence expected' : ''}</div>
        <div className="row" style={{ gap: 6 }}>
          {myDrafts.map((d) => <Badge key={d.id} tone={SEVERITY_TONE[d.severity] ?? 'muted'}>Draft finding {d.ref} · {d.severity}</Badge>)}
          {fr?.verified && <Badge tone="success">Verified</Badge>}
          {futran && answered && fr?.answered_side === 'client' && !fr.verified && <Badge tone="navy">Client pre-filled</Badge>}
        </div>
      </div>
      <h3 style={{ margin: '4px 0 2px', fontSize: 17 }}>{q.label}</h3>
      {q.help_text && <p className="small muted" style={{ margin: '0 0 8px' }}>{q.help_text}</p>}
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="stack-sm">
        <div className="row" role="radiogroup" aria-label="Answer status" style={{ gap: 6, flexWrap: 'wrap' }}>
          {[['answered', 'Answered'], ['not_yet_in_place', 'Planned → not yet in place'], ['na', 'Not applicable']].map(([k, label]) => (
            <label key={k} className="radio-pill"><input type="radio" name={`${q.id}-status`} checked={status === k} onChange={() => setStatus(k)} disabled={locked} />{label}</label>
          ))}
        </div>
        {status === 'na' ? (
          <TextField label="Why it does not apply" value={naReason} onChange={(e) => setNaReason(e.target.value)} error={fe.na_reason} disabled={locked} />
        ) : (
          <>
            {status === 'answered' && <ValueInput q={q} value={value} onChange={setValue} error={fe.value} disabled={locked} />}
            <TextArea label={status === 'not_yet_in_place' ? 'What is planned, and by when' : (q.detail_label ?? 'Answer detail (optional)')} value={detail} onChange={(e) => setDetail(e.target.value)} disabled={locked} />
          </>
        )}
        {futran && (
          <div className="grid-2">
            <TextField label="Source person" value={src.name} onChange={(e) => setSrc({ ...src, name: e.target.value })} error={fe.source_person_name} disabled={locked} help="Who gave this answer in interview." />
            <TextField label="Source title" value={src.title} onChange={(e) => setSrc({ ...src, title: e.target.value })} error={fe.source_person_title} disabled={locked} />
          </div>
        )}
        <div className="small">
          <strong>Evidence</strong>{' '}
          {evidence.length === 0 ? <span className="muted">None linked</span> : evidence.map((id) => {
            const f = evidenceFiles.find((x) => x.id === id) ?? r?.evidence.find((x) => x.id === id);
            return <span key={id} className="chip">{f ? <a href={fileUrl(id)}>{f.filename}</a> : 'file'}{!locked && <button type="button" className="linklike" aria-label="Remove" onClick={() => setEvidence(evidence.filter((x) => x !== id))}> ×</button>}</span>;
          })}
          {!locked && futran && evidenceFiles.filter((f) => !evidence.includes(f.id)).length > 0 && (
            <select className="select" style={{ maxWidth: 260, marginLeft: 8 }} value="" aria-label="Link evidence" onChange={(e) => e.target.value && setEvidence([...evidence, e.target.value])}>
              <option value="">Link evidence…</option>
              {evidenceFiles.filter((f) => !evidence.includes(f.id)).map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
            </select>
          )}
          {!locked && onUpload && <label className="linklike" style={{ marginLeft: 8 }}>Upload<input type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>}
        </div>
        {clientDiffers && <div className="small muted">Client pre-filled: {fr!.client_status === 'na' ? `N/A (${fr!.client_na_reason})` : fr!.client_status === 'not_yet_in_place' ? 'not yet in place' : displayValue(q, fr!.client_value)}</div>}
        {!locked && (
          <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button size="sm" variant="primary" onClick={save} disabled={busy}>Save</Button>
            {futran && <Checkbox label="Verified" checked={verified} onChange={(e) => setVerified(e.target.checked)} />}
            {futran && fr && answered && !fr.verified && onVerify && fr.answered_side === 'client' && <Button size="sm" variant="ghost" onClick={() => onVerify(fr.id).catch((e) => setErr(errorMessage(e)))}>Verify client answer</Button>}
            {saved && <span className="small muted" role="status">Saved</span>}
          </div>
        )}
      </div>
    </div>
  );
}
