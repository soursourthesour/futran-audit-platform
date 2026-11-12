import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { can, useMe, type Me } from '@/api/auth';
import { Badge, Card, Dialog, fmtDate } from '@/components/ui';
import '@/styles/staff-forms.css';
import './stage-timeline.css';

type TimelineStage = { number: number; name: string; state: 'done' | 'current' | 'upcoming'; summary: string; started_on: string | null; finished_on: string | null; target_on: string | null };
type Timeline = { engagement: { audit_ref: string; stage: number } | null; stages: TimelineStage[] };

/** The client screen where each stage is worked, first match wins. `requires` mirrors the menu entry for that screen in
 *  nav.ts, so a stage links only to a screen the person's menu offers (never a 403 page). Futran QA (6) has no client
 *  screen. */
const SCREENS: Record<number, { to: string; label: string; requires: string[] }[]> = {
  1: [{ to: '/start', label: 'Getting started', requires: ['view_initiation_checklist'] }],
  2: [{ to: '/people/departments', label: 'People', requires: ['manage_client_users'] }],
  3: [
    { to: '/attestation', label: 'Attestation', requires: ['view_attestation_aggregates', 'send_attestation'] },
    { to: '/governance', label: 'Governance', requires: ['view_governance'] },
    { to: '/inventory', label: 'AI inventory', requires: ['view_inventory'] },
    { to: '/my-attestation', label: 'My AI attestation', requires: ['complete_own_attestation'] },
  ],
  4: [{ to: '/review', label: 'Review', requires: ['sign_client_signoff', 'submit_use_case'] }],
  5: [
    { to: '/systems', label: 'AI systems', requires: ['prefill_system'] },
    { to: '/documents', label: 'Documents', requires: ['upload_requested_document'] },
  ],
  6: [],
  7: [{ to: '/responses', label: 'Responses', requires: ['respond_findings', 'approve_responses'] }],
  8: [{ to: '/report', label: 'Report', requires: ['view_scores'] }],
  9: [{ to: '/remediation', label: 'Remediation', requires: ['view_findings_responses'] }],
};

export function stageScreen(me: Me | null | undefined, n: number) {
  return me ? SCREENS[n]?.find((s) => can(me, ...s.requires)) ?? null : null;
}

const STATE_WORD = { done: 'Done', current: 'Current', upcoming: 'Upcoming' } as const;

function when(s: TimelineStage): string | null {
  if (s.state === 'done') return s.finished_on ? fmtDate(s.finished_on) : s.started_on ? `from ${fmtDate(s.started_on)}` : null;
  if (s.state === 'current') return s.started_on ? `since ${fmtDate(s.started_on)}` : s.target_on ? `target ${fmtDate(s.target_on)}` : null;
  return s.target_on ? `target ${fmtDate(s.target_on)}` : null;
}

/** The nine audit stages of the client's current engagement (10 Nov feedback U2), on every client home: done, current and
 *  upcoming with dates where known. Each stage opens the screen where it is worked or, when the person cannot open that
 *  screen, a short summary of the stage. Horizontal on wide screens, a vertical list on phones. */
export function StageTimeline() {
  const { data: me } = useMe();
  const q = useQuery({ queryKey: ['me', 'stages'], queryFn: () => api.get<Timeline>('/me/stages') });
  const [open, setOpen] = useState<TimelineStage | null>(null);
  if (q.isLoading || q.isError || !q.data) return null;  // the home's own content carries any error
  const d = q.data;
  return (
    <Card title="Audit timeline" className="stl-card" actions={d.engagement ? <span className="small muted">{d.engagement.audit_ref}</span> : undefined}>
      {!d.engagement ? <p className="small muted" style={{ margin: 0 }}>The audit stages appear here once Futran starts your audit.</p> : (
        <ol className="stl" aria-label="Audit stages">
          {d.stages.map((s) => {
            const screen = stageScreen(me, s.number);
            const date = when(s);
            const body = (
              <>
                <span className="tl-dot" aria-hidden="true">{s.state === 'done' ? '✓' : s.number}</span>
                <span className="tl-text">
                  <span className="tl-num">Stage {s.number}</span>
                  <span className="tl-name">{s.name}</span>
                  <span className="tl-when">{STATE_WORD[s.state]}{date ? ` · ${date}` : ''}</span>
                </span>
                <span className="sr-only">{screen ? `. Opens ${screen.label}` : '. Shows a summary'}</span>
              </>
            );
            const cur = s.state === 'current' ? 'step' as const : undefined;
            return (
              <li key={s.number} className={`tl-stage ${s.state}`}>
                {screen
                  ? <Link className="tl-target" to={screen.to} aria-current={cur}>{body}</Link>
                  : <button type="button" className="tl-target" aria-current={cur} onClick={() => setOpen(s)}>{body}</button>}
              </li>
            );
          })}
        </ol>
      )}
      {open && (
        <Dialog title={`Stage ${open.number} · ${open.name}`} onClose={() => setOpen(null)}>
          <div className="stack-sm">
            <div className="stage-meta">
              <Badge tone={open.state === 'done' ? 'success' : open.state === 'current' ? 'navy' : 'muted'}>{STATE_WORD[open.state]}</Badge>
              {open.started_on && <span>Started {fmtDate(open.started_on)}</span>}
              {open.finished_on && <span>Finished {fmtDate(open.finished_on)}</span>}
              {open.target_on && <span>Target {fmtDate(open.target_on)}</span>}
            </div>
            <p style={{ margin: 0 }}>{open.summary}</p>
            {open.number === 6 && <p className="small muted" style={{ margin: 0 }}>Nothing is needed from you in this stage.</p>}
          </div>
        </Dialog>
      )}
    </Card>
  );
}
