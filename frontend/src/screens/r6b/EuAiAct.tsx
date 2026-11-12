import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { SIGNOFF_TONE, type EuDetail, type EuListing, type EuObligation } from '@/api/r6b';
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate, fmtDateTime } from '@/components/ui';
import '@/styles/r6b.css';

const opts = (m: Record<string, string>) => Object.entries(m).map(([value, label]) => ({ value, label }));
const OB_STATUS: Record<string, string> = { not_started: 'Not started', not_met: 'Not met', partly_met: 'Partly met', met: 'Met', not_applicable: 'Not applicable' };
const OB_TONE: Record<string, string> = { met: 'r6b-go', not_applicable: 'muted', partly_met: 'r6b-hold', not_met: 'r6b-bad', not_started: '' };
const SECTION: Record<string, string> = { not_started: 'Not started', in_progress: 'In progress', done: 'Done' };

/** G-08 on an EU AI Act readiness engagement: `/e/:engagementId/eu-ai-act`. */
export function EuAiActEngagementScreen() {
  const { engagementId = '' } = useParams();
  return <EuWorkspace listPath={`/e/${engagementId}/eu-ai-act`} engagementId={engagementId} />;
}

/** G-08 from the client's systems with EU geography, outside an EU AI Act engagement: `/clients/:clientId/eu-ai-act`. */
export function EuAiActClientScreen() {
  const { clientId = '' } = useParams();
  return <EuWorkspace listPath={`/clients/${clientId}/eu-ai-act`} />;
}

