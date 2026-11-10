import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Button, Card, EmptyState, Loading, PageHeader, fmtDate, fmtDateTime } from '@/components/ui';
import { FieldHelp } from '@/components/ui/FieldHelp';

type T = { key: string; name: string; type: string; version: number; body: string; package_item: number | null; requires_action: string | null; format: string; updated_at: string; approved_at: string; approved_by: string | null };

/** What the (i) beside a template's name says: its revision, and when and by whom it was approved (11-03 F10). */
function Revision({ t }: { t: T }) {
  return (
    <FieldHelp label={`${t.name} revision`}>
      <strong>Revision {t.version}.</strong>{' '}
      {t.approved_by ? `Approved ${fmtDateTime(t.approved_at)} by ${t.approved_by}.` : `The platform's standard text, in use since ${fmtDate(t.approved_at)}.`}
      {' '}Documents generated from now on use this revision; documents already generated keep the revision they were made from.
    </FieldHelp>
  );
}

export function TemplatesAdmin() {
  const { data: me } = useMe();
  const canEdit = hasRole(me ?? undefined, 'admin');
  const q = useQuery({ queryKey: ['templates'], queryFn: () => api.get<T[]>('/admin/templates') });
  const [key, setKey] = useState<string | null>(null);
  const [body, setBody] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const qc = useQueryClient();
  const current = q.data?.find((t) => t.key === key) ?? null;
  useEffect(() => { if (current) setBody(current.body); }, [current?.key, current?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  // the text box grows with its text, so the whole template reads without a scroll box inside the page
  const box = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + (el.offsetHeight - el.clientHeight)}px`;
  }, [body, current?.key]);

  async function save() {
    if (!current) return;
    setMsg(null);
    try {
      const t = await api.put<T>(`/admin/templates/${current.key}`, { body });
      setMsg({ tone: 'success', text: `Saved as revision ${t.version}. Documents generated from now on use this revision; documents already generated keep the revision they were made from.` });
      await qc.invalidateQueries({ queryKey: ['templates'] });
    } catch (e) {
      setMsg({ tone: 'danger', text: fieldErrors(e).body ?? errorMessage(e) });
    }
  }

  return (
    <div className="page">
      <PageHeader title="Templates" subtitle="The text of the initiation package, notices and emails. Merge fields in {{ double braces }} are filled from the client and engagement." />
      <div className="split">
        <section className="card side" style={{ flex: '1 1 280px' }} aria-label="Templates">
          {q.isLoading ? <Loading /> : (
            <div className="card-body stack-sm">
              {q.data?.map((t) => (
                <button key={t.key} type="button" className="btn btn-block" aria-pressed={key === t.key} style={{ justifyContent: 'flex-start', height: 'auto', whiteSpace: 'normal', fontWeight: key === t.key ? 600 : 400, borderColor: key === t.key ? 'var(--navy)' : undefined }} onClick={() => { setKey(t.key); setMsg(null); }}>
                  <span style={{ textAlign: 'left' }}>{t.package_item ? `${t.package_item}. ` : ''}{t.name}</span>
                </button>
              ))}
            </div>
          )}
        </section>
        <div className="main">
          {!current ? <Card><EmptyState>Choose a template to view{canEdit ? ' or edit' : ''} it.</EmptyState></Card> : (
            <Card title={<h2 className="row" style={{ gap: 4, alignItems: 'center' }}>{current.name}<Revision t={current} /></h2>} actions={canEdit ? <Button variant="primary" onClick={save} disabled={body === current.body}>Save as revision {current.version + 1}</Button> : undefined}>
              <div className="stack">
                {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
                {current.requires_action && <p className="small muted">Client action: {current.requires_action}</p>}
                <label className="sr-only" htmlFor="tpl-body">Template text</label>
                <textarea id="tpl-body" ref={box} className="textarea" readOnly={!canEdit} value={body} onChange={(e) => setBody(e.target.value)} style={{ minHeight: 200, overflow: 'hidden', resize: 'none', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 13 }} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
