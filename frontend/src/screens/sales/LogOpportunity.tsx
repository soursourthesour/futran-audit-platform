import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ApiError, api, errorMessage, fieldErrors } from '@/api/client';
import { Alert, Button, Checkbox, Dialog, SelectField, TextArea, TextField } from '@/components/ui';
import { type Duplicate, type OppDetail, type OppList, oppLink } from '@/api/sales';
import { salesHelp as H } from '@/help/sales';

type CompanyHit = { id: string; name: string; kind: 'client' | 'prospect'; website: string | null; domain: string | null };
type ContactDraft = { name: string; title: string; email: string; phone: string; contact_role: string };
const blankContact = (): ContactDraft => ({ name: '', title: '', email: '', phone: '', contact_role: '' });

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** SM-03 Log opportunity: an existing client or prospect, or a new prospect checked for duplicates (spec §4.3). */
export function LogOpportunity({ opts, me, onClose }: { opts: OppList; me: string; onClose: () => void }) {
  const nav = useNavigate();
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<CompanyHit | null>(null);
  const [p, setP] = useState({ name: '', website: '', industry: '', size_band: '', hq_state: '', hq_country: 'US' });
  const [contacts, setContacts] = useState<ContactDraft[]>([blankContact()]);
  const [f, setF] = useState({ source: '', partner_id: '', segment: '', trigger_event: '', est_value: '', close_date: '', next_step: '', next_step_due: '', owner_id: '', name: '' });
  const [products, setProducts] = useState<string[]>([]);
  const [bant, setBant] = useState({ budget: '', authority: '', need: '', timeline: '' });
  const [confirmDifferent, setConfirmDifferent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const q = useDebounced(query);
  const search = useQuery({ queryKey: ['sales-companies', q], queryFn: () => api.get<{ items: CompanyHit[] }>(`/sales/companies?q=${encodeURIComponent(q)}`), enabled: !picked && q.trim().length >= 2 });
  const isNew = !picked;
  const newName = isNew ? p.name || query : '';
  const dupKey = useDebounced(JSON.stringify([newName.trim(), p.website.trim(), contacts.map((c) => c.email.trim()).filter(Boolean).join(',')]));
  const dups = useQuery({
    queryKey: ['sales-dups', dupKey],
    queryFn: () => {
      const [name, website, email] = JSON.parse(dupKey) as string[];
      return api.get<{ matches: Duplicate[] }>(`/sales/duplicates?${new URLSearchParams({ name, website, email }).toString()}`);
    },
    enabled: isNew && (JSON.parse(dupKey) as string[]).some((x) => x.length >= 3),
  });
  const matches = isNew ? dups.data?.matches ?? [] : [];
  useEffect(() => { setConfirmDifferent(false); }, [dupKey]);
  const indep = useQuery({ queryKey: ['sales-indep', picked?.id], queryFn: () => api.get<{ flag: boolean; reason: string }>(`/sales/independence?organization_id=${picked!.id}`), enabled: !!picked });

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const setPr = (k: keyof typeof p) => (e: { target: { value: string } }) => setP({ ...p, [k]: e.target.value });
  const setC = (i: number, k: keyof ContactDraft) => (e: { target: { value: string } }) => setContacts(contacts.map((c, j) => (j === i ? { ...c, [k]: e.target.value } : c)));
  const blocked = isNew && matches.length > 0 && !confirmDifferent;
  const canSave = (picked || newName.trim().length >= 2) && !blocked && !busy;
  const ownerOptions = useMemo(() => opts.owners.map((o) => ({ value: o.id, label: o.id === me ? `${o.name} (me)` : o.name })), [opts.owners, me]);

  async function save() {
    setErr(null); setErrs({}); setBusy(true);
    const body: Record<string, unknown> = {
      contacts: contacts.filter((c) => c.name.trim()).map((c) => ({ name: c.name.trim(), title: c.title || null, email: c.email || null, phone: c.phone || null, contact_role: c.contact_role || null })),
      source: f.source || null, partner_id: f.partner_id || null, segment: f.segment || null, trigger_event: f.trigger_event || null, products_of_interest: products, name: f.name || null,
      est_value: f.est_value ? Number(f.est_value) : null, close_date: f.close_date || null, next_step: f.next_step || null, next_step_due: f.next_step_due || null,
      owner_id: f.owner_id || null, bant: Object.values(bant).some(Boolean) ? bant : null, confirm_different: confirmDifferent,
    };
    if (picked) body.organization_id = picked.id;
    else body.prospect = { name: newName.trim(), website: p.website || null, industry: p.industry || null, size_band: p.size_band || null, hq_state: p.hq_state || null, hq_country: p.hq_country || null };
    try {
      const o = await api.post<OppDetail>('/sales/opportunities', body);
      nav(oppLink(o.id));
    } catch (e) {
      setErr(errorMessage(e)); setErrs(fieldErrors(e));
      if (e instanceof ApiError && e.status === 409) void dups.refetch();
    } finally { setBusy(false); }
  }

  return (
    <Dialog title="Log opportunity" onClose={onClose} large>
      <div className="stack sales-log">
        {err && <Alert tone="danger">{err}</Alert>}
        <fieldset className="stack-sm">
          <legend>Company</legend>
          {picked ? (
            <div className="row">
              <span><strong>{picked.name}</strong> <span className="small muted">{picked.kind === 'prospect' ? 'Prospect' : 'Client'}{picked.domain ? ` · ${picked.domain}` : ''}</span></span>
              <Button size="sm" onClick={() => setPicked(null)}>Change</Button>
            </div>
          ) : (
            <>
              <TextField label="Company" help={H.company} placeholder="Search existing clients and prospects, or type a new company" value={query}
                onChange={(e) => { setQuery(e.target.value); setP({ ...p, name: e.target.value }); }} error={errs.organization_id} autoFocus />
              {(search.data?.items.length ?? 0) > 0 && (
                <ul className="sales-hits" aria-label="Companies on file">
                  {search.data!.items.map((c) => (
                    <li key={c.id}><button type="button" className="linklike left" onClick={() => setPicked(c)}>{c.name}</button> <span className="small muted">{c.kind === 'prospect' ? 'Prospect' : 'Client'}{c.domain ? ` · ${c.domain}` : ''}</span></li>
                  ))}
                </ul>
              )}
              {matches.length > 0 && (
                <div className="alert alert-warn" role="alert" data-testid="duplicate-warning">
                  {matches.map((m) => (
                    <p key={m.organization_id} style={{ margin: '0 0 6px' }}>
                      <strong>Possible duplicate:</strong> {m.name} ({m.kind}, {m.reason}).{' '}
                      {m.open_opportunity_id ? <Link to={oppLink(m.open_opportunity_id)}>Open it</Link> : <button type="button" className="linklike" onClick={() => setPicked({ id: m.organization_id, name: m.name, kind: m.kind, website: m.website, domain: null })}>Use it</button>}
                    </p>
                  ))}
                  <Checkbox label="This is a different company" checked={confirmDifferent} onChange={(e) => setConfirmDifferent(e.target.checked)} />
                </div>
              )}
              <div className="grid-2">
                <TextField label="Website" help={H.website} value={p.website} onChange={setPr('website')} placeholder="acme.com" />
                <SelectField label="Industry" value={p.industry} onChange={setPr('industry')} options={opts.industries.map((x) => ({ value: x, label: x }))} placeholder="Choose" />
                <SelectField label="Employees" value={p.size_band} onChange={setPr('size_band')} options={opts.size_bands.map((x) => ({ value: x, label: x }))} placeholder="Choose" />
                <TextField label="Headquarters state" value={p.hq_state} onChange={setPr('hq_state')} placeholder="NJ" />
              </div>
            </>
          )}
        </fieldset>

        <fieldset className="stack-sm">
          <legend>Contacts</legend>
          {contacts.map((c, i) => (
            <div key={i} className="grid-2 sales-contact" aria-label={i === 0 ? 'Main contact' : `Contact ${i + 1}`}>
              <TextField label={i === 0 ? 'Main contact name' : 'Name'} value={c.name} onChange={setC(i, 'name')} />
              <TextField label="Title" value={c.title} onChange={setC(i, 'title')} />
              <TextField label="Email" type="email" value={c.email} onChange={setC(i, 'email')} />
              <SelectField label="Role in deal" help={H.contactRole} value={c.contact_role} onChange={setC(i, 'contact_role')} options={opts.contact_roles} placeholder="Choose" />
            </div>
          ))}
          <div><Button size="sm" onClick={() => setContacts([...contacts, blankContact()])}>Add another contact</Button></div>
        </fieldset>

        <fieldset className="stack-sm">
          <legend>Deal</legend>
          <div className="grid-2">
            <SelectField label="Source" help={H.source} value={f.source} onChange={set('source')} options={opts.sources.filter((s) => s.value !== 'auto_trigger')} placeholder="Choose" />
            {opts.partners.length > 0 && <SelectField label="Partner (if referred)" help={H.partner} value={f.partner_id} onChange={set('partner_id')} options={opts.partners.map((x) => ({ value: x.id, label: x.name }))} placeholder="None" error={errs.partner_id} />}
            <SelectField label="Segment" value={f.segment} onChange={set('segment')} options={opts.segments} placeholder="Choose" />
            <SelectField label="Trigger" help={H.trigger} value={f.trigger_event} onChange={set('trigger_event')} options={opts.trigger_events} placeholder="Choose" />
            <TextField label="Estimated value ($)" type="number" min={0} value={f.est_value} onChange={set('est_value')} error={errs.est_value} />
            <TextField label="Expected close" type="date" value={f.close_date} onChange={set('close_date')} />
            {opts.can_reassign && <SelectField label="Owner" value={f.owner_id} onChange={set('owner_id')} options={ownerOptions} placeholder="Me" />}
            <TextField label="Next step" value={f.next_step} onChange={set('next_step')} />
            <TextField label="Due" type="date" value={f.next_step_due} onChange={set('next_step_due')} />
          </div>
          <div role="group" aria-label="Products of interest">
            <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>Products of interest</div>
            <div className="sales-checks">
              {opts.products.map((x) => <Checkbox key={x.value} label={x.label} checked={products.includes(x.value)} onChange={(e) => setProducts(e.target.checked ? [...products, x.value] : products.filter((y) => y !== x.value))} />)}
            </div>
          </div>
          <details>
            <summary>Qualification (BANT), optional now</summary>
            <div className="grid-2" style={{ marginTop: 8 }}>
              <TextField label="Budget" value={bant.budget} onChange={(e) => setBant({ ...bant, budget: e.target.value })} />
              <TextField label="Authority (who signs)" value={bant.authority} onChange={(e) => setBant({ ...bant, authority: e.target.value })} />
              <TextArea label="Need" rows={2} value={bant.need} onChange={(e) => setBant({ ...bant, need: e.target.value })} />
              <TextField label="Timeline" value={bant.timeline} onChange={(e) => setBant({ ...bant, timeline: e.target.value })} />
            </div>
          </details>
        </fieldset>

        <p className="small" data-testid="independence-check">
          <strong>Independence check:</strong>{' '}
          {picked ? (indep.data ? (indep.data.flag ? <span className="text-warn">flagged — {indep.data.reason}</span> : 'no flag — not a current or recent audit client.') : 'checking…') : 'no flag — a new prospect.'}
        </p>
        <div className="row">
          <Button variant="primary" disabled={!canSave} onClick={save}>Save and open</Button>
          <Button onClick={onClose}>Cancel</Button>
          {blocked && <span className="small muted">Open the company on file, or tick “This is a different company”.</span>}
        </div>
      </div>
    </Dialog>
  );
}
