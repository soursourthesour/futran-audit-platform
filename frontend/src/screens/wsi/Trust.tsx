import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import type { PublicItem, PublicTrust, TrustEditorData, TrustItem } from '@/api/wsi';
import { Alert, Badge, Button, Checkbox, Dialog, Loading, PageHeader, SelectField, TextArea, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import { DataGrid } from '@/components/ui/DataGrid';
import { trustHelp as H } from '@/help/wsi';
import './wsi.css';

const STATUS: Record<TrustItem['status'], { label: string; tone: 'warn' | 'navy' | 'danger' | 'success' | 'muted' }> = {
  draft: { label: 'Draft', tone: 'warn' }, awaiting_confirmation: { label: 'Waiting for Futran', tone: 'navy' }, returned: { label: 'Returned by Futran', tone: 'danger' },
  published: { label: 'Published', tone: 'success' }, withdrawn: { label: 'Withdrawn', tone: 'muted' },
};

/** Trust Center editor `/trust` (screen 32): the CAICO builds the page and approves items; Futran confirms each one
 *  against the signed report before it is public. The Client Admin can view. */
export function TrustEditor() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['trust'], queryFn: () => api.get<TrustEditorData>('/trust') });
  const [editing, setEditing] = useState<TrustItem | 'new' | null>(null);
  const [settings, setSettings] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['trust'] });
  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ tone: 'success', text: ok }); await refresh(); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  const total = d.views.reduce((n, v) => n + v.views, 0);
  const max = Math.max(1, ...d.views.map((v) => v.views));
  return (
    <div className="page">
      <PageHeader title="Trust Center" subtitle="Your public page on how you govern AI. Each item is published only after you approve it and Futran confirms it matches the signed report."
        actions={<>{d.page && <a className="btn" href={d.page.url_path} target="_blank" rel="noreferrer">Open public page</a>}{d.can.edit && <Button onClick={() => setSettings(true)}>{d.page ? 'Page settings' : 'Set up the page'}</Button>}{d.can.edit && d.page && <Button variant="primary" onClick={() => setEditing('new')}>Add item</Button>}</>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!d.has_signed_report && <Alert tone="warn">There is no signed Futran report yet, so Futran cannot confirm any item. You can prepare items now.</Alert>}
      {d.page ? (
        <div className="wsi-two">
          <section className="card wsi-main" aria-labelledby="tc-items-h">
            <div className="card-header"><h2 id="tc-items-h">Items</h2><span className="small muted">{d.page.live ? `Live at ${d.page.url_path}` : 'Not live'}{d.page.access === 'nda' ? ' · NDA click-through' : ''}{d.page.indexable ? '' : ' · hidden from search engines'}</span></div>
            <div className="card-body">
              <DataGrid label="Trust Center items" rows={d.items} rowId={(i) => i.id} rowLabel={(i) => i.title} emptyText="No items yet. Add commitments, policies, the bias audit summary and the Audited by Futran badge."
                columns={[
                  { key: 'title', header: 'Item', value: (i) => i.title, render: (i) => <><strong>{i.title}</strong><div className="small muted">{i.kind_label}</div>{i.problem && <div className="small wsi-overdue">{i.problem}</div>}</> },
                  { key: 'status', header: 'Status', value: (i) => i.status, render: (i) => <><Badge tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Badge>{i.live && i.status !== 'published' && <div className="small muted">Confirmed version still public</div>}{i.return_note && i.status === 'returned' && <div className="small">{i.return_note}</div>}</> },
                  { key: 'confirmed', header: 'Confirmed by Futran', value: (i) => i.confirmed_at ?? '', render: (i) => i.confirmed_at ? <span className="small">{i.confirmed_by}, {fmtDate(i.confirmed_at)}</span> : '—' },
                ]}
                rowActions={(i) => [
                  ...(i.update_to ? [{ label: `Move to version ${i.update_to.version_no}`, disabled: !d.can.edit, onSelect: () => act(() => api.put(`/trust/items/${i.id}`, { source_id: i.update_to!.policy_id }), `'${i.title}' now uses version ${i.update_to!.version_no}. Approve it to send it to Futran.`) }] : []),
                  { label: 'Edit', disabled: !d.can.edit, onSelect: () => (i.kind === 'heading' ? setSettings(true) : setEditing(i)) },
                  { label: 'Approve and send to Futran', disabled: !d.can.edit || !['draft', 'returned'].includes(i.status) || Boolean(i.problem), onSelect: () => act(() => api.post(`/trust/items/${i.id}/approve`), `'${i.title}' sent to Futran to confirm against the signed report.`) },
                  { label: 'Withdraw from public page', disabled: !d.can.edit || !i.live, onSelect: () => act(() => api.post(`/trust/items/${i.id}/withdraw`), `'${i.title}' is no longer public.`) },
                  { label: 'Remove', danger: true, disabled: !d.can.edit || i.live || i.kind === 'heading', onSelect: () => act(() => api.delete(`/trust/items/${i.id}`), `'${i.title}' removed.`) },
                ]} />
              {d.can.edit && d.items.some((i) => ['draft', 'returned'].includes(i.status) && !i.problem) && (
                <div className="row" style={{ marginTop: 12 }}><Button variant="primary" disabled={busy} onClick={() => act(async () => { for (const i of d.items.filter((x) => ['draft', 'returned'].includes(x.status) && !x.problem)) await api.post(`/trust/items/${i.id}/approve`); }, 'All drafts approved and sent to Futran.')}>Approve all drafts</Button></div>
              )}
            </div>
          </section>
          <aside className="card wsi-side" aria-labelledby="tc-views-h">
            <div className="card-header"><h2 id="tc-views-h">Views, last 30 days</h2><span className="small muted">{total}</span></div>
            <div className="card-body stack-sm">
              <div className="wsi-spark" role="img" aria-label={`${total} views in the last 30 days`}>{d.views.map((v) => <span key={v.day} title={`${fmtDate(v.day)}: ${v.views}`} style={{ height: `${(100 * v.views) / max}%` }} />)}</div>
              <p className="small muted" style={{ margin: 0 }}>Page views by day. No information about visitors is kept, except the name, email and company of people who accept the NDA.</p>
            </div>
          </aside>
        </div>
      ) : <Alert tone="info">{d.can.edit ? 'Set up the page to choose its address and start adding items.' : 'The Trust Center has not been set up yet.'}</Alert>}
      {settings && <PageDialog d={d} onClose={() => setSettings(false)} onDone={async () => { setSettings(false); setMsg({ tone: 'success', text: 'Page settings saved. A changed heading or introduction goes public after you approve it and Futran confirms it.' }); await refresh(); }} />}
      {editing && <ItemDialog d={d} item={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onDone={async (t) => { setEditing(null); setMsg({ tone: 'success', text: t }); await refresh(); }} />}
    </div>
  );
}

