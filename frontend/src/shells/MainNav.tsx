import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { can, type Me } from '@/api/auth';
import { activeNav, groupsFor, type NavBadge, type NavEntry, type NavGroup } from '@/nav';
import '@/styles/nav.css';

type Badges = Partial<Record<NavBadge, number>>;

/** Counts for entries that carry a badge (F6). Fetched only when this person has such an entry; refreshed on each
 *  navigation and every minute. */
function useBadges(me: Me, entries: NavEntry[], pathname: string): Badges {
  const wanted = entries.some((e) => e.badge);
  const q = useQuery({ queryKey: ['nav-badges'], queryFn: () => api.get<Badges>('/nav/badges'), enabled: wanted, refetchInterval: 60_000, staleTime: 15_000 });
  const { refetch } = q;
  useEffect(() => { if (wanted) void refetch(); }, [pathname, wanted, refetch]);
  return wanted && can(me, 'approve_obligations') ? q.data ?? {} : {};
}

function Count({ n, label }: { n: number | undefined; label: string }) {
  if (!n) return null;
  return <span className="nav-count" aria-label={`${n} ${label}`}>{n}</span>;
}

/** The main navigation, grouped into menus (11-03 F4, C1). Wide screens: a disclosure button per group opens a panel of
 *  links below it (Escape or a click outside closes it; arrow keys move between links). Phones: the groups sit inside
 *  the header's Menu panel as an accordion, with the current page's group open. A group with a single entry, or a
 *  person with a single group, gets plain links. The menu never traps focus. */
export function MainNav({ me, groups, pathname, phoneOpen, onFollow }: { me: Me; groups: NavGroup[]; pathname: string; phoneOpen: boolean; onFollow: () => void }) {
  const mine = groupsFor(me, groups);
  const entries = mine.flatMap((g) => g.entries);
  const current = activeNav(pathname, entries);
  const badges = useBadges(me, entries, pathname);
  const currentGroup = mine.find((g) => g.entries.some((e) => e.to === current))?.id ?? null;
  const [open, setOpen] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});

  // a new page closes the open menu; opening the phone menu shows the current page's group
  useEffect(() => setOpen(null), [pathname]);
  useEffect(() => { if (phoneOpen) setOpen(currentGroup); }, [phoneOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // wide screens: the open panel drops below its button, shifted left as far as needed to stay inside the window
  // (a group near the right end of the row would otherwise open past the edge and scroll the page sideways)
  useLayoutEffect(() => {
    if (!open) return undefined;
    const place = () => {
      const panel = navRef.current?.querySelector<HTMLElement>(`#nav-panel-${open}`);
      if (!panel) return;
      panel.style.left = '';
      if (getComputedStyle(panel).position !== 'absolute') return; // phones: the panel sits in the menu's flow
      const gap = 8;
      const vw = document.documentElement.clientWidth;
      const r = panel.getBoundingClientRect();
      if (r.right > vw - gap) panel.style.left = `${Math.max(gap - r.left, vw - gap - r.right)}px`;
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open, phoneOpen]);

  // wide screens: a click outside the navigation closes the open menu
  useEffect(() => {
    if (!open || phoneOpen) return undefined;
    const onDown = (e: PointerEvent) => { if (!navRef.current?.contains(e.target as Node)) setOpen(null); };
    document.addEventListener('pointerdown', onDown, true);
    return () => document.removeEventListener('pointerdown', onDown, true);
  }, [open, phoneOpen]);

  function onKeyDown(e: ReactKeyboardEvent<HTMLElement>) {
    if (!open) return;
    if (e.key === 'Escape' && !phoneOpen) {  // on phones Escape closes the whole menu (the header handles it)
      e.preventDefault();
      const id = open;
      setOpen(null);
      buttons.current[id]?.focus();
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
    const panel = navRef.current?.querySelector<HTMLElement>(`#nav-panel-${open}`);
    const links = Array.from(panel?.querySelectorAll<HTMLAnchorElement>('a') ?? []);
    if (!links.length) return;
    e.preventDefault();
    const at = links.indexOf(document.activeElement as HTMLAnchorElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? links.length - 1 : e.key === 'ArrowDown' ? (at + 1) % links.length : at <= 0 ? links.length - 1 : at - 1;
    links[next].focus();
  }

  const link = (n: NavEntry, plain: boolean) => (
    <Link key={n.to} to={n.to} className={`${plain ? 'nav-plain' : 'nav-item'}${n.to === current ? ' active' : ''}`} aria-current={n.to === current ? 'page' : undefined}>
      <span>{n.label}</span>{n.badge && <Count n={badges[n.badge]} label="waiting for a decision" />}
    </Link>
  );

  const flat = mine.length === 1;
  return (
    <nav ref={navRef} className="shell-nav" aria-label="Main" onKeyDown={onKeyDown}
      onClick={(e) => { if ((e.target as HTMLElement).closest('a')) { setOpen(null); onFollow(); } }}>
      {mine.map((g) => {
        if (flat || g.entries.length === 1) return g.entries.map((n) => link(n, true));
        const isOpen = open === g.id;
        const total = g.entries.reduce((sum, n) => sum + (n.badge ? badges[n.badge] ?? 0 : 0), 0);
        return (
          <div key={g.id} className="nav-group" data-open={isOpen ? 'true' : 'false'}>
            <button
              ref={(el) => { buttons.current[g.id] = el; }}
              type="button"
              className={`nav-group-btn${g.id === currentGroup ? ' active' : ''}`}
              aria-expanded={isOpen}
              aria-controls={`nav-panel-${g.id}`}
              onClick={() => setOpen(isOpen ? null : g.id)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown' && !isOpen) {
                  e.preventDefault();
                  setOpen(g.id);
                  requestAnimationFrame(() => navRef.current?.querySelector<HTMLElement>(`#nav-panel-${g.id} a`)?.focus());
                }
              }}
            >
              <span>{g.label}</span>
              {g.id === currentGroup && <span className="sr-only"> (current section)</span>}
              <Count n={total} label="waiting for a decision" />
              <svg className="nav-chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
            <div id={`nav-panel-${g.id}`} className="nav-panel" hidden={!isOpen}
              onBlur={(e) => { if (!phoneOpen && !e.currentTarget.parentElement?.contains(e.relatedTarget as Node)) setOpen((o) => (o === g.id ? null : o)); }}>
              {g.entries.map((n) => link(n, false))}
            </div>
          </div>
        );
      })}
    </nav>
  );
}
