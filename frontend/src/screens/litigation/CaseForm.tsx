import { useState } from 'react';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Checkbox, Dialog, SelectField, TextArea, TextField, WithHelp } from '@/components/ui';
import { caseHelp as H } from '@/help/monitoring';
import type { CaseDetail } from './types';

const TYPES = [
  { value: 'vendor_app', label: 'Vendor AI app' }, { value: 'embedded_feature', label: 'Embedded AI feature' }, { value: 'genai_chat_tool', label: 'Generative AI tool or chatbot' },
  { value: 'agent', label: 'AI agent' }, { value: 'foundation_model_api', label: 'Foundation model API' }, { value: 'in_house_model', label: 'In-house model' },
];
const STAGES = ['filed', 'pleadings', 'discovery', 'stayed', 'trial', 'appeal', 'decided', 'settled', 'dismissed'];
const csv = (v: string) => v.split(',').map((x) => x.trim()).filter(Boolean);

/** Add or edit a case (Chief Auditor). */
export function CaseForm({ initial, onClose, onSaved }: { initial?: CaseDetail; onClose: () => void; onSaved: (c: CaseDetail) => void }) {
  const [f, setF] = useState({
    name: initial?.name ?? '', geography: initial?.geography ?? '', jurisdiction_code: '', area: initial?.area ?? '', court: initial?.court ?? '', docket_ref: initial?.docket_ref ?? '',
    stage: initial?.stage ?? 'filed', stage_note: initial?.stage_note ?? '', description: initial?.description ?? '', why_matters: initial?.why_matters ?? '',
    talking_points_futran: initial?.talking_points_futran ?? '', talking_points_client: initial?.talking_points_client ?? '',
    sources: (initial?.sources ?? []).map((s) => `${s.title} ${s.url}`).join('\n'), uses: (initial?.match_rule.uses ?? []).join(', '), vendors: (initial?.match_rule.vendors ?? []).join(', '),
  });
  const [types, setTypes] = useState<string[]>(initial?.match_rule.types ?? []);
  const [consequential, setConsequential] = useState((initial?.match_rule.decision_impact ?? []).includes('consequential'));
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setErr(null); setErrs({});
    const sources = f.sources.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.lastIndexOf(' '); return i > 0 ? { title: l.slice(0, i).trim(), url: l.slice(i + 1).trim() } : { title: l, url: l }; });
    const body: Record<string, unknown> = {
      name: f.name, geography: f.geography || null, area: f.area, court: f.court || null, docket_ref: f.docket_ref || null, stage: f.stage, stage_note: f.stage_note || null,
      description: f.description || null, why_matters: f.why_matters || null, talking_points_futran: f.talking_points_futran || null, talking_points_client: f.talking_points_client || null,
      sources, match_rule: { types, uses: csv(f.uses), vendors: csv(f.vendors), decision_impact: consequential ? ['consequential'] : [] },
    };
    if (f.jurisdiction_code) body.jurisdiction_code = f.jurisdiction_code;
    try {
      const out = initial ? await api.patch<CaseDetail>(`/litigation/${initial.id}`, body) : await api.post<CaseDetail>('/litigation', body);
      onSaved(out);
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); }
  }
  return (
    <Dialog title={initial ? `Edit ${initial.name}` : 'Add case'} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="form-grid">
          <TextField label="Case name" help={H.name} value={f.name} onChange={set('name')} error={errs.name} required />
          <TextField label="Law or area" help={H.area} value={f.area} onChange={set('area')} error={errs.area} required />
          <TextField label="Geography" help={H.geography} value={f.geography} onChange={set('geography')} />
          <TextField label="Jurisdiction code" help={H.jurisdiction} value={f.jurisdiction_code} onChange={set('jurisdiction_code')} placeholder={initial ? 'Unchanged' : 'US'} />
          <TextField label="Court" help={H.court} value={f.court} onChange={set('court')} />
          <TextField label="Case number or citation" help={H.docket} value={f.docket_ref} onChange={set('docket_ref')} />
          <SelectField label="Stage" help={H.stage} value={f.stage} onChange={set('stage')} options={STAGES.map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) }))} error={errs.stage} />
          <TextField label="Stage note" help={H.stageNote} value={f.stage_note} onChange={set('stage_note')} />
        </div>
        <TextArea label="What it is about" help={H.description} value={f.description} onChange={set('description')} rows={3} />
        <TextArea label="Why it matters to our clients" help={H.whyMatters} value={f.why_matters} onChange={set('why_matters')} rows={3} />
        <div className="form-grid">
          <TextArea label="Talking points for the Chief Auditor and Sales Team" help={H.pointsFutran} value={f.talking_points_futran} onChange={set('talking_points_futran')} rows={4} />
          <TextArea label="Talking points for the client (the briefing's to-dos)" help={H.pointsClient} value={f.talking_points_client} onChange={set('talking_points_client')} rows={4} />
        </div>
        <fieldset className="stack-sm">
          <legend><WithHelp help={H.types}>Clients with similar AI: system types</WithHelp></legend>
          <div className="row wrap">{TYPES.map((t) => <Checkbox key={t.value} label={t.label} checked={types.includes(t.value)} onChange={(e) => setTypes(e.target.checked ? [...types, t.value] : types.filter((x) => x !== t.value))} />)}</div>
          <Checkbox label="Only systems that make consequential decisions about people" help={H.impact} checked={consequential} onChange={(e) => setConsequential(e.target.checked)} />
        </fieldset>
        <div className="form-grid">
          <TextField label="Use words" help={H.uses} value={f.uses} onChange={set('uses')} placeholder="applicant, résumé, screening" />
          <TextField label="Vendor names" help={H.vendors} value={f.vendors} onChange={set('vendors')} />
        </div>
        <TextArea label="Sources" help={H.sources} value={f.sources} onChange={set('sources')} rows={3} error={errs.sources} />
        <div className="row"><Button variant="primary" onClick={save}>{initial ? 'Save case' : 'Add case'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
