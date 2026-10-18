import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { fmtDateTime } from '@/components/ui';

type Item = { id: string; kind: string; title: string; body: string | null; link: string | null; at: string; read: boolean };

/** In-app notifications (spec §14). Refreshes every minute. */
export function NotificationBell() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => api.get<{ unread: number; items: Item[] }>('/me/notifications'), refetchInterval: 60_000 });
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const unread = q.data?.unread ?? 0;
  async function openItem(n: Item) {
    if (!n.read) await api.post(`/notifications/${n.id}/read`);
    await qc.invalidateQueries({ queryKey: ['notifications'] });
    setOpen(false);
    if (n.link) nav(n.link);
  }
  async function readAll() { await api.post('/notifications/read-all'); await qc.invalidateQueries({ queryKey: ['notifications'] }); }
  return (
    <div className="bell" ref={ref}>
      <button type="button" className="bell-btn" aria-label={`Notifications, ${unread} unread`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
        {unread > 0 && <span className="bell-count">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="row" style={{ justifyContent: 'space-between', padding: '10px 14px', borderBottom: '1px solid var(--line-soft)' }}>
            <strong>Notifications</strong>
            {unread > 0 && <button type="button" className="linklike small" onClick={readAll}>Mark all read</button>}
          </div>
          {(q.data?.items ?? []).length === 0 ? <p className="small muted" style={{ padding: 14, margin: 0 }}>Nothing yet.</p> : (
            <ul>
              {q.data!.items.map((n) => (
                <li key={n.id} className={n.read ? '' : 'unread'}>
                  <button type="button" onClick={() => openItem(n)}>
                    <span className="t">{n.title}</span>
                    {n.body && <span className="b">{n.body}</span>}
                    <span className="d">{fmtDateTime(n.at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
