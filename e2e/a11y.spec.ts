import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import { test, expect, type Page } from '@playwright/test';

const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string; meridian: string; attest_link: string };
const PW = 'Demo-Password-2026';

async function signIn(page: Page, portal: '/staff/login' | '/login', email: string) {
  await page.context().clearCookies();
  await page.goto(portal);
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function axe(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main, body').first()).toBeVisible();
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const bad = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${path} ${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
  return bad;
}

test('key screens have no serious or critical accessibility violations', async ({ page }) => {
  test.setTimeout(180_000);
  const { abc, attest_link } = late();
  const bad: string[] = [];
  bad.push(...await axe(page, '/staff/login'));
  bad.push(...await axe(page, '/login'));
  bad.push(...await axe(page, attest_link));
  await signIn(page, '/staff/login', 'auditor1@futran.demo');
  for (const p of ['/audits', `/clients/${abc}`, `/clients/${abc}/systems`, `/clients/${abc}/findings`, `/clients/${abc}/report`]) bad.push(...await axe(page, p));
  await signIn(page, '/login', 'maria.lopez@abccorp.example');
  for (const p of ['/start', '/inventory', '/review']) bad.push(...await axe(page, p));
  expect(bad).toEqual([]);
});
