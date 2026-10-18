import { test, expect, type Page } from '@playwright/test';
import path from 'path';

async function signIn(page: Page, email: string) {
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

test('admin re-imports the law matrix, browses Illinois and edits a law into a new version', async ({ page }) => {
  await signIn(page, 'admin@futran.demo');
  await page.getByRole('link', { name: 'Reference data' }).click();
  await page.getByRole('tab', { name: 'Import workbook' }).click();
  await page.getByLabel('Law matrix workbook').setInputFiles(path.resolve(__dirname, '../backend/seeds/law_matrix.xlsx'));
  await page.getByRole('button', { name: 'Preview import' }).click();
  await expect(page.getByText(/Preview — status/)).toBeVisible();
  await page.screenshot({ path: 'screenshots/p2-import-preview.png', fullPage: false });
  await page.getByRole('button', { name: /^Publish \d+ laws$/ }).click();
  await expect(page.getByText(/unchanged/)).toBeVisible();

  await page.getByRole('tab', { name: 'Laws' }).click();
  await page.getByLabel('Geography').selectOption({ label: 'Illinois (US)' });
  const law = page.getByRole('button', { name: /AI Video Interview Act/ });
  await expect(law).toBeVisible();
  await page.screenshot({ path: 'screenshots/p2-law-browser.png', fullPage: true });
  await law.click();
  await page.getByLabel('Key obligations').fill('Notice, explanation and consent before AI analysis of video interviews; delete recordings within 30 days on request.');
  await page.getByRole('button', { name: 'Save' }).click();
  await page.getByRole('tab', { name: 'Versions' }).click();
  await expect(page.getByRole('cell', { name: /Manual edit — AI Video Interview Act/ })).toBeVisible();
  await page.screenshot({ path: 'screenshots/p2-versions.png', fullPage: true });

  await page.getByRole('tab', { name: 'Jurisdictions' }).click();
  await expect(page.getByText('New York City · US-NYC')).toBeVisible();
  await expect(page.getByText('European Union · EU')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p2-jurisdictions.png', fullPage: true });

  await page.getByRole('tab', { name: 'Law updates' }).click();
  await expect(page.getByText('Law updates are switched off')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p2-law-updates.png', fullPage: true });
});
