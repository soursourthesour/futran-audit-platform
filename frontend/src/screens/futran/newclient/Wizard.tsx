import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, type FieldError } from '@/api/client';
import { saveStep, useWizard, type Wizard as WizardData } from '@/api/clients';
import { Alert, Button, Card, Loading, PageHeader, fmtDateTime } from '@/components/ui';
import { StepCompany } from './StepCompany';
import { StepLocations } from './StepLocations';
import { StepScope } from './StepScope';
import { StepContacts } from './StepContacts';
import { StepPackage } from './StepPackage';

export const STEPS = [
  { key: 'company', label: 'Company' },
  { key: 'locations', label: 'Locations and laws' },
  { key: 'scope', label: 'Scope and team' },
  { key: 'contacts', label: 'Client contacts' },
  { key: 'submit', label: 'Review and submit' },
] as const;

type Ctx = {
  clientId: string;
  data: WizardData;
  editable: boolean;
  /** Field errors keyed like "company.legal_name". */
  errors: Record<string, string>;
  /** Queue an autosave of `payload` to `step` (debounced). */
  autosave: (step: string, payload: unknown) => void;
  flush: () => Promise<void>;
};
const WizardCtx = createContext<Ctx | null>(null);
export function useWizardCtx(): Ctx {
  const c = useContext(WizardCtx);
  if (!c) throw new Error('outside wizard');
  return c;
}

/** Keep a local copy of a step's form, autosaving every change. */
export function useStepForm<T>(step: string, initial: T): [T, (next: T) => void] {
  const { autosave } = useWizardCtx();
  const [value, setValue] = useState<T>(initial);
  const set = useCallback((next: T) => {
    setValue(next);
    autosave(step, next);
  }, [autosave, step]);
  return [value, set];
}

export function NewClientStart() {
  const nav = useNavigate();
  const started = useRef(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api.post<{ client_id: string }>('/clients').then((r) => nav(`/clients/${r.client_id}/setup/company`, { replace: true })).catch((e) => setErr(errorMessage(e)));
  }, [nav]);
  return <div className="page">{err ? <Alert tone="danger">{err}</Alert> : <Loading label="Starting a new client…" />}</div>;
}

export function NewClientWizard() {
  const { clientId = '', step = 'company' } = useParams();
  const w = useWizard(clientId);
  const nav = useNavigate();
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<{ saving: boolean; savedAt: string | null; error: string | null }>({ saving: false, savedAt: null, error: null });
  const pending = useRef<Map<string, unknown>>(new Map());
  const timer = useRef<number | null>(null);
  const inflight = useRef<Promise<void>>(Promise.resolve());
  const submitting = useRef(false);

  const flush = useCallback(async () => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    const batch = [...pending.current.entries()];
    pending.current.clear();
    if (!batch.length) return inflight.current;
    const run = inflight.current.then(async () => {
      setStatus((s) => ({ ...s, saving: true, error: null }));
      try {
        for (const [st, payload] of batch) {
          const r = await saveStep(clientId, st, payload);
          setErrors((prev) => {
            const next = Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith(`${st === 'requirements' ? 'locations.requirements' : st}.`)));
            for (const e of r.errors) next[e.field] = e.message;
            return next;
          });
          setStatus({ saving: false, savedAt: r.saved_at, error: null });
        }
        await qc.invalidateQueries({ queryKey: ['suggestions', clientId] });
      } catch (e) {
        setStatus({ saving: false, savedAt: null, error: errorMessage(e) });
      }
    });
    inflight.current = run;
    return run;
  }, [clientId, qc]);

  const autosave = useCallback((st: string, payload: unknown) => {
    pending.current.set(st, payload);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void flush(); }, 700);
  }, [flush]);

  useEffect(() => () => { void flush(); }, [flush]);

  if (w.isLoading) return <div className="page"><Loading /></div>;
  if (w.isError || !w.data) return <div className="page"><Alert tone="danger">{errorMessage(w.error)}</Alert></div>;
  if (!STEPS.some((s) => s.key === step)) return <Navigate to={`/clients/${clientId}/setup/company`} replace />;

  const data = w.data;
  const editable = data.engagement.status === 'draft';
  const idx = STEPS.findIndex((s) => s.key === step);
  const name = data.company.trading_name || data.company.legal_name;
  const go = async (to: string) => { await flush(); await qc.invalidateQueries({ queryKey: ['wizard', clientId] }); nav(to); };

  async function submit() {
    if (submitting.current) return;
    submitting.current = true;
    await flush();
    try {
      await api.post(`/clients/${clientId}/submit`);
      await qc.invalidateQueries();
      nav('/audits', { state: { flash: `${name ?? 'The client'} was sent to the Chief Auditor for approval.` } });
    } catch (e) {
      const errs = (e as { errors?: FieldError[] }).errors ?? [];
      setErrors(toMap(errs));
      setStatus((s) => ({ ...s, error: errorMessage(e) }));
    } finally {
      submitting.current = false;
    }
  }

  let body: ReactNode = null;
  if (step === 'company') body = <StepCompany />;
  else if (step === 'locations') body = <StepLocations />;
  else if (step === 'scope') body = <StepScope />;
  else if (step === 'contacts') body = <StepContacts />;
  else body = data.engagement.status === 'draft' ? <Review onSubmit={submit} /> : <StepPackage />;

  return (
    <WizardCtx.Provider value={{ clientId, data, editable, errors, autosave, flush }}>
      <div className="page">
        <PageHeader
          crumbs={[{ to: '/audits', label: 'Audits' }, { label: 'New client' }, ...(name ? [{ label: String(name) }] : [])]}
          title={name ? `New client: ${name}` : 'New client'}
          subtitle={<>Drafts save automatically. The Chief Auditor approves before anything is sent to the client. <span className="muted">· {data.engagement.audit_ref}</span></>}
        />
        <nav aria-label="Steps" className="pills" style={{ marginBottom: 16 }}>
          {STEPS.map((s, i) => (
            <Link key={s.key} to={`/clients/${clientId}/setup/${s.key}`} className="pill" aria-current={s.key === step ? 'step' : undefined} aria-selected={s.key === step} style={{ display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }} onClick={(e) => { e.preventDefault(); void go(`/clients/${clientId}/setup/${s.key}`); }}>
              {i + 1} · {s.key === 'submit' && !editable ? 'Initiation package' : s.label}{i < idx ? ' ✓' : ''}
            </Link>
          ))}
        </nav>
        {data.engagement.returned_comment && editable && <Alert tone="warn"><strong>Returned by the Chief Auditor:</strong> {data.engagement.returned_comment}</Alert>}
        {!editable && step !== 'submit' && <Alert tone="info">This engagement is with the Chief Auditor for approval, so it can't be edited. It can be changed if it is returned.</Alert>}
        <div className="stack" style={{ marginTop: 12 }}>
          {body}
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="small muted" role="status" aria-live="polite">
              {status.saving ? 'Saving…' : status.error ? <span style={{ color: 'var(--danger)' }}>{status.error}</span> : status.savedAt ? `Saved ${fmtDateTime(status.savedAt)}` : ''}
            </span>
            <div className="row">
              {idx > 0 && <Button onClick={() => go(`/clients/${clientId}/setup/${STEPS[idx - 1].key}`)}>Back</Button>}
              <Button onClick={() => go('/audits')}>Save draft and exit</Button>
              {idx < STEPS.length - 1 && <Button variant="primary" onClick={() => go(`/clients/${clientId}/setup/${STEPS[idx + 1].key}`)}>Next: {STEPS[idx + 1].label.toLowerCase()}</Button>}
            </div>
          </div>
        </div>
      </div>
    </WizardCtx.Provider>
  );
}

