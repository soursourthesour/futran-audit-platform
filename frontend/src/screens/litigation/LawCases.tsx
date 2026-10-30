import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Badge, Card } from '@/components/ui';
import { STAGE_TONE, type CaseRow } from './types';

/** Cases that interpret a law, for the law record (M2). Drop in as <LawCases regulationId={law.id} />.
 *  Hidden for people who cannot see the litigation tracker. */
export function LawCases({ regulationId }: { regulationId: string }) {
  const q = useQuery({ queryKey: ['law-cases', regulationId], queryFn: () => api.get<CaseRow[]>(`/laws/${regulationId}/cases`), retry: false });
  if (q.isError || !q.data) return null;
  return (
    <Card title={`Court cases (${q.data.length})`}>
      {!q.data.length ? <p className="small muted" style={{ margin: 0 }}>No tracked case interprets this law.</p> : (
        <ul className="tight">
          {q.data.map((c) => <li key={c.id}><Link to={`/litigation/${c.id}`}>{c.name}</Link> <Badge tone={STAGE_TONE[c.stage] ?? 'muted'}>{c.stage_label}</Badge> <span className="small muted">{c.court}</span></li>)}
        </ul>
      )}
    </Card>
  );
}
