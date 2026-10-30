import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField } from '@/components/ui';
import { APPLIES_OPTIONS, STATUS_OPTIONS, TYPE_OPTIONS, type LawRecord, type Library, type Requirement } from '@/api/regmaster';
import { lawHelp as H } from '@/help/regmaster';
import { RegTabs } from './LawLibrary';
import '@/styles/regmaster.css';

type Source = { name: string; url: string; kind: string };
type Test = { question_text: string; prefill_from: string | null };
type Form = {
  region: string; jurisdiction_code: string; short_name: string; label: string; citation: string; type: string; binding: string; topics: string[];
  status: string; signed_on: string; effective_on: string; compliance_on: string; enforcer: string; private_right_of_action: string; penalty_text: string; cure_period: string;
  applies_to: string[]; scope_text: string; exemptions_text: string; sources: Source[]; scope_tests: Test[]; requirements: Partial<Requirement>[];
};
const EMPTY: Form = {
  region: 'us_states', jurisdiction_code: '', short_name: '', label: '', citation: '', type: 'statute', binding: 'yes', topics: [], status: 'enacted_not_in_force', signed_on: '', effective_on: '',
  compliance_on: '', enforcer: '', private_right_of_action: '', penalty_text: '', cure_period: '', applies_to: ['deployer'], scope_text: '', exemptions_text: '', sources: [],
  scope_tests: [{ question_text: '', prefill_from: 'client_geographies' }, { question_text: '', prefill_from: 'decision_impact' }], requirements: [],
};
const TOPICS = [{ value: 'hiring', label: 'Hiring and employment' }, { value: 'consumer_decisions', label: 'Consumer decisions' }, { value: 'genai', label: 'Generative AI disclosure' }, { value: 'frontier', label: 'Frontier models' }, { value: 'personal_data', label: 'Personal data' }, { value: 'health', label: 'Health care' }];
const DRAFT_KEY = 'reg-law-draft';

function fromLaw(d: LawRecord): Form {
  const v = d.version;
  return {
    region: d.region, jurisdiction_code: d.jurisdiction_code ?? '', short_name: d.short_name, label: d.label === d.short_name ? '' : d.label, citation: d.citation ?? '', type: d.type,
    binding: d.binding === false ? 'no' : 'yes', topics: d.topics, status: v.status, signed_on: v.signed_on ?? '', effective_on: v.effective_on ?? '', compliance_on: v.compliance_on ?? '',
    enforcer: v.enforcer ?? '', private_right_of_action: v.private_right_of_action === null ? '' : v.private_right_of_action ? 'yes' : 'no', penalty_text: v.penalty_text ?? '', cure_period: v.cure_period ?? '',
    applies_to: v.applies_to, scope_text: v.scope_text ?? '', exemptions_text: v.exemptions_text ?? '', sources: d.sources.map((s) => ({ name: s.name, url: s.url, kind: s.kind })),
    scope_tests: d.scope_tests.map((t) => ({ question_text: t.question_text, prefill_from: t.prefill_from })), requirements: [],
  };
}

/** Field-level differences between the record and the form, as proposed changes (edit mode). */
function diff(d: LawRecord, f: Form) {
  const base = fromLaw(d);
  const out: { field_path: string; new_value: unknown }[] = [];
  const pairs: [keyof Form, string, (v: Form[keyof Form]) => unknown][] = [
    ['short_name', 'law.short_name', (x) => x], ['label', 'law.label', (x) => x || null], ['citation', 'law.citation', (x) => x || null], ['type', 'law.type', (x) => x],
    ['binding', 'law.binding', (x) => x === 'yes'], ['topics', 'law.topics', (x) => x], ['status', 'law.status', (x) => x], ['signed_on', 'law.signed_on', (x) => x || null],
    ['effective_on', 'law.effective_on', (x) => x || null], ['compliance_on', 'law.compliance_on', (x) => x || null], ['enforcer', 'law.enforcer', (x) => x || null],
    ['private_right_of_action', 'law.private_right_of_action', (x) => (x === '' ? null : x === 'yes')], ['penalty_text', 'law.penalty_text', (x) => x || null],
    ['cure_period', 'law.cure_period', (x) => x || null], ['applies_to', 'law.applies_to', (x) => x], ['scope_text', 'law.scope_text', (x) => x || null], ['exemptions_text', 'law.exemptions_text', (x) => x || null],
  ];
  for (const [k, path, conv] of pairs) if (JSON.stringify(base[k]) !== JSON.stringify(f[k])) out.push({ field_path: path, new_value: conv(f[k]) });
  const n = Math.max(base.scope_tests.length, f.scope_tests.length);
  for (let i = 0; i < n; i++) {
    const a = base.scope_tests[i], b = f.scope_tests[i];
    if (JSON.stringify(a) === JSON.stringify(b)) continue;
    const prev = d.scope_tests[i];
    out.push({ field_path: `scope_test.${i + 1}`, new_value: b && b.question_text.trim() ? { question_text: b.question_text, prefill_from: b.prefill_from, in_scope_rule: prev?.in_scope_rule ?? { equals: 'yes' } } : null });
  }
  return out;
}

