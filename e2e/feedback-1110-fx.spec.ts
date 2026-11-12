import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { navLink, openNav } from './nav';

/* Feedback of 10 November, workstream FX: Futran users and departments, Client users (F1), no Law library section tabs (F3),
   the roles pivot (F4) and Trust Center confirmations by client (F5). Runs against the "late" server (ABC Corp and
   Meridian GmbH both have people), at 1440 px and 375 px. */

const SHOTS = process.env.FX_SHOTS || '/mnt/user-data/outputs/feedback-1110/fx';
mkdirSync(SHOTS, { recursive: true });
const PW = 'Demo-Password-2026';
test.use({ baseURL: `http://127.0.0.1:${Number(process.env.E2E_PORT || 8765) + 1}` });
const run = Date.now().toString(36).slice(-4);  // names unique to this run, so a re-run against the same server still works

async function signIn(page: Page, email: string, staff = false) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email').fill(email);
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
  // start every Futran test from the law library (every Futran role here can open it), not from a role home another
  // workstream is changing at the same time
  if (staff) { await page.goto('/reg'); await expect(page.locator('h1')).toBeVisible(); }
}

async function csrf(page: Page): Promise<string> {
  return page.evaluate(() => fetch('/api/v1/auth/me').then((r) => r.json()).then((m) => m.csrf_token));
}

async function noSidewaysScroll(page: Page, what: string) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, `${what} scrolls sideways`).toBeLessThanOrEqual(0);
}

async function shoot(page: Page, name: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(200);
  await noSidewaysScroll(page, name);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
}

test('F1: the Futran Admin keeps Futran departments and sets a user\'s department', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, 'admin@futran.demo', true);
  await openNav(page, 'Users');
  const depts = page.getByRole('list', { name: 'Futran departments' });
  for (const name of [`Audit delivery ${run}`, `Business development ${run}`]) {
    await page.getByLabel('New department').fill(name);
    await page.getByRole('button', { name: 'Add department' }).click();
    await expect(page.getByText(`Added ${name}.`)).toBeVisible();
  }
  await expect(depts.getByText(`Audit delivery ${run}`)).toBeVisible();

  await page.getByRole('button', { name: 'Add user' }).click();
  await page.getByLabel('Full name').fill('Priya Delivery');
  await page.getByLabel('Work email').fill(`priya.${run}@futran.demo`);
  await page.getByLabel('Department').first().selectOption({ label: `Audit delivery ${run}` });
  await page.getByRole('button', { name: 'Add and send invitation' }).click();
  const grid = page.getByRole('table', { name: 'Futran users' });
  const row = grid.getByRole('row', { name: new RegExp(`priya.${run}@futran.demo`) });
  await expect(row.getByRole('cell', { name: `Audit delivery ${run}` })).toBeVisible();

  // edit: move her to another department
  await row.getByRole('button', { name: /^Actions for Priya Delivery/ }).click();
  await page.getByRole('menuitem', { name: 'Edit' }).click();
  const dlg = page.getByRole('dialog', { name: 'Edit Priya Delivery' });
  await dlg.getByLabel('Department').selectOption({ label: `Business development ${run}` });
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(row.getByRole('cell', { name: `Business development ${run}` })).toBeVisible();

  // the department filter
  await page.getByRole('search', { name: 'Filter futran users' }).getByLabel('Department').selectOption({ label: `Business development ${run}` });
  await expect(grid.getByRole('row')).toHaveCount(2);  // the header and Priya
  await shoot(page, 'users-departments');
  await page.getByRole('button', { name: 'Clear filters' }).click();

  // a client never reaches Futran's departments
  await signIn(page, 'katrin.vogel@meridian.example');
  const r = await page.request.get('/api/v1/admin/departments');
  expect([403, 404]).toContain(r.status());
  const w = await page.request.post('/api/v1/admin/departments', { data: { name: 'x' }, headers: { 'X-CSRF-Token': await csrf(page) } });
  expect([403, 404]).toContain(w.status());
});

