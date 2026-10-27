import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page, email: string) {
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

test('admin adds a Futran user, the invitation lands in the outbox and the audit log', async ({ page }) => {
  await signIn(page, 'admin@futran.demo');
  await page.getByRole('link', { name: 'Users' }).click();
  await page.getByRole('button', { name: 'Add user' }).click();
  await page.getByLabel('Full name').fill('Quinn Reviewer');
  await page.getByLabel('Work email').fill('quinn@futran.demo');
  await page.getByLabel('QA Reviewer').check();
  await page.getByLabel('Auditor', { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Add and send invitation' }).click();
  await expect(page.getByRole('cell', { name: 'quinn@futran.demo' })).toBeVisible();
  await page.screenshot({ path: 'screenshots/p1-users.png', fullPage: true });

  await page.getByRole('link', { name: 'Outbox' }).click();
  await page.getByRole('button', { name: /your Futran Audit Platform account is ready/ }).first().click();
  await expect(page.frameLocator('iframe[title="Email preview"]').getByText('Accept invitation')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p1-outbox.png', fullPage: true });
  await page.keyboard.press('Escape'); // the message opens in a dialog; close it to use the navigation
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.getByRole('link', { name: 'Audit log' }).click();
  await expect(page.getByText('Added quinn@futran.demo')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p1-audit-log.png', fullPage: true });
});

test('auditor does not see admin navigation', async ({ page }) => {
  await signIn(page, 'auditor1@futran.demo');
  await expect(page.getByRole('link', { name: 'Users' })).toHaveCount(0);
  await page.goto('/staff/login');
  await page.screenshot({ path: 'screenshots/p1-login.png' });
});
