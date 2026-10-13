import { PageHeader, EmptyState } from '@/components/ui';

export function Dashboard() {
  return (
    <div className="page">
      <PageHeader title="Audits" subtitle="All clients and engagements you can see. Auditors see only assigned clients and their own drafts." />
      <section className="card"><EmptyState>No engagements yet.</EmptyState></section>
    </div>
  );
}
