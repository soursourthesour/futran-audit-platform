import '@/styles/staff-forms.css';

export const STAGES = ['Onboarding', 'Setup', 'Discovery', 'Client review', 'Fieldwork', 'Futran QA', 'Response', 'Final report', 'Remediation'];

/** The nine engagement stages (spec §7), with the current one highlighted. With `onOpen`, each stage is a button
 *  that opens its detail. */
export function StageTracker({ stage, status, onOpen }: { stage: number; status: string; onOpen?: (n: number) => void }) {
  const closed = status === 'completed' || status === 'archived';
  const notStarted = status === 'draft' || status === 'pending_approval';
  return (
    <ol className="stages" aria-label="Engagement stages" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {STAGES.map((name, i) => {
        const n = i + 1;
        const state = closed || n < stage ? 'done' : !notStarted && n === stage ? 'current' : '';
        const word = state === 'done' ? 'complete' : state === 'current' ? 'current stage' : 'not started';
        const label = (
          <>
            <span className="stage-name">{n} · {name}</span>
            {state === 'current' && <div className="small">Current</div>}
          </>
        );
        return (
          <li key={name} className={`stage ${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            {onOpen ? <button type="button" className="stage-btn" aria-label={`Stage ${n}, ${name}: ${word}. Show details`} onClick={() => onOpen(n)}>{label}</button> : label}
          </li>
        );
      })}
    </ol>
  );
}
