import { test, expect, type Page } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import { openNav } from './nav';

/* Release 2 R6b: G-07 Copilot readiness (Futran workspace and the CAICO's phone view) and G-08 EU AI Act conformity with
   legal sign-off. Acme Staffing LLC and Northbank Credit Union come from app.demo.r6b (seed-e2e). */
const PW = 'Demo-Password-2026';
const SHOTS = '/mnt/user-data/outputs/release2/r6b';
const SCRATCH = process.env.R6B_SCRATCH || '/tmp';

const LICENCES = `Report Refresh Date,User Principal Name,Display Name,Department,Has Copilot License,Last Activity Date of Microsoft 365 Copilot (UTC)
2026-11-08,ana@acme.example,Ana,HR,Yes,2026-11-05
2026-11-08,bo@acme.example,Bo,HR,Yes,2026-09-01
2026-11-08,cy@acme.example,Cy,Finance,Yes,
2026-11-08,di@acme.example,Di,Sales,Yes,2026-11-07
`;
const PURVIEW = `Site name,Site URL,Site owner,Sensitive items,Label coverage,Sharing scope,Last activity
HR · Candidate files,https://acme.sharepoint.com/sites/hr-candidates,HR IT,"2,140",12%,Everyone except external users,2026-11-01
Finance · Payroll archive,https://acme.sharepoint.com/sites/payroll,Finance,860,0%,Organization-wide link,2025-04-30
Sales · Client contracts,https://acme.sharepoint.com/sites/contracts,Sales ops,310,65%,Specific people,2026-10-20
Marketing · Public assets,https://acme.sharepoint.com/sites/marketing,,0,,Organization-wide,2026-11-02
`;

async function signIn(page: Page, email: string, staff = false) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 4; i++) {
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
    else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
    else if (p.startsWith('/welcome/mailbox')) { await page.getByRole('button', { name: 'Not now' }).click(); }
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function importFile(page: Page, kind: RegExp, name: string, body: string) {
  await page.getByLabel('Export').selectOption({ label: (await page.getByLabel('Export').locator('option', { hasText: kind }).textContent())! });
  await page.getByLabel('File (CSV or Excel)').setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(body) });
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'imported' })).toBeVisible();
}

async function openClient(page: Page, name: string) {
  await page.goto('/clients');
  await page.getByRole('link', { name }).first().click();
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible();
}

