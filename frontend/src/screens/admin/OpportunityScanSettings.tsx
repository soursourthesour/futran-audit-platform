import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Card, Loading, SelectField, TextField, fmtDate, fmtDateTime } from '@/components/ui';
import './opportunityScan.css';

type Found = { id: string; client_name: string; trigger_label: string; service: string; why_now: string | null };
type Run = {
  id: string; trigger: 'scheduled' | 'manual'; status: 'running' | 'completed' | 'failed'; started_at: string; finished_at: string | null; since: string; by: string;
  counts: Partial<Record<'laws' | 'regulatory_updates' | 'renewals' | 'already_open' | 'held_back' | 'failed_clients', number>>;
  errors: { client: string | null; error: string }[]; found: Found[];
};
type Scan = { every_days: number | null; choices: number[]; min_days: number; max_days: number; last_run: Run | null; next_run_on: string | null; can_edit: boolean };

const KEY = ['admin-opportunity-scan'];

const HELP = {
  interval: (
    <>
      Off by default. When on, the daily jobs (06:00 New York time) run the scan once this many days have passed since the last completed scan.
      Each scan looks at what changed since the one before; the first looks back one interval. It opens an opportunity, once per client and reason, for
      laws added or changed in the law library that apply to the client, regulatory updates published and matched to the client, and renewal audits due
      within 90 days where no annual review has been started. Offers to current audit clients still need Chief Auditor approval, and Futran never sells the
      fix for a finding it raised.
    </>
  ),
  custom: 'Any whole number of days from 1 to 365.',
};

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

function summary(r: Run): string {
  const c = r.counts;
  const parts = [
    plural(c.laws ?? 0, 'from the law library', 'from the law library'),
    plural(c.regulatory_updates ?? 0, 'regulatory update', 'regulatory updates'),
    plural(c.renewals ?? 0, 'renewal audit', 'renewal audits'),
  ];
  if (c.already_open) parts.push(`${c.already_open} already open`);
  if (c.held_back) parts.push(`${c.held_back} held back by the independence rule`);
  return parts.join(' · ');
}

export function OpportunityScanSettings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => api.get<Scan>('/admin/opportunity-scan') });
  const [choice, setChoice] = useState('');
  const [custom, setCustom] = useState('');
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const s = q.data;

  useEffect(() => {
    if (!s) return;
    const n = s.every_days;
    if (n === null) { setChoice('off'); setCustom(''); }
    else if (s.choices.includes(n)) { setChoice(String(n)); setCustom(''); }
    else { setChoice('custom'); setCustom(String(n)); }
  }, [s?.every_days]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (every_days: number | null) => api.put<Scan>('/admin/opportunity-scan', { every_days }),
    onSuccess: (d) => { qc.setQueryData(KEY, d); setMsg({ tone: 'success', text: d.every_days ? `Saved. The scan runs every ${d.every_days} days.` : 'Saved. The scan is off.' }); },
    onError: (e) => setMsg({ tone: 'danger', text: errorMessage(e) }),
  });
  const run = useMutation({
    mutationFn: () => api.post<Scan>('/admin/opportunity-scan/run', {}),
    onSuccess: (d) => {
      qc.setQueryData(KEY, d);
      qc.invalidateQueries({ queryKey: ['opportunities'] });
      const n = d.last_run?.found.length ?? 0;
      setMsg({ tone: 'success', text: n ? `Scan finished: ${plural(n, 'new opportunity', 'new opportunities')}.` : 'Scan finished: nothing new.' });
    },
    onError: (e) => setMsg({ tone: 'danger', text: errorMessage(e) }),
  });

  if (q.isLoading || !s) return <Card title="Opportunity scan"><Loading /></Card>;

  const wanted: number | null | undefined = choice === 'off' ? null : choice === 'custom' ? (custom.trim() ? Number(custom) : undefined) : Number(choice);
  const customBad = choice === 'custom' && (wanted === undefined || !Number.isInteger(wanted) || (wanted as number) < s.min_days || (wanted as number) > s.max_days);
  const changed = wanted !== undefined && wanted !== s.every_days;
  const r = s.last_run;

  return (
    <Card title="Opportunity scan" actions={s.can_edit ? <Button onClick={() => { setMsg(null); run.mutate(); }} disabled={run.isPending}>{run.isPending ? 'Scanning…' : 'Run now'}</Button> : undefined}>
      <div className="opp-scan">
        <p className="small muted">Looks for new sales opportunities on a schedule and adds them to <Link to="/opportunities">Opportunities</Link> with the reason in "Why now". Off until you turn it on.</p>
        {msg && <Alert tone={msg.tone} role="status">{msg.text}</Alert>}
        {s.can_edit ? (
          <form className="opp-scan-form" onSubmit={(e) => { e.preventDefault(); if (!customBad && wanted !== undefined) { setMsg(null); save.mutate(wanted); } }}>
            <SelectField label="Look for new opportunities" help={HELP.interval} value={choice} onChange={(e) => setChoice(e.target.value)}
              options={[{ value: 'off', label: 'Off' }, ...s.choices.map((n) => ({ value: String(n), label: `Every ${n} days` })), { value: 'custom', label: 'Every … days (custom)' }]} />
            {choice === 'custom' && (
              <TextField label="Number of days" help={HELP.custom} type="number" inputMode="numeric" min={s.min_days} max={s.max_days} step={1} value={custom}
                onChange={(e) => setCustom(e.target.value)} error={custom.trim() && customBad ? `Enter a whole number from ${s.min_days} to ${s.max_days}.` : undefined} />
            )}
            <div className="opp-scan-actions"><Button type="submit" variant="primary" disabled={!changed || customBad || save.isPending}>Save</Button></div>
          </form>
        ) : (
          <p className="small">Look for new opportunities: <strong>{s.every_days ? `every ${s.every_days} days` : 'off'}</strong>. Only the Futran Admin changes this.</p>
        )}
        <dl className="kv">
          <dt>Last run</dt>
          <dd>
            {r ? (
              <>
                {fmtDateTime(r.started_at)} · {r.trigger === 'manual' ? `Run now by ${r.by}` : 'Scheduled'}{' '}
                {r.status === 'completed' ? <Badge tone="success">Completed</Badge> : r.status === 'failed' ? <Badge tone="danger">Failed</Badge> : <Badge tone="warn">Running</Badge>}
                <div className="small muted">Looked at changes since {fmtDateTime(r.since)}</div>
              </>
            ) : 'Not run yet'}
          </dd>
          <dt>Next run</dt>
          <dd>{s.next_run_on ? `${fmtDate(s.next_run_on)}, at the daily run` : 'Off'}</dd>
          <dt>Last run found</dt>
          <dd>
            {!r ? '—' : (
              <>
                <div>{summary(r)}</div>
                {r.errors.length > 0 && (
                  <Alert tone="warn">
                    {r.status === 'failed' ? 'The scan could not run. ' : `Not scanned: ${r.errors.map((x) => x.client).filter(Boolean).join(', ')}. `}
                    The next scan tries again; the server log has the details.
                  </Alert>
                )}
                {r.found.length > 0 && (
                  <ul className="opp-scan-found">
                    {r.found.map((f) => (
                      <li key={f.id}><strong>{f.client_name}</strong> · {f.trigger_label}: {f.service}{f.why_now && <div className="small muted">{f.why_now}</div>}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </dd>
        </dl>
      </div>
    </Card>
  );
}
