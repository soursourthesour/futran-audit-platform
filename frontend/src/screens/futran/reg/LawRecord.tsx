import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, FieldGroup, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { AI_TYPE_OPTIONS, APPLIES_OPTIONS, STAGE_OPTIONS, appliesLabel, stageLabel, statusTone, type LawRecord as Law, type Requirement } from '@/api/regmaster';
import { requirementHelp as H } from '@/help/regmaster';
import { RegTabs, canReviewLaws } from './LawLibrary';
import { can, useMe } from '@/api/auth';
import { LawCases } from '@/screens/litigation/LawCases';
import '@/styles/regmaster.css';

const LEVEL_LABEL: Record<string, string> = { required: 'Required', recommended: 'Recommended', no_longer_required: 'No longer required' };

export function LawRecord() {
  const { lawId = '' } = useParams();
  const loc = useLocation();
  const { data: me } = useMe();
  const review = canReviewLaws(me);
  const q = useQuery({ queryKey: ['reg-law', lawId], queryFn: () => api.get<Law>(`/reg/laws/${lawId}`) });
  const [editing, setEditing] = useState<Requirement | 'new' | null>(null);
  const [bulk, setBulk] = useState<Requirement[] | null>(null);
  const [suggest, setSuggest] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  useEffect(() => { if (loc.hash === '#suggest') setSuggest(true); }, [loc.hash]);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const v = d.version;
  const done = (m: string) => { setEditing(null); setBulk(null); setSuggest(false); setFlash(m); q.refetch(); };
  const dates = [v.signed_on && `Signed ${fmtDate(v.signed_on)}`, v.effective_on && `Effective ${fmtDate(v.effective_on)}`, v.compliance_on && `Compliance from ${fmtDate(v.compliance_on)}`].filter(Boolean).join(' · ');
  return (
    <div className="page">
      <PageHeader title={d.label}
        crumbs={[{ to: '/reg', label: 'Law library' }, ...(d.parent_geography ? [{ label: d.parent_geography }] : []), { label: d.geography }, { label: d.label }]}
        subtitle={<>
          <Badge tone={statusTone(v.status)}>{v.status_label}</Badge>{v.verify && <> <Badge tone="warn">Verify</Badge></>} {d.short_name !== d.label ? d.short_name : ''}{d.citation && d.citation.length < 120 ? ` · ${d.citation}` : ''}
          <span className="reg-sub" style={{ display: 'block' }}>Version {v.version_no}{v.approved_at ? `, approved ${fmtDate(v.approved_at)}${v.approved_by ? ` by ${v.approved_by}` : ''}` : ''} · Used by {d.used_by_clients} clients · {d.used_by_systems} AI systems</span>
        </>}
        actions={<>
          {d.can_edit && <Link className="btn" to={`/reg/${d.id}/edit`}>Edit record</Link>}
          {!d.can_edit && <Button onClick={() => setSuggest(true)}>Suggest a change</Button>}
          {can(me, 'run_law_refresh') && <Link className="btn" to={`/reg/refresh?law=${d.id}`}>Refresh this law only</Link>}
        </>} />
      <RegTabs />
      {flash && <Alert tone="success">{flash}</Alert>}
      {d.pending.length > 0 && (
        <Alert tone="warn">
          <strong>{d.pending.length} proposed {d.pending.length === 1 ? 'change' : 'changes'} waiting for Chief Auditor approval.</strong> Not live until approved.
          <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>{d.pending.slice(0, 5).map((p) => <li key={p.id} className="small">{p.summary} <span className="muted">({p.proposed_by ?? 'Futran'}{p.origin === 'auditor_suggestion' ? ', suggestion' : ''})</span></li>)}</ul>
          {review && <div style={{ marginTop: 6 }}><Link to="/reg/refresh">Review changes</Link></div>}
        </Alert>
      )}
      <div className="stack">
        <Card title="Overview">
          <dl className="reg-kv">
            <dt>Geography</dt><dd>{[d.parent_geography, d.geography].filter(Boolean).join(' · ')}</dd>
            <dt>Type</dt><dd>{d.type.charAt(0).toUpperCase() + d.type.slice(1)}{d.binding === false ? ', not binding' : ', binding'}</dd>
            {dates && <><dt>Dates</dt><dd>{dates}</dd></>}
            {v.effective_text && <><dt>Timing</dt><dd>{v.effective_text}</dd></>}
            <dt>Enforced by</dt><dd>{v.enforcer || '—'}{/private right/i.test(v.enforcer ?? '') ? '' : v.private_right_of_action === false ? '. No private right of action.' : v.private_right_of_action ? '. Private right of action.' : ''}</dd>
            <dt>Applies to</dt><dd>{appliesLabel(v.applies_to)}{v.scope_text ? ` — ${v.scope_text}` : ''}</dd>
            {v.exemptions_text && <><dt>Exemptions</dt><dd>{v.exemptions_text}</dd></>}
            <dt>Penalty</dt><dd>{v.penalty_text || '—'}</dd>
            {v.cure_period && <><dt>Cure period</dt><dd>{v.cure_period}</dd></>}
            {v.removed_text && <><dt>Removed from the earlier law</dt><dd>{v.removed_text}</dd></>}
            {v.litigation_text && <><dt>Litigation and rules</dt><dd>{v.litigation_text}</dd></>}
            <dt>Sources</dt><dd>{d.sources.length ? d.sources.map((s) => <div key={s.id}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.name}</a> {s.kind === 'secondary' && <Badge tone="muted">Secondary</Badge>}</div>) : '—'}</dd>
          </dl>
        </Card>
        <Card title="Scope tests used at client set-up">
          <p className="small muted">The client applicability check asks these. Every decisive question must be answered yes for the client to be in scope.</p>
          {d.scope_tests.length ? <ol style={{ paddingLeft: 20, margin: 0 }}>{d.scope_tests.map((t) => <li key={t.order} style={{ marginBottom: 6 }}>{t.question_text}{!t.decisive && <span className="muted small"> (informs duties, does not decide scope)</span>}{t.note && <div className="reg-sub">{t.note}</div>}</li>)}</ol> : <EmptyState>No scope tests yet. The law applies only where it is confirmed in client set-up.</EmptyState>}
        </Card>
        <section id="requirements">
          <Card title={`Statutory requirements (${d.requirements.length})`} actions={d.can_edit ? <Button onClick={() => setEditing('new')}>Add a requirement</Button> : undefined}>
            <DataGrid
              label="Statutory requirements"
              rows={d.requirements}
              rowId={(r) => r.code}
              rowLabel={(r) => r.code}
              selectable={d.can_edit}
              emptyText="No requirements recorded for this law yet."
              columns={[
                { key: 'code', header: 'ID', value: (r) => r.code, render: (r) => <><strong>{r.code}</strong>{r.verify_flag && <div><Badge tone="warn">Verify</Badge></div>}</> },
                { key: 'text', header: 'Requirement', value: (r) => r.text, render: (r) => <div style={{ minWidth: 240 }}>{r.text}{r.source_quote && <div className="reg-quote">“{r.source_quote}”</div>}</div> },
                { key: 'applies', header: 'Applies to', value: (r) => appliesLabel(r.applies_to) },
                { key: 'needed', header: 'Needed by', value: (r) => stageLabel(r.needed_by_stage) },
                { key: 'evidence', header: 'Evidence the auditor checks', value: (r) => r.evidence_text ?? '', render: (r) => <span className="small">{r.evidence_text || '—'}</span> },
                { key: 'role', header: 'Role responsible', value: (r) => r.role_name ?? '' },
                { key: 'citation', header: 'Citation', value: (r) => r.citation ?? '', render: (r) => r.source_url ? <a href={r.source_url} target="_blank" rel="noreferrer noopener" className="small">{r.citation}</a> : <span className="small">{r.citation}</span> },
              ]}
              bulkActions={d.can_edit ? [{ label: 'Edit selected', run: (rows) => setBulk(rows) }] : []}
              rowActions={(r) => d.can_edit ? [{ label: 'Edit requirement', onSelect: () => setEditing(r) }] : [{ label: 'Suggest a change', onSelect: () => setSuggest(true) }]}
            />
            <p className="reg-note">Citations are checked against the official text before approval. A Verify badge means the wording or section number still needs confirming against the final official text.</p>
          </Card>
        </section>
        <Card title="Roles and committees this law requires">
          {d.role_maps.length ? (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Role (from the role catalogue)</th><th>Level</th><th>Needed by</th><th>Basis</th></tr></thead>
              <tbody>{d.role_maps.map((m) => (
                <tr key={m.role + m.level}><td>{m.name}</td><td>{m.level === 'required' ? <span className="reg-pill-req">Required</span> : m.level === 'recommended' ? <span className="reg-pill-rec">Recommended</span> : <span className="muted">{LEVEL_LABEL[m.level]}</span>}{m.verify && <> <Badge tone="warn">Verify</Badge></>}</td>
                  <td>{m.needed_by_stage ? stageLabel(m.needed_by_stage) : '—'}</td><td className="small">{m.basis || (m.requirements.length ? m.requirements.join(', ') : '—')}</td></tr>
              ))}</tbody>
            </table></div>
          ) : <EmptyState>No roles mapped yet.</EmptyState>}
          {d.committees.map((c) => <p key={c.committee_type} className="small" style={{ marginTop: 12 }}><strong>{c.title}</strong> · {c.level === 'required' ? 'Required' : 'Recommended'}{c.basis ? ` · ${c.basis}` : ''}{c.condition ? `. ${c.condition}.` : ''}</p>)}
          <p className="reg-note">Change a role's level from <Link to="/reg/roles">Roles and committees</Link>.</p>
        </Card>
        {can(me, 'view_litigation') && <section id="cases" aria-label="Related cases"><LawCases regulationId={d.id} /></section>}
        <section id="history">
          <Card title="Version history">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Version</th><th>Change</th><th>By</th><th>Date</th></tr></thead>
              <tbody>{d.history.map((h) => <tr key={h.id}><td>{h.version_no}</td><td>{h.change}</td><td className="small">{h.by}</td><td className="small">{fmtDate(h.date)}</td></tr>)}</tbody>
            </table></div>
            <p className="reg-note">Client letters and audits record the version they used, so earlier reports still show the rules that applied at the time.</p>
          </Card>
        </section>
      </div>
      {editing && <RequirementEditor law={d} req={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onDone={done} />}
      {bulk && <RequirementBulk law={d} reqs={bulk} onClose={() => setBulk(null)} onDone={done} />}
      {suggest && <SuggestChange law={d} onClose={() => setSuggest(false)} onDone={done} />}
    </div>
  );
}

