import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import { DocumentUploadsList, type DocRequest } from '@/screens/futran/DocumentRegister';

/** The client's requested documents (template §2): upload each one, or confirm it does not exist. */
export function DocumentUploads() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['me-documents'], queryFn: () => api.get<{ requests: DocRequest[]; due: string | null }>('/me/document-requests') });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  const open = d.requests.filter((r) => r.status === 'pending').length;
  return (
    <div className="page">
      <PageHeader title="Documents" subtitle={d.due ? `Please provide these by ${fmtDate(d.due)}. ${open} still to do.` : 'Documents the auditor has asked for.'} />
      {d.requests.length === 0 ? <EmptyState>Futran has not requested any documents from you yet.</EmptyState> : <div className="stack"><DocumentUploadsList rows={d.requests} onDone={() => qc.invalidateQueries({ queryKey: ['me-documents'] })} /></div>}
    </div>
  );
}
