import type { ComponentType, ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { Grid } from '@/api/catalog';
import { EmptyState, fmtDate } from '@/components/ui';
import '@/styles/catalog.css';

/**
 * SM-14 tab shell, agreed paths (Release 2 plan, Shared names):
 *   /staff/admin/catalog                     Price list          R1 (PriceList.tsx)
 *   /staff/admin/catalog/rules               Mapping rules       R3 fills it
 *   /staff/admin/catalog/packages            Packages            R1 (Packages.tsx)
 *   /staff/admin/catalog/questions           Question bank       R3 fills it
 *   /staff/admin/catalog/proposal-templates  Proposal templates  R4 fills it
 * R1 owns these routes (routes.r1.tsx). To fill a tab, add a file anywhere under src/screens named
 * `catalog-tab-rules.tsx`, `catalog-tab-questions.tsx` or `catalog-tab-proposal-templates.tsx` whose default export is
 * the tab's content; it is found at build time and rendered below this shell's header and tab bar. Do not add a second
 * route for these paths.
 */
export type CatalogTab = 'prices' | 'rules' | 'packages' | 'questions' | 'proposal-templates';

const SLOT_FILES = import.meta.glob('/src/screens/**/catalog-tab-*.tsx', { eager: true }) as Record<string, { default?: ComponentType }>;
export const CATALOG_SLOTS: Partial<Record<CatalogTab, ComponentType>> = Object.fromEntries(
  Object.entries(SLOT_FILES)
    .map(([path, mod]) => [path.match(/catalog-tab-([a-z-]+)\.tsx$/)?.[1], mod.default] as const)
    .filter(([k, c]) => k && c),
);

const TABS: { tab: CatalogTab; to: string; label: string }[] = [
  { tab: 'prices', to: '/staff/admin/catalog', label: 'Price list' },
  { tab: 'rules', to: '/staff/admin/catalog/rules', label: 'Mapping rules' },
  { tab: 'packages', to: '/staff/admin/catalog/packages', label: 'Packages' },
  { tab: 'questions', to: '/staff/admin/catalog/questions', label: 'Question bank' },
  { tab: 'proposal-templates', to: '/staff/admin/catalog/proposal-templates', label: 'Proposal templates' },
];

export function useGrid(includeRetired = false) {
  return useQuery({ queryKey: ['catalog', includeRetired], queryFn: () => api.get<Grid>(`/catalog${includeRetired ? '?include_retired=true' : ''}`) });
}

export function countsLine(g: Grid): string {
  const c = g.counts;
  const saved = g.last_saved ? ` · last saved by ${g.last_saved.saved_by}, ${fmtDate(g.last_saved.saved_at)}` : '';
  return `${c.items} items · ${c.available} available · ${c.manual_delivery} manual delivery · ${c.roadmap} roadmap · catalog version ${g.version}${saved}.`;
}

export function CatalogShell({ tab, actions, children }: { tab: CatalogTab; actions?: ReactNode; children: ReactNode }) {
  const { data: g } = useGrid(false);
  return (
    <div className="page catalog-page">
      <div className="page-header">
        <div>
          <h1>Master price list</h1>
          <p>
            {g ? countsLine(g) : 'Loading…'} Only the CEO and President can change it; everyone else views, exports or suggests a change.
          </p>
        </div>
        {actions && <div className="row">{actions}</div>}
      </div>
      <nav className="tabs catalog-tabs" aria-label="Catalog tabs">
        {TABS.map((t) => (
          <NavLink key={t.tab} to={t.to} end className={({ isActive }) => (isActive ? 'active' : '')} aria-current={t.tab === tab ? 'page' : undefined}>
            {t.label}{t.tab === 'packages' && g ? ` (${g.package_count})` : ''}{t.tab === 'rules' && g && g.rule_flags.length > 0 ? ` · ${g.rule_flags.length} to repair` : ''}
          </NavLink>
        ))}
      </nav>
      {children}
    </div>
  );
}

/** A tab another workstream fills (see the comment above). */
export function CatalogSlotTab({ tab }: { tab: Exclude<CatalogTab, 'prices' | 'packages'> }) {
  const Slot = CATALOG_SLOTS[tab];
  const owner = tab === 'proposal-templates' ? 'the proposal builder' : 'the scoping questionnaire';
  return (
    <CatalogShell tab={tab}>
      {Slot ? <Slot /> : <EmptyState>This tab is maintained with {owner}. It appears here once that part of Release 2 is installed.</EmptyState>}
    </CatalogShell>
  );
}
