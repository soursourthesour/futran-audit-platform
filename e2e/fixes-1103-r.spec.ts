import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

/** 11-03 C7–C15: the AI system register's new-system form, governance roles, import and the AI model list.
 *  Runs against the late server (ABC Corp with the regulatory master), like register.spec.ts. */
const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const PRIYA = `priya.shah@${ABC}`;
const MARIA = `maria.lopez@${ABC}`;
const LATE = `http://127.0.0.1:${Number(process.env.E2E_PORT || 8765) + 1}`;
const SHOTS = process.env.R_SHOTS_DIR || '/mnt/user-data/outputs/fixes-1103/r';
mkdirSync(SHOTS, { recursive: true });

test.use({ baseURL: LATE, viewport: { width: 1440, height: 1000 } });

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function staff(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w).toBeLessThanOrEqual(1);
}

async function stepOne(page: Page, name: string) {
  await page.goto('/register/new');
  await page.getByLabel('Name *', { exact: true }).fill(name);
  await page.getByLabel('Type *', { exact: true }).selectOption({ label: 'Vendor app with AI' });
  await page.getByLabel('Built or bought *', { exact: true }).selectOption({ label: 'Bought from vendor' });
  await page.getByLabel('Stage *', { exact: true }).selectOption({ label: 'In development / procurement' });
  await page.getByLabel('Purpose *', { exact: true }).fill('Ranks job applicants for recruiters.');
}

