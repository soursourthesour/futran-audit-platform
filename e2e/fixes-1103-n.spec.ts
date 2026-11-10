import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { expectNav, mainNav, navLink, openNav } from './nav';

/* 11-03 review fixes, workstream N: grouped navigation for Futran and clients (F4, C1), the obligations count (F6),
   templates (F10), law library and reference data (F3, F11), add user (F12), the audit log's When column (F13), the
   outbox as a tab of the email log (F14b) and "Needed by" explained (F2). Futran screens run on the fresh server; the
   client navigation runs on the late server (ABC Corp at stage 6 with every client role filled). */

const SHOTS = process.env.WSN_SHOTS || '/mnt/user-data/outputs/fixes-1103/n';
mkdirSync(SHOTS, { recursive: true });
const PW = 'Demo-Password-2026';
const LATE = `http://127.0.0.1:${Number(process.env.E2E_PORT || 8765) + 1}`;

async function signIn(page: Page, email: string, staff: boolean) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {  // first sign-in: terms, then the employee data notice
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
    else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
    else if (p.startsWith('/welcome/mailbox')) { await page.getByRole('button', { name: 'Not now' }).click(); }
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

async function api(page: Page, method: 'GET' | 'POST', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

/** No sideways scrolling, and every visible control in the header and page is at least 44 px tall at phone width. */
async function phoneLayout(page: Page, where: string) {
  const r = await page.evaluate(() => {
    const wide = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small: string[] = [];
    document.querySelectorAll<HTMLElement>('.shell-header button, .shell-nav a').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.height < 44) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(b.height)}px`);
    });
    return { wide, small };
  });
  expect(r.wide, `${where}: page scrolls sideways`).toBeLessThanOrEqual(0);
  expect(r.small, `${where}: header controls under 44 px`).toEqual([]);
}

async function shots(page: Page, name: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), `${name} at 375 px scrolls sideways`).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

/** At 1440 px the groups sit on one row of the header. */
async function oneRow(page: Page) {
  const tops = await mainNav(page).locator(':scope > *').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(new Set(tops).size, `navigation rows (tops ${tops.join(', ')})`).toBe(1);
}

const group = (page: Page, name: string) => mainNav(page).getByRole('button', { name: new RegExp(`^${name}`) });

test.describe('Futran', () => {
  test('F4: the Futran Admin navigation is grouped into menus, keyboard and phone friendly', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, 'admin@futran.demo', true);
    for (const g of ['Home and work', 'Law library', 'Administration']) await expect(group(page, g)).toBeVisible();
    await oneRow(page);
    await expectNav(page, ['Admin home', 'Dashboard', 'Clients', 'Law library', 'Refresh and review', 'Roles and committees', 'Client alerts', 'Templates', 'Reference data', 'Users', 'Audit log', 'Email and groups', 'Email log', 'Settings'],
      ['Outbox', 'Regulatory master', 'My work', 'QA queue', 'Litigation', 'Opportunities']);
    await expect(navLink(page, 'Users')).toBeHidden();  // closed until its menu opens

    // a click opens a menu; Escape closes it and returns focus; a click outside closes it
    const admin = group(page, 'Administration');
    await admin.click();
    await expect(admin).toHaveAttribute('aria-expanded', 'true');
    for (const name of ['Users', 'Templates', 'Reference data', 'Email and groups', 'Email log', 'Audit log', 'Settings']) await expect(navLink(page, name)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/futran-nav-1440.png` });
    await page.keyboard.press('Escape');
    await expect(admin).toHaveAttribute('aria-expanded', 'false');
    await expect(admin).toBeFocused();
    await admin.click();
    await page.getByRole('heading', { level: 1 }).click();
    await expect(admin).toHaveAttribute('aria-expanded', 'false');

    // keyboard: ArrowDown on a group opens it and moves into it
    const law = group(page, 'Law library');
    await law.focus();
    await page.keyboard.press('ArrowDown');
    await expect(navLink(page, 'Law library')).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(navLink(page, 'Refresh and review')).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(navLink(page, 'Roles and committees')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/reg\/roles$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Role and committee catalogue' })).toBeVisible();
    await expect(law).toHaveAttribute('aria-expanded', 'false');  // a new page closes the menu
    await expect(law).toHaveClass(/active/);                     // and its group shows as current
    await expect(navLink(page, 'Roles and committees')).toHaveAttribute('aria-current', 'page');
    await expect(navLink(page, 'Law library')).not.toHaveAttribute('aria-current', 'page');

    // phones: the groups sit behind Menu as an accordion, with the current page's group open
    await page.setViewportSize({ width: 375, height: 812 });
    const menu = page.getByRole('button', { name: 'Menu' });
    await menu.click();
    await expect(law).toHaveAttribute('aria-expanded', 'true');
    await expect(navLink(page, 'Roles and committees')).toBeVisible();
    await expect(navLink(page, 'Users')).toBeHidden();
    await phoneLayout(page, 'Futran menu');
    await page.screenshot({ path: `${SHOTS}/futran-nav-375.png`, fullPage: true });
    await group(page, 'Administration').click();
    await navLink(page, 'Audit log').click();
    await expect(page).toHaveURL(/\/admin\/audit-log$/);
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
  });

  test('F6: obligations waiting for a decision show a count on the navigation', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, 'chief@futran.demo', true);
    const laws = await api(page, 'GET', '/reg/laws');
    const ll144 = laws.groups.flatMap((g: { laws: { id: string; short_name: string }[] }) => g.laws).find((l: { short_name: string }) => /144/.test(l.short_name));
    await api(page, 'POST', `/reg/laws/${ll144.id}/obligations/extract`);
    const { obligations_to_review: n } = await api(page, 'GET', '/nav/badges');
    expect(n).toBeGreaterThan(0);
    await page.goto('/audits');
    await expect(group(page, 'Law library')).toContainText(String(n));
    await group(page, 'Law library').click();
    const link = navLink(page, /^Obligations to review/);
    await expect(link).toContainText(String(n));
    await page.screenshot({ path: `${SHOTS}/obligations-count-1440.png` });
    await link.click();
    await expect(page).toHaveURL(/\/reg\/obligations$/);
  });

  test('F12, F14b: the admin adds a user from Users and reads the invitation in the email log outbox tab', async ({ page }) => {
    await signIn(page, 'admin@futran.demo', true);
    await openNav(page, 'Users');
    await page.getByRole('button', { name: 'Add user' }).click();
    await page.getByLabel('Full name').fill('Rowan Reviewer');
    await page.getByLabel('Work email').fill('rowan@futran.demo');
    await page.getByRole('button', { name: 'Add and send invitation' }).click();
    await expect(page.getByRole('cell', { name: 'rowan@futran.demo' })).toBeVisible();
    await shots(page, 'users');

    await openNav(page, 'Email log');
    await page.getByRole('tab', { name: 'Outbox (test mode)' }).click();
    await expect(page).toHaveURL(/\/admin\/log\?tab=outbox$/);
    const outbox = page.getByRole('table', { name: 'Outbox' });
    await expect(outbox.getByRole('cell', { name: 'rowan@futran.demo' }).first()).toBeVisible();
    await shots(page, 'email-log-outbox');
    await page.getByRole('tab', { name: 'Email and admin log' }).click();
    await expect(page.getByRole('heading', { name: 'Emails sent' })).toBeVisible();
    await shots(page, 'email-log');

    await page.goto('/admin/outbox');  // the old route lands on the tab
    await expect(page).toHaveURL(/\/admin\/log\?tab=outbox$/);
    await expect(page.getByRole('tab', { name: 'Outbox (test mode)' })).toHaveAttribute('aria-selected', 'true');

    // the Chief Auditor reads the users list and is told who adds users
    await signIn(page, 'chief@futran.demo', true);
    await openNav(page, 'Users');
    await expect(page.getByText('Only a Futran Admin adds users and changes their roles.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add user' })).toHaveCount(0);
  });

  test('F3, F11: reference data and the law library explain each other, and a law opens its own record', async ({ page }) => {
    await signIn(page, 'admin@futran.demo', true);
    await openNav(page, 'Reference data');
    await expect(page.getByText(/Reference data is the lists the platform uses around the laws/)).toBeVisible();
    await expect(page.getByRole('main').getByRole('link', { name: 'Open the law library' })).toHaveAttribute('href', '/reg');
    await page.getByLabel('Geography').selectOption({ label: 'Illinois (US)' });
    await page.getByRole('button', { name: /AI Video Interview Act/ }).click();
    await shots(page, 'reference-data');
    await page.getByRole('link', { name: 'Open the full law record' }).click();
    await expect(page).toHaveURL(/\/reg\/[0-9a-f-]{36}$/);
    await expect(page.getByRole('heading', { level: 1, name: /Video Interview/ })).toBeVisible();

    await openNav(page, 'Law library');
    await expect(page.getByText(/The law library is the laws themselves/)).toBeVisible();
    await expect(page.getByRole('main').getByRole('link', { name: 'Open reference data' })).toHaveAttribute('href', '/admin/reference');

    // without the editor, a law opens straight on its record
    await signIn(page, 'chief@futran.demo', true);
    await openNav(page, 'Reference data');
    await page.getByLabel('Geography').selectOption({ label: 'Illinois (US)' });
    await page.getByRole('button', { name: /AI Video Interview Act/ }).click();
    await expect(page).toHaveURL(/\/reg\/[0-9a-f-]{36}$/);
  });

  test('F10: templates have no version chip, an (i) gives the revision, and the text box fits its text', async ({ page }) => {
    await signIn(page, 'admin@futran.demo', true);
    await openNav(page, 'Templates');
    const list = page.getByRole('region', { name: 'Templates' });
    await expect(list.getByText(/^v\d+$/)).toHaveCount(0);
    await list.getByRole('button').first().click();
    const info = page.getByRole('button', { name: /^About .* revision$/ });
    await info.click();
    await expect(page.getByRole('tooltip')).toContainText(/Revision \d+/);
    await expect(page.getByRole('tooltip')).toContainText(/Approved|standard text/);
    const box = page.getByLabel('Template text');
    const fit = await box.evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(fit, 'the text box shows all of its text').toBeLessThanOrEqual(2);
    await shots(page, 'templates');
  });

  test('F13: the audit log When column keeps date and time on one line', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, 'admin@futran.demo', true);
    await openNav(page, 'Audit log');
    const when = page.locator('table tbody tr td').first();
    await expect(when).toBeVisible();
    const r = await when.evaluate((td) => ({ ws: getComputedStyle(td).whiteSpace, h: td.getBoundingClientRect().height, lh: parseFloat(getComputedStyle(td).lineHeight) || 20 }));
    expect(r.ws).toBe('nowrap');
    await page.screenshot({ path: `${SHOTS}/audit-log-1440.png` });
  });

  test('F2: "Needed by" is explained on the roles catalogue', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, 'admin@futran.demo', true);
    await openNav(page, 'Roles and committees');
    // every gate-stage role is checked once, when the system is submitted for go-live; ongoing and yearly are not
    await expect(page.getByText(/Needed by is the point in the system's life/)).toBeVisible();
    await expect(page.getByText(/checked when the system is submitted for go-live/).first()).toBeVisible();
    await expect(page.getByText(/Roles needed for ongoing or yearly work are not checked at go-live/).first()).toBeVisible();
    await page.getByRole('button', { name: 'About Needed by' }).first().click();
    await expect(page.getByRole('tooltip')).toContainText(/checked when the system is submitted for go-live/);
    await expect(page.getByRole('tooltip')).toContainText(/not checked at go-live/);
    await page.screenshot({ path: `${SHOTS}/roles-needed-by-1440.png` });
  });
});

