import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Card, Loading, PageHeader } from '@/components/ui';
import { DataGrid, type GridColumn } from '@/components/ui/DataGrid';
import type { Carried as CarriedData, CarriedItem } from '@/api/wsk';

const STATUS: Record<CarriedItem['status'], [string, 'muted' | 'success' | 'warn']> = { pending: ['To confirm', 'muted'], confirmed: ['Confirmed', 'success'], changed: ['Changed', 'warn'] };

function useEngagementId(): { id: string | null; loading: boolean } {
  const q = useQuery({ queryKey: ['me-systems'], queryFn: () => api.get<{ engagement: { id: string } | null }>('/me/systems') });
  return { id: q.data?.engagement?.id ?? null, loading: q.isLoading };
}

/** Client screen: last year's answers carried into the annual review, to confirm or update (spec §21 F16). */
export function ClientCarried() {
  const eng = useEngagementId();
  if (eng.loading) return <div className="page"><Loading /></div>;
  if (!eng.id) return <div className="page"><PageHeader title="Last year’s answers" /><Alert tone="info">There is no engagement to show yet.</Alert></div>;
  return <CarriedScreen engagementId={eng.id} client />;
}

/** Futran screen: what the client confirmed or changed since the prior engagement. */
export function FutranCarried() {
  const { engagementId = '' } = useParams();
  return <CarriedScreen engagementId={engagementId} client={false} />;
}

function CarriedScreen({ engagementId, client }: { engagementId: string; client: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const key = ['carried', engagementId];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<CarriedData>(`/engagements/${engagementId}/carried`) });
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  async function confirm(rows: CarriedItem[]) {
    setMsg(null);
    try {
      for (const r of rows.filter((x) => x.status === 'pending')) await api.post(`/responses/${r.response_id}/confirm-carried`);
      setMsg({ tone: 'success', text: `Confirmed ${rows.filter((x) => x.status === 'pending').length} answer${rows.length === 1 ? '' : 's'} unchanged.` });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
    await refresh();
  }
  const columns: GridColumn<CarriedItem>[] = [
    { key: 'system', header: 'System', value: (r) => r.system, sortable: true },
    { key: 'question', header: 'Question', value: (r) => `${r.code} ${r.label}`, render: (r) => <><strong>{r.code}</strong> {r.label}</> },
    { key: 'prior', header: `Answer in ${d.prior_ref ?? 'the prior audit'}`, value: (r) => r.prior.text },
    { key: 'current', header: 'Answer now', value: (r) => r.current.text, render: (r) => r.status === 'changed' ? <strong className="changed-text">{r.current.text}</strong> : r.current.text },
    { key: 'status', header: 'Status', value: (r) => r.status, sortable: true, render: (r) => <Badge tone={STATUS[r.status][1]}>{STATUS[r.status][0]}</Badge> },
  ];
  const editPath = (r: CarriedItem) => (r.system_id ? `/systems/${r.system_id}` : '/systems/governance');
  return (
    <div className="page">
      <PageHeader title={client ? 'Last year’s answers' : 'Changes since the prior audit'}
        crumbs={client ? undefined : [{ to: '/audits', label: 'Audits' }, { label: d.engagement.audit_ref ?? 'Annual review' }]}
        subtitle={`${d.prior_ref ? `Carried forward from ${d.prior_ref}. ` : ''}${d.counts.total} answers · ${d.counts.pending} to confirm · ${d.counts.confirmed} confirmed · ${d.counts.changed} changed`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {client ? <Alert tone="info">Confirm each answer that is still true. If something changed, open the system and update the answer; the auditor sees what changed.</Alert>
        : <Alert tone="info">Changed answers are highlighted. Unchanged answers are confirmed by the client and still need your verification in fieldwork.</Alert>}
      <Card>
        <DataGrid label="Carried-forward answers" rows={d.items} rowId={(r) => r.response_id} rowLabel={(r) => `${r.code} ${r.label}`} columns={columns} selectable={client}
          rowClassName={(r) => (r.status === 'changed' ? 'row-changed' : undefined)}
          bulkActions={client ? [{ label: 'Confirm unchanged', run: confirm, available: (rows) => rows.some((r) => r.status === 'pending') }] : []}
          rowActions={(r) => client ? [{ label: 'Confirm unchanged', onSelect: () => void confirm([r]), disabled: r.status !== 'pending' }, { label: 'Update the answer', onSelect: () => navigate(editPath(r)) }]
            : r.system_id ? [{ label: 'Open the assessment', onSelect: () => navigate(`/systems/${r.system_id}/assess`) }] : []}
          filters={[{ key: 'status', label: 'Status', options: [{ value: 'pending', label: 'To confirm' }, { value: 'confirmed', label: 'Confirmed' }, { value: 'changed', label: 'Changed' }], test: (r, v) => r.status === v }]}
          search={{ label: 'Search answers', text: (r) => `${r.system} ${r.code} ${r.label}` }}
          emptyText="No answers were carried forward into this engagement." />
      </Card>
      {client && <p className="small"><Link to="/systems">Back to AI systems</Link></p>}
    </div>
  );
}

/** Banner on the client's AI systems list when an annual review carried answers forward. */
export function CarriedBanner({ engagementId }: { engagementId: string | null | undefined }) {
  const q = useQuery({ queryKey: ['carried', engagementId], queryFn: () => api.get<CarriedData>(`/engagements/${engagementId}/carried`), enabled: !!engagementId, retry: false });
  if (!q.data || q.data.counts.total === 0) return null;
  const c = q.data.counts;
  return <Alert tone="info">{`Last year’s answers were carried forward from ${q.data.prior_ref ?? 'the prior audit'}: ${c.pending} to confirm, ${c.confirmed} confirmed, ${c.changed} changed. `}<Link to="/carried">Review last year’s answers</Link></Alert>;
}
