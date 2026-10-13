const STAGES = ['Onboarding', 'Setup', 'Discovery', 'Client review', 'Fieldwork', 'Futran QA', 'Response', 'Final report', 'Remediation'];

/** The nine engagement stages (spec §7), with the current one highlighted. */
export function StageTracker({ stage, status }: { stage: number; status: string }) {
  const closed = status === 'completed' || status === 'archived';
  const notStarted = status === 'draft' || status === 'pending_approval';
  return (
    <ol className="stages" aria-label="Engagement stages" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {STAGES.map((name, i) => {
        const n = i + 1;
        const state = closed || n < stage ? 'done' : !notStarted && n === stage ? 'current' : '';
        return (
          <li key={name} className={`stage ${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            {n} · {name}
            {state === 'current' && <div className="small">Current</div>}
          </li>
        );
      })}
    </ol>
  );
}
