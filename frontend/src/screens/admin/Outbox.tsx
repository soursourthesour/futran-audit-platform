import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, fmtDateTime } from '@/components/ui';
import '@/styles/staff-forms.css';

type Msg = { id: string; to: string[]; cc: string[] | null; subject: string; body_html: string; template_key: string; status: string; error: string | null; created_at: string };

/** Invitation links in a message body (absolute, as the email carries them). */
function inviteLinks(html: string): string[] {
  const found = html.match(/https?:\/\/[^\s"'<>]+\/invite\/[A-Za-z0-9_-]+/g) ?? [];
  return [...new Set(found)];
}

/** The email shown in a sandboxed frame. Links open in a new tab; scripts never run. */
function frameDoc(html: string): string {
  const base = '<base target="_blank"><meta name="viewport" content="width=device-width, initial-scale=1"><style>table, img { max-width: 100% !important; height: auto; } body { margin: 8px; }</style>';
  return /<head[^>]*>/i.test(html) ? html.replace(/<head([^>]*)>/i, `<head$1>${base}`) : `${base}${html}`;
}

function statusBadge(status: string) {
  return status === 'sent' ? <Badge tone="success">Sent</Badge> : status === 'failed' ? <Badge tone="danger">Failed</Badge> : <Badge>Queued</Badge>;
}

export function OutboxScreen() {
  const q = useQuery({ queryKey: ['outbox'], queryFn: () => api.get<Msg[]>('/admin/outbox') });
  const [open, setOpen] = useState<string | null>(null);
  const selected = q.data?.find((m) => m.id === open);
  return (
    <div className="page">
      <PageHeader title="Outbox" subtitle="Every email the platform has sent or would send. In test mode nothing leaves the platform; open a message to read it." />
      <Card>
        {q.isLoading ? <Loading /> : !q.data?.length ? <EmptyState>No emails yet.</EmptyState> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>To</th><th>Subject</th><th>Status</th></tr></thead>
              <tbody>
                {q.data.map((m) => (
                  <tr key={m.id} className="clickable" onClick={(e) => { e.currentTarget.querySelector('button')?.focus(); setOpen(m.id); }}>
                    <td>{fmtDateTime(m.created_at)}</td>
                    <td>{m.to.join(', ')}</td>
                    <td><button type="button" className="link-btn" onClick={(e) => { e.stopPropagation(); setOpen(m.id); }} aria-haspopup="dialog">{m.subject}</button></td>
                    <td>{statusBadge(m.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {selected && <MessageDialog m={selected} onClose={() => setOpen(null)} />}
    </div>
  );
}

function MessageDialog({ m, onClose }: { m: Msg; onClose: () => void }) {
  const links = inviteLinks(m.body_html);
  const [copied, setCopied] = useState<string | null>(null);
  async function copy(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(link);
    } catch {
      window.prompt('Copy the invitation link', link);
    }
  }
  return (
    <Dialog title={m.subject} onClose={onClose} large>
      <div className="stack">
        <dl className="email-meta">
          <dt>To</dt><dd>{m.to.join(', ')}</dd>
          {m.cc?.length ? <><dt>CC</dt><dd>{m.cc.join(', ')}</dd></> : null}
          <dt>When</dt><dd>{fmtDateTime(m.created_at)}</dd>
          <dt>Status</dt><dd>{statusBadge(m.status)}</dd>
        </dl>
        {m.error && <div className="alert alert-danger">{m.error}</div>}
        {links.map((link) => (
          <div key={link} className="copy-row">
            <Button size="sm" variant="primary" onClick={() => copy(link)}>Copy link</Button>
            <code>{link}</code>
            <span className="small muted" role="status">{copied === link ? 'Copied.' : ''}</span>
          </div>
        ))}
        <iframe title="Email preview" className="email-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={frameDoc(m.body_html)} />
      </div>
    </Dialog>
  );
}
