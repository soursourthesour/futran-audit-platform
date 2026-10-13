import { useLocation } from 'react-router-dom';
import { Alert, ButtonLink, PageHeader, EmptyState } from '@/components/ui';
import { hasRole, useMe } from '@/api/auth';

export function Dashboard() {
  const { data: me } = useMe();
  const flash = (useLocation().state as { flash?: string } | null)?.flash;
  const canCreate = hasRole(me ?? undefined, 'auditor', 'chief_auditor', 'admin');
  return (
    <div className="page">
      <PageHeader title="Audits" subtitle="All clients and engagements you can see. Auditors see only assigned clients and their own drafts." actions={canCreate ? <ButtonLink to="/audits/new" variant="primary">New client</ButtonLink> : undefined} />
      {flash && <Alert tone="success">{flash}</Alert>}
      <section className="card"><EmptyState>No engagements yet.</EmptyState></section>
    </div>
  );
}
