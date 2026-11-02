import type { RouteObject } from 'react-router-dom';
import { Policies } from '@/screens/wsi/Policies';
import { PolicyBuilder } from '@/screens/wsi/PolicyBuilder';
import { Learn, MyTraining, Training } from '@/screens/wsi/Training';
import { TrustConfirmations, TrustEditor, TrustPublic } from '@/screens/wsi/Trust';
import { FutranPolicies } from '@/screens/wsi/FutranPolicies';

/** Wave 3 WS-I: policy builder (27), AI literacy training (33) and Trust Center (32). */
export const wsiClientRoutes: RouteObject[] = [
  { path: '/policies', element: <Policies /> },
  { path: '/policies/:policyId', element: <PolicyBuilder /> },
  { path: '/training', element: <Training /> },
  { path: '/my-training', element: <MyTraining /> },
  { path: '/learn/:assignmentId', element: <Learn /> },
  { path: '/trust', element: <TrustEditor /> },
];
export const wsiFutranRoutes: RouteObject[] = [
  { path: '/trust-confirmations', element: <TrustConfirmations /> },
  { path: '/client-policies', element: <FutranPolicies /> },
];
export const wsiPublicRoutes: RouteObject[] = [{ path: '/trust/:slug', element: <TrustPublic /> }];
