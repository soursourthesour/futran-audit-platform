import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT || 8765);
const LATE = PORT + 1; // ABC Corp at stage 6 and Meridian at stage 3 (start-server.sh … late)
const chrome = { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } };
const LATE_SPECS = /(journey|mobile|a11y)\.spec\.ts/;

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts/,
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  projects: [
    { name: 'desktop', testIgnore: LATE_SPECS, use: { ...chrome, baseURL: `http://127.0.0.1:${PORT}` } },
    { name: 'late', testMatch: LATE_SPECS, use: { ...chrome, baseURL: `http://127.0.0.1:${LATE}` } },
  ],
  webServer: [
    { command: `bash ./start-server.sh ${PORT}`, url: `http://127.0.0.1:${PORT}/api/v1/health`, reuseExistingServer: false, timeout: 120_000 },
    { command: `bash ./start-server.sh ${LATE} late`, url: `http://127.0.0.1:${LATE}/api/v1/health`, reuseExistingServer: false, timeout: 240_000 },
  ],
});
