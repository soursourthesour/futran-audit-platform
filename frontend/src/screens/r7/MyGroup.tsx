import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Dialog, EmptyState, Loading, PageHeader, fmtDate } from '@/components/ui';
import { hierarchyApi, type MyGroup as Group } from '@/api/r7';
import { RollupCounts } from '@/screens/r7/ClientEntities';
import '@/styles/r7.css';

/** G-04 client view (CAICO, phone width): the group this organization belongs to, the roll-up of subsidiaries that
 *  consent, and — for a subsidiary — its own consent to share counts with the parent. */
export function MyGroup() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['my-group'], queryFn: hierarchyApi.myGroup });
  const [confirm, setConfirm] = useState<'give' | 'revoke' | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const g = q.data;
  async function act(kind: 'give' | 'revoke') {
    setMsg(null);
    try {
      const out: Group = kind === 'give' ? await hierarchyApi.consent() : await hierarchyApi.revoke();
      qc.setQueryData(['my-group'], { ...out, can_give_consent: g.can_give_consent });
      setMsg({ tone: 'success', text: kind === 'give' ? 'Consent given. The parent now sees the counts below, nothing else.' : 'Consent withdrawn. The parent no longer sees your counts.' });
    } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setConfirm(null); }
  }
  const nothing = !g.parent && g.children.length === 0;
  return (
    <div className="page page-narrow">
      <PageHeader title="Group" subtitle={`${g.organization.name}${g.organization.relationship_label ? ` · ${g.organization.relationship_label}` : ''}`} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {nothing && <EmptyState>Your organization is not part of a group in the Futran Audit Platform. Futran sets up parents, subsidiaries and end-clients on request.</EmptyState>}
      {g.parent && (
        <Card title="Parent">
          <div className="stack-sm">
            <p style={{ margin: 0 }}><strong>{g.parent.name}</strong></p>
            {g.can_consent ? (
              <>
                <p className="small" style={{ margin: 0 }}>
                  Roll-up to the parent: {g.consent ? <><Badge tone="success">Shared</Badge> since {fmtDate(g.consent.given_at)}, given by {g.consent.given_by}.</> : <Badge tone="muted">Not shared</Badge>}
                </p>
                <p className="small muted" style={{ margin: 0 }}>
                  If you share, the parent sees counts and statuses only: how many AI systems you have by stage, how many are high risk or due a bias audit, and where your current audit stands. It never sees system names, answers, evidence or findings. Each view is logged in your audit log. You can stop sharing at any time.
                </p>
                {g.can_give_consent && (g.consent
                  ? <Button onClick={() => setConfirm('revoke')}>Stop sharing with {g.parent.name}</Button>
                  : <Button variant="primary" onClick={() => setConfirm('give')}>Share counts with {g.parent.name}</Button>)}
                {!g.can_give_consent && <p className="small muted" style={{ margin: 0 }}>Your Chief AI Compliance Officer decides whether to share.</p>}
              </>
            ) : <p className="small muted" style={{ margin: 0 }}>{g.parent.name} lists your organization as {g.organization.relationship_label?.toLowerCase()}. Nothing of your data is shared with it.</p>}
          </div>
        </Card>
      )}
      {g.children.length > 0 && (
        <Card title="Entities in your group">
          <ul className="r7-card-list">
            {g.children.map((c) => (
              <li key={c.id}>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <strong>{c.name}</strong>
                  <span className="small muted">{c.relationship_label}</span>
                </div>
                {c.relationship === 'subsidiary' && (c.rollup ? <RollupCounts r={c.rollup} /> : <p className="small muted" style={{ margin: '6px 0 0' }}>Roll-up not shared. Its Chief AI Compliance Officer decides whether to share counts with you.</p>)}
                {c.ll144 && <p className="small" style={{ margin: '6px 0 0' }}>{c.ll144.in_scope ? `LL144 in scope${c.ll144.roles_note ? ` · ${c.ll144.roles_note}` : ''}${c.ll144.own_public_summary ? ' · own public summary' : ''}` : `LL144 not in scope${c.ll144.roles_note ? ` · ${c.ll144.roles_note}` : ''}`}</p>}
              </li>
            ))}
          </ul>
          <p className="r7-note">Each entity is its own organization in the platform. You see a subsidiary's counts only while its Chief AI Compliance Officer shares them.</p>
        </Card>
      )}
      {confirm && g.parent && (
        <Dialog title={confirm === 'give' ? 'Share counts with the parent?' : 'Stop sharing?'} onClose={() => setConfirm(null)}>
          <div className="stack">
            <p style={{ margin: 0 }}>{confirm === 'give' ? `${g.parent.name} will see counts and statuses of your AI register and current audit. Nothing else.` : `${g.parent.name} will stop seeing your counts at once.`}</p>
            <div className="row"><Button variant="primary" onClick={() => act(confirm)}>{confirm === 'give' ? 'Share counts' : 'Stop sharing'}</Button><Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button></div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
