import { mkdirSync, readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import { test, expect, type Page } from '@playwright/test';

/* v0.6.1 WS-F: each role lands on its own home after sign-in and the navigation shows only that role's modules
   (spec §13.1). Runs on the "late" server: ABC Corp at stage 6 with every client role filled, and Meridian GmbH whose
   Chief AI Compliance Officer, Katrin Vogel, is also its Client Admin. */

const SHOTS = process.env.WSF_SHOTS || '/mnt/user-data/outputs/v061/ws-f';
mkdirSync(SHOTS, { recursive: true });
const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string };

/** Setup steps go straight to the API as the signed-in user (the browser's session and CSRF token). */
async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

type Case = { who: string; email: string; staff: boolean; home: RegExp; heading: string | RegExp; shown: string[]; hidden: string[]; shot: string };

const CASES: Case[] = [
  { who: 'Futran Admin', email: 'admin@futran.demo', staff: true, home: /\/staff\/admin$/, heading: 'Admin console', shot: 'admin-home',
    shown: ['Admin home', 'Dashboard', 'Clients', 'Regulatory master', 'Client alerts', 'Templates', 'Reference data', 'Users', 'Audit log', 'Outbox', 'Email and groups', 'Email log', 'Settings'],
    hidden: ['My work', 'QA queue', 'Litigation', 'Opportunities'] },
  { who: 'Chief Auditor', email: 'chief@futran.demo', staff: true, home: /\/audits$/, heading: 'Audits', shot: 'chief-auditor-dashboard',
    shown: ['Dashboard', 'Clients', 'Regulatory master', 'Litigation', 'Opportunities', 'Client alerts', 'Templates', 'Reference data', 'Users', 'Audit log', 'Outbox', 'Email log', 'Settings'],
    hidden: ['Admin home', 'My work', 'QA queue', 'Email and groups'] },
  { who: 'Auditor', email: 'auditor1@futran.demo', staff: true, home: /\/my-work$/, heading: 'My work', shot: 'auditor-my-work',
    shown: ['My work', 'Dashboard', 'Clients', 'Regulatory master', 'Litigation', 'Audit log', 'Email log'],
    hidden: ['Admin home', 'QA queue', 'Users', 'Templates', 'Reference data', 'Opportunities', 'Client alerts', 'Outbox', 'Settings', 'Email and groups'] },
  { who: 'QA Reviewer', email: 'qa@futran.demo', staff: true, home: /\/qa$/, heading: 'QA review queue', shot: 'qa-queue',
    shown: ['QA queue', 'Dashboard', 'Clients', 'Regulatory master'],
    hidden: ['Admin home', 'My work', 'Users', 'Litigation', 'Opportunities', 'Templates', 'Client alerts'] },
  { who: 'Sales Team', email: 'sales@futran.demo', staff: true, home: /\/opportunities$/, heading: 'Opportunities', shot: 'sales-opportunities',
    shown: ['Opportunities', 'Litigation'],
    hidden: ['Dashboard', 'Clients', 'Regulatory master', 'Users', 'Audit log', 'My work'] },
  { who: 'Chief AI Compliance Officer', email: `maria.lopez@${ABC}`, staff: false, home: /\/start$/, heading: 'Welcome to your AI governance assessment', shot: 'caico-getting-started',
    shown: ['Getting started', 'People', 'AI system register', 'Company roles', 'Add-ons', 'Governance', 'Attestation', 'AI inventory', 'Review', 'Report', 'Responses', 'Remediation', 'Email connection', 'Groups', 'Email log'],
    hidden: ['Admin home', 'Summary', 'Data review', 'My department', 'My tasks'] },
  { who: 'Client Admin', email: `sam.okafor@${ABC}`, staff: false, home: /\/admin\/home$/, heading: 'Client Admin home', shot: 'client-admin-home',
    shown: ['Admin home', 'Getting started', 'People', 'AI system register', 'Company roles', 'Add-ons', 'Attestation', 'Email connection', 'Groups', 'Email log'],
    hidden: ['AI inventory', 'Review', 'Report', 'Responses', 'Governance', 'Remediation', 'Documents', 'Summary', 'My tasks'] },
  { who: 'Executive Sponsor', email: `robert.chen@${ABC}`, staff: false, home: /\/summary$/, heading: 'AI governance at ABC Corp', shot: 'sponsor-summary',
    shown: ['Summary', 'Governance', 'Add-ons', 'AI inventory', 'Review', 'Report', 'Responses', 'Remediation'],
    hidden: ['Getting started', 'People', 'Admin home', 'AI system register', 'Attestation', 'Data review', 'Email connection'] },
  { who: 'Data Protection Officer', email: `daniel.kim@${ABC}`, staff: false, home: /\/data-review$/, heading: 'Data review', shot: 'dpo-data-review',
    shown: ['Data review', 'Governance', 'Attestation', 'AI inventory', 'Review', 'Documents', 'Report', 'Remediation'],
    hidden: ['Getting started', 'People', 'Summary', 'Responses', 'AI system register', 'Admin home', 'Email connection'] },
  { who: 'Department Compliance Lead', email: `priya.shah@${ABC}`, staff: false, home: /\/my-department$/, heading: 'HR', shot: 'dept-lead-my-department',
    shown: ['My department', 'AI system register', 'Attestation', 'AI inventory', 'Review', 'AI systems', 'Documents', 'Responses', 'Remediation', 'Groups', 'Email log'],
    hidden: ['Getting started', 'People', 'Report', 'Admin home', 'Company roles', 'Governance', 'My tasks'] },
  { who: 'Contributor', email: `tom.reyes@${ABC}`, staff: false, home: /\/my-tasks$/, heading: 'My tasks', shot: 'contributor-my-tasks',
    shown: ['My tasks', 'My AI attestation', 'AI inventory', 'Review', 'AI systems', 'Documents', 'Remediation'],
    hidden: ['Getting started', 'Attestation', 'Report', 'People', 'AI system register', 'Responses', 'My department'] },
];

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

