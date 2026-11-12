import { mkdirSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import { test, expect, type Page } from '@playwright/test';
import { navLink } from './nav';

/* 10 Nov feedback, workstream HM. Runs on the "late" server: ABC Corp at stage 6 with every client role filled, and
   Meridian GmbH at stage 3.
   F2: every Futran role home shows the Dashboard (KPIs, the engagements list and recent activity, scoped as the Dashboard
       was), the "Dashboard" menu entry is gone and /audits opens the person's home.
   U2: every client home shows the nine audit stages as a timeline you can click. */

const SHOTS = '/mnt/user-data/outputs/feedback-1110/hm';
mkdirSync(SHOTS, { recursive: true });
const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';

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

/** No sideways page scroll, and every control is at least 44 px tall. */
async function checkPhone(page: Page, where: string) {
  const r = await page.evaluate(() => {
    const wide = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small: string[] = [];
    document.querySelectorAll<HTMLElement>('button, a.btn, .shell-nav a, .timeline a, select, textarea, input:not([type=checkbox]):not([type=radio]):not([type=hidden])').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.height < 44) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(b.height)}px`);
    });
    return { wide, small };
  });
  expect(r.wide, `${where}: page scrolls sideways`).toBeLessThanOrEqual(0);
  expect(r.small, `${where}: controls under 44 px`).toEqual([]);
}

async function shots(page: Page, name: string, phoneCheck = true) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(250);
  if (phoneCheck) await checkPhone(page, name);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
}

// ---- F2: the Futran homes show the Dashboard
const FUTRAN = [
  { who: 'Chief Auditor', email: 'chief@futran.demo', home: /\/staff\/chief$/, heading: 'Chief Auditor home', shot: 'futran-chief-home', own: /Waiting for your approval/ },
  { who: 'Admin', email: 'admin@futran.demo', home: /\/staff\/admin$/, heading: 'Admin console', shot: 'futran-admin-home', own: /Futran users/ },
  { who: 'Auditor', email: 'auditor1@futran.demo', home: /\/my-work$/, heading: 'My work', shot: 'futran-auditor-my-work', own: /Today ·/ },
  { who: 'QA Reviewer', email: 'qa@futran.demo', home: /\/qa$/, heading: 'QA review queue', shot: 'futran-qa-queue', own: /Waiting ·/ },
  { who: 'Engagement Manager', email: 'em@futran.demo', home: /\/my-work$/, heading: 'My work', shot: 'futran-em-my-work', own: /Today ·/ },
  { who: 'Legal Reviewer', email: 'legal@futran.demo', home: /\/my-work$/, heading: 'My work', shot: 'futran-legal-my-work', own: /Today ·/ },
];

for (const c of FUTRAN) {
  test(`F2: the ${c.who} home shows the Dashboard with its own lists, and /audits opens it`, async ({ page }) => {
    await signIn(page, c.email, true);
    await expect(page).toHaveURL(c.home);
    await expect(page.getByRole('heading', { level: 1, name: c.heading })).toBeVisible();
    await expect(page.getByText(c.own).first()).toBeVisible();  // the role's own list stays
    // the Dashboard: KPIs, the engagements list and recent activity
    const dash = page.getByRole('region', { name: 'Engagements' });
    await expect(dash).toBeVisible();
    for (const k of ['In progress', 'Completed', 'Awaiting client']) await expect(dash.getByText(k, { exact: true }).first()).toBeVisible();
    await expect(dash.getByRole('heading', { name: 'Recent activity' })).toBeVisible();
    // exactly the engagements the Dashboard API gives this person (all for the Chief Auditor and Admin, assigned for others)
    const api = await (await page.request.get('/api/v1/engagements?filter=all&q=')).json();
    await expect(dash.locator('tbody tr')).toHaveCount(api.rows.length);
    for (const r of api.rows) await expect(dash.getByRole('link', { name: r.client_name }).first()).toBeVisible();
    // no separate Dashboard menu entry; the old address opens this home
    await expect(navLink(page, 'Dashboard')).toHaveCount(0);
    await page.goto('/audits');
    await expect(page).toHaveURL(c.home);
    await expect(page.getByRole('region', { name: 'Engagements' })).toBeVisible();
    await axe(page);
    if (['Chief Auditor', 'Admin', 'Auditor', 'QA Reviewer'].includes(c.who)) await shots(page, c.shot, false);
  });
}

test('F2: an auditor sees only assigned engagements on the home, as on the Dashboard', async ({ page }) => {
  await signIn(page, 'auditor2@futran.demo', true);
  const dash = page.getByRole('region', { name: 'Engagements' });
  await expect(dash.getByRole('link', { name: 'Meridian GmbH' }).first()).toBeVisible();
  await expect(dash.getByRole('link', { name: 'ABC Corp' })).toHaveCount(0);  // not on the ABC team
});

test('F2: the Sales Team still has no engagement information', async ({ page }) => {
  await signIn(page, 'sales@futran.demo', true);
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByRole('region', { name: 'Engagements' })).toHaveCount(0);
  await page.goto('/audits');
  await expect(page).toHaveURL(/\/opportunities$/);
  expect((await page.request.get('/api/v1/engagements?filter=all&q=')).status()).toBe(403);
});

// ---- U2: the audit stage timeline on the client homes
const timeline = (page: Page) => page.getByRole('list', { name: 'Audit stages' });
const stage = (page: Page, n: number, name: string) => timeline(page).getByRole('listitem').filter({ hasText: new RegExp(`Stage ${n}\\b`) }).filter({ hasText: name });

test('U2: Getting started shows the nine stages; a stage opens its screen or its summary', async ({ page }) => {
  await signIn(page, `maria.lopez@${ABC}`, false);
  await expect(page).toHaveURL(/\/start$/);
  await expect(timeline(page).getByRole('listitem')).toHaveCount(9);
  // done, current and upcoming, with dates
  const current = timeline(page).locator('[aria-current="step"]');
  await expect(current).toHaveCount(1);
  await expect(current).toContainText('Futran QA');
  await expect(stage(page, 1, 'Onboarding')).toContainText(/Done/);
  await expect(stage(page, 1, 'Onboarding')).toContainText(/\d{4}/);
  await expect(stage(page, 9, 'Remediation')).toContainText(/Upcoming/);
  await shots(page, 'client-getting-started-timeline');
  // a stage with a screen this person can open goes there
  await stage(page, 3, 'Discovery').getByRole('link').click();
  await expect(page).toHaveURL(/\/attestation$/);
  await page.goBack();
  await stage(page, 7, 'Response').getByRole('link').click();
  await expect(page).toHaveURL(/\/responses$/);
  await page.goBack();
  // Futran QA has no client screen: a short summary instead
  await stage(page, 6, 'Futran QA').getByRole('button').click();
  const dlg = page.getByRole('dialog', { name: /Stage 6 · Futran QA/ });
  await expect(dlg).toContainText('releases the draft report');
  await dlg.getByRole('button', { name: 'Close' }).click();
  await expect(dlg).toHaveCount(0);
});

test('U2: a Contributor gets summaries for the stages whose screens they cannot open, by keyboard too', async ({ page }) => {
  await signIn(page, `tom.reyes@${ABC}`, false);
  await expect(page).toHaveURL(/\/my-tasks$/);
  await expect(timeline(page).getByRole('listitem')).toHaveCount(9);
  // People is not theirs: the Setup stage shows a summary, never a 403 page
  const setup = stage(page, 2, 'Setup').getByRole('button');
  await setup.focus();
  await page.keyboard.press('Enter');
  const dlg = page.getByRole('dialog', { name: /Stage 2 · Setup/ });
  await expect(dlg).toContainText('departments');
  await page.keyboard.press('Escape');
  await expect(dlg).toHaveCount(0);
  await expect(setup).toBeFocused();
  // Discovery: they record use cases in the inventory
  await expect(stage(page, 3, 'Discovery').getByRole('link')).toHaveAttribute('href', '/inventory');
  await expect(stage(page, 8, 'Final report').getByRole('button')).toBeVisible();  // the report is not theirs
  await axe(page);
});

const CLIENT_HOMES = [
  { email: `robert.chen@${ABC}`, home: /\/summary$/, shot: 'client-sponsor-summary-timeline' },
  { email: `daniel.kim@${ABC}`, home: /\/data-review$/, shot: '' },
  { email: `sam.okafor@${ABC}`, home: /\/admin\/home$/, shot: '' },
  { email: `priya.shah@${ABC}`, home: /\/my-department$/, shot: 'client-dept-lead-timeline' },
];
for (const c of CLIENT_HOMES) {
  test(`U2: the timeline is on the home at ${c.home.source}`, async ({ page }) => {
    await signIn(page, c.email, false);
    await expect(page).toHaveURL(c.home);
    await expect(timeline(page).getByRole('listitem')).toHaveCount(9);
    await expect(timeline(page).locator('[aria-current="step"]')).toContainText('Futran QA');
    // every stage is a link or a button, none is dead
    for (let n = 1; n <= 9; n++) await expect(timeline(page).getByRole('listitem').nth(n - 1).locator('a, button')).toHaveCount(1);
    if (c.shot) await shots(page, c.shot);
  });
}

test('U2: on a phone the stages run down the page inside the timeline, with 44 px targets', async ({ page }) => {
  await signIn(page, `katrin.vogel@meridian.example`, false);
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(timeline(page).locator('[aria-current="step"]')).toContainText('Discovery');
  const boxes = await timeline(page).getByRole('listitem').evaluateAll((els) => els.map((e) => e.getBoundingClientRect()).map((b) => ({ top: b.top, bottom: b.bottom, left: b.left })));
  for (let i = 1; i < boxes.length; i++) expect(boxes[i].top, `stage ${i + 1} is below stage ${i}`).toBeGreaterThanOrEqual(boxes[i - 1].bottom - 1);
  await checkPhone(page, 'meridian getting started');
});

test('U2: with no engagement yet the home shows a plain note', async ({ page }) => {
  await signIn(page, `tom.reyes@${ABC}`, false);
  await page.route('**/api/v1/me/stages', (r) => r.fulfill({ json: { engagement: null, stages: [] } }));
  await page.reload();
  await expect(page.getByText('The audit stages appear here once Futran starts your audit.')).toBeVisible();
  await expect(timeline(page)).toHaveCount(0);
});
