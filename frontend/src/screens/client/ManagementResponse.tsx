import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, SelectField, TextArea, TextField, fileUrl, fmtDate } from '@/components/ui';
import { SignPanel, type SignOffView } from '@/components/SignPanel';
import { SEV_TONE } from '@/screens/futran/FieldworkUseCase';

type Row = {
  id: string | null; response: string | null; planned_action: string | null; owner_user_id: string | null; owner: string | null; due_date: string | null; status: string; adequacy_note: string | null;
  finding: { id: string; ref: string; title: string; severity: string; description: string | null; recommended_remediation: string | null };
  can_respond?: boolean; can_review?: boolean;
};
type Data = { audit_ref: string; client: string; stage: number; responses: Row[]; people: { id: string; name: string }[]; answered: number; total: number; sign_off_6: SignOffView | null; unmet: string[]; can_submit: boolean; draft_report: { pdf_file_id: string | null; docx_file_id: string | null; released_at: string } | null };

const RESPONSES = [{ value: 'agree', label: 'Agree' }, { value: 'partially_agree', label: 'Partially agree' }, { value: 'disagree', label: 'Disagree' }];
const STATUS: Record<string, { label: string; tone: 'warn' | 'navy' | 'success' | 'danger' }> = {
  needed: { label: 'Response needed', tone: 'warn' }, answered: { label: 'Answered · with Futran', tone: 'navy' }, adequate: { label: 'Accepted by Futran', tone: 'success' }, inadequate: { label: 'Futran asks for changes', tone: 'danger' },
};
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/** Screen 19: management responses to the draft report's findings, Futran's adequacy review, and sign-off 6. */
export function ManagementResponse() {
  const params = useParams();
  const { data: me } = useMe();
  const futran = !!params.clientId;
  const clientId = params.clientId ?? me?.organization.id ?? '';
  const key = ['responses', clientId];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/clients/${clientId}/responses`), enabled: !!clientId });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading || !clientId) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const run = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); await refresh(); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } };
  return (
    <div className="page">
      <PageHeader title={futran ? 'Management responses' : 'Respond to findings'}
        crumbs={futran ? [{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: `${d.client} · ${d.audit_ref}` }, { label: 'Responses' }] : undefined}
        subtitle={`Stage ${d.stage}${d.draft_report ? ` · draft report issued ${fmtDate(d.draft_report.released_at)}` : ''} · ${d.answered} of ${d.total} answered`}
        actions={d.draft_report?.pdf_file_id && <a className="btn" href={fileUrl(d.draft_report.pdf_file_id)}>Download draft report</a>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="split" style={{ marginTop: 16 }}>
        <div className="main stack">
          {d.responses.length === 0 && <Card><EmptyState>There are no findings for you to respond to.</EmptyState></Card>}
          {d.responses.map((r, i) => <ResponseCard key={r.finding.id} n={i + 1} r={r} people={d.people} futran={futran} run={run} />)}
        </div>
        <div className="side">
          <Card title="Sign-off 6 · Accept the remediation plan">
            <div className="stack">
              <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
                <li>Department Leads draft responses.</li>
                <li>Futran reviews each response for adequacy.</li>
                <li>The CAICO reviews all responses.</li>
                <li>The Executive Sponsor (or the CAICO) accepts the plan.</li>
              </ol>
              {d.sign_off_6 && <SignPanel signOffId={d.sign_off_6.id} hideTitle onSigned={refresh} agreeText="I accept these management responses and the remediation plan." />}
              {d.unmet.length > 0 && (!d.sign_off_6 || d.sign_off_6.status === 'returned') && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{d.unmet.map((m) => <li key={m}>{m}</li>)}</ul>}
              {!futran && (!d.sign_off_6 || d.sign_off_6.status === 'returned') && <div><Button variant="primary" disabled={!d.can_submit} onClick={() => run(() => api.post(`/clients/${clientId}/signoffs/6/submit`, {}), 'The remediation plan was sent for sign-off 6.')}>Send for sign-off 6</Button></div>}
              <p className="small muted" style={{ margin: 0 }}>Available when every finding has a response, owner and due date. Futran reviews responses for adequacy before the final report.</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ResponseCard({ n, r, people, futran, run }: { n: number; r: Row; people: Data['people']; futran: boolean; run: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const [v, setV] = useState({ response: r.response ?? '', planned_action: r.planned_action ?? '', owner_user_id: r.owner_user_id ?? '', due_date: r.due_date ?? '' });
  const [fe, setFe] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const st = STATUS[r.status] ?? STATUS.needed;
  const f = r.finding;
  async function save() {
    setFe({});
    try { await run(async () => { try { await api.put(`/findings/${f.id}/response`, v); } catch (e) { setFe(fieldErrors(e)); throw e; } }, `Response to ${f.ref} saved.`); } catch { /* shown above */ }
  }
  return (
    <Card>
      <div className="stack">
        <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
          <span className="small muted">Finding {n} · <Badge tone={SEV_TONE[f.severity]}>{cap(f.severity)}</Badge> · {f.ref}</span>
          <Badge tone={st.tone}>{st.label}</Badge>
        </div>
        <h3 style={{ margin: 0 }}>{f.title}</h3>
        <div className="statement small" style={{ whiteSpace: 'pre-wrap' }}><span className="muted">Written by Futran · read only</span>{'\n'}{f.description}{f.recommended_remediation && `\n\nRecommended action: ${f.recommended_remediation}`}</div>
        {r.adequacy_note && <Alert tone={r.status === 'inadequate' ? 'warn' : 'info'}>Futran: {r.adequacy_note}</Alert>}
        {r.can_respond ? (
          <>
            <fieldset className="stack-sm"><legend>Management response *</legend>
              <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>{RESPONSES.map((o) => <label key={o.value} className="check"><input type="radio" name={`resp-${f.id}`} checked={v.response === o.value} onChange={() => setV({ ...v, response: o.value })} /><span>{o.label}</span></label>)}</div>
              {fe.response && <span className="error">{fe.response}</span>}
            </fieldset>
            <TextArea label={v.response === 'disagree' ? 'Why you disagree *' : 'Planned action *'} value={v.planned_action} error={fe.planned_action} onChange={(e) => setV({ ...v, planned_action: e.target.value })} />
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <SelectField label="Owner *" value={v.owner_user_id} error={fe.owner_user_id} onChange={(e) => setV({ ...v, owner_user_id: e.target.value })} options={[{ value: '', label: 'Choose a person' }, ...people.map((p) => ({ value: p.id, label: p.name }))]} />
              <TextField label="Due date *" type="date" value={v.due_date} error={fe.due_date} onChange={(e) => setV({ ...v, due_date: e.target.value })} />
            </div>
            <div><Button variant="primary" onClick={save}>Save response</Button></div>
          </>
        ) : r.id ? (
          <dl className="kv-stacked">
            <dt>Response</dt><dd>{RESPONSES.find((o) => o.value === r.response)?.label}</dd>
            <dt>{r.response === 'disagree' ? 'Reason' : 'Planned action'}</dt><dd>{r.planned_action}</dd>
            {r.owner && <><dt>Owner</dt><dd>{r.owner}</dd></>}
            {r.due_date && <><dt>Due</dt><dd>{fmtDate(r.due_date)}</dd></>}
          </dl>
        ) : <p className="small muted" style={{ margin: 0 }}>No response yet.</p>}
        {futran && r.can_review && (
          <div className="stack-sm">
            <TextField label="Adequacy note" placeholder="Required if the response needs changes" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row" style={{ gap: 8 }}>
              <Button variant="primary" onClick={() => run(() => api.post(`/responses/${r.id}/adequacy`, { adequate: true, note }), `Response to ${f.ref} accepted.`)}>Adequate</Button>
              <Button onClick={() => run(() => api.post(`/responses/${r.id}/adequacy`, { adequate: false, note }), `Response to ${f.ref} sent back to the client.`)}>Ask for changes</Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
