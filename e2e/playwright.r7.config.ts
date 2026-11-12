import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/* Release 2 R7 only: the fresh server, no "late" server (its seed is slow and these specs do not use it).
   Usage: E2E_PORT=8962 bash e2e/run.sh -c playwright.r7.config.ts release2-r7.spec.ts */
const PORT = Number(process.env.E2E_PORT || 8765);
const servers = Array.isArray(base.webServer) ? base.webServer : [base.webServer!];

export default defineConfig({
  ...base,
  projects: (base.projects ?? []).filter((p) => p.name === 'desktop'),
  webServer: servers.filter((s) => !String(s.command).includes(' late')).map((s) => ({ ...s, url: `http://127.0.0.1:${PORT}/api/v1/health` })),
});
