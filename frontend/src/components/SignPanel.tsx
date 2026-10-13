import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Loading, TextField, fileUrl, fmtDateTime } from '@/components/ui';

export type SignOffView = {
  id: string; number: number; title: string; status: string; approved_at: string | null;
  parties: { role: string; role_label: string; signed: boolean; signed_by: string | null; signed_at: string | null }[];
  document: { id: string; title: string; pdf_file_id: string | null; docx_file_id: string | null } | null;
  can_sign: boolean; my_name: string;
};

/** Click-to-sign (schematic D8): open the document, type your name, sign. */
export function SignPanel({ signOffId, onSigned }: { signOffId: string; onSigned?: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['signoff', signOffId], queryFn: () => api.get<SignOffView>(`/signoffs/${signOffId}`) });
  const [name, setName] = useState('');
  const [agree, setAgree] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
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

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>Sign-off {so.number}: {so.title}</strong>
        {so.status === 'approved' ? <Badge tone="success">Approved</Badge> : <Badge tone="warn">Awaiting signatures</Badge>}
      </div>
      {so.document && (
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
      {so.can_sign && (
        <form className="stack" onSubmit={submit} noValidate>
          {err && <Alert tone="danger">{err}</Alert>}
          <TextField label="Type your full name to sign" value={name} onChange={(e) => setName(e.target.value)} placeholder={so.my_name} error={fe.typed_name} autoComplete="name" />
          <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /><span>I have read the document and agree to it. Typing my name and selecting Sign is my signature.</span></label>
          <div><Button type="submit" variant="primary" disabled={!agree || !name.trim() || busy}>Sign</Button></div>
        </form>
      )}
    </div>
  );
}