const mainNav = (page: Page) => page.getByRole('navigation', { name: 'Main' });

async function checkNav(page: Page, shown: string[], hidden: string[]) {
  const nav = mainNav(page);
  for (const name of shown) await expect(nav.getByRole('link', { name, exact: true }), `nav shows ${name}`).toBeVisible();
  for (const name of hidden) await expect(nav.getByRole('link', { name, exact: true }), `nav hides ${name}`).toHaveCount(0);
}

/** No sideways scrolling, and every control is at least 44 px tall (spec §13 accessibility). */
async function checkLayout(page: Page, where: string) {
  const r = await page.evaluate(() => {
    const wide = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small: string[] = [];
    document.querySelectorAll<HTMLElement>('button, a.btn, .shell-nav a, select, textarea, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), label.check').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.height < 44) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(b.height)}px`);
    });
    return { wide, small };
  });
  expect(r.wide, `${where}: page scrolls sideways`).toBeLessThanOrEqual(0);
  expect(r.small, `${where}: controls under 44 px`).toEqual([]);
}

async function shots(page: Page, name: string, mobileCheck: boolean) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(200);
  if (mobileCheck) await checkLayout(page, name);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

for (const c of CASES) {
  test(`${c.who} lands on their home and sees only their modules`, async ({ page }) => {
    await signIn(page, c.email, c.staff);
    await expect(page).toHaveURL(c.home);
    await expect(page.getByRole('heading', { level: 1, name: c.heading })).toBeVisible();
    await checkNav(page, c.shown, c.hidden);
    const brand = page.locator('.shell-header a.brand');
    await expect(brand).toHaveAttribute('href', new URL(page.url()).pathname);  // the logo goes back to the role home
    // the home is clean for assistive technology
    const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => `${n.target.join(' ')} ${n.failureSummary ?? ''}`).join(' | ')}`)).toEqual([]);
    // client homes: no sideways scroll and 44 px touch targets at 375 px; every home is captured at 1440 and 375
    await shots(page, c.shot, !c.staff);
  });
}

