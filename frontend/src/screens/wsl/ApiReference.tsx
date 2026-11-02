import { useQuery } from '@tanstack/react-query';
import { Alert, Badge, Card, Loading, PageHeader } from '@/components/ui';
import '@/styles/wsl.css';

type Op = { summary?: string; description?: string; tags?: string[]; 'x-required-scope'?: string; parameters?: { name: string; in: string; required?: boolean }[] };
type Spec = { info: { title: string; version: string; description?: string }; paths: Record<string, Record<string, Op>> };

const BASE = '/api/public/v1';
const METHOD_TONE: Record<string, 'navy' | 'success' | 'warn' | 'danger' | 'default'> = { get: 'navy', post: 'success', patch: 'warn', put: 'warn', delete: 'danger' };

/** API reference `/admin/api/reference` (spec §21 F17): the public API's own OpenAPI document, read from
 *  /api/public/v1/openapi.json. It lists the public endpoints only. */
export function ApiReference() {
  const q = useQuery({ queryKey: ['public-openapi'], queryFn: async () => { const r = await fetch(`${BASE}/openapi.json`); if (!r.ok) throw new Error('The API reference could not be loaded.'); return (await r.json()) as Spec; } });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{q.error instanceof Error ? q.error.message : 'The API reference could not be loaded.'}</Alert></div>;
  const spec = q.data;
  const groups = new Map<string, { method: string; path: string; op: Op }[]>();
  for (const [path, ops] of Object.entries(spec.paths)) {
    for (const [method, op] of Object.entries(ops)) {
      const tag = op.tags?.[0] ?? 'other';
      groups.set(tag, [...(groups.get(tag) ?? []), { method, path, op }]);
    }
  }
  return (
    <div className="page">
      <PageHeader title="API reference" subtitle={`${spec.info.title}, version ${spec.info.version}. Base address: ${BASE}`}
        crumbs={[{ to: '/admin/api', label: 'API and webhooks' }, { label: 'API reference' }]} />
      {spec.info.description && <Alert tone="info">{spec.info.description}</Alert>}
      <p className="small"><a href={`${BASE}/openapi.json`} download="futran-public-api.json">Download the OpenAPI document</a> to import into your integration tool.</p>
      {[...groups.entries()].map(([tag, ops]) => (
        <Card key={tag} title={tag[0].toUpperCase() + tag.slice(1)}>
          <ul className="list-rows" style={{ margin: 0 }}>
            {ops.map(({ method, path, op }) => (
              <li key={method + path} style={{ display: 'block' }}>
                <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Badge tone={METHOD_TONE[method] ?? 'default'}>{method.toUpperCase()}</Badge>
                  <code style={{ overflowWrap: 'anywhere' }}>{BASE}{path}</code>
                  {op['x-required-scope'] && <span className="small muted">scope <code>{op['x-required-scope']}</code></span>}
                </div>
                {op.summary && <div style={{ marginTop: 4 }}><strong>{op.summary}</strong></div>}
                {op.description && <p className="small muted" style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{op.description}</p>}
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
