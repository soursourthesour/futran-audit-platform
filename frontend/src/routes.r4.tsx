import type { RouteObject } from 'react-router-dom';
import { ProposalBuilder } from '@/screens/proposals/ProposalBuilder';
import { ProposalSend } from '@/screens/proposals/ProposalSend';
import { ProposalList } from '@/screens/proposals/ProposalList';
import { Approvals } from '@/screens/proposals/Approvals';
import { ProposalAcceptance } from '@/screens/proposals/ProposalAcceptance';

/** Release 2 R4: SM-09 builder, SM-10 preview and send, SM-11 approvals (Futran shell) and SM-12 acceptance (public,
 *  no login). The SM-14 Proposal templates tab is screens/proposals/catalog-tab-proposal-templates.tsx, mounted by
 *  R1's CatalogShell. */
export const r4FutranRoutes: RouteObject[] = [
  { path: '/sales/proposals', element: <ProposalList /> },
  { path: '/sales/proposals/:id', element: <ProposalBuilder /> },
  { path: '/sales/proposals/:id/send', element: <ProposalSend /> },
  { path: '/sales/approvals', element: <Approvals /> },
];

export const r4PublicRoutes: RouteObject[] = [{ path: '/p/:token', element: <ProposalAcceptance /> }];
