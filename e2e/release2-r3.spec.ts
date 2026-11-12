import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Release 2 R3: the scoping call (SM-05), sending to the client (SM-06), the client's questions on a phone (SM-07) and the
   review with a conflict to settle and the lock (SM-08). Run on the fresh server:
   E2E_PORT=8937 bash e2e/run.sh -c playwright.r3.config.ts release2-r3.spec.ts */

const PW = 'Demo-Password-2026';
const SHOTS = process.env.R3_SHOTS || '/mnt/user-data/outputs/release2/r3';
mkdirSync(SHOTS, { recursive: true });

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

/** The link in the last scoping email, read from the outbox (test mode keeps it readable). */
function lastLink(): string {
  const py = `import sqlite3,re;c=sqlite3.connect('data/e2e.db');t=c.execute("select body_text from outbox_messages where template_key='scoping_questionnaire' order by created_at desc limit 1").fetchone()[0];print(re.search(r'/q/[A-Za-z0-9_\\-]+',t).group(0))`;
  return execFileSync('python3', ['-c', py], { cwd: `${__dirname}/../backend` }).toString().trim();
}

async function noSideways(page: Page, what: string) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(wide, `${what} scrolls sideways`).toBeLessThanOrEqual(1);
}

test('scoping: record on the call, send the rest, client answers on a phone, review and lock', async ({ page, browser }) => {
  test.setTimeout(180_000);
  await signIn(page, 'sales@futran.demo');
  const list = await api(page, 'GET', '/opportunities');
  const opp = await api(page, 'POST', '/opportunities', { organization_id: list.clients[0].id, service: 'LL144 readiness and Monitor', why_now: 'Bias audit due' });

  // SM-05: record on the call
  await page.goto(`/sales/opportunities/${opp.id}/scoping`);
  await expect(page.getByRole('heading', { name: /Scoping call/ })).toBeVisible();
  await page.getByRole('button', { name: /^B\. Footprint/ }).click();
  await page.getByLabel('SQ-B.01 Number of employees').fill('600');
  await page.getByRole('button', { name: /^C\. AI inventory/ }).click();
  await page.getByLabel('SQ-C.01 Vendor apps with AI').fill('3');
  await page.getByRole('radiogroup', { name: 'Confidence for SQ-C.01' }).getByLabel('Estimate').check();
  await page.getByLabel('SQ-C.02 Embedded AI (Copilot etc.)').fill('1');
  await page.getByLabel('SQ-C.03 GenAI chat tools').fill('2');
  await page.getByLabel('Partial list, probably missing tools').check();
  for (const s of ['Okta / Entra ID', 'Microsoft 365', 'Expense export']) await page.getByRole('group', { name: /SQ-C.11/ }).getByLabel(s).check();
  await page.getByRole('group', { name: /SQ-C.12/ }).getByLabel('Microsoft 365 Copilot').check();
  await page.keyboard.press('Control+s');
  const aside = page.getByRole('complementary', { name: 'Suggested line items' });
  await expect(aside.getByText('Because SQ-C.07 = 6 (estimate)')).toBeVisible({ timeout: 15_000 });
  await expect(aside.getByText(/A-05/).first()).toBeVisible();
  await expect(aside.getByText(/X-04/).first()).toBeVisible();
  await expect(page.getByText(/autosaved/)).toBeVisible();
  await expect(page.getByText('Total:')).toContainText('6');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await noSideways(page, 'SM-05');
  await page.screenshot({ path: `${SHOTS}/SM05-scoping-call-1440.png`, fullPage: true });

  // SM-06: send the rest to the client
  await page.getByRole('button', { name: 'Send rest to client' }).click();
  const dlg = page.getByRole('dialog', { name: 'Send questionnaire to client' });
  await expect(dlg.getByText('Budget, competitors, red flags, independence — internal, never sent')).toBeVisible();
  await dlg.getByLabel('To').selectOption('other');
  await dlg.getByLabel('Name').fill('Pat Champion');
  await dlg.getByLabel('Email').fill('pat@client.example');
  await expect(dlg.getByText(/Sends from/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/SM06-send-questionnaire-1440.png`, fullPage: false });
  await dlg.getByRole('button', { name: /^Send \d+ questions?$/ }).click();
  await expect(dlg).toBeHidden();
  const link = lastLink();

  // SM-07: the client on a phone, no login
  const phone = await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, baseURL: new URL(page.url()).origin });
  const c = await phone.newPage();
  await c.goto(link);
  await expect(c.getByText(/Scoping questions for/)).toBeVisible();
  await expect(c.getByText('Budget')).toHaveCount(0);
  await expect(c.getByText(/not legal advice/)).toBeVisible();
  // step through to the AI inventory step and answer the total
  for (let i = 0; i < 6; i++) {
    if (await c.getByText('In total, how many AI systems do you use?').isVisible()) break;
    await c.getByRole('button', { name: 'Save and continue' }).click();
  }
  await c.getByLabel('In total, how many AI systems do you use?').fill('12');
  await c.getByRole('group', { name: 'How many vendors supply your AI tools?' }).getByLabel('Not sure').check();
  await expect(c.getByText(/% done/)).toBeVisible();
  await noSideways(c, 'SM-07 at 375 px');
  const small = await c.evaluate(() => [...document.querySelectorAll<HTMLElement>('button, select, textarea, input:not([type=checkbox]):not([type=radio])')]
    .filter((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0 && b.height < 44; }).map((el) => el.textContent || el.getAttribute('aria-label')));
  expect(small, 'SM-07 controls under 44 px').toEqual([]);
  await c.screenshot({ path: `${SHOTS}/SM07-client-questionnaire-375.png`, fullPage: true });
  await c.getByRole('button', { name: 'Save and continue' }).click();
  while (await c.getByRole('button', { name: 'Save and continue' }).isVisible()) await c.getByRole('button', { name: 'Save and continue' }).click();
  await c.getByRole('button', { name: 'Submit answers' }).click();
  await expect(c.getByRole('heading', { name: 'Thank you' })).toBeVisible();
  await phone.close();

  // SM-08: review, settle the conflict, lock
  await page.goto(`/sales/opportunities/${opp.id}/scoping/review`);
  await expect(page.getByRole('heading', { name: 'Review answers' })).toBeVisible();
  const row = page.getByRole('row', { name: /SQ-C.07/ }).first();
  await expect(row).toContainText('6 (estimate)');
  await expect(row).toContainText('12');
  await expect(row).toContainText('A-02a → A-02b');
  await expect(page.getByRole('row', { name: /SQ-C.08/ })).toContainText('Vendor review priced per vendor');
  await expect(page.getByRole('button', { name: 'Lock and build proposal' })).toBeDisabled();
  await noSideways(page, 'SM-08');
  await page.screenshot({ path: `${SHOTS}/SM08-review-answers-1440.png`, fullPage: true });
  await row.getByLabel('Client').check();
  await row.getByRole('button', { name: 'Settle' }).click();
  await expect(page.getByText('No conflicts.')).toBeVisible();
  await page.getByRole('button', { name: 'Lock questionnaire' }).click();
  await expect(page.getByText('Version 1 locked.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Unlock for edits' })).toBeVisible();
});

test('question bank and mapping rules tabs', async ({ page }) => {
  await signIn(page, 'admin@futran.demo');
  await page.goto('/staff/admin/catalog/questions');
  await expect(page.getByText(/Starter — replace with the Sales Collateral questionnaire/)).toBeVisible();
  await expect(page.getByRole('row', { name: /SQ-A.02/ })).toContainText('Internal, never sent');
  await page.goto('/staff/admin/catalog/rules');
  await expect(page.getByRole('row', { name: /MR-01a/ })).toContainText('A-02a');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: `${SHOTS}/SM14-mapping-rules-1440.png`, fullPage: false });
});
