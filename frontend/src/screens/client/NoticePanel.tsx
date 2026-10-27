import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Badge, Button, Dialog, FieldHelp, Loading, TextArea, fmtDateTime } from '@/components/ui';
import { DownloadLinks } from '@/components/DownloadLinks';
import { HtmlReader } from '@/components/DocReader';
import { noticeHelp as H } from '@/help/client';

export type NoticeView = {
  can_edit: boolean;
  document: { id: string; title: string; html: string; body_md: string | null; pdf_file_id: string | null; docx_file_id: string | null };
  sent: { version: number; sent_at: string; sent_by: string | null; recipients: number } | null;
  unsent_changes: boolean;
  acknowledgements: { acknowledged: number; pending: number; version: number } | null;
};

/**
 * The employee AI audit and data notice (checklist item 6). Everyone can read it. The Chief AI Compliance Officer can
 * edit it and send it to every person on People > Users; sending completes the item and starts the audit.
 */
export function NoticeDialog({ onClose, onSent }: { onClose: () => void; onSent: (text: string) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['my-notice'], queryFn: () => api.get<NoticeView>('/me/notice') });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [confirmSend, setConfirmSend] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  if (q.isLoading || !q.data) return <Dialog title="Employee AI audit and data notice" onClose={onClose} wide><Loading /></Dialog>;
  const n = q.data;

  async function save() {
    setErr(null); setFe({}); setBusy(true);
    try {
      await api.put('/me/notice', { body_md: draft });
      await qc.invalidateQueries({ queryKey: ['my-notice'] });
      setEditing(false);
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); } finally { setBusy(false); }
  }
  async function send() {
    setErr(null); setBusy(true);
    try {
      const r = await api.post<{ version: number; recipients: number }>('/me/notice/send');
      await qc.invalidateQueries();
      setConfirmSend(false);
      onSent(`Version ${r.version} of the notice was emailed to ${r.recipients} ${r.recipients === 1 ? 'person' : 'people'}. Each person with a login acknowledges it at their next sign-in.`);
    } catch (ex) { setErr(errorMessage(ex)); setConfirmSend(false); } finally { setBusy(false); }
  }

  return (
    <Dialog title={n.document.title} onClose={onClose} wide>
      <div className="stack">
        <div className="notice-status">
          {n.sent ? <Badge tone="success">Version {n.sent.version} sent {fmtDateTime(n.sent.sent_at)}{n.sent.sent_by ? ` by ${n.sent.sent_by}` : ''}</Badge> : <Badge tone="warn">Not sent to employees yet</Badge>}
          {n.acknowledgements && <span>{n.acknowledgements.acknowledged} acknowledged · {n.acknowledgements.pending} pending</span>}
          {n.unsent_changes && <Badge tone="warn">Changed since it was sent</Badge>}
          <span className="spacer" />
          <DownloadLinks pdf={n.document.pdf_file_id} docx={n.document.docx_file_id} title={n.document.title} />
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
        {editing ? (
          <>
            <TextArea label="Notice text" help={H.body} className="textarea notice-editor" value={draft} onChange={(e) => setDraft(e.target.value)} error={fe.body_md} />
            <div className="row">
              <Button variant="primary" onClick={save} disabled={busy}>Save changes</Button>
              <Button onClick={() => { setEditing(false); setErr(null); setFe({}); }}>Cancel</Button>
            </div>
          </>
        ) : (
          <HtmlReader html={n.document.html} label={n.document.title} maxHeight="52vh" />
        )}
        {n.can_edit && !editing && (
          confirmSend ? (
            <Alert tone="warn">
              <div className="stack-sm">
                <span>Email {n.sent ? `version ${n.sent.version + 1}` : 'the notice'} to everyone on People &gt; Users? People with a login will be asked to acknowledge it at their next sign-in{n.sent ? ', including those who acknowledged an earlier version' : ''}.</span>
                <div className="row"><Button variant="primary" onClick={send} disabled={busy}>Send to employees</Button><Button onClick={() => setConfirmSend(false)}>Cancel</Button></div>
              </div>
            </Alert>
          ) : (
            <div className="row">
              <Button variant="primary" onClick={() => setConfirmSend(true)} disabled={!!n.sent && !n.unsent_changes} title={n.sent && !n.unsent_changes ? 'This version has already been sent. Edit the notice to send a new version.' : undefined}>
                {n.sent ? 'Send the new version to employees' : 'Send to employees'}
              </Button>
              <Button onClick={() => { setDraft(n.document.body_md ?? ''); setEditing(true); }}>Edit notice</Button>
              <FieldHelp label="Send to employees">{H.send}</FieldHelp>
            </div>
          )
        )}
        {!n.can_edit && <p className="small muted" style={{ margin: 0 }}>Only the Chief AI Compliance Officer can change or send this notice.</p>}
      </div>
    </Dialog>
  );
}
