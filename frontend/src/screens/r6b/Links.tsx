import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { can, useMe } from '@/api/auth';
import type { EuClientView, Workspaces } from '@/api/r6b';
import { Badge, Card } from '@/components/ui';

/** On the engagement (Futran client page): the Copilot readiness and EU AI Act workspaces this engagement opens, those
 *  on the client's other engagements (the page shows only the latest), and the EU AI Act view of the client's systems
 *  with EU geography. Renders nothing when none applies. */
export function DeliveryWorkspaceLinks({ engagementId, clientId }: { engagementId: string; clientId: string }) {
  const q = useQuery({ queryKey: ['workspaces', engagementId], queryFn: () => api.get<Workspaces>(`/e/${engagementId}/workspaces`), retry: false });
  const w = q.data;
  const elsewhere = w?.elsewhere ?? [];
  if (!w || (!w.copilot && !w.eu_ai_act && !w.eu_systems && elsewhere.length === 0)) return null;
  return (
    <Card title="Delivery workspaces">
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {w.copilot && <li><Link to={`/e/${engagementId}/copilot`}>Copilot readiness</Link>: licences and usage, site risk list, rollout waves and controls</li>}
        {w.eu_ai_act && <li><Link to={`/e/${engagementId}/eu-ai-act`}>EU AI Act conformity</Link>: role, classification, legal sign-off, articles and deadlines</li>}
        {elsewhere.map((o) => (
          <li key={o.engagement_id}>
            {o.workspace === 'copilot' ? <Link to={`/e/${o.engagement_id}/copilot`}>Copilot readiness</Link> : <Link to={`/e/${o.engagement_id}/eu-ai-act`}>EU AI Act conformity</Link>}
            : {o.name}{o.audit_ref ? ` · ${o.audit_ref}` : ''}
          </li>
        ))}
        {!w.eu_ai_act && !elsewhere.some((o) => o.workspace === 'eu_ai_act') && w.eu_systems > 0 && <li><Link to={`/clients/${clientId}/eu-ai-act`}>EU AI Act conformity</Link>: {w.eu_systems} AI system{w.eu_systems > 1 ? 's' : ''} with EU geography</li>}
      </ul>
    </Card>
  );
}

/** On the client's register record: the system's EU AI Act status, with the classification once the legal reviewer
 *  has signed it off. Shown when the system has EU geography or has been assessed. */
export function RegisterEuCard({ systemId }: { systemId: string }) {
  const { data: me } = useMe();
  const allowed = !!me && can(me, 'view_eu_ai_act');
  const q = useQuery({ queryKey: ['eu-client', systemId], queryFn: () => api.get<EuClientView>(`/eu-ai-act/systems/${systemId}`), enabled: allowed, retry: false });
  const v = q.data;
  if (!allowed || !v || (!v.eu_exposure && v.status_text === 'Not assessed yet')) return null;
  return (
    <Card title="EU AI Act" actions={v.classification ? <Badge tone="success">Signed off</Badge> : undefined}>
      <dl className="kv-stacked">
        {v.eu_exposure && <div><dt>EU exposure</dt><dd>{v.eu_exposure}</dd></div>}
        {v.role_label && <div><dt>Role</dt><dd>{v.role_label}</dd></div>}
        {v.classification_label && <div><dt>Classification</dt><dd>{v.classification_label}</dd></div>}
        {v.deadline && <div><dt>Deadline</dt><dd>{v.deadline.label}</dd></div>}
      </dl>
      <p className="small muted" style={{ marginBottom: 0 }}>{v.status_text}</p>
    </Card>
  );
}
