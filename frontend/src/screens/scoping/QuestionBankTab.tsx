import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Checkbox, Dialog, Loading, SelectField, TextArea, TextField } from '@/components/ui';
import type { Question } from '@/api/scoping';
import '@/styles/scoping.css';

type Bank = { version: number; label: string; note: string | null; can_edit: boolean; sections: { key: string; label: string }[]; types: string[]; questions: Question[] };
const TYPE_LABELS: Record<string, string> = { count: 'Number', total: 'Total of counts', single: 'One choice', multi: 'Tick boxes', yes_no: 'Yes or no', text: 'Text' };

function optsText(q?: Question): string {
  return (q?.options ?? []).map((o) => `${o.value} | ${o.label}`).join('\n');
}
function parseOpts(t: string) {
  return t.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const [v, ...rest] = l.split('|'); return { value: v.trim(), label: (rest.join('|') || v).trim() }; });
}

function Editor({ q, bank, onClose, onSaved }: { q: Question | null; bank: Bank; onClose: () => void; onSaved: (msg: string) => void }) {
  const [f, setF] = useState({ code: q?.code ?? '', label: q?.label ?? '', client_label: q?.client_label ?? '', help: q?.help ?? '', type: q?.type ?? 'count', options: optsText(q ?? undefined),
    internal_only: q?.internal_only ?? false, client_visible: q?.client_visible ?? true, unknown_assumption: q?.unknown_assumption ?? '', active: q?.active ?? true });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null); setFe({});
    const body = { ...f, options: ['single', 'multi', 'yes_no'].includes(f.type) ? parseOpts(f.options) : [], client_label: f.client_label || null, help: f.help || null, unknown_assumption: f.unknown_assumption || null };
    try {
      const r = q ? await api.put<{ version: number }>(`/scoping/bank/questions/${q.code}`, body) : await api.post<{ version: number }>('/scoping/bank/questions', body);
      onSaved(`${q ? q.code : f.code} saved in bank version ${r.version}.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); }
  }
  return (
    <Dialog title={q ? `Edit ${q.code}` : 'Add a question'} onClose={onClose} large>
      <div className="stack">
        {err && <Alert tone="danger">{err}</Alert>}
        {q && bank.version && <p className="small muted">If a questionnaire already uses this bank version, saving makes a new version; answered questionnaires keep their wording.</p>}
        {!q && <TextField label="Code" hint="The section letter, a dot and two digits, e.g. SQ-C.13" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} error={fe.code} />}
        <TextField label="Question (as the rep sees it)" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} error={fe.label} />
        <TextField label="Plain wording for the client link (optional)" value={f.client_label} onChange={(e) => setF({ ...f, client_label: e.target.value })} />
        <TextField label="Help (optional)" value={f.help} onChange={(e) => setF({ ...f, help: e.target.value })} />
        <SelectField label="Answer type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as Question['type'] })} options={bank.types.map((t) => ({ value: t, label: TYPE_LABELS[t] ?? t }))} error={fe.type} />
        {['single', 'multi', 'yes_no'].includes(f.type) && <TextArea label="Options" hint="One per line: value | label" rows={5} value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} error={fe.options} />}
        <TextField label="Proposal assumption when the answer is unknown (optional)" value={f.unknown_assumption} onChange={(e) => setF({ ...f, unknown_assumption: e.target.value })} />
        <Checkbox label="Internal only — never on the client link" checked={f.internal_only} onChange={(e) => setF({ ...f, internal_only: e.target.checked, client_visible: e.target.checked ? false : f.client_visible })} />
        <Checkbox label="Offer on the send dialog" disabled={f.internal_only} checked={f.client_visible && !f.internal_only} onChange={(e) => setF({ ...f, client_visible: e.target.checked })} />
        <Checkbox label="In use" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
        <div className="row" style={{ gap: 8 }}><Button variant="primary" onClick={save}>Save</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}

/** SM-14 Question bank tab content. The Futran Admin maintains it; the Sales Manager owns it. */
export function QuestionBankTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['scoping-bank'], queryFn: () => api.get<Bank>('/scoping/bank') });
  const [edit, setEdit] = useState<Question | null | 'new'>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [section, setSection] = useState('');
  if (q.isLoading) return <Loading />;
  const b = q.data;
  if (!b) return <Alert tone="danger">{errorMessage(q.error)}</Alert>;
  const rows = b.questions.filter((x) => !section || x.section === section);
  const label = (k: string) => b.sections.find((s) => s.key === k)?.label ?? k;
  return (
    <div className="stack">
      {b.note && <Alert tone="warn">{b.note}</Alert>}
      {msg && <Alert tone="success">{msg}</Alert>}
      <div className="row sc-toolbar">
        <span className="small muted">{b.label} · version {b.version} · {b.questions.length} questions</span>
        <label className="small">Section <select className="input input-sm" aria-label="Section" value={section} onChange={(e) => setSection(e.target.value)}><option value="">All</option>{b.sections.map((s) => <option key={s.key} value={s.key}>{s.key === 'RF' ? s.label : `${s.key}. ${s.label}`}</option>)}</select></label>
        {b.can_edit && <Button variant="primary" onClick={() => setEdit('new')}>Add a question</Button>}
      </div>
      <div className="sc-table-wrap"><table className="sc-table">
        <thead><tr><th>Code</th><th>Section</th><th>Question</th><th>Type</th><th>Client link</th><th>If unknown</th>{b.can_edit && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{rows.map((x) => (
          <tr key={x.code} className={x.active ? '' : 'muted'}>
            <td className="nowrap"><strong>{x.code}</strong></td><td>{label(x.section)}</td>
            <td>{x.label}{x.client_label && <span className="small muted block">Client sees: {x.client_label}</span>}{x.options.length > 0 && <span className="small muted block">{x.options.map((o) => o.label).join(' · ')}</span>}</td>
            <td>{TYPE_LABELS[x.type] ?? x.type}</td>
            <td>{x.internal_only ? <Badge tone="muted">Internal, never sent</Badge> : x.client_visible ? <Badge tone="success">Offered</Badge> : <Badge>Not offered</Badge>}{!x.active && <> <Badge tone="muted">Not in use</Badge></>}</td>
            <td className="small">{x.unknown_assumption ?? '—'}</td>
            {b.can_edit && <td><Button size="sm" onClick={() => setEdit(x)}>Edit</Button></td>}
          </tr>
        ))}</tbody>
      </table></div>
      {edit && <Editor q={edit === 'new' ? null : edit} bank={b} onClose={() => setEdit(null)} onSaved={(m) => { setEdit(null); setMsg(m); void qc.invalidateQueries({ queryKey: ['scoping-bank'] }); }} />}
    </div>
  );
}