test('new-system form: departments, who uses it, owner by department, model list, whose data, places and suggested laws', async ({ page }) => {
  await clientUser(page, PRIYA);
  await stepOne(page, 'Applicant ranker 1103');

  // C9: several (not all) departments
  await page.getByRole('checkbox', { name: 'Used by several departments' }).check();
  const depts = page.getByRole('group', { name: 'Departments that use it' });
  await expect(depts.getByRole('checkbox').first()).toBeVisible();
  const boxes = depts.getByRole('checkbox');
  expect(await boxes.count()).toBeGreaterThan(1);
  for (let i = 0; i < await boxes.count(); i++) if (!(await boxes.nth(i).isChecked())) { await boxes.nth(i).check(); break; }

  // C10: named users, searchable, select all and clear, count calculated
  await page.getByLabel('Who uses it', { exact: true }).selectOption({ label: 'Named users' });
  const people = page.getByRole('group', { name: 'People' });
  await page.getByRole('button', { name: /^Select all \(\d+\)$/ }).click();
  const all = await people.getByRole('checkbox').count();
  await expect(page.getByText(`${all} selected`)).toBeVisible();
  await expect(page.getByLabel('Number of users', { exact: true })).toHaveValue(String(all));
  await page.getByLabel('Search people').fill('Priya');
  await page.getByRole('button', { name: /^Clear shown$/ }).click();
  await expect(page.getByText(`${all - 1} selected`)).toBeVisible();
  await page.getByLabel('Search people').fill('');
  await shot(page, '1440-step1-named-users');

  // by role level: AI compliance roles counted among the departments that use it
  await page.getByLabel('Who uses it', { exact: true }).selectOption({ label: 'By role level' });
  await page.getByRole('group', { name: 'AI compliance roles' }).getByRole('checkbox', { name: /^Department Compliance Lead/ }).check();
  await expect(page.getByLabel('Number of users', { exact: true })).not.toHaveValue('');
  await expect(page.getByText('Calculated from the selection')).toBeVisible();

  // C11: the owner picker is grouped by department
  const owner = page.getByLabel('System owner', { exact: true });
  await expect(owner.locator('optgroup[label="HR"] option', { hasText: 'Priya Shah' })).toHaveCount(1);
  await expect(owner.locator('optgroup[label="Finance"] option', { hasText: 'Grace Liu' })).toHaveCount(1);
  await owner.selectOption({ label: 'Priya Shah · Head of HR' });
  await shot(page, '1440-step1-what-it-is');

  // C12: the model list for the provider, and Other
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'Vendor and model' })).toBeVisible();
  await page.getByLabel('Underlying AI provider', { exact: true }).selectOption({ label: 'OpenAI' });
  const model = page.getByLabel('Model or algorithm', { exact: true });
  await expect(model.locator('option', { hasText: /^GPT-5\.5$/ })).toHaveCount(1);
  await model.selectOption({ label: 'Other' });
  await page.getByLabel('Other model or algorithm', { exact: true }).fill('Acme ranker 1103');
  await shot(page, '1440-step2-vendor-model');

  // C13: the company's own data
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel("The company's own data", { exact: true }).check();
  await page.getByLabel('Job candidates', { exact: true }).check();
  await page.getByLabel('Personal information', { exact: true }).check();
  await shot(page, '1440-step3-data');

  // C14: places, suggestions with their reason, accept and remove, the law library dropdown
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Add where it runs, or where the people whose data it uses are, to see the laws that apply.')).toBeVisible();
  const run = page.getByRole('group', { name: 'Where it runs' });
  await run.getByLabel('Country', { exact: true }).selectOption({ label: 'United States' });
  await run.getByLabel('State or region', { exact: true }).selectOption({ label: 'New York' });
  await run.getByLabel('City', { exact: true }).fill('New York');
  await page.getByRole('button', { name: 'Add a place' }).click();
  const p1 = page.getByRole('group', { name: 'Place 1' });
  await p1.getByLabel('State or region', { exact: true }).selectOption({ label: 'Illinois' });
  await page.getByLabel('Makes or substantially makes the decision').check();
  const sugg = page.getByRole('list', { name: 'Suggested laws' });
  const ll144 = sugg.getByRole('listitem').filter({ hasText: 'NYC Local Law 144' });
  await expect(ll144).toContainText('Why: Runs in New York City; makes employment decisions');
  const il = sugg.getByRole('listitem').filter({ hasText: 'HB 3773' });
  await expect(il).toContainText('people whose data it uses are in Illinois');
  await shot(page, '1440-step-laws-suggested');
  await ll144.getByRole('button', { name: /^Accept/ }).click();
  await il.getByRole('button', { name: /^Remove suggestion/ }).click();
  await expect(sugg.getByRole('listitem').filter({ hasText: 'HB 3773' })).toHaveCount(0);
  const chosen = page.locator('.reg-lawchips');
  await expect(chosen.getByText('NYC Local Law 144')).toBeVisible();
  const lib = page.getByLabel('Law library', { exact: true });
  const lawOpt = lib.locator('optgroup[label="European Union"] option').first();
  const lawName = (await lawOpt.textContent())!.trim();
  await lib.selectOption({ label: lawName });
  await expect(chosen.getByText(lawName)).toBeVisible();
  await shot(page, '1440-step-laws-chosen');

  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Save and fill governance roles' }).click();
  await expect(page).toHaveURL(/\/register\/[^/]+\/roles$/);

  // C15: AI compliance role and the geography of each role's law
  const own = page.getByRole('table', { name: 'AI compliance roles for this AI system', exact: true });
  await expect(own.getByRole('button', { name: 'AI compliance role', exact: true })).toBeVisible();
  await expect(own.getByRole('button', { name: 'Geography of law', exact: true })).toBeVisible();
  await expect(own.getByRole('row').filter({ hasText: 'Bias testing lead' }).getByText('New York City')).toBeVisible();
  await shot(page, '1440-roles-tab');

  // the details tab keeps the places and the accepted suggestion's reason; the Other model is offered next time
  await page.getByRole('navigation', { name: 'AI system sections' }).getByRole('link', { name: 'Details' }).click();
  await expect(page.getByRole('group', { name: 'Where it runs' }).getByLabel('City', { exact: true })).toHaveValue('New York');
  await expect(page.locator('.reg-lawchips .chip', { hasText: 'NYC Local Law 144' })).toHaveAttribute('title', /Runs in New York City/);
  await shot(page, '1440-details-laws');
  await stepOne(page, 'Applicant ranker 1103 b');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('Underlying AI provider', { exact: true }).selectOption({ label: 'OpenAI' });
  await expect(page.getByLabel('Model or algorithm', { exact: true }).locator('option', { hasText: 'Acme ranker 1103 (added by your company)' })).toHaveCount(1);
});

