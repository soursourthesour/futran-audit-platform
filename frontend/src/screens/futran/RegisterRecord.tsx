import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { Bias, HistoryEntry, Statement } from '@/api/register';
import { Badge, Card, EmptyState, Loading, fmtDate, fmtDateTime, fileUrl } from '@/components/ui';

type BiasTest = { id: string; tested_on: string; next_due: string | null; tester_type: string; tester_name: string | null; method: string | null; groups_tested: string | null; result: string; result_text: string | null; unknown_share: number | null; null_compliance: boolean };
export type RegisterRecordData = {
  system: { id: string; reference: string; name: string; type_label: string; stage_label: string; risk_tier: number | null; live_since: string | null; bias: Bias; history_answers: Record<string, string> } | null;
  bias_tests: BiasTest[]; history: HistoryEntry[]; statement: Statement;
};
const TESTER: Record<string, string> = { independent: 'Independent auditor', internal: 'Internal team', vendor: 'Vendor' };

/** The client's register record behind an audit system: what the client recorded, read-only for the audit team. */
export function RegisterRecord({ systemId }: { systemId: string }) {
  const q = useQuery({ queryKey: ['register-record', systemId], queryFn: () => api.get<RegisterRecordData>(`/systems/${systemId}/register-record`) });
  if (q.isLoading) return <Loading />;
  const d = q.data;
  if (!d?.system) return <Card title="Client's register record"><EmptyState>This system is not linked to the client's AI system register. Link it when adding a system from the register on the AI systems page.</EmptyState></Card>;
  const s = d.system;
  return (
    <div className="stack">
      <Card title={`Client's register record · ${s.reference}`}>
        <div className="stack-sm">
          <p className="small muted" style={{ margin: 0 }}>Recorded by the client in their AI system register. Read-only here: test it as evidence, do not rely on it alone.</p>
          <dl className="details">
            <dt>System</dt><dd>{s.name} · {s.type_label}</dd>
            <dt>Stage</dt><dd>{s.stage_label}{s.live_since ? ` since ${fmtDate(s.live_since)}` : ''}</dd>
            <dt>Client's risk tier</dt><dd>{s.risk_tier ? `Tier ${s.risk_tier}` : '—'}</dd>
            <dt>Bias testing</dt><dd>{s.bias.last_tested_on ? `Last test ${fmtDate(s.bias.last_tested_on)} · ${s.bias.label}` : s.bias.label}{s.bias.null_compliance && <> <Badge tone="danger">Over 50% unknown demographics</Badge></>}</dd>
            <dt>Incidents question</dt><dd>{s.history_answers.incidents === 'no' ? 'No incidents known' : s.history_answers.incidents === 'yes' ? 'Incidents reported, see the log' : 'Not answered'}</dd>
          </dl>
          {d.statement && <blockquote className="statement">{d.statement.statement}<div className="small muted">{d.statement.signed_at ? `Signed by ${d.statement.signed_by} on ${fmtDateTime(d.statement.signed_at)}` : 'Not signed yet'}</div></blockquote>}
        </div>
      </Card>
      <Card title={`Bias tests (${d.bias_tests.length})`}>
        {d.bias_tests.length === 0 ? <EmptyState>No bias test recorded.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Date</th><th>Tested by</th><th>Method</th><th>Result</th><th>Unknown share</th><th>Next due</th></tr></thead>
            <tbody>{d.bias_tests.map((b) => (
              <tr key={b.id}><td>{fmtDate(b.tested_on)}</td><td>{TESTER[b.tester_type] ?? b.tester_type}{b.tester_name && <div className="small muted">{b.tester_name}</div>}</td><td className="small">{b.method ?? '—'}{b.groups_tested && <div className="muted">{b.groups_tested}</div>}</td>
                <td><Badge tone={b.result === 'passed' ? 'success' : b.result === 'flagged' ? 'danger' : 'muted'}>{b.result}</Badge>{b.result_text && <div className="small">{b.result_text}</div>}</td>
                <td>{b.unknown_share != null ? `${b.unknown_share}%` : '—'}{b.null_compliance && <div className="small" style={{ color: 'var(--danger)' }}>Possible null compliance</div>}</td><td>{fmtDate(b.next_due)}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      <Card title={`History log (${d.history.length})`}>
        {d.history.length === 0 ? <EmptyState>No history entries.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Date</th><th>Type</th><th>What happened</th><th>Result</th><th>Evidence</th><th>Recorded by</th></tr></thead>
            <tbody>{d.history.map((e) => (
              <tr key={e.id}><td>{fmtDate(e.occurred_on)}</td><td>{e.type_label}{e.severity_label && <div className="small muted">{e.severity_label}</div>}</td><td>{e.summary}</td><td className="small">{e.result ?? '—'}</td>
                <td className="small">{e.evidence.length ? e.evidence.map((f) => <div key={f.id}><a href={fileUrl(f.id)}>{f.filename}</a></div>) : '—'}</td><td className="small">{e.recorded_by}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}
