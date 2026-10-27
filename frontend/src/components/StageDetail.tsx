import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Dialog, EmptyState, Loading, fmtDateTime } from '@/components/ui';
import '@/styles/staff-forms.css';

type Signer = { role: string; role_label: string; signed_by: string | null; signed_at: string | null };
type SignOffRow = {
  id: string; number: number; title: string; scope_label: string | null; version: number; status: string; status_label: string;
  preparer: string | null; sent_at: string | null; approved_at: string | null; signers: Signer[]; reason: string | null; correction_reason: string | null;
};
export type Stage = {
  number: number; name: string; state: 'done' | 'current' | 'upcoming' | 'not_started'; summary: string; exit: string;
  entered_at: string | null; exited_at: string | null; sign_offs: SignOffRow[]; expected_sign_offs: { number: number; title: string; signers: string[] }[];
  events: { at: string; actor: string; action: string; summary: string | null }[]; open: string[]; links: { label: string; to: string }[];
};

const STATE_LABEL = { done: 'Complete', current: 'Current stage', upcoming: 'Not started', not_started: 'Not started' } as const;
const TONE = { done: 'success', current: 'navy', upcoming: 'muted', not_started: 'muted' } as const;

/** What happened in one engagement stage: sign-offs and signatures, key events and what is still open. */
export function StageDetail({ clientId, number, onClose }: { clientId: string; number: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ['stage', clientId, number], queryFn: () => api.get<Stage>(`/clients/${clientId}/stages/${number}`) });
  const s = q.data;
  const title = s ? `Stage ${s.number} · ${s.name}` : `Stage ${number}`;
  return (
    <Dialog title={title} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : q.isError || !s ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : (
        <div>
          <div className="stage-meta">
            <Badge tone={TONE[s.state]}>{STATE_LABEL[s.state]}</Badge>
            {s.entered_at && <span>Started {fmtDateTime(s.entered_at)}</span>}
            {s.exited_at && <span>Finished {fmtDateTime(s.exited_at)}</span>}
          </div>
          <section className="stage-section" style={{ marginTop: 16 }}>
            <p style={{ margin: '0 0 6px' }}>{s.summary}</p>
            <p className="small muted" style={{ margin: 0 }}><strong>{s.state === 'done' ? 'Completed when: ' : 'To move on: '}</strong>{s.exit}</p>
          </section>

          {s.open.length > 0 && (
            <section className="stage-section">
              <h3>Still open</h3>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{s.open.map((u) => <li key={u}>{u}</li>)}</ul>
            </section>
          )}

          {(s.sign_offs.length > 0 || s.expected_sign_offs.length > 0) && (
            <section className="stage-section">
              <h3>Sign-offs</h3>
              {s.sign_offs.length === 0 ? (
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  {s.expected_sign_offs.map((x) => <li key={x.number}>Sign-off {x.number}: {x.title}. Signed by the {x.signers.join(' and the ')}. Not sent yet.</li>)}
                </ul>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Sign-off</th><th>Status</th><th>Prepared by</th><th className="wrap">Signatures</th><th className="wrap">Notes</th></tr></thead>
                    <tbody>
                      {s.sign_offs.map((so) => (
                        <tr key={so.id}>
                          <td className="wrap"><strong>{so.number}</strong> · {so.title}{so.scope_label ? ` · ${so.scope_label}` : ''}{so.version > 1 && <span className="cell-sub">Version {so.version}</span>}</td>
                          <td><Badge tone={so.status === 'approved' && !so.status_label.startsWith('Replaced') ? 'success' : so.status === 'returned' ? 'warn' : 'default'}>{so.status_label}</Badge>{so.approved_at && <span className="cell-sub">{fmtDateTime(so.approved_at)}</span>}</td>
                          <td className="wrap">{so.preparer ?? '—'}{so.sent_at && <span className="cell-sub">Sent {fmtDateTime(so.sent_at)}</span>}</td>
                          <td className="wrap">
                            <ul className="signers small">
                              {so.signers.map((x) => <li key={x.role}><strong>{x.role_label}:</strong> {x.signed_by ? <>{x.signed_by}, {fmtDateTime(x.signed_at)}</> : <span className="muted">not signed</span>}</li>)}
                            </ul>
                          </td>
                          <td className="wrap small">{[so.reason && `Reason: ${so.reason}`, so.correction_reason && `Reopened: ${so.correction_reason}`].filter(Boolean).join(' ') || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {(s.state === 'done' || s.state === 'current' || s.events.length > 0) && (
            <section className="stage-section">
              <h3>Key events</h3>
              {s.events.length === 0 ? <EmptyState>Nothing recorded yet.</EmptyState> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>When</th><th>By</th><th className="wrap">What happened</th></tr></thead>
                    <tbody>{s.events.map((ev, i) => <tr key={i}><td>{fmtDateTime(ev.at)}</td><td>{ev.actor}</td><td className="wrap">{ev.summary ?? ev.action}</td></tr>)}</tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {s.links.length > 0 && (
            <section className="stage-section">
              <h3>Go to</h3>
              <div className="work-areas">{s.links.map((l) => <Link key={l.to} to={l.to} onClick={onClose}>{l.label}</Link>)}</div>
            </section>
          )}
        </div>
      )}
    </Dialog>
  );
}