export function LawEdit() {
  const { lawId } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const law = useQuery({ queryKey: ['reg-law', lawId], queryFn: () => api.get<LawRecord>(`/reg/laws/${lawId}`), enabled: !!lawId });
  const lib = useQuery({ queryKey: ['reg-laws', 'meta'], queryFn: () => api.get<Library>('/reg/laws') });
  const [f, setF] = useState<Form>(() => {
    if (lawId) return EMPTY;
    try { const s = localStorage.getItem(DRAFT_KEY); return s ? { ...EMPTY, ...JSON.parse(s) } : EMPTY; } catch { return EMPTY; }
  });
  const [ref, setRef] = useState('');
  const [drafted, setDrafted] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [flash, setFlash] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  useEffect(() => { if (law.data) setF(fromLaw(law.data)); }, [law.data]);
  if ((lawId && law.isLoading) || lib.isLoading) return <div className="page"><Loading /></div>;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const toggle = (k: 'topics' | 'applies_to', v: string) => set(k, f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v]);
  const claude = lib.data?.claude_available ?? false;

  async function draft() {
    setBusy(true); setErr(null); setWarnings([]);
    try {
      const r = await api.post<{ draft: Record<string, unknown> | null; warnings: string[] }>('/reg/laws/draft', { ref });
      setWarnings(r.warnings);
      if (r.draft) {
        const d = r.draft as Partial<Form> & { binding?: boolean; private_right_of_action?: boolean | null };
        setF((x) => ({ ...x, ...Object.fromEntries(Object.entries(d).filter(([, v]) => v !== null && v !== undefined)), binding: d.binding === false ? 'no' : 'yes',
          private_right_of_action: d.private_right_of_action === true ? 'yes' : d.private_right_of_action === false ? 'no' : '' } as Form));
        setDrafted(true);
      }
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }

  async function send() {
    setBusy(true); setErr(null); setErrs({});
    try {
      if (lawId && law.data) {
        const changes = diff(law.data, f);
        if (!changes.length) { setErr('Nothing has changed.'); return; }
        await api.post(`/reg/laws/${lawId}/proposals`, { changes, summary: `Edit ${law.data.label}: ${changes.length} field${changes.length === 1 ? '' : 's'}`, reason: reason || null });
        await qc.invalidateQueries({ queryKey: ['reg-law', lawId] });
        nav(`/reg/${lawId}`);
        return;
      }
      const body = { ...f, binding: f.binding === 'yes', private_right_of_action: f.private_right_of_action === '' ? null : f.private_right_of_action === 'yes', label: f.label || null,
        scope_tests: f.scope_tests.filter((t) => t.question_text.trim()) };
      await api.post('/reg/laws/new', { law: body, drafted_with_claude: drafted });
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* storage unavailable */ }
      await qc.invalidateQueries({ queryKey: ['reg-laws'] });
      setFlash(`${f.short_name} was sent to the Chief Auditor for approval. It joins the library once approved.`);
      setF(EMPTY); setDrafted(false);
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); } finally { setBusy(false); }
  }

  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(f)); setFlash('Draft saved on this computer. It is not shared until you send it for approval.'); } catch { setErr('This browser does not allow saving drafts.'); }
  }

  const title = lawId ? `Edit ${law.data?.label ?? 'law'}` : 'Add a law';
  return (
    <div className="page">
      <PageHeader title={title} crumbs={[{ to: '/reg', label: 'Law library' }, ...(lawId && law.data ? [{ to: `/reg/${lawId}`, label: law.data.label }] : []), { label: lawId ? 'Edit' : 'Add a law' }]}
        subtitle="Saved as a proposed change. It goes live after Chief Auditor approval."
        actions={<>{!lawId && <Button onClick={saveDraft}>Save draft</Button>}<Button variant="primary" disabled={busy} onClick={send}>Send for approval</Button></>} />
      <RegTabs />
      {flash && <Alert tone="success">{flash}</Alert>}
      {err && <Alert tone="danger">{err}</Alert>}
      {!lawId && (
        <Card title="Draft with Claude">
          {!claude && <Alert tone="warn">Drafting with Claude needs an Anthropic API key in settings. Fill the form by hand, or ask an administrator to add the key.</Alert>}
          <div className="row" style={{ alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 320px' }}><TextField label="Bill number or official link" help={H.draftRef} placeholder="https://leg.colorado.gov/bills/sb26-189" value={ref} onChange={(e) => setRef(e.target.value)} disabled={!claude} /></div>
            <Button disabled={!claude || busy || !ref.trim()} onClick={draft}>{busy ? 'Drafting…' : 'Draft the record'}</Button>
          </div>
          <p className="small muted">Claude fills the fields below from the official text, with a quote for each requirement. Check every field before sending for approval.</p>
          {drafted && <Alert tone="info">Drafted by Claude. Every requirement is marked Verify until the Chief Auditor approves it.</Alert>}
          {warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
        </Card>
      )}
      <div className="stack" style={{ marginTop: 16 }}>
        <Card title="1 · Law">
          <div className="reg-form-grid">
            <SelectField label="Region *" help={H.region} value={f.region} onChange={(e) => set('region', e.target.value)} options={lib.data?.regions ?? []} />
            <TextField label="Geography *" help={H.geography} value={f.jurisdiction_code} onChange={(e) => set('jurisdiction_code', e.target.value.toUpperCase())} error={errs.jurisdiction_code} disabled={!!lawId} placeholder="US-CO" />
            <TextField label="Short name *" help={H.shortName} value={f.short_name} onChange={(e) => set('short_name', e.target.value)} error={errs.short_name} />
            <TextField label="Column label" help={H.label} value={f.label} onChange={(e) => set('label', e.target.value)} />
            <TextField label="Citation *" help={H.citation} value={f.citation} onChange={(e) => set('citation', e.target.value)} error={errs.citation} />
            <SelectField label="Type *" help={H.type} value={f.type} onChange={(e) => set('type', e.target.value)} options={TYPE_OPTIONS} />
            <SelectField label="Binding?" help={H.binding} value={f.binding} onChange={(e) => set('binding', e.target.value)} options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No (voluntary)' }]} />
          </div>
          <FieldGroup legend="Topics" help={H.topics}><div className="reg-checks">{TOPICS.map((t) => <Checkbox key={t.value} label={t.label} checked={f.topics.includes(t.value)} onChange={() => toggle('topics', t.value)} />)}</div></FieldGroup>
        </Card>
        <Card title="2 · Status, dates and enforcement">
          <div className="reg-form-grid">
            <SelectField label="Status *" help={H.status} value={f.status} onChange={(e) => set('status', e.target.value)} options={STATUS_OPTIONS} error={errs.status} />
            <TextField type="date" label="Signed" help={H.signed} value={f.signed_on} onChange={(e) => set('signed_on', e.target.value)} />
            <TextField type="date" label="Effective" help={H.effective} value={f.effective_on} onChange={(e) => set('effective_on', e.target.value)} />
            <TextField type="date" label="Compliance from" help={H.compliance} value={f.compliance_on} onChange={(e) => set('compliance_on', e.target.value)} />
            <TextField label="Enforced by" help={H.enforcer} value={f.enforcer} onChange={(e) => set('enforcer', e.target.value)} placeholder="State Attorney General" />
            <SelectField label="Private right of action?" help={H.pra} value={f.private_right_of_action} onChange={(e) => set('private_right_of_action', e.target.value)} placeholder="Not known" options={[{ value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }]} />
            <TextField label="Penalty" help={H.penalty} value={f.penalty_text} onChange={(e) => set('penalty_text', e.target.value)} placeholder="Amount, per violation or per day" />
            <TextField label="Cure period" help={H.cure} value={f.cure_period} onChange={(e) => set('cure_period', e.target.value)} placeholder="e.g. 60 days" />
          </div>
        </Card>
        <Card title="3 · Scope">
          <FieldGroup legend="Applies to *" help={H.appliesTo}><div className="reg-checks">{APPLIES_OPTIONS.map((o) => <Checkbox key={o.value} label={o.label} checked={f.applies_to.includes(o.value)} onChange={() => toggle('applies_to', o.value)} />)}</div></FieldGroup>
          {errs.applies_to && <div className="error">{errs.applies_to}</div>}
          <TextArea label="Scope in plain words *" help={H.scope} value={f.scope_text} onChange={(e) => set('scope_text', e.target.value)} error={errs.scope_text} rows={3} />
          <TextField label="Exemptions" help={H.exemptions} value={f.exemptions_text} onChange={(e) => set('exemptions_text', e.target.value)} placeholder="e.g. fewer than 50 employees" />
        </Card>
        <Card title="4 · Sources" actions={<Button size="sm" onClick={() => set('sources', [...f.sources, { name: '', url: '', kind: 'official' }])}>Add a source</Button>}>
          {f.sources.length === 0 && <p className="small muted">Add the legislature or regulator page first. Law firm alerts are marked secondary.</p>}
          {f.sources.map((s, i) => (
            <div className="reg-form-grid" key={i}>
              <TextField label="Source" value={s.name} onChange={(e) => set('sources', f.sources.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <TextField label="Link" type="url" help={H.sourceUrl} value={s.url} onChange={(e) => set('sources', f.sources.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))} />
              <SelectField label="Kind" value={s.kind} onChange={(e) => set('sources', f.sources.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))} options={[{ value: 'official', label: 'Official' }, { value: 'secondary', label: 'Secondary' }]} />
            </div>
          ))}
        </Card>
        <Card title="5 · Scope test questions" actions={<Button size="sm" onClick={() => set('scope_tests', [...f.scope_tests, { question_text: '', prefill_from: null }])}>Add a question</Button>}>
          <p className="small muted">Asked in the client applicability check (M5). A decisive question answered no takes the client out of scope.</p>
          {f.scope_tests.map((t, i) => (
            <div className="reg-form-grid" key={i}>
              <TextField label={`Question ${i + 1}`} help={H.question} value={t.question_text} onChange={(e) => set('scope_tests', f.scope_tests.map((x, j) => (j === i ? { ...x, question_text: e.target.value } : x)))} />
              <SelectField label="Pre-filled from" help={H.prefill} value={t.prefill_from ?? ''} onChange={(e) => set('scope_tests', f.scope_tests.map((x, j) => (j === i ? { ...x, prefill_from: e.target.value || null } : x)))} placeholder="Not pre-filled" options={[{ value: 'client_geographies', label: 'Client geographies' }, { value: 'decision_impact', label: 'AI system: decision impact' }]} />
            </div>
          ))}
        </Card>
        {!lawId && f.requirements.length > 0 && (
          <Card title={`Requirements drafted by Claude (${f.requirements.length})`}>
            <ul className="reg-law-list">{f.requirements.map((r) => <li key={r.code}><strong>{r.code}</strong> {r.text} <Badge tone="warn">Verify</Badge><div className="reg-sub">{r.citation}</div>{r.source_quote && <div className="reg-quote">“{r.source_quote}”</div>}</li>)}</ul>
          </Card>
        )}
        {lawId && <TextField label="Reason for change" help="Saved with each proposed change." value={reason} onChange={(e) => setReason(e.target.value)} />}
        <p className="reg-note">{lawId ? 'Requirements and role mapping are changed on the law record and in Roles and committees.' : 'Requirements and role mapping are added on the law record (M2) once the law is approved.'}</p>
      </div>
    </div>
  );
}
