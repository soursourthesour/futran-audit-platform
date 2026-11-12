import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, EmptyState, Loading, fmtDate } from '@/components/ui';
import { money, type ProposalSummary } from '@/api/proposals';
import { statusBadge } from './ProposalBuilder';
import '@/styles/proposals.css';

/** Every proposal, latest version of each. Proposals start from an opportunity, the Estimator or a locked questionnaire. */
export function ProposalList() {
  const q = useQuery({ queryKey: ['proposals'], queryFn: () => api.get<{ items: ProposalSummary[] }>('/sales/proposals') });
  return (
    <div className="page">
      <div className="page-header"><div><h1>Proposals</h1><p>Latest version of each proposal. Start one from the Estimator or a locked scoping questionnaire.</p></div></div>
      {q.isLoading ? <Loading /> : q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : !q.data?.items.length ? <EmptyState>No proposals yet.</EmptyState> : (
        <section className="card"><div className="table-wrap">
          <table className="table" aria-label="Proposals">
            <thead><tr><th>Company</th><th>Version</th><th>Status</th><th className="num">Year-1 total</th><th>Valid until</th><th>Updated</th></tr></thead>
            <tbody>
              {q.data.items.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/sales/proposals/${p.id}`}>{p.company}</Link>{p.prospect && <span className="small muted"> · prospect</span>}</td>
                  <td>v{p.version}</td><td>{statusBadge(p.status, p.status_label)}</td><td className="num">{money(p.totals.y1_total)}</td>
                  <td>{fmtDate(p.valid_until)}</td><td>{fmtDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div></section>
      )}
    </div>
  );
}
