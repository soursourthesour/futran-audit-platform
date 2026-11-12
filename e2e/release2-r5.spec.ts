import { test, expect, type Page } from '@playwright/test';
import { openNav } from './nav';

/* Release 2 R5: SM-13 hand-off to delivery, G-01 plan and usage, G-02 engagement commercials and change orders,
   G-03 time and hours. The e2e seed (app.demo.r5) hands off a won proposal for Acme Staffing LLC. */

const SHOTS = process.env.R5_SHOTS || '/mnt/user-data/outputs/release2/r5';

async function signIn(page: Page, email: string) {
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/login/);
  await page.waitForLoadState('networkidle');
}

async function shoot(page: Page, name: string) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(300);
  const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(scroll, `${name} scrolls sideways`).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

type Ids = { opp: string; client: string; engagement: string };
let ids: Ids;

async function findIds(page: Page): Promise<Ids> {
  const opps = await page.request.get('/api/v1/opportunities').then((r) => r.json());
  const list = Array.isArray(opps) ? opps : opps.items ?? opps.opportunities ?? [];
  const opp = list.find((o: { client_name: string; trigger: string }) => o.client_name === 'Acme Staffing LLC' && o.trigger === 'manual');
  const h = await page.request.get(`/api/v1/sales/opportunities/${opp.id}/handoff`).then((r) => r.json());
  const eng = h.items.find((i: { kind: string; label: string }) => i.kind === 'engagement' && i.label.includes('Initial'));
  return { opp: opp.id, client: h.client_id, engagement: eng.ref_id };
}

test.describe.serial('Release 2 R5: hand-off, plan, commercials, time', () => {
  test('SM-13: the Sales Officer sees what the won proposal created and confirms the hand-off', async ({ page }) => {
    await signIn(page, 'sales@futran.demo');
    ids = await findIds(page);
    await page.goto(`/sales/opportunities/${ids.opp}/handoff`);
    await expect(page.getByRole('heading', { name: 'Won — hand off to delivery' })).toBeVisible();
    const table = page.getByRole('table').first();
    for (const text of ['Client organization', /Order ORD-/, 'Engagement draft · Initial AI governance assessment', 'Engagement draft · LL144 bias audit', /Subscription · Monitor Plus/, 'Partner commission']) {
      await expect(table.getByText(text).first()).toBeVisible();
    }
    await expect(page.getByText('Nothing is sent to the client from this screen')).toBeVisible();
    await shoot(page, 'SM13-handoff');
    await page.getByRole('button', { name: 'Confirm handoff' }).click();
    await expect(page.getByText('Hand-off confirmed.')).toBeVisible();
  });

  test('G-01: the Futran Admin sees plan, entitlements with usage, order lines and runs the billing export', async ({ page }) => {
    await signIn(page, 'admin@futran.demo');
    await page.goto(`/staff/clients/${ids.client}/plan`);
    await expect(page.getByRole('heading', { name: 'Plan, entitlements and usage' })).toBeVisible();
    await expect(page.getByText('Monitor Plus').first()).toBeVisible();
    await expect(page.getByText('47 / 50 · 94%')).toBeVisible();
    await expect(page.getByRole('cell', { name: 'M-01e' })).toBeVisible();
    await shoot(page, 'G01-plan');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: /Export all clients/ }).click();
    expect((await download).suggestedFilename()).toMatch(/^billing-\d{4}-\d{2}-all-clients\.csv$/);
  });

  test('G-02: the Engagement Manager sees fee, milestones and the change order; an Auditor gets no fees', async ({ page }) => {
    await signIn(page, 'manager@futran.demo');
    await page.goto(`/e/${ids.engagement}/commercial`);
    await expect(page.getByRole('heading', { name: 'Commercial' })).toBeVisible();
    await expect(page.getByText('Hidden from Auditors.')).toBeVisible();
    await expect(page.getByRole('cell', { name: 'A-02b' })).toBeVisible();
    await expect(page.getByRole('cell', { name: '50% on start' })).toBeVisible();
    await page.getByRole('button', { name: 'CO-001' }).first().click();
    await expect(page.getByText('CAICO approval in client app — sent')).toBeVisible();
    await shoot(page, 'G02-commercial');
    await signOut(page);
    await signIn(page, 'auditor1@futran.demo');
    const r = await page.request.get(`/api/v1/e/${ids.engagement}/commercial`);
    expect(r.status()).toBe(403);
    const cos = await page.request.get(`/api/v1/e/${ids.engagement}/change-orders`).then((x) => x.text());
    expect(cos).not.toContain('unit_price');
  });

  test('G-03: an auditor logs and submits a week; the Chief Auditor sees banks, retainers and margins', async ({ page }) => {
    await signIn(page, 'admin@futran.demo');
    await page.goto('/staff/time');
    await page.getByLabel('Cost per hour (US$)').fill('95');
    await page.getByLabel('From').fill('2026-01-01');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('cell', { name: '$95.00' })).toBeVisible();
    await signOut(page);

    await signIn(page, 'auditor1@futran.demo');
    await openNav(page, 'Time and hours');
    await expect(page.getByRole('heading', { name: 'Time and hours' })).toBeVisible();
    await page.getByRole('button', { name: 'Add row' }).click();
    const row = page.locator('table.timesheet tbody tr').first();
    await row.getByLabel('Charged to').selectOption({ label: 'Acme Staffing LLC · Initial AI governance assessment ' + new Date().getFullYear() });
    await row.getByLabel('Mon hours').fill('6');
    await row.getByLabel('Tue hours').fill('7.5');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Week saved.')).toBeVisible();
    await page.getByRole('button', { name: 'Add row' }).click();
    const bank = page.locator('table.timesheet tbody tr').nth(1);
    await bank.getByLabel('Charged to').selectOption({ label: 'Acme Staffing LLC · Advisor hours bank' });
    await bank.getByLabel('Activity').selectOption('advisory');
    await bank.getByLabel('Wed hours').fill('2');
    await page.getByRole('button', { name: 'Submit week' }).click();
    await expect(page.getByText('Week submitted for approval.')).toBeVisible();
    await signOut(page);

    await signIn(page, 'chief@futran.demo');
    await page.goto('/staff/time');
    await expect(page.getByRole('heading', { name: 'Hours banks and retainers' })).toBeVisible();
    await expect(page.getByText(/18 h left · 10% used/)).toBeVisible();
    await expect(page.getByText('M-12 Incident retainer')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Margin by engagement/ })).toBeVisible();
    const audit = page.getByRole('row', { name: /Acme Staffing LLC · Initial AI governance assessment/ });
    await expect(audit.getByRole('cell', { name: /^\$1,28[23]$/ })).toBeVisible();  // 13.5 h × $95
    await expect(audit.getByRole('cell', { name: '97%' })).toBeVisible();
    await shoot(page, 'G03-time');
  });
});
