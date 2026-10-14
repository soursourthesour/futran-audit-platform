import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, Progress } from '@/components/ui';
import { QuestionCard, type FileRef, type SaveBody } from '@/components/QuestionCard';
import type { Assessment } from '@/screens/futran/SystemAssessment';

type MySystems = { systems: { id: string; reference_id: string; name: string; status: string; answered: number; applicable: number; pct: number }[]; engagement: { id: string; audit_ref: string; locked: boolean; can_answer_governance_questions: boolean } | null };
const STATUS: Record<string, string> = { not_started: 'Not started', client_prefill: 'In progress', in_review: 'With the auditor', scored: 'With the auditor', locked: 'Locked' };

/** Client list of AI systems to describe before fieldwork (pre-audit questionnaire). */
export function SystemsPrefillList() {
  const q = useQuery({ queryKey: ['me-systems'], queryFn: () => api.get<MySystems>('/me/systems') });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><Alert tone="danger">{errorMessage(q.error)}</Alert></div>;
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="AI systems" subtitle="Describe each AI system in scope before fieldwork. The auditor checks your answers in interviews, so answer as things are today, not as planned." />
      {d.engagement?.locked && <Alert tone="info">Your answers were locked when management representation was signed. Ask the auditor if something must change.</Alert>}
      <Card>
        {d.systems.length === 0 ? <EmptyState>No AI systems are assigned to you yet.</EmptyState> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>System</th><th>Status</th><th>Your progress</th></tr></thead>
            <tbody>{d.systems.map((s) => (
              <tr key={s.id}>
                <td><Link to={`/systems/${s.id}`}><strong>{s.name}</strong></Link><div className="small muted">{s.reference_id}</div></td>
                <td><Badge tone={s.status === 'not_started' ? 'muted' : 'navy'}>{STATUS[s.status] ?? s.status}</Badge></td>
                <td style={{ minWidth: 200 }}><Progress value={s.pct} label={`${s.answered} of ${s.applicable} answered`} /></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {d.engagement?.can_answer_governance_questions && <p className="small" style={{ marginBottom: 0 }}><Link to="/systems/governance">Governance and accountability questions (§4)</Link> — answered once for the whole organization.</p>}
      </Card>
    </div>
  );
}

/** The client's pre-fill of one system (or the §4 engagement questions). Shows only the client's own answers. */
export function SystemPrefill() {
  const { systemId = '' } = useParams();
  const { data: me } = useMe();
  const engagementLevel = systemId === 'governance';
  const base = engagementLevel ? `/clients/${me?.organization.id}` : `/systems/${systemId}`;
  const key = ['prefill', base];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Assessment>(`${base}/assessment`), enabled: !engagementLevel || !!me });
  const [section, setSection] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading || !q.data) return <div className="page">{q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />}</div>;
  const d = q.data;
  const current = section ?? d.sections[0]?.code;
  const idx = d.sections.findIndex((x) => x.code === current);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: key }), qc.invalidateQueries({ queryKey: ['me-systems'] })]);
  const save = (code: string) => async (body: SaveBody) => { await api.put(`${base}/responses/${code}`, body); await refresh(); };
  const upload = engagementLevel ? undefined : async (file: File) => { const form = new FormData(); form.append('file', file); return api.upload<FileRef>(`${base}/evidence`, form); };
  async function submit() {
    setMsg(null);
    try { await api.post(`${base}/prefill/submit`); await refresh(); setMsg({ tone: 'success', text: 'Sent to the auditor. You can still correct answers until management representation is signed.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const sys = d.target.system;
  return (
    <div className="page">
      <PageHeader title={sys ? sys.name : 'Governance and accountability'} crumbs={[{ to: '/systems', label: 'AI systems' }, { label: sys ? sys.reference_id : '§4' }]}
        subtitle="Answer what is true today. If something is planned but not done yet, choose “Planned → not yet in place” and say when. Use “Not applicable” only with a reason."
        actions={<span className="small muted">{d.completion.answered}/{d.completion.applicable} answered</span>} />
      {d.locked && <Alert tone="info">Your answers are locked. Ask the auditor if something must change.</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="assess" style={{ marginTop: 16 }}>
        <nav className="assess-nav" aria-label="Sections">
          {d.sections.map((x) => <button key={x.code} type="button" aria-current={x.code === current} onClick={() => setSection(x.code)}><span>§{x.code} {x.title}</span><span className="count">{x.answered}/{x.applicable}</span></button>)}
        </nav>
        <div>
          {d.questions.filter((x) => x.sub_section === current).map((x) => (
            <QuestionCard key={x.id} q={x} futran={false} locked={d.locked} evidenceFiles={[]} drafts={[]} onSave={save(x.code)} onUpload={upload} />
          ))}
          <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
            {idx >= 0 && idx < d.sections.length - 1 ? <Button variant="primary" onClick={() => { setSection(d.sections[idx + 1].code); window.scrollTo(0, 0); }}>Next: §{d.sections[idx + 1].code}</Button>
              : sys && !d.locked && <Button variant="primary" onClick={submit}>Send to the auditor</Button>}
          </div>
        </div>
      </div>
    </div>
  );
}
