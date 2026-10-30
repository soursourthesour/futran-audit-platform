import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, setCsrf } from './client';

export type RoleRef = { role: string; scope_type: string; scope_id: string | null };
export type Me = {
  user: { id: string; name: string; email: string; job_title: string | null; mfa_enabled: boolean };
  organization: { id: string; name: string; type: 'futran' | 'client'; client_ref: string | null };
  roles: RoleRef[];
  test_mode: boolean;
  mfa_required: boolean;
  email_mode: string;
  csrf_token: string;
  terms_required?: boolean;
  notice_required?: boolean;
  /** The role home to land on after sign-in (spec §13.1; precedence in backend app/policy/homes.py). */
  home?: string;
  /** Every action the permission matrix grants this person's roles; the navigation is built from it. */
  actions?: string[];
};
export type SessionState = {
  authenticated: boolean;
  mfa_pending?: boolean;
  mfa_enrolled?: boolean;
  csrf_token?: string;
  test_mode: boolean;
};

export const ROLE_LABELS: Record<string, string> = {
  chief_auditor: 'Chief Auditor',
  admin: 'Admin',
  auditor: 'Auditor',
  qa_reviewer: 'QA Reviewer',
  engagement_manager: 'Engagement Manager',
  legal_reviewer: 'Legal/Compliance Reviewer',
  sales_team: 'Sales Team',
  exec_sponsor: 'Executive Sponsor',
  caico: 'Chief AI Compliance Officer',
  client_admin: 'Client Admin',
  dpo: 'Data Protection Officer',
  dept_compliance_lead: 'Department Compliance Lead',
  contributor: 'Contributor',
};
const ROLE_ORDER = Object.keys(ROLE_LABELS);

export function primaryRole(me: Me): string {
  const names = me.roles.map((r) => r.role).sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b));
  return names[0] ? ROLE_LABELS[names[0]] ?? names[0] : '';
}

/** True when the person holds any of `actions` (the union over all their roles). */
export function can(me: Me | null | undefined, ...actions: string[]): boolean {
  return !!me && (me.actions ?? []).some((a) => actions.includes(a));
}

export function hasRole(me: Me | undefined, ...roles: string[]): boolean {
  return !!me && me.roles.some((r) => roles.includes(r.role));
}

export function useSessionState() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async () => {
      const s = await api.get<SessionState>('/auth/session');
      if (s.csrf_token) setCsrf(s.csrf_token);
      return s;
    },
    staleTime: 0,
  });
}

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        const me = await api.get<Me>('/auth/me');
        setCsrf(me.csrf_token);
        return me;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useSignOut() {
  const qc = useQueryClient();
  return async (staff?: boolean) => {
    try {
      await api.post('/auth/logout');
    } finally {
      setCsrf(null);
      qc.clear();
      window.location.assign(staff ? '/staff/login' : '/login');
    }
  };
}
