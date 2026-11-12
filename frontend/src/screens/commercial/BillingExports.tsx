import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Button, Card, EmptyState, Loading, PageHeader, TextField, fmtDateTime } from '@/components/ui';
import './commercial.css';

type Run = { id: string; period: string; client_id: string | null; client_name: string | null; rows: number; run_at: string };

/** G-01 billing export for all clients (generic CSV for the accounting system; written on the 1st for the month before). */
export function BillingExports() {
  const q = useQuery({ queryKey: ['billing-exports'], queryFn: () => api.get<Run[]>('/staff/billing-export') });
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1);
  const [period, setPeriod] = useState(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  const [err, setErr] = useState<string | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  const run = async () => {
    setErr(null);
    try { const r = await api.post<Run>('/staff/billing-export', { period }); await q.refetch(); window.location.assign(`/api/v1/staff/billing-export/${r.id}.csv`); }
    catch (e) { setErr(errorMessage(e)); }
  };
  return (
    <div className="page commercial">
      <PageHeader title="Billing export" subtitle="Order lines due, overages, hours beyond banks, retainer hours and partner commissions, as a CSV for the accounting system. No invoices are created here." />
      {err && <Alert tone="danger">{err}</Alert>}
      <Card title="Run an export">
        <div className="row cost-form"><TextField label="Month" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} /><Button variant="primary" onClick={run}>Export all clients</Button></div>
      </Card>
      <Card title="Earlier exports">
        {!q.data || q.data.length === 0 ? <EmptyState>None yet.</EmptyState> : (
          <ul className="plain">{q.data.map((r) => <li key={r.id}><a href={`/api/v1/staff/billing-export/${r.id}.csv`}>{r.period} · {r.client_name ?? 'all clients'}</a> <span className="small muted">· {r.rows} rows · {fmtDateTime(r.run_at)}</span></li>)}</ul>
        )}
      </Card>
    </div>
  );
}
