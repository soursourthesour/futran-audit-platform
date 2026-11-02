import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Badge, Card, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import '@/styles/monitoring.css';
import '@/styles/regupdates.css';

type Item = {
  id: string; kind: 'update' | 'law_library'; change_label: string; law_name: string | null; jurisdiction_name: string | null; title: string; summary: string | null; effective_on: string | null;
  source_url: string | null; published_at: string | null; systems: { id: string; reference: string; name: string; risk_tier: number | null }[]; todos: { code: string; text: string; deadline?: string | null }[];
  why: string | null;
};
type Data = { items: Item[]; calendar: { law: string; date: string; what: string }[] };

/** Client view of regulatory change alerts (screen 26, client side): published updates that concern the company. */
export function ClientUpdates() {
  const q = useQuery({ queryKey: ['client-updates'], queryFn: () => api.get<Data>('/updates') });
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="What this means for you" subtitle="Regulatory changes reviewed by Futran that concern your AI systems, with what to do and the dates that apply to you. General information, not legal advice." />
      {!d ? <Loading /> : (
        <div className="ru-layout">
          <section className="ru-main" aria-label="Regulatory changes">
            {d.items.length === 0 ? <Card><EmptyState>No regulatory changes concern your AI systems yet. Futran adds them here as they are reviewed.</EmptyState></Card> : d.items.map((i) => (
              <Card key={`${i.kind}-${i.id}`}>
                <article className="ru-update">
                  <div className="row"><Badge tone={i.change_label === 'Enforcement' ? 'danger' : 'navy'}>{i.change_label}</Badge>{i.jurisdiction_name && <span className="small muted">{i.jurisdiction_name}</span>}
                    {i.published_at && <span className="small muted">Published {fmtDate(i.published_at)}</span>}</div>
                  <h3>{i.law_name && !i.title.includes(i.law_name) ? `${i.law_name}: ` : ''}{i.title}</h3>
                  {i.summary && <p style={{ margin: 0 }}>{i.summary}</p>}
                  {i.systems.length > 0 && (
                    <div><strong className="small">Your systems affected</strong>
                      <ul className="ru-list">{i.systems.map((s) => <li key={s.id}><Link to={`/register/${s.id}`}>{s.reference} {s.name}</Link>{s.risk_tier ? ` · Tier ${s.risk_tier}` : ''}</li>)}</ul></div>)}
                  {i.todos.length > 0 && (
                    <div><strong className="small">What to do</strong>
                      <ul className="ru-list">{i.todos.map((t) => <li key={t.code}>{t.text}</li>)}</ul></div>)}
                  <div className="small muted">{i.effective_on && <>From {fmtDate(i.effective_on)}</>}{i.effective_on && i.source_url && ' · '}{i.source_url && <a href={i.source_url} target="_blank" rel="noreferrer">Official source</a>}</div>
                </article>
              </Card>))}
          </section>
          <aside className="ru-aside">
            <Card title="Your deadline calendar">
              {d.calendar.length === 0 ? <EmptyState>No upcoming dates for the laws that apply to you.</EmptyState> : (
                <ul className="ru-dates">{d.calendar.map((r) => <li key={`${r.law}-${r.date}-${r.what}`}><span>{r.law}<span className="small muted block">{r.what}</span></span><strong className="nowrap">{fmtDate(r.date)}</strong></li>)}</ul>)}
            </Card>
          </aside>
        </div>
      )}
    </div>
  );
}
