import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { RISK_TONE, type CopilotNotStarted, type CopilotSite, type CopilotView, type CopilotWave } from '@/api/r6b';
import { Alert, Badge, Button, Card, Checkbox, Dialog, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate } from '@/components/ui';
import '@/styles/r6b.css';

const opts = (m: Record<string, string>) => Object.entries(m).map(([value, label]) => ({ value, label }));
const short = (h: string) => `${h.slice(0, 12)}…`;

/** G-07 on the Futran side: `/e/:engagementId/copilot`. */
export function CopilotReadinessScreen() {
  const { engagementId = '' } = useParams();
  return <CopilotWorkspace engagementId={engagementId} />;
}

/** G-07 client view (`/copilot`): the CAICO's latest Copilot readiness engagement. */
export function ClientCopilotScreen() {
  const q = useQuery({ queryKey: ['copilot-list'], queryFn: () => api.get<{ engagement_id: string; name: string }[]>('/copilot') });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const first = q.data?.[0];
  if (!first) {
    return (
      <div className="page">
        <PageHeader title="Copilot readiness" />
        <EmptyState>There is no Microsoft 365 Copilot readiness work for your organisation yet.</EmptyState>
      </div>
    );
  }
  return <CopilotWorkspace engagementId={first.engagement_id} />;
}