test('G-07: imports, site risk list, waves, controls, register entry and report; the CAICO works remediation on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await signIn(page, 'auditor1@futran.demo', true);
  await openClient(page, 'Acme Staffing LLC');
  await page.getByRole('link', { name: 'Copilot readiness' }).click();
  await expect(page).toHaveURL(/\/e\/[^/]+\/copilot$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Microsoft 365 Copilot readiness' })).toBeVisible();
  await expect(page.getByText('Controls ready')).toBeVisible();

  // a file without the needed columns is refused with the columns named
  await page.getByLabel('Export').selectOption({ label: (await page.getByLabel('Export').locator('option', { hasText: /Purview/ }).textContent())! });
  await page.getByLabel('File (CSV or Excel)').setInputFiles({ name: 'wrong.csv', mimeType: 'text/csv', buffer: Buffer.from('Site,Owner\nHR,x\n') });
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Sensitive items');

  await importFile(page, /licence and usage/, 'copilot-usage.csv', LICENCES);
  await importFile(page, /Purview/, 'purview-oversharing.csv', PURVIEW);
  const summary = page.getByRole('region', { name: 'Readiness summary' });
  await expect(summary).toContainText('4');
  await expect(page.getByRole('list', { name: 'Imported reports' })).toContainText('SHA-256');

  const sites = page.getByRole('table', { name: 'Site risk list' });
  await expect(sites.getByRole('row').nth(1)).toContainText('HR · Candidate files');
  await expect(sites.getByRole('row').nth(1)).toContainText('High');
  await page.getByRole('button', { name: 'Update HR · Candidate files' }).click();
  const dlg = page.getByRole('dialog', { name: 'Update HR · Candidate files' });
  await dlg.getByLabel('Action').selectOption('restrict_discovery');
  await dlg.getByLabel('Remediation owner').fill('HR IT');
  await dlg.getByLabel('Status').selectOption('in_progress');
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(sites.getByRole('row').nth(1)).toContainText('Restrict discovery');

  // rollout waves with gates
  await page.getByRole('button', { name: 'Add wave' }).click();
  let w = page.getByRole('dialog', { name: 'Add a rollout wave' });
  await w.getByLabel('Wave', { exact: true }).fill('Pilot');
  await w.getByLabel('Groups', { exact: true }).fill('IT, Compliance');
  await w.getByLabel('Users', { exact: true }).fill('20');
  await w.getByLabel('Date', { exact: true }).fill('2026-12-01');
  await w.getByLabel('Pilot group defined').check();
  await w.getByRole('button', { name: 'Save' }).click();
  await page.getByRole('button', { name: 'Add wave' }).click();
  w = page.getByRole('dialog', { name: 'Add a rollout wave' });
  await w.getByLabel('Wave', { exact: true }).fill('Wave 1');
  await w.getByLabel('Groups', { exact: true }).fill('HR, Finance');
  await w.getByLabel('Users', { exact: true }).fill('60');
  await w.getByLabel('Date', { exact: true }).fill('2027-01-15');
  await w.getByLabel(/HR · Candidate files/).check();
  await w.getByLabel(/Finance · Payroll archive/).check();
  await w.getByRole('button', { name: 'Save' }).click();
  const waves = page.getByRole('table', { name: 'Rollout waves' });
  await expect(waves).toContainText('Hold · Pilot group defined');
  await expect(waves).toContainText('Hold · 2 sites open');
  await page.getByLabel('Status of Pilot group defined').selectOption('done');
  await expect(waves.getByRole('row').nth(1)).toContainText('Go');

  await page.getByLabel('Status of Copilot usage policy approved').selectOption('done');
  await page.getByRole('button', { name: 'Add Copilot to the AI register' }).click();
  await expect(page.getByText(/Copilot is in Acme Staffing LLC's AI register as AIS-\d+ Microsoft 365 Copilot/)).toBeVisible();
  await page.getByRole('button', { name: 'Produce the readiness report' }).click();
  const report = page.getByRole('link', { name: /Copilot.readiness.report.*\.pdf/ });
  await expect(report).toBeVisible();
  const pdf = await page.request.get((await report.getAttribute('href'))!);
  expect(pdf.ok()).toBeTruthy();
  writeFileSync(`${SCRATCH}/copilot-readiness-report.pdf`, await pdf.body());
  await shot(page, 'g07-1280-workspace');
  await sites.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/g07-1280-site-risk-list-and-waves.png` });

  // the client's CAICO on a phone: the same workspace, remediation only
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, 'dana.reyes@acmestaffing.example');
  await openNav(page, 'Copilot readiness');
  await expect(page.getByRole('heading', { level: 1, name: 'Microsoft 365 Copilot readiness' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add wave' })).toHaveCount(0);
  await noSidewaysScroll(page);
  await shot(page, 'g07-375-client-view');
  await page.getByRole('button', { name: 'Update Finance · Payroll archive' }).click();
  const cd = page.getByRole('dialog', { name: 'Update Finance · Payroll archive' });
  await expect(cd.getByLabel('Action')).toHaveCount(0);
  await cd.getByLabel('Remediation owner').fill('Payroll team');
  await cd.getByLabel('Status').selectOption('done');
  await cd.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'updated' })).toBeVisible();
  await noSidewaysScroll(page);
});

test('G-08: classification, computed articles and deadline, legal sign-off by the reviewer only, and the CAICO sees it once signed', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await signIn(page, 'auditor1@futran.demo', true);
  await openClient(page, 'Northbank Credit Union');
  await page.getByRole('link', { name: 'EU AI Act conformity' }).click();
  await expect(page).toHaveURL(/\/e\/[^/]+\/eu-ai-act$/);
  const url = new URL(page.url()).pathname;
  await expect(page.getByRole('heading', { level: 1, name: 'EU AI Act conformity' })).toBeVisible();
  await expect(page.getByText(/Annex III high-risk from 2 Dec 2027 · Annex I from 2 Aug 2028/)).toBeVisible();
  const systems = page.getByRole('table', { name: 'AI systems under the EU AI Act' });
  await expect(systems.getByRole('row')).toHaveCount(5);

  // the credit model: provider that also uses it, Annex III credit scoring
  await page.getByLabel('EU exposure').fill('EU members');
  await page.getByLabel('Role').selectOption('provider');
  await page.getByLabel('The client also uses it (deployer duties apply too)').check();
  await page.getByLabel('Classification').selectOption('high_risk_annex_iii');
  await page.getByLabel('Annex III area').selectOption('credit');
  await page.getByLabel('Reasoning').fill('Evaluates the creditworthiness of natural persons, so Annex III point 5(b). Built and placed in service under the credit union\'s own name.');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Classification saved.' })).toBeVisible();
  const row = systems.getByRole('row').filter({ hasText: 'Credit decision model' });
  await expect(row).toContainText('2 Dec 2027');
  await expect(row).toContainText('Provider (also uses it)');
  const obligations = page.getByRole('table', { name: 'Obligations' });
  for (const a of ['Art. 9', 'Art. 11 · Annex IV', 'Art. 27', 'Art. 73']) await expect(obligations).toContainText(a);
  await page.getByLabel('Status of Art. 9').selectOption('met');
  await page.getByLabel('Status of 1. General description of the AI system').selectOption('done');
  await expect(obligations).toContainText('1 of 9 sections');
  await page.getByRole('button', { name: 'Send for legal sign-off' }).click();
  await expect(row).toContainText('Pending');
  await expect(page.getByRole('button', { name: 'Sign off the classification' })).toHaveCount(0);  // the auditor never signs

  // the Legal/Compliance Reviewer signs it off
  await signIn(page, 'legal@futran.demo', true);
  await page.goto(url);
  await expect(page.getByLabel('Role')).toHaveCount(0);  // reads the reasoning, does not edit it
  await page.getByLabel('Note to the audit team (optional)').fill('Agree: Annex III point 5(b); FRIA needed as deployer.');
  await page.getByRole('button', { name: 'Sign off the classification' }).click();
  await expect(page.getByText(/Signed off by Jordan Ellis on/)).toBeVisible();
  await expect(systems.getByRole('row').filter({ hasText: 'Credit decision model' })).toContainText('Signed');
  await shot(page, 'g08-1280-classification-signoff-articles-deadlines');

  // the CAICO sees the signed-off classification on the register record
  await signIn(page, 'ines.maier@northbank.example');
  await page.goto('/register');
  await page.getByRole('link', { name: 'Credit decision model' }).first().click();
  const card = page.getByRole('region', { name: 'EU AI Act' }).or(page.locator('section.card', { hasText: 'Signed off by the legal reviewer' }));
  await expect(card.first()).toContainText('High-risk · Annex III');
  await expect(card.first()).toContainText('2 Dec 2027');
  await shot(page, 'g08-1280-register-record-client');
});
