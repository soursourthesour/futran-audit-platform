import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { safeNext } from '@/lib/safeNext';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { homePath } from '@/nav';
import { Alert, Button, Checkbox, Loading } from '@/components/ui';
import { AuthLayout } from './AuthLayout';

/** Screen 9a, last step before the checklist: terms of use and the audit-log notice. */
export function Terms() {
  const { data: me, isLoading } = useMe();
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params] = useSearchParams();
  if (isLoading) return <AuthLayout><Loading /></AuthLayout>;
  if (!me) { nav('/login', { replace: true }); return null; }
  async function accept() {
    setErr(null);
    try { await api.post('/auth/terms', { accepted: ok }); await qc.invalidateQueries({ queryKey: ['me'] }); nav(safeNext(params.get('next')) ?? homePath(me!), { replace: true }); } catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <AuthLayout>
      <div className="stack">
        <div>
          <div className="small muted">Step 4 of 4</div>
          <h1>Before you start</h1>
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="small stack-sm">
          <p style={{ margin: 0 }}>{me.organization.name} uses the Futran Audit Platform to give Futran Solutions the information for its AI governance audit.</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>Answer as things are today. Futran checks answers in interviews and against evidence.</li>
            <li>Upload only documents your organization has agreed to share for the audit.</li>
            <li>Everything you do here (sign-ins, answers, uploads and sign-offs) is recorded in an audit log that cannot be edited. Futran and your organization's administrators can see it.</li>
            <li>Keep your password and authenticator app to yourself. Your Client Admin can remove your access at any time.</li>
          </ul>
        </div>
        <Checkbox label="I accept the terms of use and understand my actions are recorded in the audit log." checked={ok} onChange={(e) => setOk(e.target.checked)} />
        <Button variant="primary" block onClick={accept} disabled={!ok}>Accept and continue</Button>
      </div>
    </AuthLayout>
  );
}
