import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, Checkbox, Dialog, Loading, TextArea, fileUrl } from '@/components/ui';
import { DocPreview } from '@/components/DocPreview';
import { useWizardCtx } from './Wizard';

type Doc = { id: string; item: number; title: string; requires_action: string; action_label: string; format: string; docx_file_id: string | null; pdf_file_id: string | null; csv_file_id: string | null; editable: boolean; edited: boolean; template_version: number };
type Pkg = { id: string; status: string; version: number; prepared_by: string | null; documents: Doc[]; sends_to: { name: string; email: string; roles: string[] }[]; summary: { type_label: string; sites: string[]; laws: string[]; departments: string[]; team: string[] } };

const DEFAULT_MESSAGE = (client: string) => `We look forward to working with you on ${client}'s AI governance assessment. Please sign the engagement letter and nominate your role holders within the next 10 business days.`;

export function StepPackage() {
  const { clientId, data } = useWizardCtx();
  const { data: me } = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const client = String(data.company.trading_name || data.company.legal_name || 'the client');
  const pkg = useQuery({ queryKey: ['package', clientId], queryFn: () => api.get<Pkg>(`/clients/${clientId}/package`) });
  const [message, setMessage] = useState(DEFAULT_MESSAGE(client));
  const [checks, setChecks] = useState({ scope_ok: false, no_conflict: false, letter_previewed: false });
  const [preview, setPreview] = useState<Doc | null>(null);
  const [editing, setEditing] = useState<{ doc: Doc; body: string } | null>(null);
  const [returning, setReturning] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const isChief = hasRole(me ?? undefined, 'chief_auditor');

  if (pkg.isLoading) return <Loading label="Generating the initiation package…" />;
  if (pkg.isError || !pkg.data) return <Alert tone="danger">{errorMessage(pkg.error)}</Alert>;
  const p = pkg.data;

  async function openEdit(doc: Doc) {
    const r = await api.get<{ body_md: string }>(`/packages/documents/${doc.id}/preview`);
    setEditing({ doc, body: r.body_md });
  }
  async function saveEdit() {
    if (!editing) return;
    try {
      await api.put(`/packages/documents/${editing.doc.id}`, { body_md: editing.body });
      await qc.invalidateQueries({ queryKey: ['package', clientId] });
      await qc.invalidateQueries({ queryKey: ['doc-preview', editing.doc.id] });
      setEditing(null);
    } catch (ex) { setErr(errorMessage(ex)); }
  }
  async function approve() {
    setErr(null); setFe({}); setBusy(true);
    try {
      await api.post(`/clients/${clientId}/approve`, { client_message: message, checklist: checks });
      await qc.invalidateQueries();
      nav(`/clients/${clientId}`, { state: { flash: 'Approved and sent. The client contacts have their invitations.' } });
    } catch (ex) { setErr(errorMessage(ex)); setFe(fieldErrors(ex)); } finally { setBusy(false); }
  }
  async function sendBack() {
    try {
      await api.post(`/clients/${clientId}/return`, { comment: returning ?? '' });
      await qc.invalidateQueries();
      nav('/audits', { state: { flash: `${client} was returned to the author with your comments.` } });
    } catch (ex) { setErr(errorMessage(ex)); }
  }

  return (
    <div className="split">
      <div className="main stack">
        <Card title="Documents" actions={<Badge tone="warn">Awaiting approval</Badge>}>
          <div className="stack">
            <p className="small muted">Generated from the current templates with {client}'s details merged in. Drafted by {p.prepared_by ?? 'the auditor'}.</p>
            <ol className="checklist">
              {p.documents.map((d) => (
                <li key={d.id}>
                  <span className="num">{d.item}</span>
                  <div className="body">
                    <h3>{d.title} {d.edited && <Badge tone="muted">Edited</Badge>}</h3>
                    <div className="small muted">{d.action_label}</div>
                    <div className="row small" style={{ gap: 12, marginTop: 4 }}>
                      <button type="button" className="link-btn" onClick={() => { setPreview(d); if (d.item === 1) setChecks((c) => ({ ...c, letter_previewed: true })); }}>Preview</button>
                      {d.editable && isChief && <button type="button" className="link-btn" onClick={() => openEdit(d)}>Edit</button>}
                      {d.pdf_file_id && <a href={fileUrl(d.pdf_file_id)}>PDF</a>}
                      {d.docx_file_id && <a href={fileUrl(d.docx_file_id)}>Word</a>}
                      {d.csv_file_id && <a href={fileUrl(d.csv_file_id)}>CSV</a>}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </Card>
        <Card title="Message to the client">
          <TextArea label="Appears in the invitation email above the link" value={message} onChange={(e) => setMessage(e.target.value)} help="Invitation links expire after 7 days." disabled={!isChief} />
        </Card>
      </div>
      <div className="side stack">
        <Card title="Summary">
          <dl className="kv" style={{ gridTemplateColumns: '1fr' }}>
            <dt>Engagement</dt><dd>{p.summary.type_label}</dd>
            <dt>Sites in scope</dt><dd>{p.summary.sites.join(' · ')}</dd>
            <dt>Laws and frameworks</dt><dd>{p.summary.laws.join(' · ')}</dd>
            <dt>Departments</dt><dd>{p.summary.departments.length} in scope</dd>
            <dt>Futran team</dt><dd>{p.summary.team.join(' · ')}</dd>
            <dt>Sends to</dt><dd>{p.sends_to.map((s) => <div key={s.email}>{s.name}, {s.roles.join(' and ')}</div>)}</dd>
          </dl>
        </Card>
        {isChief ? (
          <Card title="Your approval">
            <div className="stack">
              {err && <Alert tone="danger">{err}</Alert>}
              <Checkbox label="Scope, laws and departments are appropriate for this client" checked={checks.scope_ok} onChange={(e) => setChecks({ ...checks, scope_ok: e.target.checked })} />
              {fe['checklist.scope_ok'] && <p className="small" style={{ color: 'var(--danger)', margin: 0 }}>{fe['checklist.scope_ok']}</p>}
              <Checkbox label="The team has no conflict of interest" checked={checks.no_conflict} onChange={(e) => setChecks({ ...checks, no_conflict: e.target.checked })} />
              <Checkbox label="I have previewed the engagement letter" checked={checks.letter_previewed} onChange={(e) => setChecks({ ...checks, letter_previewed: e.target.checked })} />
              <Button variant="primary" onClick={approve} disabled={busy}>Approve and send</Button>
              <Button onClick={() => setReturning('')}>Return to author with comments</Button>
              <p className="small muted" style={{ margin: 0 }}>Sending creates the client accounts, emails the invitations and records the approval in the audit log.</p>
            </div>
          </Card>
        ) : <Alert tone="info">Waiting for the Chief Auditor to approve and send this package.</Alert>}
      </div>
      {preview && <DocPreview docId={preview.id} title={preview.title} onClose={() => setPreview(null)} />}
      {editing && (
        <Dialog title={`Edit: ${editing.doc.title}`} onClose={() => setEditing(null)} wide>
          <div className="stack">
            <p className="small muted">This changes the document for this client only. To change it for every client, edit the template under Templates.</p>
            <TextArea label="Document text (Markdown)" value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} rows={18} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13 }} />
            <div className="row"><Button variant="primary" onClick={saveEdit}>Save document</Button><Button onClick={() => setEditing(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
      {returning !== null && (
        <Dialog title="Return to the author" onClose={() => setReturning(null)}>
          <div className="stack">
            <TextArea label="What needs to change" value={returning} onChange={(e) => setReturning(e.target.value)} />
            <div className="row"><Button variant="primary" onClick={sendBack} disabled={!returning.trim()}>Return with comments</Button><Button onClick={() => setReturning(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