function RequirementEditor({ law, req, onClose, onDone }: { law: Law; req: Requirement | null; onClose: () => void; onDone: (m: string) => void }) {
  const qc = useQueryClient();
  const nextCode = () => {
    const prefix = law.requirements[0]?.code.replace(/-?\d+$/, '') || 'REQ';
    return `${prefix}-${String(law.requirements.length + 1).padStart(2, '0')}`;
  };
  const [f, setF] = useState({ code: req?.code ?? nextCode(), text: req?.text ?? '', applies_to: req?.applies_to ?? ['deployer'], needed_by_stage: req?.needed_by_stage ?? 'go_live', role: req?.role ?? '',
    ai_types: req?.ai_types ?? ['decision'], evidence_text: req?.evidence_text ?? '', citation: req?.citation ?? '', source_quote: req?.source_quote ?? '', source_url: req?.source_url ?? '' });
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const toggle = (k: 'applies_to' | 'ai_types', v: string) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] });
  async function save() {
    setErr(null); setErrs({});
    try {
      const { code, ...value } = f;
      await api.post(`/reg/laws/${law.id}/proposals`, { changes: [{ field_path: `requirement.${code}`, new_value: { ...value, role: value.role || null }, change_type: req ? 'amendment' : 'new_rule' }], summary: `${req ? 'Edit' : 'Add'} requirement ${code}`, reason: reason || null });
      await qc.invalidateQueries({ queryKey: ['reg-laws'] });
      onDone(`Requirement ${code} saved as a proposed change. It goes live after Chief Auditor approval.`);
    } catch (e) {
      setErr(errorMessage(e));
      const fe = fieldErrors(e);
      setErrs(Object.fromEntries(Object.entries(fe).map(([k, m]) => [k.replace('new_value.', ''), m])));
    }
  }
  return (
    <Dialog title={req ? `Edit requirement ${req.code}` : 'Add a requirement'} onClose={onClose} large>
      {err && <Alert tone="danger">{err}</Alert>}
      {!req && <TextField label="ID *" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} help="A short reference, for example CO-09." />}
      <TextArea label="Requirement *" help={H.text} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} error={errs.text} rows={2} />
      <FieldGroup legend="Applies to *" help={H.appliesTo}><div className="reg-checks">{APPLIES_OPTIONS.map((o) => <Checkbox key={o.value} label={o.label} checked={f.applies_to.includes(o.value)} onChange={() => toggle('applies_to', o.value)} />)}</div></FieldGroup>
      <div className="reg-form-grid">
        <SelectField label="Needed by *" help={H.neededBy} value={f.needed_by_stage} onChange={(e) => setF({ ...f, needed_by_stage: e.target.value })} options={STAGE_OPTIONS} />
        <SelectField label="Role responsible" help={H.role} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={law.roles.map((r) => ({ value: r.code, label: r.name }))} placeholder="No role" error={errs.role} />
      </div>
      <FieldGroup legend="AI types it applies to" help={H.aiTypes}><div className="reg-checks">{AI_TYPE_OPTIONS.map((o) => <Checkbox key={o.value} label={o.label} checked={f.ai_types.includes(o.value)} onChange={() => toggle('ai_types', o.value)} />)}</div></FieldGroup>
      <TextField label="Evidence the auditor checks" help={H.evidence} value={f.evidence_text} onChange={(e) => setF({ ...f, evidence_text: e.target.value })} />
      <div className="reg-form-grid">
        <TextField label="Citation *" help={H.citation} value={f.citation} onChange={(e) => setF({ ...f, citation: e.target.value })} />
        <TextField label="Source link" help={H.sourceUrl} type="url" value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} />
      </div>
      <TextArea label="Source quote *" help={H.quote} value={f.source_quote} onChange={(e) => setF({ ...f, source_quote: e.target.value })} error={errs.source_quote} rows={3} />
      <TextField label="Reason for change" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save as proposed change</Button></div>
    </Dialog>
  );
}

