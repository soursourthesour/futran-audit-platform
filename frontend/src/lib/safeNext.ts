/** A `next` or return path is followed only when it is a same-origin relative path that starts with a single "/".
 *  Anything else (another host, "//host", "/\host", a scheme, control characters) falls back to the caller's default. */
export function safeNext(v: unknown): string | null {
  if (typeof v !== 'string' || !v.startsWith('/') || v.startsWith('//') || v.startsWith('/\\')) return null;
  if (/[\u0000-\u001f\u007f\\]/.test(v)) return null;
  try {
    const u = new URL(v, window.location.origin);
    return u.origin === window.location.origin ? u.pathname + u.search + u.hash : null;
  } catch {
    return null;
  }
}

/** The path and query of a location, for a `next` parameter. */
export const herePath = (loc: { pathname: string; search: string }) => loc.pathname + loc.search;

/** "?next=…" for a path worth coming back to (not the home page, not a /welcome step). */
export function nextQuery(path: string | null | undefined): string {
  const p = safeNext(path);
  return p && p !== '/' && !p.startsWith('/welcome/') ? `?next=${encodeURIComponent(p)}` : '';
}
