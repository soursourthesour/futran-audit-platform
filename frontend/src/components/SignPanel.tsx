import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Checkbox, Loading, TextField, fileUrl, fmtDateTime } from '@/components/ui';
import { signHelp as H } from '@/help/client';

export type SignOffView = {
  id: string; number: number; title: string; status: string; approved_at: string | null;
  parties: { role: string; role_label: string; signed: boolean; signed_by: string | null; signed_at: string | null }[];
  document: { id: string; title: string; pdf_file_id: string | null; docx_file_id: string | null } | null;
  can_sign: boolean; my_name: string;
  version?: number; comment?: string | null; statement?: string | null; correction_reason?: string | null; preparer?: string | null; can_return?: boolean; can_withdraw?: boolean;
};

const STATUS: Record<string, { label: string; tone: 'success' | 'warn' | 'danger' | 'navy' }> = {
  approved: { label: 'Approved', tone: 'success' }, returned: { label: 'Returned', tone: 'danger' }, in_review: { label: 'Awaiting signatures', tone: 'warn' }, pending: { label: 'Awaiting signatures', tone: 'warn' },
};

/** Click-to-sign (schematic D8): open the document, type your name, sign. */
export function SignPanel({ signOffId, onSigned, agreeText, hideTitle, hideDocument }: { signOffId: string; onSigned?: () => void; agreeText?: string; hideTitle?: boolean; hideDocument?: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['signoff', signOffId], queryFn: () => api.get<SignOffView>(`/signoffs/${signOffId}`) });
  const [name, setName] = useState('');
  const [agree, setAgree] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [returning, setReturning] = useState(false);
  const [comment, setComment] = useState('');
  if (q.isLoading || !q.data) return <Loading />;
  const so = q.data;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null); setFe({}); setBusy(true);
    try {
      await api.post(`/signoffs/${signOffId}/sign`, { typed_name: name });
      await qc.invalidateQueries();
      onSigned?.();
    } catch (ex) {
      setErr(errorMessage(ex)); setFe(fieldErrors(ex));
    } finally {
      setBusy(false);
    }
  }

  async function sendBack() {
    setErr(null); setFe({});
    try { await api.post(`/signoffs/${signOffId}/return`, { comment }); await qc.invalidateQueries(); setReturning(false); onSigned?.(); } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); }
  }
  const st = STATUS[so.status] ?? STATUS.pending;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
        {hideTitle ? <span className="small muted">{so.preparer ? `Prepared by ${so.preparer}` : ''}{so.version && so.version > 1 ? ` · version ${so.version}` : ''}</span> : <strong>Sign-off {so.number}: {so.title}{so.version && so.version > 1 ? ` (version ${so.version})` : ''}</strong>}
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      {so.correction_reason && <p className="small" style={{ margin: 0 }}>Reopened: {so.correction_reason}</p>}
      {so.status === 'returned' && so.comment && <Alert tone="warn">Returned: {so.comment}</Alert>}
      {so.statement && <blockquote className="statement" style={{ whiteSpace: 'pre-wrap' }}>{so.statement}</blockquote>}
      {so.document && !hideDocument && (
        <p className="small">
          Read the document before signing: {so.document.pdf_file_id && <a href={fileUrl(so.document.pdf_file_id)}>PDF</a>}
          {so.document.docx_file_id && <> · <a href={fileUrl(so.document.docx_file_id)}>Word</a></>}
        </p>
      )}
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {so.parties.map((p) => (
          <li key={p.role}>{p.role_label}: {p.signed ? `signed by ${p.signed_by}, ${fmtDateTime(p.signed_at)}` : 'not signed yet'}</li>
        ))}
      </ul>
      {so.can_withdraw && (
        <div><Button size="sm" variant="ghost" onClick={async () => { setErr(null); try { await api.post(`/signoffs/${signOffId}/withdraw`); await qc.invalidateQueries(); onSigned?.(); } catch (ex) { setErr(errorMessage(ex)); } }}>Withdraw (you prepared this)</Button>{!so.can_sign && err && <Alert tone="danger">{err}</Alert>}</div>
      )}
      {so.can_sign && (
        <form className="stack" onSubmit={submit} noValidate>
          {err && <Alert tone="danger">{err}</Alert>}
          <TextField label="Type your full name to sign" help={H.typedName} value={name} onChange={(e) => setName(e.target.value)} placeholder={so.my_name} error={fe.typed_name} autoComplete="name" />
          <Checkbox label={`${agreeText ?? 'I have read the document and agree to it.'} Typing my name and selecting Sign is my signature.`} help={H.agree} checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <div className="row" style={{ gap: 8 }}>
            <Button type="submit" variant="primary" disabled={!agree || !name.trim() || busy}>Sign</Button>
            {so.can_return && !returning && <Button onClick={() => setReturning(true)}>Return with a comment</Button>}
          </div>
        </form>
      )}
      {returning && (
        <div className="stack-sm">
          <TextField label="What needs to change" help={H.returnComment} value={comment} onChange={(e) => setComment(e.target.value)} error={fe.comment} />
          <div className="row" style={{ gap: 8 }}><Button onClick={sendBack}>Return to preparer</Button><Button variant="ghost" onClick={() => setReturning(false)}>Cancel</Button></div>
        </div>
      )}
    </div>
  );
}
