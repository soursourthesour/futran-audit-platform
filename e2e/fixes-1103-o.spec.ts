import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

/** 11-03 F8: the periodic opportunity scan in Platform settings. */
const PW = 'Demo-Password-2026';
const SHOTS = process.env.SHOTS_DIR || 'screenshots';
const HOME: Record<string, RegExp> = { 'admin@futran.demo': /\/staff\/admin$/, 'sales@futran.demo': /\/opportunities$/ };

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  if (HOME[email]) await expect(page).toHaveURL(HOME[email]);
  else await expect(page).not.toHaveURL(/\/login/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w).toBeLessThanOrEqual(1);
}

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

test('Futran Admin turns on the opportunity scan and runs it now; a change already opened at approval is not opened twice', async ({ page }) => {
  // An approved change to a law Harbor Point Staffing is in scope of: the scan's law source has something to find.
  await signIn(page, 'chief@futran.demo');
  const harbor = (await api(page, 'GET', '/opportunities')).clients.find((c: { name: string }) => c.name === 'Harbor Point Staffing');
  const law = (await api(page, 'GET', `/clients/${harbor.id}/applicability`)).laws_in.find((l: { kind: string }) => l.kind === 'Binding');
  await signIn(page, 'admin@futran.demo');
  const proposed = await api(page, 'POST', `/reg/laws/${law.regulation_id}/proposals`, {
    summary: 'Civil penalties raised for each violation', changes: [{ field_path: 'law.penalty_text', new_value: 'Up to $1,500 for each violation; each day is a separate violation.' }],
  });
  await signIn(page, 'chief@futran.demo');
  await api(page, 'POST', `/reg/changes/${proposed.proposals[0].id}/decide`, { action: 'approve', note: 'Checked against the act.', notify_clients: false });

  await signIn(page, 'admin@futran.demo');
  await page.goto('/admin/settings');
  const card = page.locator('section.card', { has: page.getByRole('heading', { name: 'Opportunity scan' }) });
  await expect(card).toBeVisible();
  const interval = card.getByLabel('Look for new opportunities', { exact: true });
  await expect(interval).toHaveValue('off'); // off until someone turns it on
  await expect(card.getByText('Not run yet')).toBeVisible();
  await card.getByRole('button', { name: /About Look for new opportunities/ }).click();
  await expect(page.getByText(/Off by default\. When on, the daily jobs/)).toBeVisible();
  await page.keyboard.press('Escape');

  await interval.selectOption('custom');
  await card.getByLabel('Number of days', { exact: true }).fill('400');
  await expect(card.getByText('Enter a whole number from 1 to 365.')).toBeVisible();
  await expect(card.getByRole('button', { name: 'Save' })).toBeDisabled();
  await card.getByLabel('Number of days', { exact: true }).fill('12');
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText('Saved. The scan runs every 12 days.')).toBeVisible();
  await expect(card.getByText(/, at the daily run$/)).toBeVisible();

  // The approval itself opened Harbor Point's opportunity for the change, so the scan finds it already open.
  await card.getByRole('button', { name: 'Run now' }).click();
  await expect(card.getByText('Scan finished: nothing new.')).toBeVisible();
  await expect(card.getByText('Run now by Ada Admin')).toBeVisible();
  await expect(card.getByText('0 from the law library · 0 regulatory updates · 0 renewal audits · 1 already open')).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 900 });
  await card.scrollIntoViewIfNeeded();
  await shot(page, 'o-settings-1440');
  await page.setViewportSize({ width: 375, height: 812 });
  await noSidewaysScroll(page);
  await shot(page, 'o-settings-375');

  await page.setViewportSize({ width: 1280, height: 900 });
  await interval.selectOption('off');
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText('Saved. The scan is off.')).toBeVisible();
  await expect(card.getByRole('definition').filter({ hasText: /^Off$/ })).toBeVisible(); // next run

  // the Chief Auditor sees the setting but cannot change it
  await signIn(page, 'chief@futran.demo');
  await page.goto('/admin/settings');
  await expect(page.getByText('Only the Futran Admin changes this.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run now' })).toHaveCount(0);

  await signIn(page, 'sales@futran.demo');
  await expect(page.getByRole('cell', { name: 'Law change' }).first()).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await shot(page, 'o-opportunities-1440');
  await page.setViewportSize({ width: 375, height: 812 });
  await noSidewaysScroll(page);
  await shot(page, 'o-opportunities-375');
});