function EuWorkspace({ listPath, engagementId }: { listPath: string; engagementId?: string }) {
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ['eu-list', listPath], queryFn: () => api.get<EuListing>(listPath) });
  const selected = params.get('system') ?? q.data?.systems[0]?.id ?? null;
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const v = q.data;
  return (
    <div className="page r6b">
      <PageHeader crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${v.client.id}`, label: v.client.name }, { label: 'EU AI Act conformity' }]}
        title="EU AI Act conformity" subtitle={v.banner} />
      {v.systems.length > 0 && (v.ready_for_report
        ? <Alert tone="success">Every classification is signed off by the legal reviewer. The report can be issued.</Alert>
        : <Alert>Each classification needs the legal reviewer's sign-off before the report is issued.</Alert>)}
      <Card className="r6b-card">
        {v.systems.length === 0 ? <EmptyState>No AI system in this client's register has EU geography yet.</EmptyState> : (
          <div className="table-wrap">
            <table className="table stack-table" aria-label="AI systems under the EU AI Act">
              <thead><tr><th>AI system</th><th>EU exposure</th><th>Role</th><th>Classification</th><th>Deadline</th><th>Obligations met</th><th>Legal sign-off</th></tr></thead>
              <tbody>
                {v.systems.map((s) => (
                  <tr key={s.id} className={s.id === selected ? 'r6b-selected' : undefined}>
                    <td><button type="button" className="linklike" aria-current={s.id === selected ? 'true' : undefined} onClick={() => setParams({ system: s.id })}><strong>{s.name}</strong></button><div className="small muted">{s.reference}</div></td>
                    <td data-label="EU exposure">{s.exposure_basis ?? s.eu_exposure ?? '—'}</td>
                    <td data-label="Role">{s.role_label ?? 'Not set'}</td>
                    <td data-label="Classification">{s.classification_label ?? 'Not classified'}</td>
                    <td data-label="Deadline" title={s.deadline.source ?? undefined}>{s.deadline.label}</td>
                    <td data-label="Obligations met">{s.obligations_total ? `${s.obligations_met} / ${s.obligations_total}` : '—'}</td>
                    <td data-label="Legal sign-off"><Badge tone={SIGNOFF_TONE[s.signoff_status]}>{s.signoff_label}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {selected && <SystemPanel key={selected} systemId={selected} listPath={listPath} engagementId={engagementId} />}
    </div>
  );
}

function SystemPanel({ systemId, listPath, engagementId }: { systemId: string; listPath: string; engagementId?: string }) {
  const qc = useQueryClient();
  const key = ['eu-system', systemId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<EuDetail>(`/eu-ai-act/systems/${systemId}`) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const base = `/eu-ai-act/systems/${systemId}`;

  async function run(fn: () => Promise<EuDetail>, ok?: string) {
    setMsg(null);
    setErrs({});
    try {
      qc.setQueryData(key, await fn());
      await qc.invalidateQueries({ queryKey: ['eu-list', listPath] });
      if (ok) setMsg({ tone: 'success', text: ok });
    } catch (e) {
      setErrs(fieldErrors(e));
      setMsg({ tone: 'danger', text: errorMessage(e) });
    }
  }

  return (
    <section className="stack" aria-label={`${d.name}: EU AI Act`}>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split">
        <div className="main stack">
          <ObligationsCard d={d} base={base} run={run} />
          {d.annex_iv.length > 0 && <AnnexIVCard d={d} base={base} run={run} />}
          {d.fria && <FriaCard d={d} base={base} run={run} />}
        </div>
        <aside className="side stack">
          <ClassificationCard d={d} base={base} run={run} errs={errs} engagementId={engagementId} />
          <SignOffCard d={d} base={base} run={run} />
        </aside>
      </div>
    </section>
  );
}

type Run = (fn: () => Promise<EuDetail>, ok?: string) => Promise<void>;

function ObligationsCard({ d, base, run }: { d: EuDetail; base: string; run: Run }) {
  const who = d.role_label ? `${d.role_label.toLowerCase()} obligations` : 'obligations';
  return (
    <Card title={`${d.name} · ${who}`} className="r6b-card">
      {d.obligations.length === 0 ? <EmptyState>Record the role and the classification to see the articles that apply.</EmptyState> : (
        <div className="table-wrap">
          <table className="table stack-table" aria-label="Obligations">
            <thead><tr><th>Article</th><th>Obligation</th><th>Status</th><th>Evidence</th></tr></thead>
            <tbody>{d.obligations.map((o) => <ObligationRow key={o.key} o={o} d={d} base={base} run={run} />)}</tbody>
          </table>
        </div>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>Deadline: {d.deadline.label}{d.deadline.source ? ` (${d.deadline.source})` : ''}.</p>
    </Card>
  );
}

function ObligationRow({ o, d, base, run }: { o: EuObligation; d: EuDetail; base: string; run: Run }) {
  async function upload(f: File | undefined) {
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    await run(() => api.upload(`${base}/obligations/${o.key}/evidence`, form), 'Evidence added.');
  }
  return (
    <tr>
      <td><strong>{o.article}</strong>{o.library && <div className="small muted" title={o.library.text}>Law library {o.library.code}</div>}</td>
      <td data-label="Obligation">{o.title}{o.note && <div className="small muted">{o.note}</div>}</td>
      <td data-label="Status">
        {o.progress ? <span className={OB_TONE[o.status]}>{o.progress}</span> : d.can_edit ? (
          <select aria-label={`Status of ${o.article}`} value={o.status} onChange={(e) => run(() => api.put(`${base}/obligations/${o.key}`, { status: e.target.value }))}>
            {opts(OB_STATUS).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
          </select>
        ) : <span className={OB_TONE[o.status]}>{o.status_label}</span>}
      </td>
      <td data-label="Evidence">
        {o.evidence.length === 0 && !d.can_edit && '—'}
        {o.evidence.map((f) => <a key={f.id} className="file-link r6b-ev" href={fileUrl(f.id)} title={`SHA-256 ${f.sha256}`}>{f.filename}</a>)}
        {d.can_edit && !o.progress && <label className="small r6b-attach">Attach<input type="file" className="sr-only" aria-label={`Attach evidence to ${o.article}`} onChange={(e) => upload(e.target.files?.[0])} /></label>}
      </td>
    </tr>
  );
}

function AnnexIVCard({ d, base, run }: { d: EuDetail; base: string; run: Run }) {
  return (
    <Card title={`Annex IV technical documentation · ${d.annex_iv_done} of ${d.annex_iv.length} sections`} className="r6b-card">
      <ul className="r6b-controls" aria-label="Annex IV technical documentation">
        {d.annex_iv.map((a) => (
          <li key={a.key} className="r6b-control">
            <div className="r6b-control-head">
              <span className="r6b-control-label">{a.label}</span>
              {d.can_edit ? (
                <select aria-label={`Status of ${a.label}`} value={a.status} onChange={(e) => run(() => api.put(`${base}/annex-iv/${a.key}`, { status: e.target.value }))}>
                  {opts(SECTION).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                </select>
              ) : <span>{SECTION[a.status]}</span>}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function FriaCard({ d, base, run }: { d: EuDetail; base: string; run: Run }) {
  const fria = d.fria!;
  const [answers, setAnswers] = useState<Record<string, string>>(Object.fromEntries(fria.questions.map((q) => [q.key, fria.answers[q.key] ?? ''])));
  const [status, setStatus] = useState(fria.status);
  return (
    <Card title={`Fundamental rights impact assessment (Art. 27) · ${SECTION[fria.status]}`} className="r6b-card">
      <div className="stack">
        <p className="small" style={{ margin: 0 }}>Required before first use: {d.role === 'deployer' ? 'the client deploys' : 'the client also deploys'} this Annex III system{d.public_service ? ' as a public body or provider of public services' : ''}.</p>
        {fria.questions.map((q) => d.can_edit
          ? <TextArea key={q.key} label={q.label} rows={2} value={answers[q.key] ?? ''} onChange={(e) => setAnswers({ ...answers, [q.key]: e.target.value })} />
          : <div key={q.key}><strong className="small">{q.label}</strong><div className="small">{fria.answers[q.key] || '—'}</div></div>)}
        {d.can_edit && (
          <div className="row">
            <SelectField label="Status" value={status} onChange={(e) => setStatus(e.target.value)} options={opts(SECTION)} />
            <Button variant="primary" onClick={() => run(() => api.put(`${base}/fria`, { answers, status }), 'Assessment saved.')}>Save the assessment</Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function ClassificationCard({ d, base, run, errs, engagementId }: { d: EuDetail; base: string; run: Run; errs: Record<string, string>; engagementId?: string }) {
  const init = () => ({ exposure_basis: d.exposure_basis ?? '', role: d.role ?? '', also_deployer: d.also_deployer, classification: d.classification ?? '', annex_iii_area: d.annex_iii_area ?? '',
                        public_service: d.public_service, reasoning: d.reasoning ?? '' });
  const [f, setF] = useState(init);
  useEffect(() => setF(init()), [d.role, d.classification, d.annex_iii_area, d.reasoning, d.exposure_basis]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d.can_edit) {
    return (
      <Card title="Classification reasoning" className="r6b-card">
        <dl className="kv-stacked">
          <div><dt>EU exposure</dt><dd>{d.exposure_basis ?? d.eu_exposure ?? '—'}</dd></div>
          <div><dt>Role</dt><dd>{d.role_label ?? 'Not set'}</dd></div>
          <div><dt>Classification</dt><dd>{d.classification_label ?? 'Not classified'}</dd></div>
        </dl>
        <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{d.reasoning ?? 'No reasoning recorded yet.'}</p>
        {d.classified_by && <p className="small muted" style={{ margin: 0 }}>By {d.classified_by}, {fmtDateTime(d.classified_at)}</p>}
      </Card>
    );
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  function save() {
    run(() => api.put(base, { ...f, engagement_id: engagementId ?? null, annex_iii_area: f.classification === 'high_risk_annex_iii' ? f.annex_iii_area || null : null,
                              role: f.role || null, classification: f.classification || null }), 'Classification saved.');
  }
  return (
    <Card title="Classification reasoning" className="r6b-card">
      <div className="stack">
        <TextField label="EU exposure" value={f.exposure_basis} onChange={set('exposure_basis')} hint={d.eu_exposure ? `Register: ${d.eu_exposure}` : 'For example, EU customers or EU staff'} />
        <SelectField label="Role" value={f.role} onChange={set('role')} placeholder="Choose" options={opts(d.options.roles)} error={errs.role} />
        {f.role && f.role !== 'deployer' && <Checkbox label="The client also uses it (deployer duties apply too)" checked={f.also_deployer} onChange={(e) => setF({ ...f, also_deployer: e.target.checked })} />}
        <SelectField label="Classification" value={f.classification} onChange={set('classification')} placeholder="Choose" options={opts(d.options.classifications)} error={errs.classification} />
        {f.classification === 'high_risk_annex_iii' && <SelectField label="Annex III area" value={f.annex_iii_area} onChange={set('annex_iii_area')} placeholder="Choose" options={opts(d.options.areas)} error={errs.annex_iii_area} />}
        {f.classification === 'high_risk_annex_iii' && <Checkbox label="The deployer is a public body or provides public services (Art. 27)" checked={f.public_service} onChange={(e) => setF({ ...f, public_service: e.target.checked })} />}
        <TextArea label="Reasoning" rows={4} value={f.reasoning} onChange={set('reasoning')} error={errs.reasoning} />
        <div className="row">
          <Button variant="primary" onClick={save}>Save</Button>
          {d.signoff_status !== 'signed_off' && d.signoff_status !== 'awaiting_signoff' && <Button onClick={() => run(() => api.post(`${base}/send`), 'Sent to the Legal/Compliance Reviewer.')}>Send for legal sign-off</Button>}
        </div>
        <p className="small muted" style={{ margin: 0 }}>Reviewer: partner law firm (Legal/Compliance Reviewer role). Changing the role or classification after sign-off needs a new sign-off.</p>
      </div>
    </Card>
  );
}

function SignOffCard({ d, base, run }: { d: EuDetail; base: string; run: Run }) {
  const [note, setNote] = useState('');
  return (
    <Card title="Legal sign-off" actions={<Badge tone={SIGNOFF_TONE[d.signoff_status]}>{d.signoff_label}</Badge>} className="r6b-card">
      <div className="stack">
        {d.signoff_status === 'signed_off' && <p className="small" style={{ margin: 0 }}>Signed off by <strong>{d.signed_off_by}</strong> on {fmtDateTime(d.signed_off_at)}.</p>}
        {d.signoff_status === 'awaiting_signoff' && <p className="small" style={{ margin: 0 }}>Sent by {d.sent_by} on {fmtDate(d.sent_at)}. Waiting for the Legal/Compliance Reviewer.</p>}
        {d.signoff_status === 'returned' && <p className="small" style={{ margin: 0 }}>Returned by the reviewer.</p>}
        {d.signoff_status === 'draft' && <p className="small" style={{ margin: 0 }}>Not sent for sign-off yet.</p>}
        {d.signoff_note && <p className="small statement" style={{ margin: 0 }}>{d.signoff_note}</p>}
        {d.can_sign && d.signoff_status === 'awaiting_signoff' && (
          <>
            <TextArea label="Note to the audit team (optional)" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row">
              <Button variant="primary" onClick={() => run(() => api.post(`${base}/signoff`, { approve: true, note }), 'Classification signed off.')}>Sign off the classification</Button>
              <Button onClick={() => run(() => api.post(`${base}/signoff`, { approve: false, note }), 'Returned to the audit team.')}>Return with a note</Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function EuAiActLink({ to }: { to: string }) {
  return <Link to={to}>EU AI Act conformity</Link>;
}
