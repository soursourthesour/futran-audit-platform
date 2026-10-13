import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Alert, Card, Loading, PageHeader } from '@/components/ui';

type S = Record<string, string | number | boolean | null>;

export function SettingsScreen() {
  const q = useQuery({ queryKey: ['admin-settings'], queryFn: () => api.get<S>('/admin/settings') });
  const s = q.data;
  return (
    <div className="page page-narrow">
      <PageHeader title="Platform settings" subtitle="Read-only. These values come from the server's .env file; change them there and restart." />
      {q.isLoading || !s ? <Loading /> : (
        <>
          {s.test_mode && <Alert tone="warn">The platform is in test mode. Turn on sign-in codes (MFA_REQUIRED=true) and real email (EMAIL_MODE=smtp) before any client uses it.</Alert>}
          <Card title="Current configuration">
            <dl className="kv">
              <dt>Sign-in codes (MFA)</dt><dd>{s.mfa_required ? 'Required' : 'Off (test mode)'}</dd>
              <dt>Email</dt><dd>{s.email_mode === 'smtp' ? `Sent through ${s.smtp_host}` : 'Kept in the outbox'}</dd>
              <dt>Data region label</dt><dd>{s.data_region}</dd>
              <dt>Claude law updates</dt><dd>{s.law_refresh_enabled ? `On (${s.claude_model})` : 'Off — no Anthropic API key set'}</dd>
              <dt>Session timeouts</dt><dd>{s.session_idle_min} minutes idle · {s.session_max_hours} hours maximum</dd>
              <dt>Default retention</dt><dd>{s.retention_years_default} years after completion</dd>
              <dt>Upload limit</dt><dd>{s.max_upload_mb} MB per file</dd>
              <dt>Virus scanning</dt><dd>{s.virus_scan === 'off' ? 'Off — files are marked "not scanned"' : String(s.virus_scan)}</dd>
              <dt>Address</dt><dd>{s.base_url}</dd>
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}
