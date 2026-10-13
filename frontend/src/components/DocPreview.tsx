import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Dialog, Loading } from '@/components/ui';

/** Shows a generated document as HTML. The server renders it from Markdown with raw HTML escaped. */
export function DocPreview({ docId, title, onClose }: { docId: string; title: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['doc-preview', docId], queryFn: () => api.get<{ html: string }>(`/packages/documents/${docId}/preview`) });
  return (
    <Dialog title={title} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : <div className="doc-preview" dangerouslySetInnerHTML={{ __html: q.data?.html ?? '' }} />}
    </Dialog>
  );
}