function RequirementBulk({ law, reqs, onClose, onDone }: { law: Law; reqs: Requirement[]; onClose: () => void; onDone: (m: string) => void }) {
  const [f, setF] = useState({ role: '', needed_by_stage: '', applies_to: '' });
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      const r = await api.post<{ proposals: unknown[] }>(`/reg/laws/${law.id}/requirements/bulk`, { codes: reqs.map((x) => x.code), role: f.role || null, needed_by_stage: f.needed_by_stage || null, applies_to: f.applies_to ? [f.applies_to] : null, reason });
      onDone(`${r.proposals.length} proposed changes sent to the Chief Auditor.`);
    } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <Dialog title={`Edit ${reqs.length} requirements`} onClose={onClose}>
      <p className="small">{reqs.map((r) => r.code).join(', ')}. Only the fields you set change.</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <SelectField label="Set role responsible" help={H.role} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={law.roles.map((r) => ({ value: r.code, label: r.name }))} placeholder="Keep current" />
      <SelectField label="Set needed by" help={H.neededBy} value={f.needed_by_stage} onChange={(e) => setF({ ...f, needed_by_stage: e.target.value })} options={STAGE_OPTIONS} placeholder="Keep current" />
      <SelectField label="Set applies to" help={H.appliesTo} value={f.applies_to} onChange={(e) => setF({ ...f, applies_to: e.target.value })} options={APPLIES_OPTIONS} placeholder="Keep current" />
      <TextArea label="Reason for change *" help={H.reason} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!reason.trim()} onClick={save}>Save as proposed changes</Button></div>
    </Dialog>
  );
}

