import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { Alert, Badge, Button, Checkbox, Loading, TextArea, TextField, fmtDate } from '@/components/ui';
import type { ProposalTemplate } from '@/api/proposals';
import '@/styles/proposals.css';

type List = { items: ProposalTemplate[]; merge_fields: string[]; can_edit: boolean };

/** SM-14 Proposal templates tab (mounted by R1's CatalogShell): the section wording the Futran Admin maintains. New
 *  proposals copy it; proposals already drafted keep their own wording. */
export default function ProposalTemplatesTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['proposal-templates'], queryFn: () => api.get<List>('/sales/proposal-templates') });
  const [edit, setEdit] = useState<ProposalTemplate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (!q.data) return q.error ? <Alert tone="danger">{errorMessage(q.error)}</Alert> : <Loading />;
  const d = q.data;

  async function save() {
    if (!edit) return;
    setErr(null);
    try {
      await api.put(`/sales/proposal-templates/${edit.key}`, { title: edit.title, body: edit.body, active: edit.active });
      setMsg(`"${edit.title}" saved. New proposals use it; drafted proposals keep their wording.`);
      setEdit(null);
      qc.invalidateQueries({ queryKey: ['proposal-templates'] });
    } catch (e) { setErr(errorMessage(e)); }
  }

  return (
    <div className="stack pt-tab">
      <p className="muted">Each proposal is built from these sections, in this order. The standard wording is yours to maintain; the builder adds the generated parts
        under it. Merge fields: {d.merge_fields.map((m) => `[${m}]`).join(', ')}.{!d.can_edit && ' Only the Futran Admin changes these.'}</p>
      {msg && <Alert tone="success">{msg}</Alert>}
      <ol className="pt-list">
        {d.items.map((t, i) => (
          <li key={t.key} className="card">
            <div className="card-body stack-sm">
              <div className="row">
                <strong>{i + 1}. {t.title}</strong>
                {t.is_starter && <Badge tone="muted">Starter wording</Badge>}
                {!t.active && <Badge tone="warn">Left out</Badge>}
                {t.key === 'independence' && <Badge tone="navy">Only when flagged (I-4)</Badge>}
                {d.can_edit && edit?.key !== t.key && <Button size="sm" onClick={() => { setEdit({ ...t }); setErr(null); }}>Edit</Button>}
              </div>
              {edit?.key === t.key ? (
                <>
                  <TextField label="Section title" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
                  <TextArea label="Standard wording" rows={6} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} />
                  {!t.always && <Checkbox label="Include this section in new proposals" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} />}
                  {err && <Alert tone="danger">{err}</Alert>}
                  <div className="row"><Button variant="primary" onClick={save}>Save section</Button><Button onClick={() => setEdit(null)}>Cancel</Button></div>
                </>
              ) : <p className="pt-body">{t.body || <span className="muted">No standard wording.</span>}</p>}
              {t.auto && <p className="small muted">Added by the builder: {t.auto}</p>}
              {t.updated_by && <p className="small muted">Last changed by {t.updated_by}, {fmtDate(t.updated_at)}.</p>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