function PageDialog({ d, onClose, onDone }: { d: TrustEditorData; onClose: () => void; onDone: () => void }) {
  const p = d.page;
  const { data: me } = useMe();
  const [v, setV] = useState({ slug: p?.slug ?? '', title: p?.title ?? (me ? `How ${me.organization.name} governs its use of AI` : ''), intro: p?.intro ?? '', contact_email: p?.contact_email ?? '', access: p?.access ?? 'public', nda_text: p?.nda_text ?? '', indexable: p?.indexable ?? false, live: p?.live ?? false });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Page settings" onClose={onClose} wide>
      <div className="stack">
        {err && !Object.keys(fe).length && <Alert tone="danger">{err}</Alert>}
        <TextField label="Address" help={H.slug} hint={`/trust/${v.slug || 'your-company'}`} value={v.slug} onChange={(e) => setV({ ...v, slug: e.target.value.toLowerCase() })} error={fe.slug} />
        <TextField label="Heading" help={H.heading} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} error={fe.title} />
        <TextArea label="Introduction" help={H.intro} rows={3} value={v.intro} onChange={(e) => setV({ ...v, intro: e.target.value })} />
        <TextField label="Contact email for AI questions" help={H.contact} type="email" value={v.contact_email} onChange={(e) => setV({ ...v, contact_email: e.target.value })} error={fe.contact_email} />
        <SelectField label="Access" help={H.access} value={v.access} onChange={(e) => setV({ ...v, access: e.target.value as 'public' | 'nda' })} options={[{ value: 'public', label: 'Public' }, { value: 'nda', label: 'NDA click-through before detailed documents' }]} />
        {v.access === 'nda' && <TextArea label="NDA text" help={H.nda} rows={4} value={v.nda_text} onChange={(e) => setV({ ...v, nda_text: e.target.value })} error={fe.nda_text} />}
        <Checkbox label="Let search engines list the page" help={H.indexable} checked={v.indexable} onChange={(e) => setV({ ...v, indexable: e.target.checked })} />
        <Checkbox label="The page is live" help={H.live} checked={v.live} onChange={(e) => setV({ ...v, live: e.target.checked })} />
        <div className="row"><Button variant="primary" disabled={busy} onClick={async () => { setBusy(true); setErr(null); setFe({}); try { await api.put('/trust/page', v); onDone(); } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); } }}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

