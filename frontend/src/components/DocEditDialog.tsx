import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Button, Dialog, Loading, TextArea } from '@/components/ui';
import { packageHelp as H } from '@/help/onboarding';

/**
 * The Chief Auditor's editor for an initiation package document. Saving regenerates the PDF and Word files and is
 * recorded in the audit log; once the package has been sent, the client is told the document changed.
 */
export function DocEditDialog({ docId, title, sent, onClose, onSaved }: { docId: string; title: string; sent?: boolean; onClose: () => void; onSaved?: () => void }) {
  const qc = useQueryClient();
  const [body, setBody] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.get<{ body_md: string | null }>(`/packages/documents/${docId}/preview`).then((r) => { if (live) setBody(r.body_md ?? ''); }).catch((e) => { if (live) setErr(errorMessage(e)); });
    return () => { live = false; };
  }, [docId]);

  async function save() {
    if (body === null) return;
    setBusy(true);
    setErr(null);
    try {
      await api.put(`/packages/documents/${docId}`, { body_md: body });
      await qc.invalidateQueries({ queryKey: ['doc-preview', docId] });
      onSaved?.();
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title={`Edit: ${title}`} onClose={onClose} wide>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>
          This changes the document for this client only. To change it for every client, edit the template under Templates.
          {sent && ' The client already has this document: saving replaces the PDF and Word files and tells the client it has changed.'}
        </p>
        {err && <Alert tone="danger">{err}</Alert>}
        {body === null ? (!err && <Loading />) : (
          <TextArea label="Document text (Markdown)" help={H.documentText} value={body} onChange={(e) => setBody(e.target.value)} rows={18} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13 }} />
        )}
        <div className="row"><Button variant="primary" onClick={save} disabled={busy || body === null}>Save document</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
