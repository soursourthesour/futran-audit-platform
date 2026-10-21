import type { ReactNode } from 'react';
import logo from '@/assets/futran-logo.svg';
import logoWhite from '@/assets/futran-logo-white.svg';
import { TestModeBar } from '@/shells/Shells';
import { useSessionState } from '@/api/auth';

export function AuthLayout({ children }: { children: ReactNode }) {
  const { data: s } = useSessionState();
  return (
    <>
      {s?.test_mode && <TestModeBar me={{ test_mode: true, mfa_required: false, email_mode: 'outbox' }} />}
      <div className="auth">
        <div className="auth-brand">
          <div className="brand"><img className="brand-logo brand-logo-lg" src={logoWhite} alt="Futran Solutions" /><span className="brand-name" style={{ fontSize: 20 }}>Audit Platform</span></div>
          <div>
            <div className="headline">AI governance audits, captured end to end.</div>
            <p>Inventory, evidence, findings and sign-offs for every client engagement, in one place.</p>
          </div>
          <div className="small" style={{ color: 'var(--header-sub)' }}>Futran Solutions · Edison, NJ</div>
        </div>
        <div className="auth-form">
          <div className="auth-form-inner">
            <img className="auth-logo" src={logo} alt="Futran Solutions" />
            {children}
          </div>
        </div>
      </div>
    </>
  );
}
