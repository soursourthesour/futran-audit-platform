import { test, expect } from '@playwright/test';

test('admin signs in with a password and lands on the audits dashboard', async ({ page }) => {
  await page.goto('/staff/login');
  await expect(page.getByRole('heading', { name: 'Futran staff sign in' })).toBeVisible();
  await expect(page.getByTestId('test-mode-bar')).toBeVisible();
  await page.getByLabel('Work email').fill('admin@futran.demo');
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
  await expect(page.getByRole('heading', { name: 'Audits' })).toBeVisible();
  await expect(page.getByText('Ada Admin · Admin')).toBeVisible();
});

test('wrong password shows a plain error', async ({ page }) => {
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill('admin@futran.demo');
  await page.getByLabel('Password').fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect.');
});

test('signed-out visitor is sent to the right sign-in page', async ({ page }) => {
  await page.goto('/audits');
  await expect(page).toHaveURL(/\/staff\/login/);
  await page.goto('/start');
  await expect(page).toHaveURL(/^[^?]*\/login\?/);
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByText('You do not need an account.')).toBeVisible();
});

test('staff cannot use the client sign-in', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('admin@futran.demo');
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText('staff sign-in');
  await page.getByRole('link', { name: 'Futran staff portal' }).click();
  await expect(page.getByRole('heading', { name: 'Futran staff sign in' })).toBeVisible();
});
