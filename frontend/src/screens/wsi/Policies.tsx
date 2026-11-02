import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import type { PolicyList, TemplateCard } from '@/api/wsi';
import { Alert, Badge, Button, Dialog, Loading, PageHeader, SelectField, fmtDate } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { BlockView } from './Blocks';
import { policyHelp as H } from '@/help/wsi';
import './wsi.css';

export const POLICY_TONE: Record<string, 'navy' | 'success' | 'warn' | 'muted'> = { draft: 'warn', awaiting_approval: 'navy', published: 'success', retired: 'muted' };

/** Policies `/policies` (screen 27): commitments a Futran template can answer, the client's policies, and the library. */
export function Policies() {
  const q = useQuery({ queryKey: ['policies'], queryFn: () => api.get<PolicyList>('/policies') });
  const [params, setParams] = useSearchParams();
  const [starting, setStarting] = useState<{ commitment?: string; template?: string } | null>(null);
  const [preview, setPreview] = useState<TemplateCard | null>(null);
  const navigate = useNavigate();
  useEffect(() => {
    const c = params.get('commitment');
    if (c && q.data) { setStarting({ commitment: c, template: q.data.commitments.find((x) => x.id === c)?.suggested_template ?? undefined }); setParams({}, { replace: true }); }
  }, [params, q.data, setParams]);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const nav = (id: string) => `/policies/${id}`;
  return (
    <div className="page">
      <PageHeader title="Policies" subtitle="Build AI policies from Futran templates, approve them and collect staff acknowledgments." actions={d.can.edit ? <Button variant="primary" onClick={() => setStarting({})}>Start from Futran template</Button> : undefined} />
      {d.commitments.length > 0 && (
        <section className="card" aria-labelledby="pol-commit-h">
          <div className="card-header"><h2 id="pol-commit-h">Commitments a template can answer</h2></div>
          <div className="card-body stack-sm">
            {d.commitments.map((c) => (
              <div key={c.id} className="row" style={{ justifyContent: 'space-between' }}>
                <span>{c.description} <span className="small muted">· {c.owner} · due {fmtDate(c.target_date)}</span></span>
                {d.can.edit && <Button size="sm" onClick={() => setStarting({ commitment: c.id, template: c.suggested_template ?? undefined })}>Start from Futran template</Button>}
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="card" aria-labelledby="pol-list-h">
        <div className="card-header"><h2 id="pol-list-h">Your policies</h2></div>
        <div className="card-body">
          <DataGrid label="Policies" rows={d.policies} rowId={(p) => p.id} rowLabel={(p) => p.title} initialSort={{ key: 'title', dir: 'asc' }}
            emptyText="No policies yet. Start one from a Futran template."
            search={{ label: 'Search policies', text: (p) => p.title }}
            filters={[{ key: 'status', label: 'Status', options: Object.entries({ draft: 'Draft', awaiting_approval: 'Awaiting approval', published: 'Published', retired: 'Retired' }).map(([value, label]) => ({ value, label })), test: (p, v) => p.status === v }]}
            columns={[
              { key: 'title', header: 'Policy', value: (p) => p.title, render: (p) => <Link to={nav(p.id)}>{p.title}</Link> },
              { key: 'version', header: 'Version', value: (p) => p.version_no },
              { key: 'status', header: 'Status', value: (p) => p.status_label, render: (p) => <Badge tone={POLICY_TONE[p.status]}>{p.status_label}</Badge> },
              { key: 'review', header: 'Next review', value: (p) => p.review_due ?? '', render: (p) => p.review_due ? <span className={p.review_overdue ? 'wsi-overdue' : undefined}>{fmtDate(p.review_due)}{p.review_overdue ? ' (overdue)' : ''}</span> : '—' },
              { key: 'acks', header: 'Acknowledged', value: (p) => p.acknowledgments?.acknowledged ?? -1, render: (p) => p.acknowledgments ? `${p.acknowledgments.acknowledged} of ${p.acknowledgments.sent}` : '—' },
            ]}
            rowActions={(p) => [
              { label: 'Open', onSelect: () => navigate(nav(p.id)) },
              { label: 'Download PDF', onSelect: () => { window.location.href = `/api/v1/policies/${p.id}/pdf`; } },
            ]} />
        </div>
      </section>
      <section aria-labelledby="pol-lib-h" className="stack-sm">
        <h2 id="pol-lib-h" style={{ fontSize: 18, margin: 0 }}>Futran template library</h2>
        <div className="wsi-cards">
          {d.templates.map((t) => (
            <article key={t.code} className="wsi-card" aria-label={t.name}>
              <h3>{t.name}</h3>
              <span className="small muted">Futran template v{t.version}</span>
              <p className="small" style={{ margin: 0, flex: 1 }}>{t.summary}</p>
              <div className="row">
                <Button size="sm" onClick={() => setPreview(t)}>Preview</Button>
                {d.can.edit && <Button size="sm" variant="primary" onClick={() => setStarting({ template: t.code })}>Use template</Button>}
              </div>
            </article>
          ))}
        </div>
        <p className="small muted" style={{ margin: 0 }}>How Futran can help: advisory hours to tailor a policy can be quoted from the policy builder. The Futran team that tailors a policy cannot audit it later.</p>
      </section>
      {starting && <StartDialog data={d} initial={starting} onClose={() => setStarting(null)} />}
      {preview && <PreviewDialog t={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function StartDialog({ data, initial, onClose }: { data: PolicyList; initial: { commitment?: string; template?: string }; onClose: () => void }) {
  const navigate = useNavigate();
  const [template, setTemplate] = useState(initial.template ?? '');
  const [commitment, setCommitment] = useState(initial.commitment ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try {
      const p = await api.post<{ id: string }>('/policies', { template_code: template, commitment_id: commitment || null });
      navigate(`/policies/${p.id}`);
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Dialog title="Start from Futran template" onClose={onClose}>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        <SelectField label="Template" help={H.template} value={template} onChange={(e) => setTemplate(e.target.value)} placeholder="Choose a template"
          options={data.templates.map((t) => ({ value: t.code, label: `${t.name} (v${t.version})` }))} />
        <SelectField label="Commitment it answers" help={H.commitment} value={commitment} onChange={(e) => setCommitment(e.target.value)}
          options={[{ value: '', label: 'None' }, ...data.commitments.map((c) => ({ value: c.id, label: c.description }))]} />
        <div className="row"><Button variant="primary" disabled={!template || busy} onClick={go}>{busy ? 'Starting…' : 'Start the draft'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function PreviewDialog({ t, onClose }: { t: TemplateCard; onClose: () => void }) {
  const q = useQuery({ queryKey: ['policy-template', t.code], queryFn: () => api.get<{ blocks: import('@/api/wsi').Block[] }>(`/policy-templates/${t.code}`) });
  return (
    <Dialog title={`${t.name} · v${t.version}`} onClose={onClose} large>
      {q.data ? <div className="wsi-doc"><BlockView blocks={q.data.blocks} /></div> : <Loading />}
    </Dialog>
  );
}
