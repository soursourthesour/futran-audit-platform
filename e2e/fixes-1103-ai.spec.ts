import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* 11-03 F1 "refresh with LLM of choice, connect AI": the Futran Admin connects an AI provider in Platform settings, tests it,
   sees a failed key reported plainly, and removes it. The server runs with AI_PROVIDER_HTTP=fake (start-server.sh), so a
   stand-in answers and nothing reaches a real provider. The key never comes back to the browser. */

const PW = 'Demo-Password-2026';
const KEY = 'sk-e2e-connection-key-0000abcd';
const BAD = 'sk-invalid-e2e-key-9999wxyz';
const SHOTS = process.env.AI_SHOTS || '/mnt/user-data/outputs/fixes-1103/ai';
mkdirSync(SHOTS, { recursive: true });

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function shoot(page: Page, name: string) {
  for (const [w, h] of [[1440, 1000], [375, 812]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(250);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${name} scrolls sideways at ${w}px`).toBeLessThanOrEqual(1);
    await section(page).screenshot({ path: `${SHOTS}/${name}-${w}.png` });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

const section = (page: Page) => page.locator('section.card').filter({ has: page.getByRole('heading', { name: 'AI provider' }) });

test('the Futran Admin connects, tests and removes an AI provider; the key never comes back', async ({ page }) => {
  test.setTimeout(120_000);
  const sent: string[] = [];
  page.on('response', async (r) => { if (r.url().includes('/api/v1/admin/')) sent.push(await r.text().catch(() => '')); });
  await signIn(page, 'admin@futran.demo');
  await page.goto('/admin/settings');
  const card = section(page);
  await expect(card.getByTestId('ai-in-use')).toContainText('demonstration model');
  await shoot(page, 'ai-provider-empty');

  // Azure needs an Azure endpoint and a deployment; a wrong endpoint is refused on the field
  await card.getByLabel('Provider', { exact: true }).selectOption('azure_openai');
  await card.getByLabel('Endpoint', { exact: true }).fill('https://example.com');
  await card.getByLabel('Deployment', { exact: true }).fill('audit-gpt');
  await card.getByLabel('API key', { exact: true }).fill(KEY);
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText(/Use the https address of an Azure OpenAI resource/).first()).toBeVisible();

  // OpenAI: save, then test
  await card.getByLabel('Provider', { exact: true }).selectOption('openai');
  await card.getByLabel('Model', { exact: true }).fill('gpt-6-astra');
  await card.getByLabel('API key', { exact: true }).fill(KEY);
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText('Saved. AI features now use OpenAI (gpt-6-astra).', { exact: false })).toBeVisible();
  await expect(card.getByTestId('ai-in-use')).toHaveText('OpenAI · gpt-6-astra (saved below)');
  await expect(card.getByText(/key …abcd/)).toBeVisible();
  await expect(card.getByLabel('API key', { exact: true })).toHaveValue('');
  await card.getByRole('button', { name: 'Test connection' }).click();
  await expect(card.getByText('Connected. OpenAI answered with model gpt-6-astra.').first()).toBeVisible();
  await expect(card.getByText('Working')).toBeVisible();
  await expect(page.getByText(/AI law updates/)).toBeVisible();
  await shoot(page, 'ai-provider-connected');

  // a refused key is reported with a fixed message
  await card.getByLabel('API key', { exact: true }).fill(BAD);
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText(/key …wxyz/)).toBeVisible();
  await card.getByRole('button', { name: 'Test connection' }).click();
  await expect(card.getByRole('alert').filter({ hasText: 'The AI provider refused the API key.' })).toBeVisible();
  await expect(card.getByText('Failed', { exact: true })).toBeVisible();
  await shoot(page, 'ai-provider-failed');

  // the Chief Auditor reads it but cannot change it
  await signIn(page, 'chief@futran.demo');
  await page.goto('/admin/settings');
  await expect(section(page).getByText('Only the Futran Admin changes the AI provider.')).toBeVisible();
  await expect(section(page).getByRole('button', { name: 'Save' })).toHaveCount(0);

  // remove: the key is deleted and the platform falls back to what it used before
  await signIn(page, 'admin@futran.demo');
  await page.goto('/admin/settings');
  await section(page).getByRole('button', { name: 'Remove' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove connection' }).click();
  await expect(section(page).getByText('Removed. The saved key is deleted.')).toBeVisible();
  await expect(section(page).getByTestId('ai-in-use')).toContainText('demonstration model');

  for (const body of sent) {
    expect(body).not.toContain(KEY);
    expect(body).not.toContain(BAD);
  }
});