function CopilotWorkspace({ engagementId }: { engagementId: string }) {
  const qc = useQueryClient();
  const key = ['copilot', engagementId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<CopilotView | CopilotNotStarted>(`/e/${engagementId}/copilot`) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [editSite, setEditSite] = useState<CopilotSite | null>(null);
  const [editWave, setEditWave] = useState<CopilotWave | 'new' | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  async function run(fn: () => Promise<CopilotView>, ok?: string) {
    setMsg(null);
    try {
      qc.setQueryData(key, await fn());
      if (ok) setMsg({ tone: 'success', text: ok });
    } catch (e) {
      setMsg({ tone: 'danger', text: errorMessage(e) });
      throw e;
    }
  }

  const base = `/e/${engagementId}/copilot`;
  if (!q.data.started) {
    const n = q.data;
    return (
      <div className="page r6b">
        <PageHeader crumbs={n.client_view ? undefined : [{ to: '/audits', label: 'Audits' }, { to: `/clients/${n.client.id}`, label: n.client.name }, { label: 'Copilot readiness' }]}
          title="Microsoft 365 Copilot readiness" subtitle={`${n.client.name} · ${n.engagement.audit_ref ?? n.engagement.name}`} />
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <EmptyState>
          {n.can_manage ? 'The workspace has not been started. Starting it sets up the controls checklist from the approved service template.'
            : 'The Futran team has not started the Copilot readiness work yet. The site risk list, rollout waves and controls show here once they do.'}
        </EmptyState>
        {n.can_manage && <div className="row"><Button variant="primary" onClick={() => run(() => api.post(`${base}/start`), 'Workspace started.').catch(() => undefined)}>Start the workspace</Button></div>}
      </div>
    );
  }
  const v = q.data;

  const s = v.summary;
  return (
    <div className="page r6b">
      <PageHeader
        crumbs={v.client_view ? undefined : [{ to: '/audits', label: 'Audits' }, { to: `/clients/${v.client.id}`, label: v.client.name }, { label: 'Copilot readiness' }]}
        title="Microsoft 365 Copilot readiness"
        subtitle={`${v.client.name} · ${v.engagement.audit_ref ?? v.engagement.name}`}
        actions={<PhasePills v={v} onPick={(p) => run(() => api.put(`${base}/phase`, { phase: p }), `Phase set to ${v.options.phases[p]}.`).catch(() => undefined)} />}
      />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <section className="r6b-tiles" aria-label="Readiness summary">
        <Tile label="Copilot licences" value={s.licences ?? '—'} sub={v.usage_as_of ? `From the licence report, ${fmtDate(v.usage_as_of)}` : 'Import the licence and usage report'} />
        <Tile label="Active users, 28 days" value={s.active_users ?? '—'} />
        <Tile label="High-risk sites" value={s.high_risk_sites} sub="From Purview and SharePoint reports" tone={s.high_risk_sites ? 'warn' : undefined} />
        <Tile label="Controls ready" value={`${s.controls_ready} / ${s.controls_total}`} />
      </section>

      {v.can_manage && <ImportsCard v={v} base={base} onDone={(view, text) => { qc.setQueryData(key, view); setMsg({ tone: 'success', text }); }} onError={(text) => setMsg({ tone: 'danger', text })} />}

      <Card title="Site risk list" className="r6b-card" actions={<a className="btn btn-sm" href={`/api/v1${base}/sites.csv`}>Export CSV</a>}>
        {v.sites.length === 0 ? <EmptyState>No sites yet. They come from the Purview oversharing and SharePoint permission reports.</EmptyState> : (
          <div className="table-wrap">
            <table className="table stack-table" aria-label="Site risk list">
              <thead><tr><th>Site</th><th>Sharing</th><th>Sensitive items</th><th>Label coverage</th><th>Risk</th><th>Action</th><th>Owner</th><th>Status</th>{v.can_update_sites && <th><span className="sr-only">Edit</span></th>}</tr></thead>
              <tbody>
                {v.sites.map((x) => (
                  <tr key={x.id}>
                    <td className="break"><strong>{x.name}</strong>{x.site_owner && <div className="small muted">Site owner: {x.site_owner}</div>}</td>
                    <td data-label="Sharing">{x.sharing_label}</td>
                    <td data-label="Sensitive items">{x.sensitive_items == null ? '—' : x.sensitive_items.toLocaleString()}</td>
                    <td data-label="Label coverage">{x.label_coverage == null ? '—' : `${x.label_coverage}%`}</td>
                    <td data-label="Risk"><Badge tone={RISK_TONE[x.risk]}>{v.options.risks[x.risk]}</Badge></td>
                    <td data-label="Action">{x.action_label ?? '—'}</td>
                    <td data-label="Owner">{x.action_owner ?? '—'}</td>
                    <td data-label="Status">{x.status_label}</td>
                    {v.can_update_sites && <td><Button size="sm" onClick={() => setEditSite(x)} aria-label={`Update ${x.name}`}>Update</Button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="r6b-halves">
        <div><ControlsCard v={v} base={base} run={run} /></div>
        <div>
          <Card title="Rollout waves" className="r6b-card" actions={v.can_manage ? <Button size="sm" onClick={() => setEditWave('new')}>Add wave</Button> : undefined}>
            {v.waves.length === 0 ? <EmptyState>No waves planned yet.</EmptyState> : (
              <div className="table-wrap"><table className="table stack-table" aria-label="Rollout waves">
                <thead><tr><th>Wave</th><th>Groups</th><th>Date</th><th>Gate</th></tr></thead>
                <tbody>
                  {v.waves.map((w) => (
                    <tr key={w.id}>
                      <td>{v.can_manage ? <button type="button" className="linklike" onClick={() => setEditWave(w)}>{w.name}</button> : <strong>{w.name}</strong>}</td>
                      <td data-label="Groups">{w.groups ?? '—'}{w.user_count != null && ` (${w.user_count})`}</td>
                      <td data-label="Date">{w.planned_on ? fmtDate(w.planned_on) : '—'}</td>
                      <td data-label="Gate"><span className={w.gate === 'go' ? 'r6b-go' : 'r6b-hold'}>{w.gate_text}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </Card>
        </div>
      </div>

      {!v.client_view && <OutputsCard v={v} base={base} run={run} />}
      {v.client_view && v.report && <Card title="Readiness report"><a className="file-link" href={fileUrl(v.report.file_id)}>{v.report.filename}</a></Card>}

      {editSite && <SiteDialog v={v} site={editSite} onClose={() => setEditSite(null)}
        onSave={(body) => run(() => api.put(`${base}/sites/${editSite.id}`, body), `${editSite.name} updated.`).then(() => setEditSite(null))} />}
      {editWave && <WaveDialog v={v} wave={editWave === 'new' ? null : editWave} onClose={() => setEditWave(null)}
        onSave={(body) => run(() => editWave === 'new' ? api.post(`${base}/waves`, body) : api.put(`${base}/waves/${editWave.id}`, body), 'Rollout waves updated.').then(() => setEditWave(null))}
        onDelete={editWave === 'new' ? undefined : () => run(() => api.delete(`${base}/waves/${editWave.id}`), 'Wave removed.').then(() => setEditWave(null))} />}
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: 'warn' }) {
  return (
    <div className={`r6b-tile${tone ? ` r6b-tile-${tone}` : ''}`}>
      <div className="small muted">{label}</div>
      <div className="r6b-tile-value">{value}</div>
      {sub && <div className="small">{sub}</div>}
    </div>
  );
}

function PhasePills({ v, onPick }: { v: CopilotView; onPick: (p: string) => void }) {
  return (
    <nav className="r6b-phases" aria-label="Phases">
      {Object.entries(v.options.phases).map(([k, label]) => v.can_manage
        ? <button key={k} type="button" aria-current={v.phase === k ? 'step' : undefined} className={v.phase === k ? 'on' : ''} onClick={() => v.phase !== k && onPick(k)}>{label}</button>
        : <span key={k} aria-current={v.phase === k ? 'step' : undefined} className={v.phase === k ? 'on' : ''}>{label}</span>)}
    </nav>
  );
}

function ImportsCard({ v, base, onDone, onError }: { v: CopilotView; base: string; onDone: (v: CopilotView, text: string) => void; onError: (t: string) => void }) {
  const [kind, setKind] = useState('licence_usage');
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  async function upload() {
    const f = file.current?.files?.[0];
    if (!f) return onError('Choose the exported file first.');
    const form = new FormData();
    form.append('file', f);
    setBusy(true);
    try {
      const view = await api.upload<CopilotView>(`${base}/imports/${kind}`, form);
      onDone(view, `${v.options.import_kinds[kind].label} imported. The file is kept as evidence with its SHA-256 hash.`);
      if (file.current) file.current.value = '';
    } catch (e) {
      const fe = fieldErrors(e);
      onError(fe.file ? `${errorMessage(e)} ${fe.file}` : errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="Imports" className="r6b-card">
      <div className="r6b-import">
        <SelectField label="Export" value={kind} onChange={(e) => setKind(e.target.value)} options={Object.entries(v.options.import_kinds).map(([value, k]) => ({ value, label: `${k.label} (${k.source})` }))} />
        <div className="field"><label htmlFor="r6b-file">File (CSV or Excel)</label><input id="r6b-file" ref={file} type="file" accept=".csv,.xlsx" /></div>
        <Button variant="primary" onClick={upload} disabled={busy}>{busy ? 'Importing…' : 'Import'}</Button>
      </div>
      {v.imports.length > 0 && (
        <ul className="r6b-list small" aria-label="Imported reports">
          {v.imports.map((i) => (
            <li key={i.id}>
              <strong>{i.kind_label}</strong> · {i.file_id ? <a className="file-link" href={fileUrl(i.file_id)}>{i.filename}</a> : i.filename} · {i.rows_used} rows ·{' '}
              <span title={i.sha256}>SHA-256 {short(i.sha256)}</span> · {i.imported_by ?? '—'}, {fmtDate(i.imported_at)}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ControlsCard({ v, base, run }: { v: CopilotView; base: string; run: (fn: () => Promise<CopilotView>, ok?: string) => Promise<void> }) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  async function evidence(key: string, f: File | undefined) {
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    setBusyKey(key);
    await run(() => api.upload(`${base}/controls/${key}/evidence`, form), 'Evidence added.').catch(() => undefined);
    setBusyKey(null);
  }
  return (
    <Card title="Controls checklist" className="r6b-card">
      <ul className="r6b-controls" aria-label="Controls checklist">
        {v.controls.map((c) => (
          <li key={c.key} className={`r6b-control r6b-control-${c.status}`}>
            <div className="r6b-control-head">
              <span className="r6b-control-label"><span className="r6b-status">{c.status_label}</span> · {c.label}</span>
              {v.can_manage && (
                <select aria-label={`Status of ${c.label}`} value={c.status} onChange={(e) => run(() => api.put(`${base}/controls/${c.key}`, { status: e.target.value })).catch(() => undefined)}>
                  {opts(v.options.control_statuses).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              )}
            </div>
            {c.note && <div className="small muted">{c.note}</div>}
            {c.evidence.length > 0 && <div className="small">{c.evidence.map((f) => <a key={f.id} className="file-link r6b-ev" href={fileUrl(f.id)} title={`SHA-256 ${f.sha256}`}>{f.filename}</a>)}</div>}
            {v.can_manage && (
              <label className="small r6b-attach">
                {busyKey === c.key ? 'Uploading…' : 'Attach evidence'}
                <input type="file" className="sr-only" aria-label={`Attach evidence to ${c.label}`} onChange={(e) => evidence(c.key, e.target.files?.[0])} />
              </label>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function OutputsCard({ v, base, run }: { v: CopilotView; base: string; run: (fn: () => Promise<CopilotView>, ok?: string) => Promise<void> }) {
  return (
    <div className="grid-2">
      <Card title="AI register entry">
        {v.register_entry
          ? <p className="small" style={{ margin: 0 }}>Copilot is in {v.client.name}'s AI register as <strong>{v.register_entry.reference} {v.register_entry.name}</strong>, with the laws in scope for the client and the roles they require.</p>
          : <p className="small" style={{ margin: 0 }}>Copilot is not in the client's AI register yet.</p>}
        {v.can_manage && !v.register_entry && <RegisterLink v={v} base={base} run={run} />}
      </Card>
      <Card title="Readiness report">
        {v.report ? <p className="small" style={{ margin: 0 }}><a className="file-link" href={fileUrl(v.report.file_id)}>{v.report.filename}</a>{v.report.created_at && ` · ${fmtDate(v.report.created_at)}`}</p>
          : <p className="small" style={{ margin: 0 }}>Not produced yet.</p>}
        {v.can_manage && <div className="row" style={{ marginTop: 12 }}><Button variant="primary" onClick={() => run(() => api.post(`${base}/report`), 'Readiness report produced.').catch(() => undefined)}>{v.report ? 'Produce it again' : 'Produce the readiness report'}</Button></div>}
      </Card>
    </div>
  );
}

function RegisterLink({ v, base, run }: { v: CopilotView; base: string; run: (fn: () => Promise<CopilotView>, ok?: string) => Promise<void> }) {
  const [pick, setPick] = useState(v.register_candidates[0]?.id ?? '');
  const choices = v.register_choices.map((c) => ({ value: c.id, label: `${c.reference} ${c.name}` }));
  return (
    <div className="stack" style={{ marginTop: 12 }}>
      {v.register_candidates.length > 0 && <p className="small" style={{ margin: 0 }}>The register already lists {v.register_candidates.map((c) => `${c.reference} ${c.name}`).join(', ')}. Link it rather than adding another entry.</p>}
      {choices.length > 0 && (
        <div className="r6b-import">
          <SelectField label="Link to an existing system" value={pick} onChange={(e) => setPick(e.target.value)} placeholder="Choose" options={choices} />
          <Button onClick={() => pick && run(() => api.post(`${base}/register`, { register_system_id: pick }), 'Copilot linked to the existing register entry.').catch(() => undefined)}>Link</Button>
        </div>
      )}
      {v.register_candidates.length === 0 && <div className="row"><Button onClick={() => run(() => api.post(`${base}/register`, {}), 'Copilot added to the AI register.').catch(() => undefined)}>Add Copilot to the AI register</Button></div>}
    </div>
  );
}

function SiteDialog({ v, site, onClose, onSave }: { v: CopilotView; site: CopilotSite; onClose: () => void; onSave: (b: Record<string, unknown>) => Promise<void> }) {
  const [f, setF] = useState({ action: site.action ?? '', risk_override: site.risk_overridden ? site.risk : '', action_owner: site.action_owner ?? '', status: site.status, note: site.note ?? '' });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  function save() {
    const body: Record<string, unknown> = { action_owner: f.action_owner, status: f.status, note: f.note };
    if (v.can_manage) Object.assign(body, { action: f.action || null, risk_override: f.risk_override || null });
    onSave(body).catch(() => undefined);
  }
  return (
    <Dialog title={`Update ${site.name}`} onClose={onClose}>
      <div className="stack">
        {v.can_manage && <SelectField label="Action" value={f.action} onChange={set('action')} placeholder="Not chosen" options={opts(v.options.actions)} />}
        {v.can_manage && <SelectField label="Risk" value={f.risk_override} onChange={set('risk_override')} placeholder={`As calculated (${v.options.risks[site.risk]})`} options={opts(v.options.risks)} />}
        <TextField label="Remediation owner" value={f.action_owner} onChange={set('action_owner')} />
        <SelectField label="Status" value={f.status} onChange={set('status')} options={opts(v.options.statuses)} />
        <TextArea label="Note" value={f.note} onChange={set('note')} rows={3} />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function WaveDialog({ v, wave, onClose, onSave, onDelete }: { v: CopilotView; wave: CopilotWave | null; onClose: () => void; onSave: (b: Record<string, unknown>) => Promise<void>; onDelete?: () => Promise<void> }) {
  const [f, setF] = useState({ name: wave?.name ?? '', groups: wave?.groups ?? '', user_count: wave?.user_count?.toString() ?? '', planned_on: wave?.planned_on ?? '', hold_note: wave?.hold_note ?? '' });
  const [sites, setSites] = useState<string[]>(wave?.gate_site_ids ?? []);
  const [ctls, setCtls] = useState<string[]>(wave?.gate_control_keys ?? []);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const toggle = (list: string[], set: (x: string[]) => void, id: string) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  function save() {
    onSave({ name: f.name, groups: f.groups, user_count: f.user_count ? Number(f.user_count) : null, planned_on: f.planned_on || null, hold_note: f.hold_note,
             gate_site_ids: sites, gate_control_keys: ctls }).catch(() => undefined);
  }
  return (
    <Dialog title={wave ? `Wave: ${wave.name}` : 'Add a rollout wave'} onClose={onClose} wide>
      <div className="stack">
        <div className="grid-2">
          <TextField label="Wave" value={f.name} onChange={set('name')} />
          <TextField label="Groups" value={f.groups} onChange={set('groups')} hint="Who gets Copilot in this wave" />
          <TextField label="Users" type="number" min={0} value={f.user_count} onChange={set('user_count')} />
          <TextField label="Date" type="date" value={f.planned_on} onChange={set('planned_on')} />
        </div>
        <fieldset className="r6b-fieldset"><legend>Sites that must be done first</legend>
          {v.sites.length === 0 ? <p className="small muted">No sites imported yet.</p> : v.sites.map((s) => <Checkbox key={s.id} label={`${s.name} (${v.options.risks[s.risk]})`} checked={sites.includes(s.id)} onChange={() => toggle(sites, setSites, s.id)} />)}
        </fieldset>
        <fieldset className="r6b-fieldset"><legend>Controls that must be ready first</legend>
          {v.controls.map((c) => <Checkbox key={c.key} label={c.label} checked={ctls.includes(c.key)} onChange={() => toggle(ctls, setCtls, c.key)} />)}
        </fieldset>
        <TextField label="Hold, whatever the checks say (optional)" value={f.hold_note} onChange={set('hold_note')} hint="For example, waiting for the works council" />
        <div className="row"><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button>{onDelete && <Button variant="danger" onClick={() => onDelete().catch(() => undefined)}>Remove the wave</Button>}</div>
      </div>
    </Dialog>
  );
}

export function CopilotLink({ engagementId }: { engagementId: string }) {
  return <Link to={`/e/${engagementId}/copilot`}>Copilot readiness</Link>;
}
