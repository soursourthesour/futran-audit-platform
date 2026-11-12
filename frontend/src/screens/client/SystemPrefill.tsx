import { Fragment, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { Alert, Button, Loading, PageHeader } from '@/components/ui';
import { QuestionCard, type FileRef, type SaveBody } from '@/components/QuestionCard';
import { ExplainQuestion } from '@/screens/ai/Explain';
import { useAISwitch } from '@/api/ai';
import type { Assessment } from '@/screens/futran/SystemAssessment';

/** The client's pre-fill of one system (or the §4 engagement questions). Shows only the client's own answers. */
export function SystemPrefill() {
  const { systemId = '' } = useParams();
  const { data: me } = useMe();
  const engagementLevel = systemId === 'governance';
  const base = engagementLevel ? `/clients/${me?.organization.id}` : `/systems/${systemId}`;
  const key = ['prefill', base];
  const qc = useQueryClient();
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Assessment>(`${base}/assessment`), enabled: !engagementLevel || !!me });
  const aiOn = !!useAISwitch(q.data?.target.engagement_id).data?.enabled;  // "Explain this question" only when AI is on for the engagement
  const [section, setSection] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  if (q.isLoading || !q.data) return <div className="page">{q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />}</div>;
  const d = q.data;
  const current = section ?? d.sections[0]?.code;
  const idx = d.sections.findIndex((x) => x.code === current);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: key }), qc.invalidateQueries({ queryKey: ['me-systems'] })]);
  const save = (code: string) => async (body: SaveBody) => { await api.put(`${base}/responses/${code}`, body); await refresh(); };
  const thread = (code: string) => async () => (await api.post<{ id: string }>(`${base}/responses/${code}/thread`)).id;
  const upload = engagementLevel ? undefined : async (file: File) => { const form = new FormData(); form.append('file', file); return api.upload<FileRef>(`${base}/evidence`, form); };
  async function submit() {
    setMsg(null);
    try { await api.post(`${base}/prefill/submit`); await refresh(); setMsg({ tone: 'success', text: 'Sent to the auditor. You can still correct answers until management representation is signed.' }); } catch (e) { setMsg({ tone: 'danger', text: errorMessage(e) }); }
  }
  const sys = d.target.system;
  return (
    <div className="page">
      <PageHeader title={sys ? sys.name : 'Governance and accountability'} crumbs={[{ to: '/register?audit=yes', label: 'AI systems' }, { label: sys ? sys.reference_id : '§4' }]}
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
            <Fragment key={x.id}>
              <QuestionCard q={x} futran={false} locked={d.locked} evidenceFiles={[]} drafts={[]} onSave={save(x.code)} onUpload={upload} onThread={thread(x.code)} />
              {aiOn && <ExplainQuestion base={base} code={x.code} />}
            </Fragment>
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