test('F1: Administration > Client users is a read-only list for the Admin and Chief Auditor', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, 'admin@futran.demo', true);
  await openNav(page, 'Client users');
  await expect(page.getByRole('heading', { level: 1, name: 'Client users' })).toBeVisible();
  const grid = page.getByRole('table', { name: 'Client users' });
  await expect(grid.getByRole('cell', { name: 'ABC Corp' }).first()).toBeVisible();
  await expect(grid.getByRole('cell', { name: 'Meridian GmbH' }).first()).toBeVisible();
  await expect(grid.getByRole('button', { name: /^Actions for/ })).toHaveCount(0);  // read-only
  await expect(page.getByRole('button', { name: /Add|Edit|Disable|Invite/ })).toHaveCount(0);
  const filters = page.getByRole('search', { name: 'Filter client users' });
  await filters.getByLabel('Client').selectOption({ label: (await filters.getByLabel('Client').locator('option', { hasText: 'Meridian GmbH' }).textContent())! });
  await expect(grid.getByRole('cell', { name: 'ABC Corp' })).toHaveCount(0);
  await expect(grid.getByText('Katrin Vogel', { exact: true })).toBeVisible();
  await filters.getByLabel('AI compliance role').selectOption({ index: 1 });
  await expect(grid.getByRole('row').nth(1)).toBeVisible();
  await filters.getByRole('button', { name: 'Clear filters' }).click();
  await shoot(page, 'client-users');

  await openNav(page, 'Audit log');
  await expect(page.getByText(/Viewed the client users list/).first()).toBeVisible();

  // the Chief Auditor has it; an Auditor does not
  await signIn(page, 'chief@futran.demo', true);
  await expect(navLink(page, 'Client users')).toHaveCount(1);
  await signIn(page, 'auditor1@futran.demo', true);
  await expect(navLink(page, 'Client users')).toHaveCount(0);
  expect((await page.request.get('/api/v1/admin/client-users')).status()).toBe(403);
  await signIn(page, 'katrin.vogel@meridian.example');
  expect([403, 404]).toContain((await page.request.get('/api/v1/admin/client-users')).status());
});

test('F3: the Law library pages have no section tabs; the menu stays', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, 'chief@futran.demo', true);
  for (const name of ['Law library', 'Refresh and review', 'Roles and committees']) {
    await openNav(page, name);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Law library sections' })).toHaveCount(0);
  }
  for (const name of ['Law library', 'Refresh and review', 'Roles and committees', 'Obligations to review', 'Regulatory updates']) await expect(navLink(page, name)).toHaveCount(1);
  await openNav(page, 'Law library');
  await page.getByPlaceholder('Law, citation or requirement').fill('LL144');
  await page.getByRole('link', { name: /NYC|New York/ }).first().click();
  await expect(page.getByRole('navigation', { name: 'Law library sections' })).toHaveCount(0);
  await openNav(page, 'Law library');
  await shoot(page, 'law-library');
});

test('F4: Roles and committees as a pivot of the regulations you pick, with a CSV export', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, 'chief@futran.demo', true);
  await openNav(page, 'Roles and committees');
  await expect(page.getByRole('heading', { level: 1, name: 'Roles and committees' })).toBeVisible();
  await expect(page.getByText('Choose one or more regulations to see the roles and committees they require.')).toBeVisible();
  const picker = page.getByRole('group', { name: 'Regulations by jurisdiction' });
  for (const [find, label] of [['LL144', 'NYC LL144'], ['EU AI', 'EU AI Act'], ['Colorado', null]] as const) {
    await page.getByLabel('Find regulations').fill(find);
    const box = label ? picker.getByRole('checkbox', { name: new RegExp(`^${label}(\\s|$)`) }) : picker.getByRole('checkbox').first();
    await box.check();
  }
  await page.getByLabel('Find regulations').fill('');
  await expect(page.getByRole('list', { name: 'Selected regulations' }).getByRole('button')).toHaveCount(3);
  const table = page.getByRole('table', { name: 'Roles by regulation' });
  await expect(table.getByRole('columnheader')).toHaveCount(4);
  const bias = table.getByRole('row', { name: /Bias testing lead/ });
  await expect(bias.getByText('Required').first()).toBeVisible();
  await expect(bias.getByText(/Needed by/).first()).toBeVisible();
  await expect(table.getByText('Committees and programs')).toBeVisible();
  await expect(page.getByRole('list', { name: 'Needed by any selected regulation' }).getByText('Bias testing lead')).toBeVisible();
  expect(page.url()).toMatch(/laws=/);  // the selection is kept in the page address

  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export CSV' }).click()]);
  const text = readFileSync(await dl.path(), 'utf8').replace(/^﻿/, '');
  const lines = text.trim().split(/\r?\n/);
  expect(lines[0]).toContain('NYC LL144');
  expect(lines.some((l) => l.includes('Bias testing lead'))).toBeTruthy();
  for (const l of lines) for (const c of l.split(',')) expect(c.replace(/^"/, '')).not.toMatch(/^[=+\-@]/);
  await shoot(page, 'roles-pivot');

  // the catalogue is still one click away
  await page.getByRole('button', { name: 'Full catalogue' }).click();
  await expect(page.getByRole('heading', { name: 'Role and committee catalogue' })).toBeVisible();
  await page.getByRole('button', { name: 'By regulation' }).click();
  await expect(page.getByRole('list', { name: 'Selected regulations' }).getByRole('button')).toHaveCount(3);
});

