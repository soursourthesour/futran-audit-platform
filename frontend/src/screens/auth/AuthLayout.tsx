import type { ReactNode } from 'react';
import { TestModeBar } from '@/shells/Shells';
import { useSessionState } from '@/api/auth';

export function AuthLayout({ children }: { children: ReactNode }) {
  const { data: s } = useSessionState();
  return (
    <>
      {s?.test_mode && <TestModeBar me={{ test_mode: true, mfa_required: false, email_mode: 'outbox' }} />}
      <div className="auth">
        <div className="auth-brand">
          <div className="brand"><span className="brand-mark" style={{ width: 36, height: 36, borderRadius: 6 }} aria-hidden="true" /><span className="brand-name" style={{ fontSize: 20 }}>Futran Audit</span></div>
          <div>
            <div className="headline">AI governance audits, captured end to end.</div>
            <p>Inventory, evidence, findings and sign-offs for every client engagement, in one place.</p>
          </div>
          <div className="small" style={{ color: 'var(--header-sub)' }}>Futran Solutions · Edison, NJ</div>
        </div>
        <div className="auth-form">{children}</div>
      </div>
    </>
  );
}
