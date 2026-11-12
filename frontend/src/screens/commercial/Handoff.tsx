import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { money, useHandoff, type Handoff as H } from '@/api/commercial';
import { Alert, Badge, Button, Card, Loading, PageHeader, SelectField, TextArea, fmtDateTime } from '@/components/ui';
import './commercial.css';

const TONE: Record<string, 'success' | 'warn' | 'muted' | 'navy'> = {
  Created: 'success', Updated: 'success', Approved: 'success', 'Awaiting Chief Auditor': 'warn', 'Submitted to Chief Auditor': 'navy', 'Not needed': 'muted', 'Not created': 'warn',
};

/** SM-13 Won — hand off to delivery. The records the accepted proposal created, each with its status and link, and the
 *  delivery team with the Chief Auditor's independence confirmation. Nothing here is sent to the client. */
export function Handoff() {
  const { oppId = '' } = useParams();
  const q = useHandoff(oppId);
  const qc = useQueryClient();
  const [owner, setOwner] = useState<string | null>(null);
  const [team, setTeam] = useState<string[] | null>(null);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) {
    const missing = (q.error as { status?: number } | null)?.status === 404;
    const finish = async () => {
      setBusy(true); setMsg(null);
      try { qc.setQueryData(['handoff', oppId], await api.post<H>(`/sales/opportunities/${oppId}/handoff`)); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
    };
    return (
      <div className="page commercial">
        <PageHeader crumbs={[{ to: '/sales/opportunities', label: 'Opportunities' }, { to: `/sales/opportunities/${oppId}`, label: 'Opportunity' }, { label: 'Hand off' }]} title="Won — hand off to delivery" />
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        {missing ? (
          <Card>
            <div className="stack">
              <p style={{ margin: 0 }}>The hand-off records for this opportunity have not been created yet. If the client accepted a proposal and the automatic hand-off did not finish, finish it here. Nothing is sent to the client.</p>
              <div><Button variant="primary" disabled={busy} onClick={finish}>Finish the hand-off</Button></div>
            </div>
          </Card>
        ) : <Alert tone="danger">{errorMessage(q.error)}</Alert>}
      </div>
    );
  }
  const h = q.data;
  const chosenTeam = team ?? h.team.separate_team.map((p) => p.id);
  const run = async (fn: () => Promise<H>, ok: string) => {
    setBusy(true); setMsg(null);
    try { qc.setQueryData(['handoff', oppId], await fn()); setMsg({ tone: 'success', text: ok }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); } finally { setBusy(false); }
  };
  const a = h.accepted_by;
  const blocked = h.needs_separate_team.length > 0 && !h.independence_confirmed_by;
  return (
    <div className="page commercial">
      <PageHeader crumbs={[{ to: '/sales/opportunities', label: 'Opportunities' }, { to: `/sales/opportunities/${oppId}`, label: h.client_name }, { label: 'Hand off' }]}
        title="Won — hand off to delivery"
        subtitle={`${h.client_name}${a ? ` · Proposal v${a.version} accepted by ${a.name ?? 'the client'}${a.title ? `, ${a.title}` : ''} · ${fmtDateTime(a.at)}${a.po_number ? ` · PO ${a.po_number}` : ''}` : ''}`}
        actions={<span className="pill-won">Won · {money(h.year1_value)} year 1</span>} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <Card title="Records created">
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Record</th><th>Details</th><th>Status</th><th>Next owner</th></tr></thead>
          <tbody>
            {h.items.map((it, i) => (
              <tr key={i}>
                <td>{it.link ? <Link to={it.link}>{it.label}</Link> : it.label}</td>
                <td className="small">{it.details}</td>
                <td><Badge tone={TONE[it.status] ?? 'default'}>{it.status}</Badge></td>
                <td className="small">{it.next_owner ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>
      <Card title="Delivery team and independence" actions={h.status === 'confirmed' ? <Badge tone="success">Confirmed</Badge> : undefined}>
        <div className="stack">
          <dl className="kv">
            <dt>Audit lead</dt><dd>Chief Auditor assigns on the engagement draft</dd>
            <dt>Account owner after handoff</dt>
            <dd>{h.can_confirm ? (
              <SelectField label="Account owner after handoff" value={owner ?? h.team.account_owner_id ?? ''} onChange={(e) => setOwner(e.target.value)}
                options={h.staff.map((s) => ({ value: s.id, label: s.name }))} />
            ) : (h.team.account_owner_name ?? '—')}</dd>
            {h.needs_separate_team.length > 0 && <>
              <dt>Separate delivery team</dt>
              <dd>
                {h.independence_confirmed_by
                  ? <>{h.team.separate_team.map((p) => p.name).join(', ') || '—'} <span className="muted small">· confirmed by {h.independence_confirmed_by}</span></>
                  : h.can_confirm_independence ? (
                    <fieldset className="team-pick">
                      <legend className="small">People who deliver {h.needs_separate_team.join(', ')} (kept off this client's audit team)</legend>
                      {h.staff.map((s) => (
                        <label key={s.id} className="small"><input type="checkbox" checked={chosenTeam.includes(s.id)}
                          onChange={(e) => setTeam(e.target.checked ? [...chosenTeam, s.id] : chosenTeam.filter((x) => x !== s.id))} /> {s.name}</label>
                      ))}
                    </fieldset>
                  ) : <span className="muted">Waiting for the Chief Auditor</span>}
              </dd>
            </>}
          </dl>
          {h.needs_separate_team.length > 0 && (
            <p className="small">{h.needs_separate_team.join(', ')} {h.needs_separate_team.length === 1 ? 'is' : 'are'} delivered by a separate team: the people named here are blocked from this client's audit team (rules I-2 and I-3).</p>
          )}
          {h.can_confirm_independence && !h.independence_confirmed_by && (
            <>
              <TextArea label="Note (optional)" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              <div><Button disabled={busy} onClick={() => run(() => api.post<H>(`/sales/opportunities/${oppId}/handoff/independence`, { separate_team_user_ids: chosenTeam, note }), 'Separate delivery team confirmed.')}>
                Confirm separate team</Button></div>
            </>
          )}
          <Alert tone="info">Nothing is sent to the client from this screen; the initiation package still needs Chief Auditor approval.</Alert>
          {h.can_confirm && (
            <div className="row">
              <Button variant="primary" disabled={busy || blocked} onClick={() => run(() => api.post<H>(`/sales/opportunities/${oppId}/handoff/confirm`, { account_owner_id: owner ?? h.team.account_owner_id }), 'Hand-off confirmed.')}>
                Confirm handoff</Button>
              {blocked && <span className="small muted">The Chief Auditor confirms the separate team first.</span>}
            </div>
          )}
          {h.status === 'confirmed' && <p className="small muted" style={{ margin: 0 }}>Confirmed by {h.confirmed_by} · {fmtDateTime(h.confirmed_at)}</p>}
          {h.can_view_plan && <p className="small" style={{ margin: 0 }}><Link to={`/staff/clients/${h.client_id}/plan`}>Plan, entitlements and usage</Link></p>}
        </div>
      </Card>
    </div>
  );
}
