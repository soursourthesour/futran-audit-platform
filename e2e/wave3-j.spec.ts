import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { openNav } from './nav';

/* Wave 3 WS-J on the "late" server (ABC Corp at stage 6): the Futran Admin puts ABC on the Monitor plan; the Client Admin
   uploads an expense export, connects Google Workspace through the test consent page, syncs, confirms one tool and
   dismisses another (screen 30); the CAICO runs the monitoring checks (screen 31); the assigned auditor reads both on
   the client page. Every connector runs on its in-process fake. 1440 and 375 px screenshots of each screen. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const SAM = `sam.okafor@${ABC}`; // Client Admin
const MARIA = `maria.lopez@${ABC}`; // Chief AI Compliance Officer
const SHOTS = process.env.WSJ_SHOTS || '/mnt/user-data/outputs/wave3/ws-j';
mkdirSync(SHOTS, { recursive: true });
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string };

const EXPENSE = `Date,Employee,Email,Department,Merchant,Description,Amount
2026-09-02,Dev Shah,dev.shah@${ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
2026-09-03,Owen Hart,owen.hart@${ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
2026-09-04,Nina Patel,nina.patel@${ABC},Finance,Anthropic,CLAUDE.AI SUBSCRIPTION,20.00
2026-09-05,Lee Park,lee.park@${ABC},HR,Midjourney Inc,MIDJOURNEY INC.,10.00
2026-09-06,Tom Reyes,tom.reyes@${ABC},HR,Staples,STAPLES 0042,54.10
`;

async function signIn(page: Page, email: string, staff = false) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
    else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
    else if (p.startsWith('/welcome/mailbox')) { await page.getByRole('button', { name: 'Not now' }).click(); }
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

/** No sideways page scroll at 375 px, and every control at least 44 px tall. */
async function checkPhone(page: Page, where: string) {
  const r = await page.evaluate(() => {
    const wide = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small: string[] = [];
    document.querySelectorAll<HTMLElement>('main button, main a.btn, main select, main textarea, main input:not([type=checkbox]):not([type=radio]):not([type=hidden])').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.height < 44 && !el.closest('.help-pop, .field-help')) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(b.height)}px`);
    });
    return { wide, small };
  });
  expect(r.wide, `${where}: page scrolls sideways`).toBeLessThanOrEqual(0);
  expect(r.small, `${where}: controls under 44 px`).toEqual([]);
}

async function shots(page: Page, name: string, phone: boolean) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(250);
  if (phone) await checkPhone(page, name);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

test.describe.configure({ mode: 'serial' });

test('Futran Admin puts ABC Corp on the Monitor plan from the client page', async ({ page }) => {
  await signIn(page, 'admin@futran.demo', true);
  await api(page, 'PUT', `/clients/${late().abc}/subscription`, { plan: 'audit_only' }); // a known start when the spec is run again
  await page.goto(`/clients/${late().abc}/monitoring`);
  await expect(page.getByRole('heading', { name: 'Continuous monitoring' })).toBeVisible();
  await expect(page.getByText('What the Monitor plan adds')).toBeVisible();
  await page.getByLabel('Plan *').selectOption('monitor');
  await page.getByRole('button', { name: 'Save plan' }).click();
  await expect(page.getByText('Plan set to Monitor.')).toBeVisible();
  await shots(page, 'futran-monitoring-plan', false);
});

test('Client Admin uploads expenses, connects Google Workspace and works the discovered tools', async ({ page }) => {
  await signIn(page, SAM);
  await openNav(page, 'Integrations');
  await expect(page.getByRole('heading', { name: 'Integrations and AI discovery' })).toBeVisible();
  await expect(page.getByText('Results are grouped by tool and department')).toBeVisible();

  await page.getByRole('article', { name: 'Expense data' }).getByRole('button', { name: /^Upload (CSV|new)$/ }).click();
  await page.getByLabel(/CSV file/).setInputFiles({ name: 'card-q3.csv', mimeType: 'text/csv', buffer: Buffer.from(EXPENSE) });
  await page.getByRole('dialog').getByRole('button', { name: 'Upload' }).click();
  await expect(page.getByText(/card-q3\.csv: 5 rows read, 4 matched to AI vendors/)).toBeVisible();

  await page.getByRole('article', { name: 'Google Workspace' }).getByRole('button', { name: 'Connect' }).click();
  await expect(page).toHaveURL(/\/integrations\/test-consent/);
  await expect(page.getByText('admin.reports.audit.readonly')).toBeVisible();
  await page.getByRole('textbox', { name: /Your organisation’s domain/ }).fill(ABC);
  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page).toHaveURL(/\/integrations\?connected=google_workspace/);
  await page.getByRole('article', { name: 'Google Workspace' }).getByRole('button', { name: 'Sync now' }).click();
  await expect(page.getByText(/Google Workspace synced: 2 AI tool and department pairs/)).toBeVisible();

  const grid = page.getByRole('table', { name: 'Discovered AI tools' });
  const claude = grid.getByRole('row').filter({ hasText: 'Claude' });
  await claude.getByRole('button', { name: 'Confirm' }).click();
  await expect(page.getByText(/Claude is in your AI inventory/)).toBeVisible();
  const mj = grid.getByRole('row').filter({ hasText: 'Midjourney' });
  await mj.getByRole('button', { name: 'Dismiss' }).click();
  await page.getByRole('dialog').getByRole('textbox', { name: /Reason/ }).fill('One-off banner purchase, refunded; image tools are not approved for client work.');
  await page.getByRole('dialog').getByRole('button', { name: 'Dismiss' }).click();
  await expect(page.getByText(/Midjourney dismissed/)).toBeVisible();
  await expect(grid.getByRole('row').filter({ hasText: 'Otter.ai' }).getByText('Undeclared')).toBeVisible();
  await shots(page, 'integrations-client-admin', true);
});

test('CAICO reads integrations without decisions and runs the monitoring checks', async ({ page }) => {
  await signIn(page, MARIA);
  await page.goto('/integrations');
  await expect(page.getByRole('heading', { name: 'Integrations and AI discovery' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Upload CSV' })).toHaveCount(0);
  await openNav(page, 'Monitoring');
  await expect(page.getByRole('heading', { name: 'Continuous monitoring' })).toBeVisible();
  await page.getByRole('button', { name: 'Run checks now' }).click();
  await expect(page.getByText(/Checks run: \d+ failed/)).toBeVisible();
  const need = page.getByRole('region', { name: 'Checks needing action' }).or(page.locator('section', { has: page.getByRole('heading', { name: 'Checks needing action' }) }));
  await expect(need.getByText('New undeclared AI tool').first()).toBeVisible();
  await expect(page.getByRole('list', { name: 'Check results' })).toContainText('Failed');
  await shots(page, 'monitoring-caico', true);
});

test('the assigned auditor reads both screens on the client page', async ({ page }) => {
  await signIn(page, 'auditor1@futran.demo', true);
  await page.goto(`/clients/${late().abc}/integrations`);
  await expect(page.getByText(/Read-only view of ABC Corp/)).toBeVisible();
  await expect(page.getByRole('table', { name: 'Discovered AI tools' }).getByText(/refunded/)).toBeVisible();
  await shots(page, 'futran-integrations-auditor', false);
  await page.goto(`/clients/${late().abc}/monitoring`);
  await expect(page.getByRole('heading', { name: 'Checks needing action' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run checks now' })).toHaveCount(0);
  await shots(page, 'futran-monitoring-auditor', false);
});
