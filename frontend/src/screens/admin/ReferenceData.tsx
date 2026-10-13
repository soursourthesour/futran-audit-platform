import { Fragment, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { TYPE_LABELS, useFeatures, useLawJurisdictions, type Law } from '@/api/laws';
import { LawPicker } from '@/components/LawPicker';
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { LawUpdates } from './LawUpdates';

type Tab = 'laws' | 'jurisdictions' | 'import' | 'versions' | 'updates';

export function ReferenceData() {
  const { data: me } = useMe();
  const isAdmin = hasRole(me ?? undefined, 'admin');
  const [tab, setTab] = useState<Tab>('laws');
  const tabs: { id: Tab; label: string; admin?: boolean }[] = [
    { id: 'laws', label: 'Laws' },
    { id: 'jurisdictions', label: 'Jurisdictions' },
    { id: 'import', label: 'Import workbook', admin: true },
    { id: 'updates', label: 'Law updates', admin: true },
    { id: 'versions', label: 'Versions' },
  ];
  return (
    <div className="page">
      <PageHeader title="Reference data" subtitle="The law matrix behind every client's laws in scope. Changes create a new version; laws a client already references are never deleted." />
      <div className="pills" role="tablist" aria-label="Reference data sections">
        {tabs.filter((t) => !t.admin || isAdmin).map((t) => (
          <button key={t.id} role="tab" className="pill" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      {tab === 'laws' && <LawsTab canEdit={isAdmin} />}
      {tab === 'jurisdictions' && <JurisdictionsTab canEdit={isAdmin} />}
      {tab === 'import' && <ImportTab />}
      {tab === 'updates' && <LawUpdates />}
      {tab === 'versions' && <VersionsTab />}
    </div>
  );
}

function LawsTab({ canEdit }: { canEdit: boolean }) {
  const [open, setOpen] = useState<Law | null>(null);
  const [adding, setAdding] = useState(false);
  return (
    <div className="split">
      <div className="main">
        <Card title="Browse laws" actions={canEdit ? <Button size="sm" onClick={() => { setOpen(null); setAdding(true); }}>Add a law</Button> : undefined}>
          <LawPicker mode="browse" onOpen={(l) => { setAdding(false); setOpen(l); }} presets={[{ value: 'US', label: 'United States — federal', codes: ['US'] }]} />
        </Card>
      </div>
      <div className="side">
        {adding && <LawEditor key="new" onDone={() => setAdding(false)} />}
        {open && !adding && (canEdit ? <LawEditor key={open.id} law={open} onDone={() => setOpen(null)} /> : <LawDetail law={open} />)}
        {!open && !adding && <Card><EmptyState>Select a law to see its details{canEdit ? ' or edit it' : ''}.</EmptyState></Card>}
      </div>
    </div>
  );
}

function LawDetail({ law }: { law: Law }) {
  const rows: [string, ReactNode][] = [
    ['Jurisdiction', law.jurisdiction_name],
    ['Feature', law.feature_label],
    ['Type', law.type_text ?? TYPE_LABELS[law.type]],
    ['Enforcer', law.enforcer],
    ['When it reaches AI', law.trigger_text],
    ['Obligations', law.obligations_text ?? law.summary],
    ['Developments', law.developments_text],
    ['Most affected', law.most_affected],
    ['Applies to', law.applies_to === 'developer' ? 'Developers only' : law.applies_to === 'both' ? 'Developers and deployers' : 'Deployers'],
  ];
  return (
    <Card title={law.short_name}>
      {law.verify_flag && <Alert tone="warn">Part of this entry is marked "verify" in the source: its status or date has not been confirmed from a primary source.</Alert>}
      <dl className="kv" style={{ marginTop: 12 }}>{rows.filter(([, v]) => v).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
    </Card>
  );
}

function LawEditor({ law, onDone }: { law?: Law; onDone: () => void }) {
  const features = useFeatures();
  const juris = useLawJurisdictions();
  const qc = useQueryClient();
  const [f, setF] = useState({
    jurisdiction_code: law?.jurisdiction_code ?? 'US',
    short_name: law?.short_name ?? '',
    feature: law?.feature ?? 'employment_hiring',
    type: law?.type ?? 'statute',
    enforcer: law?.enforcer ?? '',
    trigger_text: law?.trigger_text ?? '',
    obligations_text: law?.obligations_text ?? (law ? law.summary : ''),
    developments_text: law?.developments_text ?? '',
    applies_to: law?.applies_to ?? 'deployer',
    verify_flag: law?.verify_flag ?? false,
  });
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const set = (k: string, v: string | boolean) => setF({ ...f, [k]: v });
  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      if (law) {
        const { jurisdiction_code: _j, ...rest } = f;
        void _j;
        await api.patch(`/laws/${law.id}`, rest);
      } else await api.post('/laws', f);
      await qc.invalidateQueries({ queryKey: ['laws'] });
      onDone();
    } catch (ex) {
      setErr(errorMessage(ex));
      setFe(fieldErrors(ex));
    }
  }
  return (
    <Card title={law ? 'Edit law' : 'Add a law'}>
      <form className="stack" onSubmit={save} noValidate>
        {err && <Alert tone="danger">{err}</Alert>}
        <p className="small muted">Saving creates a new version of the law matrix. The previous text stays on record.</p>
        {!law && <SelectField label="Jurisdiction" value={f.jurisdiction_code} onChange={(e) => set('jurisdiction_code', e.target.value)} options={(juris.data ?? []).map((j) => ({ value: j.code, label: `${j.name} (${j.code})` }))} error={fe.jurisdiction_code} />}
        <TextField label="Short name" value={f.short_name} onChange={(e) => set('short_name', e.target.value)} error={fe.short_name} />
        <SelectField label="AI feature" value={f.feature} onChange={(e) => set('feature', e.target.value)} options={features.data ?? []} />
        <SelectField label="Type" value={f.type} onChange={(e) => set('type', e.target.value)} options={Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))} />
        <SelectField label="Applies to" value={f.applies_to} onChange={(e) => set('applies_to', e.target.value)} options={[{ value: 'deployer', label: 'Organizations using AI (deployers)' }, { value: 'developer', label: 'AI developers only' }, { value: 'both', label: 'Both' }]} />
        <TextField label="Enforcer" value={f.enforcer} onChange={(e) => set('enforcer', e.target.value)} />
        <TextArea label="When it reaches AI" value={f.trigger_text} onChange={(e) => set('trigger_text', e.target.value)} />
        <TextArea label="Key obligations" value={f.obligations_text} onChange={(e) => set('obligations_text', e.target.value)} />
        <TextArea label="Developments and key dates" value={f.developments_text} onChange={(e) => set('developments_text', e.target.value)} />
        <Checkbox label="Status or date still to be verified" checked={f.verify_flag} onChange={(e) => set('verify_flag', e.target.checked)} />
        <div className="row"><Button type="submit" variant="primary">Save</Button><Button onClick={onDone}>Cancel</Button></div>
      </form>
    </Card>
  );
}

function JurisdictionsTab({ canEdit }: { canEdit: boolean }) {
  const juris = useLawJurisdictions();
  const qc = useQueryClient();
  const [form, setForm] = useState({ level: 'city', name: '', parent_code: '', code: '', aliases: '' });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  async function add(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    setFe({});
    try {
      const j = await api.post<{ code: string; name: string }>('/jurisdictions', { ...form, parent_code: form.parent_code || null, code: form.code || null, aliases: form.aliases.split(',').map((s) => s.trim()).filter(Boolean) });
      setMsg({ tone: 'success', text: `${j.name} added as ${j.code}. Add laws to it from the Laws tab.` });
      setForm({ level: 'city', name: '', parent_code: '', code: '', aliases: '' });
      await qc.invalidateQueries({ queryKey: ['jurisdictions'] });
    } catch (ex) {
      setMsg({ tone: 'danger', text: errorMessage(ex) });
      setFe(fieldErrors(ex));
    }
  }
  const groups: Record<string, typeof juris.data> = {};
  for (const j of juris.data ?? []) (groups[j.level] ??= []).push(j);
  const order = ['supranational', 'country', 'state', 'city'];
  const labels: Record<string, string> = { supranational: 'Regional groups', country: 'Countries', state: 'States and provinces', city: 'Cities' };
  return (
    <div className="split">
      <div className="main">
        <Card title="Jurisdictions with laws">
          {juris.isLoading ? <Loading /> : (
            <div className="stack">
              <p className="small muted">Every country and first-level subdivision in ISO 3166 is available for client sites. These are the ones with laws in the matrix. A site inherits the laws of its city, state, country and any regional group (for example a Berlin office picks up Germany and the EU).</p>
              {order.filter((l) => groups[l]?.length).map((l) => (
                <div key={l}>
                  <h3 style={{ fontSize: 14, color: 'var(--muted)', marginBottom: 6 }}>{labels[l]} · {groups[l]!.length}</h3>
                  <div className="row" style={{ gap: 6 }}>{groups[l]!.map((j) => <Badge key={j.code} tone="navy">{j.name} · {j.code}</Badge>)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      {canEdit && (
        <div className="side">
          <Card title="Add a jurisdiction">
            <form className="stack" onSubmit={add} noValidate>
              {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
              <SelectField label="Level" value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })} options={[{ value: 'city', label: 'City' }, { value: 'state', label: 'State or province' }, { value: 'country', label: 'Country' }, { value: 'supranational', label: 'Regional group' }]} />
              <TextField label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={fe.name} />
              <TextField label="Parent code" value={form.parent_code} onChange={(e) => setForm({ ...form, parent_code: e.target.value })} help="For a city, the state code (for example US-IL). For a state, the country (for example GB)." error={fe.parent_code} />
              {form.level !== 'city' && <TextField label="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} help="ISO style, for example GB-SCT." error={fe.code} />}
              <TextField label="Other names" value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} help="Comma separated. Used to match addresses, for example Manhattan, Brooklyn." />
              <Button type="submit" variant="primary">Add jurisdiction</Button>
            </form>
          </Card>
        </div>
      )}
    </div>
  );
}

type PreviewRow = { row_key: string; kind: string; source_sheet: string; jurisdiction_code: string; jurisdiction_name: string; feature: string; short_name: string; full_text: string; verify_flag: boolean; applies_to: string };
type Preview = { preview_id: string; status_date: string | null; source_filename: string; rows: PreviewRow[]; warnings: string[]; counts: Record<string, number> };

function ImportTab() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'info'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setMsg(null);
    const form = new FormData();
    form.append('file', file);
    try {
      setPv(await api.upload<Preview>('/admin/laws/import', form));
      setEdits({});
    } catch (ex) {
      setMsg({ tone: 'danger', text: errorMessage(ex) });
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (!pv) return;
    setBusy(true);
    try {
      const out = await api.post<{ summary: Record<string, number> }>(`/admin/laws/import/${pv.preview_id}/publish`, { edits });
      setMsg({ tone: 'success', text: `Published. ${out.summary.created} new, ${out.summary.updated} changed, ${out.summary.unchanged} unchanged, ${out.summary.retired} no longer in the workbook (kept on record).` });
      setPv(null);
      await qc.invalidateQueries();
    } catch (ex) {
      setMsg({ tone: 'danger', text: errorMessage(ex) });
    } finally {
      setBusy(false);
    }
  }
  const rows = (pv?.rows ?? []).filter((r) => r.kind === 'regulation' && (!filter || `${r.jurisdiction_name} ${r.short_name}`.toLowerCase().includes(filter.toLowerCase())));
  return (
    <div className="stack">
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card title="Upload the law matrix workbook">
        <div className="stack">
          <p className="small muted">Upload the Futran Global AI Law Matrix (.xlsx). You will see every law the importer found before anything changes. Edit short names where the importer's guess is unclear, then publish.</p>
          <div className="row"><input ref={fileRef} type="file" accept=".xlsx" aria-label="Law matrix workbook" /><Button variant="primary" onClick={upload} disabled={busy}>{busy ? 'Reading…' : 'Preview import'}</Button></div>
        </div>
      </Card>
      {pv && (
        <Card title={`Preview — status ${fmtDate(pv.status_date)}`} actions={<Button variant="primary" onClick={publish} disabled={busy}>Publish {pv.counts.regulations} laws</Button>}>
          <div className="stack">
            <div className="row small">
              <Badge>{pv.counts.regulations} laws</Badge><Badge>{pv.counts.jurisdictions} jurisdictions</Badge><Badge tone="warn">{pv.counts.verify} to verify</Badge><Badge tone="muted">{pv.counts.developer_only} developer-only</Badge><Badge tone="muted">{pv.counts.notes} notes</Badge>
            </div>
            {pv.warnings.length > 0 && <Alert tone="warn"><strong>{pv.warnings.length} warnings.</strong> {pv.warnings.slice(0, 5).join(' ')}</Alert>}
            <div style={{ maxWidth: 360 }}><TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Jurisdiction</th><th>Feature</th><th>Short name</th><th>Source text</th></tr></thead>
                <tbody>
                  {rows.slice(0, 400).map((r) => (
                    <tr key={r.row_key}>
                      <td>{r.jurisdiction_name}</td>
                      <td className="small">{r.feature.replace(/_/g, ' ')}</td>
                      <td style={{ minWidth: 260 }}>
                        <input className="input" aria-label={`Short name for ${r.row_key}`} value={edits[r.row_key] ?? r.short_name} onChange={(e) => setEdits({ ...edits, [r.row_key]: e.target.value })} />
                        <div className="row" style={{ marginTop: 4, gap: 6 }}>{r.verify_flag && <Badge tone="warn">Verify</Badge>}{r.applies_to === 'developer' && <Badge tone="muted">Developer only</Badge>}</div>
                      </td>
                      <td className="small muted" style={{ whiteSpace: 'normal', maxWidth: 520 }}>{r.full_text.slice(0, 280)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function VersionsTab() {
  const q = useQuery({ queryKey: ['law-versions'], queryFn: () => api.get<{ id: string; label: string; origin: string; status: string; published_at: string; warnings: string[] }[]>('/admin/laws/versions'), retry: false });
  if (q.isError) return <Card><EmptyState>Only administrators can see the version history.</EmptyState></Card>;
  return (
    <Card title="Version history">
      {q.isLoading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Published</th><th>Version</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>
              {q.data?.map((v) => (
                <tr key={v.id}><td>{fmtDateTime(v.published_at)}</td><td>{v.label}</td><td>{v.origin === 'claude' ? 'Claude proposals' : v.origin === 'manual' ? 'Manual edit' : 'Workbook import'}</td><td>{v.status === 'published' ? <Badge tone="success">Current</Badge> : <Badge tone="muted">Earlier</Badge>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
