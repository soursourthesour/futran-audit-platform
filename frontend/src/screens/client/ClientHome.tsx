import { useMe } from '@/api/auth';
import { PageHeader, EmptyState } from '@/components/ui';

export function ClientHome() {
  const { data: me } = useMe();
  return (
    <div className="page">
      <PageHeader title="Getting started" subtitle={me ? `${me.organization.name} · AI governance assessment with Futran` : undefined} />
      <section className="card"><EmptyState>Your initiation package will appear here once Futran sends it.</EmptyState></section>
    </div>
  );
}