test('F5: Trust Center confirmations are grouped by client, with a filter and a count per client', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const made: { email: string; ids: string[] }[] = [];
  const make = async (email: string, slug: string, titles: string[]) => {
    await signIn(page, email);
    const mine = { email, ids: [] as string[] };
    made.push(mine);
    const h = { 'X-CSRF-Token': await csrf(page) };
    const pg = await page.request.put('/api/v1/trust/page', { headers: h, data: { slug, title: 'How we govern our use of AI', intro: 'Our commitments.', live: true } });
    expect(pg.ok(), await pg.text()).toBeTruthy();
    for (const t of titles) {
      const it = await page.request.post('/api/v1/trust/items', { headers: h, data: { kind: 'commitment', title: t, body: 'A trained person reviews every recommendation.' } });
      expect(it.ok(), await it.text()).toBeTruthy();
      const id = (await it.json()).id as string;
      mine.ids.push(id);
      const ap = await page.request.post(`/api/v1/trust/items/${id}/approve`, { headers: h });
      expect(ap.ok(), await ap.text()).toBeTruthy();
    }
  };
  await make('katrin.vogel@meridian.example', `meridian-${run}`, [`Meridian commitment ${run}`]);
  await make('maria.lopez@abccorp.example', `abc-${run}`, [`ABC commitment ${run}`, `ABC hiring ${run}`]);

  await signIn(page, 'chief@futran.demo', true);
  await openNav(page, 'Trust Center confirmations');
  const chips = page.getByRole('list', { name: 'Waiting by client' });
  await expect(chips.getByText('ABC Corp')).toBeVisible();
  await expect(chips.getByText('Meridian GmbH')).toBeVisible();
  const q = page.getByRole('table', { name: 'Items to confirm' });
  const heads = q.locator('tr.dg-group-row');
  await expect(heads.first()).toContainText('ABC Corp');  // A to Z
  await expect(heads.filter({ hasText: 'Meridian GmbH' })).toContainText(/\d+ waiting/);
  // sorting by client puts Meridian first
  await q.getByRole('button', { name: /^Client/ }).click();
  await expect(heads.first()).toContainText('Meridian GmbH');
  // the client filter
  const sel = page.getByRole('search', { name: 'Filter items to confirm' }).getByLabel('Client');
  const opt = await sel.locator('option', { hasText: 'ABC Corp' }).textContent();
  expect(opt).toMatch(/ABC Corp \(\d+\)/);
  await sel.selectOption({ label: opt! });
  await expect(q.getByRole('row', { name: new RegExp(`Meridian commitment ${run}`) })).toHaveCount(0);
  await expect(q.getByRole('row', { name: new RegExp(`ABC hiring ${run}`) })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await q.getByRole('button', { name: /^Client/ }).click();  // back to unsorted, then
  await q.getByRole('button', { name: /^Client/ }).click();  // A to Z for the screenshot
  await shoot(page, 'trust-confirmations');

  // leave the clients' editors as they were for the other specs on this server: return and remove the items made here
  for (const m of made) for (const id of m.ids) {
    const r = await page.request.post(`/api/v1/trust/items/${id}/return`, { headers: { 'X-CSRF-Token': await csrf(page) }, data: { note: 'Test item.' } });
    expect(r.ok(), await r.text()).toBeTruthy();
  }
  for (const m of made) {
    await signIn(page, m.email);
    const h = { 'X-CSRF-Token': await csrf(page) };
    for (const id of m.ids) expect((await page.request.delete(`/api/v1/trust/items/${id}`, { headers: h })).ok()).toBeTruthy();
  }
});
