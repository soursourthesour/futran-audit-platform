import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, fmtDateTime } from '@/components/ui';

type T = { key: string; name: string; type: string; version: number; body: string; package_item: number | null; requires_action: string | null; format: string; updated_at: string };

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

  async function save() {
    if (!current) return;
    setMsg(null);
    try {
      const t = await api.put<T>(`/admin/templates/${current.key}`, { body });
      setMsg({ tone: 'success', text: `Saved as version ${t.version}. Documents generated from now on use this version; documents already generated keep the version they were made from.` });
      await qc.invalidateQueries({ queryKey: ['templates'] });
    } catch (e) {
      setMsg({ tone: 'danger', text: fieldErrors(e).body ?? errorMessage(e) });
    }
  }

  return (
    <div className="page">
      <PageHeader title="Templates" subtitle="The text of the initiation package, notices and emails. Merge fields in {{ double braces }} are filled from the client and engagement." />
      <div className="split">
        <section className="card side" style={{ flex: '1 1 280px' }}>
          {q.isLoading ? <Loading /> : (
            <div className="card-body stack-sm">
              {q.data?.map((t) => (
                <button key={t.key} type="button" className="btn btn-block" aria-pressed={key === t.key} style={{ justifyContent: 'space-between', fontWeight: key === t.key ? 600 : 400, borderColor: key === t.key ? 'var(--navy)' : undefined }} onClick={() => { setKey(t.key); setMsg(null); }}>
                  <span style={{ textAlign: 'left' }}>{t.package_item ? `${t.package_item}. ` : ''}{t.name}</span>
                  <Badge tone="muted">v{t.version}</Badge>
                </button>
              ))}
            </div>
          )}
        </section>
        <div className="main">
          {!current ? <Card><EmptyState>Choose a template to view{canEdit ? ' or edit' : ''} it.</EmptyState></Card> : (
            <Card title={current.name} actions={canEdit ? <Button variant="primary" onClick={save} disabled={body === current.body}>Save as version {current.version + 1}</Button> : undefined}>
              <div className="stack">
                {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
                <p className="small muted">Version {current.version} · last saved {fmtDateTime(current.updated_at)}{current.requires_action ? ` · client action: ${current.requires_action}` : ''}</p>
                <label className="sr-only" htmlFor="tpl-body">Template text</label>
                <textarea id="tpl-body" className="textarea" readOnly={!canEdit} value={body} onChange={(e) => setBody(e.target.value)} style={{ minHeight: 520, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 13 }} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
