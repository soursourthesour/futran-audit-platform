import '@/styles/client-people.css';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Loading } from '@/components/ui';

/** A package document rendered for reading in place. The server renders it from Markdown with raw HTML escaped. */
export function DocReader({ docId, label, maxHeight }: { docId: string; label: string; maxHeight?: string }) {
  const q = useQuery({ queryKey: ['doc-preview', docId], queryFn: () => api.get<{ html: string }>(`/packages/documents/${docId}/preview`) });
  if (q.isLoading) return <Loading />;
  return (
    <div className="doc-reader" role="region" aria-label={label} tabIndex={0} style={maxHeight ? { maxHeight } : undefined}>
      <div className="doc-preview" dangerouslySetInnerHTML={{ __html: q.data?.html ?? '' }} />
    </div>
  );
}

/** Rendered HTML already fetched (for example the notice version a person must acknowledge). */
export function HtmlReader({ html, label, maxHeight }: { html: string; label: string; maxHeight?: string }) {
  return (
    <div className="doc-reader" role="region" aria-label={label} tabIndex={0} style={maxHeight ? { maxHeight } : undefined}>
      <div className="doc-preview" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