function ItemDialog({ d, item, onClose, onDone }: { d: TrustEditorData; item: TrustItem | null; onClose: () => void; onDone: (t: string) => void }) {
  const [kind, setKind] = useState<string>(item?.kind ?? 'commitment');
  const [v, setV] = useState({ title: item?.title ?? '', body: item?.body ?? '', link_label: item?.link_label ?? '', link_url: item?.link_url ?? '', source_id: item?.source_id ?? '', show_rating: Boolean(item?.options.show_rating) });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const text = ['commitment', 'governance', 'rights_contact'].includes(kind);
  const sourceOpts = kind === 'policy' ? d.sources.policies.map((p) => ({ value: p.id, label: `${p.title} (version ${p.version_no})` }))
    : kind === 'bias_summary' ? d.sources.bias_summaries.map((s) => ({ value: s.id, label: `${s.tool_name ?? 'Bias audit'}${s.audit_date ? `, audited ${fmtDate(s.audit_date)}` : ''}` }))
      : kind === 'badge' ? d.sources.engagements.map((e) => ({ value: e.id, label: `${e.name} · ${e.report_ref}` })) : [];
  useEffect(() => { if (!item && !text && sourceOpts.length === 1) setV((x) => ({ ...x, source_id: sourceOpts[0].value })); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps
  async function save() {
    setBusy(true); setErr(null); setFe({});
    const body = { kind, ...v, source_id: text ? null : v.source_id };
    try { if (item) await api.put(`/trust/items/${item.id}`, body); else await api.post('/trust/items', body); onDone(item ? 'Item saved as a draft. Approve it to send it to Futran.' : 'Item added as a draft.'); }
    catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); setBusy(false); }
  }
  return (
    <Dialog title={item ? `Edit ${item.title}` : 'Add item'} onClose={onClose} wide>
      <div className="stack">
        {err && !Object.keys(fe).length && <Alert tone="danger">{err}</Alert>}
        {item?.live && <Alert tone="info">The confirmed version stays on the public page until Futran confirms your change.</Alert>}
        <SelectField label="What the item shows" help={H.kind} value={kind} disabled={Boolean(item)} onChange={(e) => { setKind(e.target.value); setV({ ...v, source_id: '' }); }} options={d.kinds} />
        {!text && (sourceOpts.length ? <SelectField label="Built from" value={v.source_id} placeholder="Choose" onChange={(e) => setV({ ...v, source_id: e.target.value })} options={sourceOpts} error={fe.source_id} disabled={Boolean(item)} />
          : <Alert tone="warn">{kind === 'policy' ? 'No published policies yet. Publish one in Policies first.' : 'Nothing to build this from yet: it needs a signed Futran report.'}</Alert>)}
        {text && <TextField label="Heading" help={H.itemTitle} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} error={fe.title} />}
        <TextArea label={text ? 'Text' : 'Your note (optional)'} help={H.itemBody} rows={4} value={v.body} onChange={(e) => setV({ ...v, body: e.target.value })} error={fe.body} />
        {text && <div className="grid-2"><TextField label="Link text" value={v.link_label} onChange={(e) => setV({ ...v, link_label: e.target.value })} /><TextField label="Link address" help={H.linkUrl} value={v.link_url} onChange={(e) => setV({ ...v, link_url: e.target.value })} error={fe.link_url} /></div>}
        {kind === 'badge' && <Checkbox label="Show the overall rating on the badge" help={H.showRating} checked={v.show_rating} onChange={(e) => setV({ ...v, show_rating: e.target.checked })} />}
        <div className="row"><Button variant="primary" disabled={busy || (!text && !v.source_id)} onClick={save}>Save draft</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

type Confirmation = TrustItem & { client_name: string; report: { ref: string; signed_on: string; period_start: string | null; period_end: string | null; overall_rating: string } | null; approved_content: Record<string, unknown> | null };

/** Futran Chief Auditor `/trust-confirmations`: check each approved Trust Center item against the client's signed report. */
export function TrustConfirmations() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['trust-confirmations'], queryFn: () => api.get<{ items: Confirmation[] }>('/trust/confirmations') });
  const [open, setOpen] = useState<{ item: Confirmation; mode: 'confirm' | 'return' } | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  async function decide() {
    if (!open) return;
    setBusy(true); setMsg(null);
    try { await api.post(`/trust/items/${open.item.id}/${open.mode}`, { note }); setMsg({ tone: 'success', text: open.mode === 'confirm' ? `Confirmed and published '${open.item.title}'.` : `Returned '${open.item.title}' to ${open.item.client_name}.` }); setOpen(null); setNote(''); await qc.invalidateQueries({ queryKey: ['trust-confirmations'] }); }
    catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  }
  return (
    <div className="page">
      <PageHeader title="Trust Center confirmations" subtitle="Clients' Trust Center items waiting for a Chief Auditor to confirm they match the signed report. Nothing is public until you confirm it." />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <section className="card"><div className="card-body">
        <DataGrid label="Items to confirm" rows={q.data.items} rowId={(i) => i.id} rowLabel={(i) => `${i.client_name}: ${i.title}`} emptyText="Nothing is waiting for confirmation."
          columns={[
            { key: 'client', header: 'Client', value: (i) => i.client_name },
            { key: 'item', header: 'Item', value: (i) => i.title, render: (i) => <><strong>{i.title}</strong><div className="small muted">{i.kind_label} · approved by {i.client_approved_by}, {fmtDateTime(i.client_approved_at)}</div></> },
            { key: 'report', header: 'Signed report', value: (i) => i.report?.ref ?? '', render: (i) => i.report ? <span className="small">{i.report.ref}, signed {fmtDate(i.report.signed_on)}</span> : <Badge tone="danger">No signed report</Badge> },
          ]}
          rowActions={(i) => [
            { label: 'Review and confirm', disabled: !i.report, onSelect: () => setOpen({ item: i, mode: 'confirm' }) },
            { label: 'Return to client', onSelect: () => setOpen({ item: i, mode: 'return' }) },
          ]} />
      </div></section>
      {open && (
        <Dialog title={open.mode === 'confirm' ? 'Confirm against the signed report' : 'Return to the client'} onClose={() => setOpen(null)} large>
          <div className="stack">
            <div className="grid-2">
              <div className="stack-sm"><h3 style={{ margin: 0, fontSize: 15 }}>What the client will publish</h3><ContentView kind={open.item.kind} c={open.item.approved_content ?? {}} /></div>
              <div className="stack-sm"><h3 style={{ margin: 0, fontSize: 15 }}>Signed report</h3>{open.item.report ? <ul className="small" style={{ margin: 0, paddingLeft: 18 }}><li>{open.item.report.ref}, signed {fmtDate(open.item.report.signed_on)}</li><li>Period {fmtDate(open.item.report.period_start)} to {fmtDate(open.item.report.period_end)}</li><li>Overall rating {open.item.report.overall_rating}</li></ul> : <Alert tone="danger">No signed report: this item cannot be confirmed.</Alert>}</div>
            </div>
            <TextArea label={open.mode === 'confirm' ? 'Where the report supports it' : 'What does not match'} help={open.mode === 'confirm' ? H.confirmNote : H.returnNote} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row"><Button variant="primary" disabled={busy || (open.mode === 'return' && !note.trim())} onClick={decide}>{open.mode === 'confirm' ? 'Confirm and publish' : 'Return'}</Button><Button onClick={() => setOpen(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function ContentView({ kind, c }: { kind: string; c: Record<string, any> }) {
  if (kind === 'badge') return <div className="tc-badge"><strong>Audited by Futran Solutions</strong><span className="small">{c.engagement} · audit period {fmtDate(c.period_start)} – {fmtDate(c.period_end)}</span><span className="small">Report signed {fmtDate(c.signed_on)} · ref {c.report_ref}</span>{c.rating && <span className="small">Overall rating {c.rating}</span>}</div>;
  if (kind === 'bias_summary') return (
    <div className="stack-sm">
      <span className="small">{c.tool_name} · audit {fmtDate(c.audit_date)} · by {c.auditor}{c.distribution_date ? ` · in use since ${fmtDate(c.distribution_date)}` : ''}</span>
      {c.data_source && <span className="small muted">Data: {c.data_source}</span>}
      <div className="table-wrap"><table className="tc-ratios"><thead><tr><th>Category</th><th>Group</th><th>Selection rate</th><th>Impact ratio</th></tr></thead>
        <tbody>{(c.impact_ratios ?? []).map((r: any, i: number) => <tr key={i}><td>{r.category}</td><td>{r.group}</td><td>{r.selection_rate ?? '—'}</td><td>{r.excluded ? 'Excluded' : r.impact_ratio ?? 'Not calculable'}</td></tr>)}</tbody></table></div>
      {c.unknown_category_count !== null && c.unknown_category_count !== undefined && <span className="small muted">{c.unknown_category_count} records with an unknown category were not included.</span>}
    </div>
  );
  if (kind === 'policy') return <span className="small">{c.title}, version {c.version_no}, approved {fmtDate(c.approved_on)}{c.body ? `. ${c.body}` : ''}</span>;
  return <><strong>{c.title}</strong><p className="small" style={{ margin: 0, whiteSpace: 'pre-line' }}>{c.body}</p></>;
}

/** The public Trust Center `/trust/:slug` (no sign-in). Only items the client approved and Futran confirmed appear. */
export function TrustPublic() {
  const { slug = '' } = useParams();
  const q = useQuery({ queryKey: ['trust-public', slug], queryFn: () => api.get<PublicTrust>(`/public/trust/${slug}`), retry: false, refetchOnWindowFocus: false });
  const [access, setAccess] = useState<string | null>(null);
  const [nda, setNda] = useState<PublicItem | null>(null);
  useEffect(() => {
    // index.html carries noindex for the whole app; the public page lifts it only when the client opted in
    let meta = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
    const before = meta?.content ?? null;
    if (!meta) { meta = document.createElement('meta'); meta.name = 'robots'; document.head.appendChild(meta); }
    meta.content = q.data && !q.data.noindex ? 'index, follow' : 'noindex';
    if (q.data) document.title = `${q.data.organization} AI Trust Center`;
    return () => { if (meta) { if (before === null) meta.remove(); else meta.content = before; } };
  }, [q.data]);
  if (q.isLoading) return <div className="tc-public"><main><Loading /></main></div>;
  if (!q.data) return <div className="tc-public"><main><h1>Trust Center</h1><Alert tone="info">{errorMessage(q.error)}</Alert></main></div>;
  const d = q.data;
  const badge = d.items.find((i) => i.kind === 'badge');
  const docUrl = (i: PublicItem) => `/api/v1/public/trust/${d.slug}/items/${i.id}/document${access ? `?access=${encodeURIComponent(access)}` : ''}`;
  return (
    <div className="tc-public">
      <header>
        <div style={{ fontWeight: 700, fontSize: 20 }}>{d.organization} <span style={{ fontWeight: 500, color: 'var(--muted)', fontSize: 16 }}>AI Trust Center</span></div>
        {d.contact_email && <a href={`mailto:${d.contact_email}`} style={{ fontWeight: 600 }}>Contact us about AI</a>}
      </header>
      <main>
        <div className="tc-hero">
          <div style={{ maxWidth: 620 }}><h1>{d.title}</h1>{d.intro && <p style={{ margin: '12px 0 0', fontSize: 16, lineHeight: 1.6 }}>{d.intro}</p>}</div>
          {badge && (
            <div className="tc-badge" aria-label="Audited by Futran Solutions">
              <strong>Audited by Futran Solutions</strong>
              <span className="small">{badge.content.engagement} · audit period {fmtDate(badge.content.period_start)} – {fmtDate(badge.content.period_end)}</span>
              <span className="small">Report signed {fmtDate(badge.content.signed_on)} · ref {badge.content.report_ref}</span>
              {badge.content.rating && <span className="small">Overall rating {badge.content.rating}</span>}
            </div>
          )}
        </div>
        <div className="tc-grid">
          {d.items.filter((i) => i.kind !== 'badge').map((i) => (
            <section key={i.id} className="tc-card" aria-labelledby={`tc-${i.id}`}>
              <h2 id={`tc-${i.id}`}>{i.title}</h2>
              {i.kind === 'bias_summary' ? <ContentView kind={i.kind} c={i.content} /> : i.body && <p style={{ margin: 0, lineHeight: 1.55, whiteSpace: 'pre-line' }}>{i.body}</p>}
              {i.kind === 'policy' && <span className="small muted">Version {i.content.version_no}, approved {fmtDate(i.content.approved_on)}</span>}
              {i.kind === 'policy' && i.content.document && (i.gated && !access ? <Button size="sm" onClick={() => setNda(i)}>Read the policy (NDA)</Button> : <a href={docUrl(i)} style={{ fontWeight: 600 }}>Read the policy (PDF)</a>)}
              {i.content.link_url && <a href={i.content.link_url} style={{ fontWeight: 600 }}>{i.content.link_label || 'Find out more'}</a>}
            </section>
          ))}
        </div>
        {d.items.length === 0 && <p className="muted">Nothing has been published yet.</p>}
        {(d.header_confirmed || d.items.length > 0) && <p className="small muted" style={{ margin: 0 }}>{d.header_confirmed ? 'The heading, introduction and each item on this page were' : 'Each item on this page was'} approved by {d.organization} and confirmed by Futran Solutions against its signed audit report{d.updated_at ? `. Page updated ${fmtDate(d.updated_at)}` : ''}.</p>}
      </main>
      {nda && <NdaDialog d={d} onClose={() => setNda(null)} onAccepted={(t) => { setAccess(t); setNda(null); }} />}
    </div>
  );
}

function NdaDialog({ d, onClose, onAccepted }: { d: PublicTrust; onClose: () => void; onAccepted: (token: string) => void }) {
  const [v, setV] = useState({ name: '', email: '', company: '', accept: false });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Before you open detailed documents" onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0, whiteSpace: 'pre-line' }}>{d.nda_text}</p>
        <TextField label="Your name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} error={fe.name} autoComplete="name" />
        <TextField label="Work email" type="email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} error={fe.email} autoComplete="email" />
        <TextField label="Company" value={v.company} onChange={(e) => setV({ ...v, company: e.target.value })} autoComplete="organization" />
        <Checkbox label="I accept these terms" checked={v.accept} onChange={(e) => setV({ ...v, accept: e.target.checked })} />
        {fe.accept && <div className="error">{fe.accept}</div>}
        <div className="row"><Button variant="primary" disabled={busy || !v.accept} onClick={async () => { setBusy(true); setFe({}); try { const r = await api.post<{ access_token: string }>(`/public/trust/${d.slug}/nda`, v); onAccepted(r.access_token); } catch (e) { setFe(fieldErrors(e)); setBusy(false); } }}>Continue</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
