import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { hasRole, useMe } from '@/api/auth';
import { Alert, Button, Card, Checkbox, FieldGroup, TextField } from '@/components/ui';
import { governanceSetupHelp as H } from '@/help/fieldwork';
import { GovernanceView, useGovernance } from '@/screens/client/Governance';

/** Futran view of a client's governance request. The Chief Auditor chooses the items until the client starts answering. */
export function GovernanceRequestSetup() {
  const { clientId = '' } = useParams();
  const { data: me } = useMe();
  const q = useGovernance(clientId);
  const isChief = hasRole(me ?? undefined, 'chief_auditor');
  const started = !!q.data && (q.data.request.status !== 'open' || q.data.items.some((i) => i.status !== 'unanswered'));
  return <GovernanceView clientId={clientId} canAnswer={false} crumbs={[{ to: '/audits', label: 'Audits' }, { to: `/clients/${clientId}`, label: 'Client' }, { label: 'AI governance structure' }]} header={isChief && q.data && !started ? <SetupCard clientId={clientId} /> : undefined} />;
}

function SetupCard({ clientId }: { clientId: string }) {
  const q = useGovernance(clientId);
  const qc = useQueryClient();
  const g = q.data!;
  const [codes, setCodes] = useState<string[]>(g.catalog.filter((c) => c.selected).map((c) => c.code));
  const [due, setDue] = useState(g.request.due_date ?? '');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  async function save() {
    try {
      await api.put(`/clients/${clientId}/governance/setup`, { codes, due_date: due || null });
      await qc.invalidateQueries({ queryKey: ['governance', clientId] });
      setMsg({ tone: 'success', text: 'Request updated. The client sees the new list straight away.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const groups = [['document', 'Governance documents'], ['security_document', 'Data and security documents'], ['role', 'Committees and named owners']] as const;
  return (
    <Card title="Choose what to request">
      <div className="stack">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <p className="small muted" style={{ margin: 0 }}>You can change the list until the client answers the first item.</p>
        {groups.map(([kind, label]) => (
          <FieldGroup key={kind} legend={label} help={H.items}>
            <div className="grid-2">
              {g.catalog.filter((c) => c.kind === kind).map((c) => (
                <Checkbox key={c.code} disabled={!c.available} label={`${c.title}${c.optional ? ' (optional)' : ''}${!c.available ? ' — EU operations only' : ''}`} checked={codes.includes(c.code)} onChange={(e) => setCodes(e.target.checked ? [...codes, c.code] : codes.filter((x) => x !== c.code))} />
              ))}
            </div>
          </FieldGroup>
        ))}
        <div style={{ maxWidth: 240 }}><TextField type="date" label="Answer by" help={H.dueDate} value={due} onChange={(e) => setDue(e.target.value)} /></div>
        <div><Button variant="primary" onClick={save}>Save request</Button></div>
      </div>
    </Card>
  );
}