test('register grid: import from inventory help and the import template', async ({ page }) => {
  await clientUser(page, MARIA);
  await page.goto('/register');
  await page.getByRole('button', { name: 'About What the inventory import copies' }).click();
  await expect(page.getByText(/Copies into the register the AI tools and agents your company declared in the AI inventory/)).toBeVisible();
  await shot(page, '1440-grid-import-inventory-help');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Import from a file' }).click();
  const dlg = page.getByRole('dialog', { name: 'Import AI systems from a file' });
  await expect(dlg.getByRole('link', { name: /Excel, with instructions/ })).toHaveAttribute('href', '/api/v1/register/import-template.xlsx');
  const r = await page.request.get('/api/v1/register/import-template.csv');
  expect((await r.text()).replace(/^﻿/, '').startsWith('Name *,Type *,Built or bought *,Department *,Used by departments,Stage,Purpose,Who uses it')).toBeTruthy();
  await shot(page, '1440-import-dialog');
});

test('AI model list in reference data: add a model and run the check', async ({ page }) => {
  await staff(page, 'admin@futran.demo');
  await page.goto('/admin/reference?tab=models');
  await expect(page.getByRole('tab', { name: 'AI models' })).toHaveAttribute('aria-selected', 'true');
  const openai = page.getByRole('region', { name: 'OpenAI', exact: true });
  await expect(openai.getByRole('button', { name: 'Stop offering GPT-5.5', exact: true })).toBeVisible();
  await openai.getByLabel('Add a model to OpenAI', { exact: true }).fill('GPT-test 1103');
  await openai.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByText('GPT-test 1103 was added to OpenAI.')).toBeVisible();
  await page.getByRole('button', { name: 'Check now' }).click();
  await expect(page.getByText(/^Last check /)).toBeVisible();
  await shot(page, '1440-reference-ai-models');
});

test.describe('375 px', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  test('new-system steps, roles tab and the model list fit a phone', async ({ page }) => {
    await clientUser(page, PRIYA);
    await stepOne(page, 'Phone check 1103');
    await page.getByRole('checkbox', { name: 'Used by several departments' }).check();
    await page.getByLabel('Who uses it', { exact: true }).selectOption({ label: 'Named users' });
    await noSidewaysScroll(page);
    await shot(page, '375-step1-what-it-is');
    await page.getByLabel('Who uses it', { exact: true }).selectOption({ label: 'By role level' });
    await noSidewaysScroll(page);
    await shot(page, '375-step1-role-level');
    await page.getByRole('button', { name: 'Next' }).click();
    await page.getByLabel('Underlying AI provider', { exact: true }).selectOption({ label: 'Anthropic' });
    await noSidewaysScroll(page);
    await shot(page, '375-step2-vendor-model');
    await page.getByRole('button', { name: 'Next' }).click();
    await noSidewaysScroll(page);
    await shot(page, '375-step3-data');
    await page.getByRole('button', { name: 'Next' }).click();
    const run = page.getByRole('group', { name: 'Where it runs' });
    await run.getByLabel('Country', { exact: true }).selectOption({ label: 'United States' });
    await run.getByLabel('State or region', { exact: true }).selectOption({ label: 'California' });
    await page.getByRole('button', { name: 'Add a place' }).click();
    await page.getByLabel('Supports a decision a person makes').check();
    await expect(page.getByRole('list', { name: 'Suggested laws' })).toBeVisible();
    await noSidewaysScroll(page);
    await shot(page, '375-step-laws');
    const add = page.getByRole('button', { name: /^Accept/ }).first();
    const box = await add.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    await page.goto('/register');
    await page.getByRole('table', { name: 'AI systems' }).getByRole('link').first().click();
    await page.getByRole('navigation', { name: 'AI system sections' }).getByRole('link', { name: /^Governance roles/ }).click();
    await page.waitForLoadState('networkidle');
    await noSidewaysScroll(page);
    await shot(page, '375-roles-tab');
    await staff(page, 'admin@futran.demo');
    await page.goto('/admin/reference?tab=models');
    await expect(page.getByRole('region', { name: 'OpenAI', exact: true })).toBeVisible();
    await noSidewaysScroll(page);
    await shot(page, '375-reference-ai-models');
  });
});
