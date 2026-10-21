import { useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, FieldHelp, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate } from '@/components/ui';
import { governanceExtraHelp, governanceHelp as H } from '@/help/client';

export type GovItem = {
  id: string; code: string; kind: 'document' | 'security_document' | 'role'; title: string; description: string | null; control_refs: string[];
  committee: boolean; optional: boolean; status: 'unanswered' | 'in_place' | 'planned' | 'not_applicable'; files: { id: string; filename: string }[];
  names: { name: string; title: string | null }[]; chair: string | null; member_count: number | null; meeting_frequency: string | null;
  target_date: string | null; interim_owner: string | null; planned_members: string | null; na_reason: string | null;
};
export type Gov = {
  request: { id: string; status: string; due_date: string | null; requested_by: string | null; submitted_at: string | null; extra_fields: Record<string, string> };
  items: GovItem[];
  counts: { roles: { answered: number; total: number }; documents: { answered: number; total: number } };
  coverage: { oecd: Record<string, string>; nist: Record<string, string> };
  commitments: { id: string; description: string; target_date: string; owner: string; status: string }[];
  catalog: { code: string; kind: string; title: string; optional: boolean; selected: boolean; available: boolean }[];
  extra_field_defs: { key: string; label: string; type: 'text' | 'date' | 'choice'; options?: string[] }[];
};

const OECD_LABELS: Record<string, string> = { '1.2': 'Fairness', '1.3': 'Transparency', '1.4': 'Robustness, safety', '1.5': 'Accountability' };
const COVER_TONE: Record<string, 'success' | 'navy' | 'warn' | 'danger'> = { covered: 'success', planned: 'navy', partial: 'warn', gap: 'danger' };
const SECTIONS: { kind: GovItem['kind']; title: string; intro: string }[] = [
  { kind: 'document', title: '1 · Governance documents', intro: 'Upload what exists. For anything missing, commit to a date.' },
  { kind: 'security_document', title: '2 · Data security and data governance policies', intro: 'In scope for how they cover AI: data entered into AI tools, AI vendors and AI incidents. Futran does not audit the full security program; SOC 2 or ISO 27001 reports can be uploaded as supporting evidence.' },
  { kind: 'role', title: '3 · Governance bodies and named owners', intro: 'Each row shows the framework references it supports: OECD AI Principles, NIST AI RMF and the EU AI Act.' },
];

export function useGovernance(clientId: string) {
  return useQuery({ queryKey: ['governance', clientId], queryFn: () => api.get<Gov>(`/clients/${clientId}/governance`), enabled: !!clientId, retry: false });
}

function refLabel(r: string) {
  return r.replace('NIST_AI_RMF', 'NIST').replace('EU_AI_ACT', 'EU AI Act').replace(/^OECD (\d\.\d)$/, (_, k) => `OECD ${k}${OECD_LABELS[k] ? ` ${OECD_LABELS[k]}` : ''}`);
}

export function Governance() {
  const { data: me } = useMe();
  const cid = me?.organization.id ?? '';
  const canAnswer = !!me?.roles.some((r) => r.role === 'caico');
  return <GovernanceView clientId={cid} canAnswer={canAnswer} />;
}

