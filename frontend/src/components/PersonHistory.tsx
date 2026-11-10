import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Dialog, EmptyState, Loading, fmtDateTime } from '@/components/ui';
import './person-history.css';

export type ChangeEvent = {
  id: string; at: string; by: string | null; kind: 'role' | 'department'; change: string; user_id: string | null; name: string | null;
  role: string | null; department: string | null; from: string | null; to: string | null; summary: string | null; sign_off_role: boolean; current_roles: string[];
};
type History = { user: { id: string; name: string; email: string; removed: boolean }; events: ChangeEvent[] };

/** What changed, in words: "Contributor for Finance", "Finance to Legal". */
export function changeText(e: ChangeEvent): string {
  if (e.kind === 'department') return e.from ? `${e.from} to ${e.to ?? 'no department'}` : `Put in ${e.to ?? '—'}`;
  if (e.change === 'Role removed') return `${e.from ?? e.role ?? ''} removed`;
  if (e.change === 'Role given') return `${e.to ?? e.role ?? ''}${e.department ? ` for ${e.department}` : ''}`;
  return `${e.role ?? ''}: ${e.change.toLowerCase()}`;
}

/** A person's AI compliance role and department changes, newest first, from the audit log (11-03 review C2). */
export function PersonHistory({ cid, userId, name, onClose }: { cid: string; userId: string; name: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['person-history', cid, userId], queryFn: () => api.get<History>(`/clients/${cid}/users/${userId}/history`) });
  return (
    <Dialog title={`Change history: ${q.data?.user.name ?? name}`} onClose={onClose} wide>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>Every change to this person's AI compliance roles and department, newest first, as recorded in the audit log.</p>
        {q.isLoading ? <Loading /> : q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : !q.data?.events.length ? <EmptyState>No role or department changes are recorded for this person.</EmptyState> : (
          <ol className="history-list" aria-label={`Changes for ${q.data.user.name}`}>
            {q.data.events.map((e) => (
              <li key={e.id}>
                <div><strong>{e.change}</strong>: {changeText(e)}</div>
                <div className="small muted">{e.by ?? 'System'} · {fmtDateTime(e.at)}</div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Dialog>
  );
}