/** Field errors by field; repeated fields (several team problems) get "#n" keys so none are lost. */
function toMap(errs: FieldError[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of errs) {
    let k = e.field;
    for (let n = 2; k in out; n++) k = `${e.field}#${n}`;
    out[k] = e.message;
  }
  return out;
}

const STEP_OF: Record<string, string> = { company: 'company', locations: 'locations', scope: 'scope', contacts: 'contacts' };

function Review({ onSubmit }: { onSubmit: () => void }) {
  const { clientId, data, errors, editable } = useWizardCtx();
  const list = Object.entries(errors);
  const c = data.company;
  return (
    <Card title="Review and submit">
      <div className="stack">
        <p className="small muted">Submitting sends this engagement to the Chief Auditor. They review it, generate the initiation package and send it to the client. You can't edit it while it is waiting for approval.</p>
        <dl className="kv">
          <dt>Client</dt><dd>{c.legal_name ?? '—'}{c.client_ref ? ` · ${c.client_ref}` : ''}</dd>
          <dt>Sites</dt><dd>{data.locations.locations.map((l) => l.site_name).join(', ') || '—'}</dd>
          <dt>Laws and frameworks</dt><dd>{data.locations.requirements.length}</dd>
          <dt>Team</dt><dd>{(data.scope.people ?? []).map((p) => `${p.name} (${p.role_label})`).join(', ') || [...new Set(data.scope.team.map((t) => t.name))].join(', ') || '—'}</dd>
          <dt>CAICO</dt><dd>{data.contacts.caico?.name ?? '—'}</dd>
        </dl>
        {list.length > 0 && (
          <Alert tone="danger" role="alert">
            <strong>{list.length} {list.length === 1 ? 'item needs' : 'items need'} attention before you submit.</strong>
            <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
              {list.map(([field, msg]) => {
                const step = STEP_OF[field.split('.')[0]] ?? 'company';
                return <li key={field + msg}><Link to={`/clients/${clientId}/setup/${step}`}>{msg}</Link></li>;
              })}
            </ul>
          </Alert>
        )}
        <div><Button variant="primary" onClick={onSubmit} disabled={!editable}>Submit for approval</Button></div>
      </div>
    </Card>
  );
}