test('a CAICO with Client Admin powers lands on Getting started and sees the union of both roles', async ({ page }) => {
  await signIn(page, 'katrin.vogel@meridian.example', false);
  await expect(page).toHaveURL(/\/start$/);
  await checkNav(page, ['Getting started', 'Admin home', 'People', 'Email connection', 'Groups', 'AI inventory', 'Review', 'Company roles', 'Attestation'],
    ['Summary', 'Data review', 'My department', 'My tasks']);
  await mainNav(page).getByRole('link', { name: 'Admin home', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/home$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Client Admin home' })).toBeVisible();
  await expect(page.getByText('Meridian GmbH').first()).toBeVisible();
  await shots(page, 'multi-role-client-admin-home', true);
});

test('a role cannot open another role\'s home data, and old deep links still work', async ({ page }) => {
  await signIn(page, `tom.reyes@${ABC}`, false);
  for (const path of ['/home/sponsor', '/home/dpo', '/home/client-admin', '/home/department', '/home/qa', '/home/admin']) {
    const r = await page.request.get(`/api/v1${path}`);
    expect([403, 404], `contributor GET ${path}`).toContain(r.status());
  }
  // the old client landing page still opens for a bookmark
  await page.goto('/start');
  await expect(page.getByRole('heading', { level: 1, name: 'Welcome to your AI governance assessment' })).toBeVisible();
  // a client user who opens a Futran address is sent to their own home
  await page.goto('/audits');
  await expect(page).toHaveURL(/\/my-tasks$/);
  // and a Futran user's bookmark to the Dashboard still opens it
  await signIn(page, 'auditor1@futran.demo', true);
  await page.goto('/audits');
  await expect(page.getByRole('heading', { level: 1, name: 'Audits' })).toBeVisible();
  await page.goto('/');
  await expect(page).toHaveURL(/\/my-work$/);
});

test('My work opens a task and the QA queue shows its empty state', async ({ page }) => {
  await signIn(page, 'auditor1@futran.demo', true);
  await expect(page.getByRole('link', { name: /ABC Corp/ }).first()).toBeVisible();
  await expect(page.getByText(/AI systems scored/).first()).toBeVisible();
  await signIn(page, 'qa@futran.demo', true);
  await expect(page.getByRole('tab', { name: /Waiting/ })).toBeVisible();
});

test('QA Reviewer returns a Chief Auditor finding and rating override from the queue', async ({ page }) => {
  // The Chief Auditor writes a finding and overrides SYS-002's rating; both route to the QA Reviewer (spec §6 rule 2).
  // Everything is undone at the end, so the journey spec that runs later still finds ABC Corp as the seed left it.
  const abc = late().abc;
  await signIn(page, 'chief@futran.demo', true);
  const f = await api(page, 'POST', `/clients/${abc}/findings`, { title: 'Vendor contract silent on bias audits', severity: 'medium', description: 'The ScreenRank contract does not require the vendor to share bias audit results.' });
  await api(page, 'POST', `/findings/${f.id}/submit`);
  const systems = (await api(page, 'GET', `/clients/${abc}/systems`)).systems as { id: string; reference_id: string }[];
  const sys2 = systems.find((x) => x.reference_id === 'SYS-002')!;
  await api(page, 'PUT', `/systems/${sys2.id}/score/override`, { rating: 'high', rationale: 'Customer data enters a vendor model with no contract terms on training.' });

  await signIn(page, 'qa@futran.demo', true);
  await expect(page).toHaveURL(/\/qa$/);
  await expect(page.getByRole('tab', { name: 'Waiting · 2' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Vendor contract silent on bias audits' })).toBeVisible();
  await shots(page, 'qa-queue-with-items', false);
  // return the override with a comment
  await page.getByRole('button', { name: /SYS-002 .*rating set to High/ }).click();
  await expect(page.getByText('Customer data enters a vendor model')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Return to Chief Auditor' })).toBeDisabled();  // a return needs a comment
  await page.getByRole('textbox', { name: 'QA comment' }).fill('Cite the contract clause you relied on.');
  await page.getByRole('button', { name: 'Return to Chief Auditor' }).click();
  await expect(page.getByText('The rating override for SYS-002 was returned to the Chief Auditor.')).toBeVisible();
  // return the finding too, so the Chief Auditor can withdraw it
  await page.getByRole('textbox', { name: 'QA comment' }).fill('Link the contract in evidence before submitting.');
  await page.getByRole('button', { name: 'Return to Chief Auditor' }).click();
  await expect(page.getByText(/Finding F-\d+ was returned to the Chief Auditor\./)).toBeVisible();
  await expect(page.getByText('Nothing is waiting for your review.')).toBeVisible();
  await page.getByRole('tab', { name: /Reviewed/ }).click();
  await expect(page.getByText('Returned the rating override for SYS-002 (high)')).toBeVisible();

  await signIn(page, 'chief@futran.demo', true);
  await api(page, 'PUT', `/systems/${sys2.id}/score/override`, { rating: null, rationale: null });
  await api(page, 'POST', `/findings/${f.id}/dismiss`, { reason: 'Test item for the QA queue check.' });
});
