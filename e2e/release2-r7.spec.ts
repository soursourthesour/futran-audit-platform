import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import { expectNav, openNav } from './nav';

/* Release 2 R7 on the fresh server (seed from app.demo.release2_r7): the Futran Admin reads the Acme Staffing group and an
   end-client's LL144 scope (G-04); the subsidiary's CAICO gives roll-up consent on a phone and the parent's CAICO then sees
   counts only (G-04 client view, 375 px); the Chief Auditor reads Metro Retail's vault, places and releases a legal hold
   (G-10); the Sales Manager reads partners and commissions, an Auditor sees no Partners entry (G-11). */
const PW = 'Demo-Password-2026';
const SHOTS = process.env.R7_SHOTS || '/mnt/user-data/outputs/release2/r7';
mkdirSync(SHOTS, { recursive: true });
test.use({ viewport: { width: 1440, height: 1000 } });

function ids(): { acme: string; metro: string } {
  const py = `
import json, sqlite3
c = sqlite3.connect("data/e2e.db")
q = lambda n: c.execute("select id from organizations where name = ?", (n,)).fetchone()[0]
print(json.dumps({"acme": q("Acme Staffing LLC"), "metro": q("Metro Retail Inc.")}))`;
  return JSON.parse(execFileSync(join(__dirname, '../backend/.venv/bin/python'), ['-c', py], { cwd: join(__dirname, '../backend') }).toString());
}

async function signIn(page: Page, email: string, staff: boolean) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/mailbox')) await page.getByRole('button', { name: 'Not now' }).click();
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w).toBeLessThanOrEqual(1);
}

test('G-04: the Futran Admin reads the group tree and an end-client\'s LL144 scope', async ({ page }) => {
  const { acme } = ids();
  await signIn(page, 'admin@futran.demo', true);
  await page.goto(`/staff/clients/${acme}/entities`);
  await expect(page.getByRole('heading', { name: 'Entities and end-clients' })).toBeVisible();
  const tree = page.getByRole('list', { name: 'Entities in this group' });
  await expect(tree.getByRole('button')).toHaveCount(5);
  await expect(tree).toContainText('Roll-up consent: no');
  await expect(tree).toContainText('NJ roles only');
  await tree.getByRole('button', { name: /Riverside Hospital/ }).click();
  await expect(page.getByRole('heading', { name: 'Selected · Riverside Hospital' })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'End-client (staffing)' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Candidate ranking (AEDT 1)' })).toBeChecked();
  await expect(page.getByText('Billing: counted in L-09 (2 of 3 end-clients in LL144 scope).')).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'G04-tree-desktop');
});

test('G-04 client view at 375 px: the subsidiary CAICO consents, then the parent CAICO sees counts only', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, 'pat.romero@acmestaffing.example', false);
  await page.goto('/group');
  await expect(page.getByText('Roll-up not shared.')).toBeVisible();
  await noSidewaysScroll(page);
  await signIn(page, 'sid.okafor@acmehealthcare.example', false);
  await openNav(page, 'Group');
  await expect(page.getByText('Not shared')).toBeVisible();
  await shot(page, 'G04-consent-before-375');
  await page.getByRole('button', { name: 'Share counts with Acme Staffing LLC' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Share counts' }).click();
  await expect(page.getByText('Consent given.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop sharing with Acme Staffing LLC' })).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'G04-consent-given-375');
  await signIn(page, 'pat.romero@acmestaffing.example', false);
  await page.goto('/group');
  const sub = page.locator('li', { hasText: 'Acme Healthcare Staffing Inc.' });
  await expect(sub.getByText('AI systems')).toBeVisible();
  await expect(sub).not.toContainText('Nurse shift matching');  // counts only, never names
  await noSidewaysScroll(page);
  await shot(page, 'G04-parent-rollup-375');
});

test('G-10: the Chief Auditor reads the vault, places a legal hold and releases it', async ({ page }) => {
  const { metro } = ids();
  await signIn(page, 'chief@futran.demo', true);
  await page.goto(`/staff/clients/${metro}/vault`);
  await expect(page.getByRole('heading', { name: 'Evidence vault and retention' })).toBeVisible();
  await expect(page.getByText('7 years')).toBeVisible();
  await expect(page.getByText('Active · deletion blocked')).toBeVisible();
  const countdown = page.locator('.card', { hasText: 'Deletion countdown' });
  await expect(countdown.getByText('Applicant data extract (bias test).csv')).toBeVisible();
  await expect(countdown.getByText('LH-001').first()).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'G10-vault-desktop');
  await page.getByRole('button', { name: 'Place legal hold' }).click();
  const d = page.getByRole('dialog');
  await d.getByLabel('Name').fill('Regulator inquiry');
  await d.getByLabel('Matter reference').fill('IL AG 2026-118');
  await d.getByLabel('Why').fill('The Illinois Attorney General asked the client to keep all hiring AI records.');
  await d.getByRole('checkbox', { name: /Initial assessment 2019/ }).check();
  await shot(page, 'G10-place-hold-dialog');
  await d.getByRole('button', { name: 'Place legal hold' }).click();
  await expect(page.getByText('Legal hold placed.')).toBeVisible();
  await expect(page.getByText('2 active')).toBeVisible();
  await page.getByRole('row', { name: /LH-002/ }).getByRole('button', { name: 'Release' }).click();
  await page.getByRole('dialog').getByLabel('Why is the hold released?').fill('Inquiry closed with no action.');
  await page.getByRole('dialog').getByRole('button', { name: 'Release hold' }).click();
  await expect(page.getByText('LH-002 released.')).toBeVisible();
  await shot(page, 'G10-hold-released');
});

test('G-11: the Sales Manager reads partners and commissions; an Auditor has no Partners entry', async ({ page }) => {
  await signIn(page, 'salesmanager@futran.demo', true);
  await openNav(page, 'Partners');
  await expect(page.getByRole('heading', { name: 'Partners and referrals' })).toBeVisible();
  const partners = page.getByRole('table').first();
  const law = partners.getByRole('row', { name: /Employment law firm/ });
  await expect(law).toContainText('None: referrals both ways, no fees (bar rules)');
  await expect(partners.getByRole('row', { name: /ATS vendor \(example\)/ })).toContainText('15% of first-year contract value');
  const comms = page.getByRole('table').nth(1);
  await expect(comms.getByText('ORD-0172')).toBeVisible();
  await expect(comms.getByText('Paid', { exact: true })).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'G11-partners-desktop');
  await page.getByRole('button', { name: 'Add partner' }).click();
  const d = page.getByRole('dialog');
  await d.getByLabel('Type').selectOption('law_firm');
  await expect(d.getByLabel(/Commission, %/)).toHaveCount(0);
  await expect(d.getByText('None: referrals both ways, no fees (bar rules)')).toBeVisible();
  await d.getByRole('button', { name: 'Cancel' }).click();
  await signIn(page, 'auditor1@futran.demo', true);
  await expectNav(page, [], ['Partners']);
  const r = await page.request.get('/api/v1/staff/partners');
  expect(r.status()).toBe(403);
});