const SUGGEST_FIELDS = [
  { value: 'law.status', label: 'Status' }, { value: 'law.effective_on', label: 'Effective date' }, { value: 'law.compliance_on', label: 'Compliance date' },
  { value: 'law.enforcer', label: 'Enforced by' }, { value: 'law.penalty_text', label: 'Penalty' }, { value: 'law.cure_period', label: 'Cure period' },
  { value: 'law.scope_text', label: 'Scope' }, { value: 'law.litigation_text', label: 'Litigation and rules' },
];

function SuggestChange({ law, onClose, onDone }: { law: Law; onClose: () => void; onDone: (m: string) => void }) {
  const [f, setF] = useState({ field_path: 'law.status', new_value: '', summary: '', source_url: '', source_quote: '' });
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  async function save() {
    setErr(null); setErrs({});
    try {
      await api.post(`/reg/laws/${law.id}/proposals`, { changes: [{ field_path: f.field_path, new_value: f.new_value }], summary: f.summary || `Update ${SUGGEST_FIELDS.find((x) => x.value === f.field_path)?.label}`, source_url: f.source_url || null, source_quote: f.source_quote || null });
      onDone('Suggestion sent to the Chief Auditor.');
    } catch (e) { setErr(errorMessage(e)); setErrs(fieldErrors(e)); }
  }
  return (
    <Dialog title="Suggest a change" onClose={onClose}>
      <p className="small muted">{H.suggestSource}</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <SelectField label="What changes" help={H.suggestField} value={f.field_path} onChange={(e) => setF({ ...f, field_path: e.target.value })} options={SUGGEST_FIELDS} />
      <TextArea label="New value *" value={f.new_value} onChange={(e) => setF({ ...f, new_value: e.target.value })} error={errs.new_value} rows={2} help={f.field_path.endsWith('_on') ? 'Use YYYY-MM-DD.' : f.field_path === 'law.status' ? 'in_force, in_force_phased, enacted_not_in_force, delayed, guidance or repealed.' : 'The text as it should read.'} />
      <TextField label="Summary *" help="One line for the review queue." value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} />
      <TextField label="Source link *" type="url" help={H.sourceUrl} value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} error={errs.source_url} />
      <TextArea label="Quoted passage *" help={H.quote} value={f.source_quote} onChange={(e) => setF({ ...f, source_quote: e.target.value })} rows={3} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Send suggestion</Button></div>
    </Dialog>
  );
}
