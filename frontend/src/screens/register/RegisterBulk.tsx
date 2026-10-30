import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, errorMessage, fieldErrors } from '@/api/client';
import { ROLE_STATUSES, STAGES, type RegSystem } from '@/api/register';
import { Alert, Button, Dialog, FieldGroup, SelectField, TextArea, TextField } from '@/components/ui';
import { bulkHelp as H } from '@/help/register';
import { LawSearch } from './LawSearch';

export type BulkMode = 'all' | 'roles' | 'stage' | 'laws' | 'bias';
type CatalogRole = { id: string; code: string; number: number; name: string; level: 'company' | 'system' | 'agent'; main_sources: string | null };
type RoleEntry = { role_id: string; status: string; user_id: string; external_party: string; target_date: string; reason: string; on_conflict: 'keep' | 'replace' | 'add' };
type Preview = { preview: boolean; change_count: number; systems_changed: number; systems: { id: string; name: string; changes: number; conflicts: { system: string; role: string; role_id: string; current: string }[] }[] };

const KEEP = '';
const TITLES: Record<BulkMode, string> = { all: 'Edit', roles: 'Assign a role on', stage: 'Change the stage of', laws: 'Add or remove a law on', bias: 'Request a bias test for' };

export function BulkEdit({ mode, rows, people, departments, onClose, onDone }: {
  mode: BulkMode; rows: RegSystem[]; people: { id: string; name: string; job_title: string | null }[]; departments: { id: string; name: string; can_edit: boolean }[];
  onClose: () => void; onDone: (message: string) => void;
}) {
  const show = (m: BulkMode) => mode === 'all' || mode === m;
  const cat = useQuery({ queryKey: ['register', 'role-catalog'], queryFn: () => api.get<CatalogRole[]>('/register/role-catalog'), enabled: show('roles') });
  const [changes, setChanges] = useState({ department_id: KEEP, stage: KEEP, owner_user_id: KEEP, bias_next_due: '' });
  const [addLaws, setAddLaws] = useState<{ id: string; name: string }[]>([]);
  const [removeLaw, setRemoveLaw] = useState('');
  const [roles, setRoles] = useState<RoleEntry[]>(mode === 'roles' ? [blankRole()] : []);
  const [biasDue, setBiasDue] = useState('');
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const currentLaws = useMemo(() => {
    const m = new Map<string, string>();
    rows.forEach((r) => r.laws.filter((l) => l.status === 'active').forEach((l) => m.set(l.regulation_id, l.short_name)));
    return [...m].map(([value, label]) => ({ value, label }));
  }, [rows]);
  const personOpts = people.map((p) => ({ value: p.id, label: p.job_title ? `${p.name} · ${p.job_title}` : p.name }));
  const roleOpts = (cat.data ?? []).filter((r) => r.level !== 'company').map((r) => ({ value: r.id, label: `${r.name}${r.level === 'agent' ? ' (agents only)' : ''}` }));

  const body = useMemo(() => {
    const c: Record<string, string> = {};
    if (changes.department_id) c.department_id = changes.department_id;
    if (changes.stage) c.stage = changes.stage;
    if (changes.owner_user_id) c.owner_user_id = changes.owner_user_id;
    if (changes.bias_next_due) c.bias_next_due = changes.bias_next_due;
    const rs = roles.filter((r) => r.role_id && r.status).map((r) => ({
      role_id: r.role_id, status: r.status, on_conflict: r.on_conflict,
      ...(r.status === 'assigned' ? { user_id: r.user_id } : {}), ...(r.status === 'external' ? { external_party: r.external_party } : {}),
      ...(r.status === 'pending_committee' ? { target_date: r.target_date } : {}), ...(r.status === 'not_applicable' ? { reason: r.reason } : {}),
    }));
    return {
      system_ids: rows.map((r) => r.id), changes: c, add_regulation_ids: addLaws.map((l) => l.id), remove_regulation_ids: removeLaw ? [removeLaw] : [],
      roles: rs, ...(biasDue ? { request_bias_test: { due: biasDue } } : {}), reason: reason || 'preview',
    };
  }, [changes, roles, addLaws, removeLaw, biasDue, reason, rows]);
  const nothing = !Object.keys(body.changes).length && !body.add_regulation_ids.length && !body.remove_regulation_ids.length && !body.roles.length && !biasDue;

  useEffect(() => {
    if (nothing) { setPreview(null); return; }
    const t = setTimeout(async () => {
      try { setPreview(await api.post<Preview>('/register/bulk', { ...body, preview: true })); setErr(null); setFe({}); } catch (e) { setPreview(null); setErr(errorMessage(e)); setFe(fieldErrors(e)); }
    }, 350);
    return () => clearTimeout(t);
  }, [body, nothing]);

  async function apply() {
    setBusy(true); setErr(null);
    try {
      const r = await api.post<Preview>('/register/bulk', { ...body, reason });
      onDone(`${r.change_count} change${r.change_count === 1 ? '' : 's'} applied across ${r.systems_changed} system${r.systems_changed === 1 ? '' : 's'}.`);
    } catch (e) { setErr(errorMessage(e)); setFe(fieldErrors(e)); } finally { setBusy(false); }
  }
  const conflicts = (preview?.systems ?? []).flatMap((s) => s.conflicts);
  const setRole = (i: number, patch: Partial<RoleEntry>) => setRoles((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  let n = 0;
  const num = () => ++n;

  return (
    <Dialog title={`${TITLES[mode]} ${rows.length} selected AI system${rows.length === 1 ? '' : 's'}`} onClose={onClose} large>
      <div className="stack">
        <p className="small" style={{ margin: 0 }}><strong>{rows.map((r) => r.name).join(', ')}</strong></p>
        <p className="small muted" style={{ margin: 0 }}>Only the fields you change are applied. Anything left as "Keep current" stays as it is on each system.</p>
        {err && <Alert tone="danger">{err}</Alert>}
        {(mode === 'all' || mode === 'stage') && (
          <FieldGroup legend={`${num()} · Details`} className="reg-fieldset">
            <div className="grid-2">
              {mode === 'all' && <SelectField label="Department" help={H.department} value={changes.department_id} onChange={(e) => setChanges({ ...changes, department_id: e.target.value })} placeholder="Keep current" options={departments.filter((x) => x.can_edit).map((x) => ({ value: x.id, label: x.name }))} />}
              <SelectField label="Stage" help={H.stage} hint='"Live" needs approval for each system.' value={changes.stage} onChange={(e) => setChanges({ ...changes, stage: e.target.value })} placeholder="Keep current" options={STAGES.filter((s) => s.value !== 'live')} error={fe['stage']} />
              {mode === 'all' && <SelectField label="System owner" help={H.owner} value={changes.owner_user_id} onChange={(e) => setChanges({ ...changes, owner_user_id: e.target.value })} placeholder="Keep current" options={personOpts} />}
              {mode === 'all' && <TextField label="Next bias test due" help={H.biasDue} type="date" value={changes.bias_next_due} onChange={(e) => setChanges({ ...changes, bias_next_due: e.target.value })} />}
            </div>
          </FieldGroup>
        )}
        {show('laws') && (
          <FieldGroup legend={`${num()} · Laws that apply`} className="reg-fieldset">
            <div className="grid-2">
              <div className="stack-sm">
                <LawSearch label="Add a law to all selected" help={H.addLaw} onPick={(l) => setAddLaws((x) => (x.some((y) => y.id === l.id) ? x : [...x, l]))} />
                {addLaws.length > 0 && <div>{addLaws.map((l) => <span key={l.id} className="chip">{l.name} <button type="button" className="linklike" aria-label={`Do not add ${l.name}`} onClick={() => setAddLaws((x) => x.filter((y) => y.id !== l.id))}>×</button></span>)}</div>}
              </div>
              <SelectField label="Remove a law from all selected" help={H.removeLaw} value={removeLaw} onChange={(e) => setRemoveLaw(e.target.value)} placeholder="None" options={currentLaws} />
            </div>
            <p className="small muted" style={{ margin: 0 }}>Adding a law recalculates the required roles for each system. Removing a law needs the AI Compliance Officer's approval.</p>
          </FieldGroup>
        )}
        {show('roles') && (
          <FieldGroup legend={`${num()} · Governance roles`} className="reg-fieldset">
            <p className="small muted" style={{ margin: '0 0 8px' }}>Set a role on every selected system where that role applies. Company-wide roles are filled in from company settings.</p>
            {roles.map((r, i) => (
              <div key={i} className="reg-bulk-role grid-2">
                <SelectField label="Role" help={H.role} value={r.role_id} onChange={(e) => setRole(i, { role_id: e.target.value })} placeholder="Choose a role" options={roleOpts} />
                <SelectField label="Status" help={H.roleStatus} value={r.status} onChange={(e) => setRole(i, { status: e.target.value })} options={ROLE_STATUSES} />
                {r.status === 'assigned' && <SelectField label="Person" help={H.rolePerson} value={r.user_id} onChange={(e) => setRole(i, { user_id: e.target.value })} placeholder="Choose a person" options={personOpts} />}
                {r.status === 'external' && <TextField label="External party" help={H.roleParty} value={r.external_party} onChange={(e) => setRole(i, { external_party: e.target.value })} />}
                {r.status === 'pending_committee' && <TextField label="Target date" help={H.roleTarget} type="date" value={r.target_date} onChange={(e) => setRole(i, { target_date: e.target.value })} />}
                {r.status === 'not_applicable' && <TextField label="Reason" help={H.roleReason} value={r.reason} onChange={(e) => setRole(i, { reason: e.target.value })} />}
                {roles.length > 1 && <div><Button size="sm" variant="ghost" onClick={() => setRoles((rs) => rs.filter((_, j) => j !== i))}>Remove this role</Button></div>}
              </div>
            ))}
            <div><Button size="sm" onClick={() => setRoles((rs) => [...rs, blankRole()])}>Add another role</Button></div>
          </FieldGroup>
        )}
        {mode === 'bias' && (
          <FieldGroup legend={`${num()} · Bias test`} className="reg-fieldset">
            <TextField label="Test due by *" help={H.requestDue} type="date" value={biasDue} onChange={(e) => setBiasDue(e.target.value)} error={fe['request_bias_test.due']} />
            <p className="small muted" style={{ margin: 0 }}>Each system owner is told. Record the result on the system's history when the test is done.</p>
          </FieldGroup>
        )}
        {conflicts.length > 0 && (
          <FieldGroup legend={`${num()} · Review conflicts`} className="reg-fieldset">
            {roles.map((r, i) => {
              const cs = conflicts.filter((c) => c.role_id === r.role_id);
              if (!cs.length) return null;
              return (
                <div key={i} className="stack-sm">
                  {cs.map((c, j) => <p key={j} className="small" style={{ margin: 0 }}>{c.system} already has a {c.role}: {c.current}.</p>)}
                  <div className="radio-group" role="radiogroup" aria-label={`When ${cs[0].role} is already filled`}>
                    {([['keep', 'Keep the existing person'], ['replace', 'Replace them'], ['add', 'Add as a second person']] as const).map(([v, l]) => (
                      <label key={v} className="radio-pill"><input type="radio" name={`conflict-${i}`} checked={r.on_conflict === v} onChange={() => setRole(i, { on_conflict: v })} disabled={v === 'add' && r.status !== 'assigned'} />{l}</label>
                    ))}
                  </div>
                </div>
              );
            })}
          </FieldGroup>
        )}
        <TextArea label="Reason for change *" help={H.reason} hint="Saved to each system's change history with your name and the time." value={reason} onChange={(e) => setReason(e.target.value)} error={fe.reason} />
        <div className="reg-bulk-foot">
          <span className="small" aria-live="polite">{preview ? `${preview.change_count} change${preview.change_count === 1 ? '' : 's'} across ${preview.systems_changed} system${preview.systems_changed === 1 ? '' : 's'}.` : nothing ? 'Nothing changed yet.' : ''}</span>
          <div className="row">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={busy || nothing || !reason.trim()} onClick={apply}>Apply to {rows.length} system{rows.length === 1 ? '' : 's'}</Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

function blankRole(): RoleEntry {
  return { role_id: '', status: 'assigned', user_id: '', external_party: '', target_date: '', reason: '', on_conflict: 'keep' };
}
