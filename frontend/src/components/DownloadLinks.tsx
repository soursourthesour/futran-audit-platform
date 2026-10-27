import '@/styles/client-people.css';
import { fileUrl } from '@/components/ui';

/** A small download arrow. Decorative: the link text says what downloads. */
export function DownloadIcon() {
  return (
    <svg className="dl-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M8 1.5v8.2M4.6 6.6 8 10l3.4-3.4M2.5 11.5v2h11v-2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** PDF and Word download links for a generated document, each with a download icon. */
export function DownloadLinks({ pdf, docx, title }: { pdf?: string | null; docx?: string | null; title?: string }) {
  if (!pdf && !docx) return null;
  const of = title ? ` of ${title}` : '';
  return (
    <span className="dl-links">
      {pdf && <a className="dl-link" href={fileUrl(pdf)} download aria-label={`Download PDF${of}`}><DownloadIcon />PDF</a>}
      {docx && <a className="dl-link" href={fileUrl(docx)} download aria-label={`Download Word${of}`}><DownloadIcon />Word</a>}
    </span>
  );
}
