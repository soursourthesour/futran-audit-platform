import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page, email: string) {
  await page.goto('/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

test('auditor sets up a new client and submits it for approval', async ({ page }) => {
  await signIn(page, 'auditor1@futran.demo');
  await page.getByRole('link', { name: 'New client' }).click();
  await expect(page).toHaveURL(/\/setup\/company$/);

  // Step 1
  await page.getByLabel('Legal name *').fill('ABC Corp Inc.');
  await page.getByLabel('Trading name').fill('ABC Corp');
  await page.getByLabel('Industry *').selectOption('staffing');
  await page.getByLabel('250–999').check();
  await page.getByLabel('Number of AI systems in scope *').fill('2');
  await page.getByLabel('Street *').fill('1 Main Street');
  await page.getByLabel('City *').fill('New York');
  await page.getByLabel('State / region *').fill('NY');
  await page.getByLabel('Postal code *').fill('10001');
  await page.getByLabel('Country *').selectOption('US');
  await page.getByLabel('Primary countries of operation *').selectOption('US');
  await page.getByLabel('Why the client is engaging Futran').fill('ABC uses AI to screen and rank job applicants in New York and Chicago.');
  await expect(page.getByRole('status')).toContainText('Saved');
  await page.getByRole('button', { name: 'Next: locations and laws' }).click();

  // Step 2
  await page.getByRole('button', { name: 'Add location' }).click();
  await page.getByLabel('Name of site 1').fill('Headquarters');
  await page.getByLabel('State or region of site 1').selectOption('US-NY');
  await page.getByLabel('City of site 1').fill('New York');
  await page.getByRole('button', { name: 'Add location' }).click();
  await page.getByLabel('Name of site 2').fill('Chicago office');
  await page.getByLabel('State or region of site 2').selectOption('US-IL');
  await page.getByLabel('City of site 2').fill('Chicago');
  await expect(page.getByRole('cell', { name: 'NYC Local Law 144', exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('cell', { name: /^NY Civil Rights Law §52-c/ })).toBeVisible();
  await expect(page.getByLabel('Include NYC Local Law 144')).toBeChecked();
  await page.screenshot({ path: 'screenshots/p3-wizard-step2.png', fullPage: true });
  await page.getByRole('button', { name: 'Next: scope and team' }).click();

  // Step 3
  await page.getByLabel('Initial AI governance assessment').check();
  await page.getByLabel('Audit period start *').fill('2026-01-01');
  await page.getByLabel('Audit period end *').fill('2026-12-31');
  await page.getByLabel('Engagement start *').fill('2026-11-02');
  await page.getByLabel('Target date for the draft report *').fill('2027-01-15');
  await page.getByLabel('Target date for the final report *').fill('2027-02-15');
  await page.getByLabel('HR and recruiting').check();
  await page.getByLabel('AI systems in scope *').fill('HireScore\nResume parser');
  await page.getByLabel('Business processes in scope *').fill('Candidate screening and ranking');
  await page.getByLabel('Production').check();
  await page.getByLabel('Geographic scope *').fill('United States: New York and Illinois');
  await page.getByLabel('NIST AI RMF 1.0').check();
  await page.getByLabel('Chief Auditor (Lead Auditor) *').selectOption({ label: 'Chris Chief' });
  await page.getByLabel('Engagement Manager *').selectOption({ label: 'Erin Manager' });
  for (const name of ['Chris Chief', 'Erin Manager', 'Alex Auditor']) await page.getByLabel(`${name} has confirmed no conflict of interest`).check();
  await page.getByRole('button', { name: 'Next: client contacts' }).click();

  // Step 4
  await page.getByLabel('Full name *').first().fill('Maria Lopez');
  await page.getByLabel('Job title *').fill('Chief AI Compliance Officer');
  await page.getByLabel('Work email *').first().fill('maria.lopez@abccorp.example');
  await page.getByLabel(/Not appointed: Maria Lopez covers these duties/).check();
  await page.getByRole('button', { name: 'Next: review and submit' }).click();

  await page.getByRole('button', { name: 'Submit for approval' }).click();
  await expect(page).toHaveURL(/\/audits$/);
  await expect(page.getByText('ABC Corp was sent to the Chief Auditor for approval.')).toBeVisible();
});
