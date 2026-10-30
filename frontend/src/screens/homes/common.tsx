import type { ReactNode } from 'react';
import { Badge, fmtDate } from '@/components/ui';
import type { SignOffView } from '@/components/SignPanel';
import './homes.css';

export function Tile({ label, value, hint, text }: { label: string; value: ReactNode; hint?: ReactNode; text?: boolean }) {
  return <div className="tile"><div className="label">{label}</div><div className={`value${text ? ' text' : ''}`}>{value}</div>{hint && <div className="hint">{hint}</div>}</div>;
}

/** The role's rights in one line each, as on the mockups. */
export function RoleNote({ role, can, cannot }: { role: string; can: string; cannot: string }) {
  return <p className="home-note"><strong>{role} can:</strong> {can} <strong>Cannot:</strong> {cannot}</p>;
}

export const SEVERITY_TONE: Record<string, 'danger' | 'warn' | 'navy' | 'muted'> = { critical: 'danger', high: 'danger', medium: 'warn', low: 'navy', observation: 'muted' };
export const RATING_LABEL: Record<string, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };
export const cap = (s: string | null | undefined) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');

/** Sign-off status as a short label: signed (with date), waiting for this person, or with whom. */
export function signOffStatus(so: SignOffView | null): { label: string; tone: 'success' | 'warn' | 'navy' | 'muted' | 'danger' } {
  if (!so) return { label: 'Not started', tone: 'muted' };
  if (so.status === 'approved') return { label: `Signed ${fmtDate(so.approved_at)}`, tone: 'success' };
  if (so.status === 'returned') return { label: 'Returned to the preparer', tone: 'danger' };
  if (so.can_sign) return { label: 'Waiting for you', tone: 'warn' };
  const next = so.parties.find((p) => !p.signed);
  return { label: next ? `With the ${next.role_label}` : 'In review', tone: 'navy' };
}

export function SignOffBadge({ so }: { so: SignOffView | null }) {
  const s = signOffStatus(so);
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