export function GovernanceView({ clientId, canAnswer, header, crumbs }: { clientId: string; canAnswer: boolean; header?: ReactNode; crumbs?: { to?: string; label: string }[] }) {
  const q = useGovernance(clientId);
  const qc = useQueryClient();
  const [accurate, setAccurate] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="info">{errorMessage(q.error)}</Alert></div>;
  const g = q.data;
  const open = g.request.status === 'open';
  const editable = canAnswer && open;
  const remaining = g.items.filter((i) => i.status === 'unanswered');
  const refresh = () => qc.invalidateQueries({ queryKey: ['governance', clientId] });

  async function submit() {
    setMsg(null);
    try {
      await api.post(`/clients/${clientId}/governance/submit`, { accuracy_confirmed: accurate });
      await qc.invalidateQueries();
      setMsg({ tone: 'success', text: 'Submitted to the Chief Auditor. Your commitments are tracked from here.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }

  return (
    <div className="page">
      <PageHeader crumbs={crumbs ?? [{ to: '/start', label: 'Getting started' }, { label: 'AI governance structure' }]} title="AI governance structure"
        subtitle={<>Requested by {g.request.requested_by ?? 'your Chief Auditor'}, Chief Auditor{g.request.due_date ? ` · due ${fmtDate(g.request.due_date)}` : ''}. Tell us which governance bodies and named owners exist today. If something is not in place yet, choose <strong>Will constitute</strong> and give a target date and an interim owner.</>} />
      {header}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!open && <Alert tone="success">Submitted {fmtDate(g.request.submitted_at)}. The answers are locked; contact your Futran Chief Auditor if one must change.</Alert>}
      <p className="small"><strong>{g.counts.roles.answered} of {g.counts.roles.total}</strong> roles answered · <strong>{g.counts.documents.answered} of {g.counts.documents.total}</strong> documents</p>
      <div className="split">
        <div className="main stack">
          {SECTIONS.map((s) => {
            const its = g.items.filter((i) => i.kind === s.kind);
            if (!its.length) return null;
            return (
              <Card key={s.kind} title={s.title}>
                <p className="small muted" style={{ marginTop: 0 }}>{s.intro}</p>
                <div className="stack" style={{ gap: 0 }}>
                  {its.map((it) => <ItemRow key={it.id} it={it} editable={editable} onSaved={refresh} />)}
                </div>
              </Card>
            );
          })}
          <ExtraFacts g={g} clientId={clientId} editable={editable} onSaved={refresh} />
        </div>
        <div className="side stack">
          <Card title="Framework coverage">
            <p className="small muted" style={{ marginTop: 0 }}>Calculated from your answers.</p>
            <h3 style={{ fontSize: 14, margin: '8px 0 4px' }}>OECD AI Principles</h3>
            {Object.entries(g.coverage.oecd).map(([k, v]) => <div key={k} className="row small" style={{ justifyContent: 'space-between', padding: '3px 0' }}><span>{k} {OECD_LABELS[k]}</span><Badge tone={COVER_TONE[v]}>{v[0].toUpperCase() + v.slice(1)}</Badge></div>)}
            <h3 style={{ fontSize: 14, margin: '12px 0 4px' }}>NIST AI RMF</h3>
            {Object.entries(g.coverage.nist).map(([k, v]) => <div key={k} className="row small" style={{ justifyContent: 'space-between', padding: '3px 0' }}><span>{k}</span><Badge tone={COVER_TONE[v]}>{v[0].toUpperCase() + v.slice(1)}</Badge></div>)}
          </Card>
          <Card title={`${g.commitments.length} ${g.commitments.length === 1 ? 'commitment' : 'commitments'}`}>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {g.commitments.map((c) => <li key={c.id}>{c.description} <span className="muted">· {c.owner} · by {fmtDate(c.target_date)}</span></li>)}
            </ul>
            <p className="small muted">Each "Will constitute" or "Will create" answer becomes a tracked commitment with its target date. Futran reports on it and follows it in remediation.</p>
          </Card>
          {editable && (
            <Card>
              <div className="stack">
                <Checkbox label="I confirm these answers are accurate as of today" help={H.accurate} checked={accurate} onChange={(e) => setAccurate(e.target.checked)} />
                <Button variant="primary" onClick={submit} disabled={!!remaining.length || !accurate}>Submit to Chief Auditor</Button>
                {remaining.length > 0 && <p className="small muted" style={{ margin: 0 }}>{remaining.length} {remaining.length === 1 ? 'item still needs' : 'items still need'} an answer.</p>}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function ItemRow({ it, editable, onSaved }: { it: GovItem; editable: boolean; onSaved: () => void }) {
  const isRole = it.kind === 'role';
  const [mode, setMode] = useState<GovItem['status']>(it.status);
  const [expanded, setExpanded] = useState(false);
  const choose = (m: GovItem['status']) => { setMode(m); setExpanded(true); };
  const [f, setF] = useState({ names: it.names.length ? it.names : [{ name: '', title: '' }], chair: it.chair ?? '', member_count: it.member_count?.toString() ?? '', meeting_frequency: it.meeting_frequency ?? '', target_date: it.target_date ?? '', interim_owner: it.interim_owner ?? '', planned_members: it.planned_members ?? '', na_reason: it.na_reason ?? '' });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const plannedLabel = isRole ? 'Will constitute' : 'Will create';

  async function save() {
    setErr(null); setFe({});
    try {
      await api.put(`/governance/items/${it.id}`, { status: mode, ...f, names: f.names.filter((n) => n.name.trim()) });
      setExpanded(false);
      onSaved();
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  async function uploadFile(fl?: File) {
    if (!fl) return;
    setErr(null);
    const form = new FormData();
    form.append('file', fl);
    try { await api.upload(`/governance/items/${it.id}/files`, form); onSaved(); } catch (e) { setErr(errorMessage(e)); }
  }
  const summary = it.status === 'in_place' ? (isRole ? `In place · ${[it.chair && `chair ${it.chair}`, ...it.names.map((n) => n.name)].filter(Boolean).join(', ')}` : `Uploaded · ${it.files.length} ${it.files.length === 1 ? 'file' : 'files'}`)
    : it.status === 'planned' ? `${plannedLabel} · target ${fmtDate(it.target_date)} · interim owner ${it.interim_owner}`
    : it.status === 'not_applicable' ? `Not applicable · ${it.na_reason}` : 'Not answered yet';

  return (
    <div style={{ padding: '14px 0', borderTop: '1px solid var(--line-soft)' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>{it.title}</strong>{it.optional && <span className="small muted"> · optional</span>}
          {it.description && <div className="small muted">{it.description}</div>}
          {isRole && <div className="row" style={{ gap: 4, marginTop: 4 }}>{it.control_refs.map((r) => <Badge key={r} tone="muted">{refLabel(r)}</Badge>)}</div>}
          <div className="small" style={{ marginTop: 6 }}>{summary}</div>
          {it.files.length > 0 && <div className="small">{it.files.map((x) => <a key={x.id} href={fileUrl(x.id)} style={{ marginRight: 10 }}>{x.filename}</a>)}</div>}
        </div>
        {editable && (
          <div className="row" style={{ gap: 4, flexWrap: 'nowrap', alignItems: 'center' }}>
          <FieldHelp label={`answer for ${it.title}`}>{isRole ? H.answerRole : H.answerDocument}</FieldHelp>
          <div className="pills" role="group" aria-label={`Answer for ${it.title}`}>
            {isRole ? <button type="button" className="pill" aria-pressed={mode === 'in_place'} onClick={() => choose('in_place')}>In place</button>
              : <button type="button" className="pill" onClick={() => file.current?.click()}>Upload</button>}
            <button type="button" className="pill" aria-pressed={mode === 'planned'} onClick={() => choose('planned')}>{plannedLabel}</button>
            <button type="button" className="pill" aria-pressed={mode === 'not_applicable'} onClick={() => choose('not_applicable')}>N/A</button>
          </div>
          </div>
        )}
      </div>
      <input ref={file} type="file" hidden aria-label={`Upload ${it.title}`} onChange={(e) => { void uploadFile(e.target.files?.[0]); e.target.value = ''; }} />
      {editable && expanded && mode !== 'unanswered' && !(mode === 'in_place' && !isRole) && (
        <div className="stack" style={{ marginTop: 10, paddingLeft: 12, borderLeft: '3px solid var(--line)' }}>
          {err && <Alert tone="danger">{err}</Alert>}
          {mode === 'in_place' && isRole && (
            <>
              {it.committee && <div className="grid-2"><TextField label="Chair" help={H.chair} value={f.chair} onChange={(e) => setF({ ...f, chair: e.target.value })} /><TextField label="Number of members" help={H.memberCount} inputMode="numeric" value={f.member_count} onChange={(e) => setF({ ...f, member_count: e.target.value })} /><SelectField label="Meets" help={H.meets} value={f.meeting_frequency} onChange={(e) => setF({ ...f, meeting_frequency: e.target.value })} placeholder="Choose…" options={['Monthly', 'Quarterly', 'Twice a year', 'Annually', 'As needed'].map((x) => ({ value: x, label: x }))} /></div>}
              {f.names.map((n, i) => (
                <div className="grid-2" key={i}>
                  <TextField label={it.committee ? `Member ${i + 1}` : 'Name'} help={i === 0 ? (it.committee ? H.member : H.name) : undefined} value={n.name} onChange={(e) => setF({ ...f, names: f.names.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} error={i === 0 ? fe.names : undefined} />
                  <TextField label="Title" help={i === 0 ? H.title : undefined} value={n.title ?? ''} onChange={(e) => setF({ ...f, names: f.names.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
                </div>
              ))}
              <div><Button size="sm" variant="ghost" onClick={() => setF({ ...f, names: [...f.names, { name: '', title: '' }] })}>Add another person</Button>
                {it.committee && <> · <button type="button" className="link-btn small" onClick={() => file.current?.click()}>Upload terms of reference</button></>}</div>
            </>
          )}
          {mode === 'planned' && (
            <div className="grid-2">
              <TextField type="date" label="Target date *" help={H.targetDate} value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} error={fe.target_date} />
              <TextField label="Interim owner *" help={H.interimOwner} value={f.interim_owner} onChange={(e) => setF({ ...f, interim_owner: e.target.value })} error={fe.interim_owner} />
              {isRole && it.committee && <TextField label="Planned members" help={H.plannedMembers} value={f.planned_members} onChange={(e) => setF({ ...f, planned_members: e.target.value })} />}
            </div>
          )}
          {mode === 'not_applicable' && <TextArea label="Reason *" help={H.naReason} value={f.na_reason} onChange={(e) => setF({ ...f, na_reason: e.target.value })} error={fe.na_reason} />}
          <div><Button size="sm" variant="primary" onClick={save}>Save answer</Button></div>
        </div>
      )}
    </div>
  );
}

function ExtraFacts({ g, clientId, editable, onSaved }: { g: Gov; clientId: string; editable: boolean; onSaved: () => void }) {
  const [v, setV] = useState<Record<string, string>>(g.request.extra_fields);
  const [saved, setSaved] = useState(false);
  async function save() {
    await api.put(`/clients/${clientId}/governance/extra`, { fields: v });
    setSaved(true);
    onSaved();
  }
  return (
    <Card title="4 · Policy and accountability details">
      <div className="grid-2">
        {g.extra_field_defs.map((d) => d.type === 'choice'
          ? <SelectField key={d.key} label={d.label} help={governanceExtraHelp[d.key]} value={v[d.key] ?? ''} disabled={!editable} onChange={(e) => { setV({ ...v, [d.key]: e.target.value }); setSaved(false); }} placeholder="Choose…" options={(d.options ?? []).map((o) => ({ value: o, label: o[0].toUpperCase() + o.slice(1) }))} />
          : <TextField key={d.key} type={d.type === 'date' ? 'date' : 'text'} label={d.label} help={governanceExtraHelp[d.key]} value={v[d.key] ?? ''} disabled={!editable} onChange={(e) => { setV({ ...v, [d.key]: e.target.value }); setSaved(false); }} />)}
      </div>
      {editable && <div className="row" style={{ marginTop: 12 }}><Button size="sm" onClick={save}>Save details</Button>{saved && <span className="small muted">Saved</span>}</div>}
    </Card>
  );
}