test.describe('client', () => {
  test.use({ baseURL: LATE });

  test('C1: the CAICO navigation is grouped into menus at 1440 and 375 px', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, 'maria.lopez@abccorp.example', false);
    for (const g of ['Audit', 'AI governance', 'People and training', 'Email']) await expect(group(page, g)).toBeVisible();
    await oneRow(page);
    await expectNav(page, ['Getting started', 'People', 'AI system register', 'Company roles', 'Add-ons', 'Governance', 'Attestation', 'AI inventory', 'Review', 'Report', 'Responses', 'Remediation', 'Email connection', 'Groups', 'Email log'],
      ['Admin home', 'Summary', 'Data review', 'My department', 'My tasks']);
    await expect(navLink(page, 'Getting started')).toBeVisible();  // a group with one entry is a plain link
    await group(page, 'AI governance').click();
    await page.screenshot({ path: `${SHOTS}/client-nav-1440.png` });
    await navLink(page, 'Company roles').click();
    await expect(page).toHaveURL(/\/governance\/roles$/);
    await expect(group(page, 'AI governance')).toHaveClass(/active/);
    await expect(navLink(page, 'Company roles')).toHaveAttribute('aria-current', 'page');
    await expect(navLink(page, 'Governance')).not.toHaveAttribute('aria-current', 'page');

    await page.setViewportSize({ width: 375, height: 812 });
    await page.getByRole('button', { name: 'Menu' }).click();
    await expect(navLink(page, 'Company roles')).toBeVisible();
    await phoneLayout(page, 'client menu');
    await page.screenshot({ path: `${SHOTS}/client-nav-375.png`, fullPage: true });
    await group(page, 'Audit').click();
    await navLink(page, 'Report').click();
    await expect(page).toHaveURL(/\/report$/);
  });
});
