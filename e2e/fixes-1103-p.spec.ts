import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

/** 11-03 C2–C6 on the late world (Meridian at stage 3, ABC Corp at stage 6): the admin home's change grid and a person's
 * history, the People row menu, job level, the department workbook and an upload to one department. */
const PW = 'Demo-Password-2026';
const KATRIN = 'katrin.vogel@meridian.example';
const SAM = 'sam.okafor@abccorp.example';
const SHOTS = process.env.SHOTS_DIR || 'screenshots';
const LATE = `http://127.0.0.1:${Number(process.env.E2E_PORT || 8765) + 1}`;
test.use({ baseURL: process.env.LATE_URL || LATE });

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function noSideways(page: Page, what: string) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(wide, `${what} scrolls sideways`).toBeLessThanOrEqual(0);
}

const csv = (rows: string[]) => Buffer.from(['Full name,Work email,Job title,Job level,AI compliance role', ...rows].join('\n') + '\n');

test.describe.configure({ mode: 'serial' });

test('the admin home lists role and department changes in a grid; a name opens the history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, SAM);
  await page.goto('/admin/home');
  const grid = page.getByRole('table', { name: 'Role and department changes' });
  await expect(grid).toBeVisible();
  for (const h of ['Name', 'AI compliance role', 'Department', 'Change', 'Changed by', 'When']) await expect(grid.locator('thead').getByRole('button', { name: h, exact: true })).toBeVisible();
  await expect(grid.getByText(/^Gave .* the role/)).toHaveCount(0);  // no more sentence-style lines
  await page.getByLabel('Change', { exact: true }).selectOption('Role given');
  const priya = grid.getByRole('button', { name: 'Change history for Priya Shah' }).first();
  await expect(priya).toBeVisible();
  await shot(page, 'admin-home-1440');
  await priya.click();
  const dlg = page.getByRole('dialog', { name: 'Change history: Priya Shah' });
  await expect(dlg.getByText('Role given', { exact: true }).first()).toBeVisible();
  await expect(dlg.getByText(/Department Compliance Lead for /).first()).toBeVisible();
  await shot(page, 'admin-home-history-1440');
  await page.keyboard.press('Escape');
  await expect(dlg).toHaveCount(0);
});

test('People: the row menu offers each setting; job level is set from it and shown in the grid', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, KATRIN);
  await page.goto('/people/users');
  const grid = page.getByRole('table', { name: 'Users' });
  await expect(grid.locator('thead').getByRole('button', { name: 'AI compliance roles', exact: true })).toBeVisible();
  await expect(page.getByLabel('Job level', { exact: true })).toBeVisible();  // filter; the level shows under the job title
  const row = grid.getByRole('row').filter({ hasText: 'Aarav Menon' });
  await row.getByRole('button', { name: 'Actions for Aarav Menon' }).click();
  const menu = page.getByRole('menu', { name: 'Actions for Aarav Menon' });
  const items = await menu.getByRole('menuitem').allTextContents();
  expect(items.filter((x) => x !== 'Resend invitation')).toEqual(['Edit details', 'AI compliance role', 'Department', 'Job level', 'Change history', 'Remove']);
  await shot(page, 'people-menu-1440');
  await menu.getByRole('menuitem', { name: 'Job level' }).click();
  const dlg = page.getByRole('dialog', { name: 'Job level for Aarav Menon' });
  await dlg.getByLabel('Job level', { exact: true }).selectOption({ label: 'Manager' });
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(row.getByText('Manager', { exact: true })).toBeVisible();
  // right-click opens the same menu; each setting opens its own small dialog
  await row.getByRole('cell').nth(2).click({ button: 'right' });
  await menu.getByRole('menuitem', { name: 'AI compliance role' }).click();
  await expect(page.getByRole('dialog', { name: 'AI compliance roles for Aarav Menon' })).toBeVisible();
  await page.keyboard.press('Escape');
  await row.getByRole('button', { name: 'Actions for Aarav Menon' }).click();
  await menu.getByRole('menuitem', { name: 'Department' }).click();
  await expect(page.getByRole('dialog', { name: 'Department for Aarav Menon' })).toBeVisible();
  await page.keyboard.press('Escape');
  await row.getByRole('button', { name: 'Actions for Aarav Menon' }).click();
  await menu.getByRole('menuitem', { name: 'Edit details' }).click();
  await expect(page.getByRole('dialog', { name: 'Edit details: Aarav Menon' }).getByLabel('Job title', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
});

test('the department workbook downloads; an upload to one department previews, refuses a bad file, then applies', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, KATRIN);
  await page.goto('/people/departments');
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const wb = await page.request.get(`/api/v1/clients/${me.organization.id}/departments/template.xlsx`);
  expect(wb.headers()['content-type']).toContain('spreadsheetml');
  const body = await wb.body();
  expect(body.subarray(0, 2).toString()).toBe('PK');
  if (process.env.WORKBOOK_OUT) { mkdirSync(process.env.WORKBOOK_OUT, { recursive: true }); writeFileSync(`${process.env.WORKBOOK_OUT}/departments_and_people.xlsx`, body); }
  await expect(page.getByRole('link', { name: 'Download workbook' })).toHaveAttribute('href', /template\.xlsx$/);

  const grid = page.getByRole('table', { name: 'Departments' });
  const eng = grid.getByRole('row').filter({ hasText: 'Engineering' });
  // a bad file: listed by row, nothing imported
  await eng.getByRole('button', { name: 'Actions for Engineering' }).click();
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('menu', { name: 'Actions for Engineering' }).getByRole('menuitem', { name: 'Upload users to this department' }).click();
  await (await chooser).setFiles({ name: 'engineering.csv', mimeType: 'text/csv', buffer: csv(['Mia Wolf,mia.wolf@meridian.example,Engineer,Level 9,Contributor', 'Jon Berg,not-an-email,Engineer,Level 1,Contributor']) });
  const card = page.locator('.import-preview');
  await expect(card.getByRole('heading', { name: 'Upload to Engineering: engineering.csv' })).toBeVisible();
  await expect(card.getByText('Row 2: Job level must be one of', { exact: false })).toBeVisible();
  await expect(card.getByText("Row 3: Email 'not-an-email' is not a valid email address.")).toBeVisible();
  await expect(card.getByRole('button', { name: 'Fix the file to import' })).toBeDisabled();
  // the good file
  await eng.getByRole('button', { name: 'Actions for Engineering' }).click();
  const chooser2 = page.waitForEvent('filechooser');
  await page.getByRole('menu', { name: 'Actions for Engineering' }).getByRole('menuitem', { name: 'Upload users to this department' }).click();
  await (await chooser2).setFiles({ name: 'engineering.csv', mimeType: 'text/csv', buffer: csv(['Mia Wolf,mia.wolf@meridian.example,Platform engineer,Level 2,Contributor', 'Jon Berg,jon.berg@meridian.example,Engineering manager,Manager,Contributor']) });
  await expect(card.getByText(/Ready:.*2 people to add/)).toBeVisible();
  await expect(card.getByRole('table', { name: 'Changes in this file' }).getByText('Mia Wolf')).toBeVisible();
  await shot(page, 'import-preview-1440');
  await card.getByRole('button', { name: 'Import 2 changes' }).click();
  await expect(page.getByText('Imported engineering.csv: 2 people added and invited.')).toBeVisible();

  // move one of them with the Department dialog; the history and the admin home show it
  await page.goto('/people/users');
  const users = page.getByRole('table', { name: 'Users' });
  const mia = users.getByRole('row').filter({ hasText: 'Mia Wolf' });
  await expect(mia.getByText('Level 2', { exact: true })).toBeVisible();
  await mia.getByRole('button', { name: 'Actions for Mia Wolf' }).click();
  await page.getByRole('menu', { name: 'Actions for Mia Wolf' }).getByRole('menuitem', { name: 'Department' }).click();
  const dd = page.getByRole('dialog', { name: 'Department for Mia Wolf' });
  await dd.getByLabel('Move to', { exact: true }).selectOption({ label: 'Data Science' });
  await dd.getByRole('button', { name: 'Move', exact: true }).click();
  await expect(mia.getByText('Data Science', { exact: true })).toBeVisible();
  await mia.getByRole('button', { name: 'Actions for Mia Wolf' }).click();
  await page.getByRole('menu', { name: 'Actions for Mia Wolf' }).getByRole('menuitem', { name: 'Change history' }).click();
  const hist = page.getByRole('dialog', { name: 'Change history: Mia Wolf' });
  await expect(hist.getByText('Engineering to Data Science')).toBeVisible();
  await expect(hist.getByText('Contributor for Engineering')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.goto('/admin/home');
  const changes = page.getByRole('table', { name: 'Role and department changes' });
  await expect(changes.getByRole('row').nth(1)).toContainText('Mia Wolf');
  await expect(changes.getByRole('row').nth(1)).toContainText('was Engineering');
});

test.describe('on a phone', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  test('admin home, the People menu and the upload preview fit the screen', async ({ page }) => {
    await signIn(page, SAM);
    await page.goto('/admin/home');
    await expect(page.getByRole('table', { name: 'Role and department changes' })).toBeVisible();
    await noSideways(page, '/admin/home');
    await shot(page, 'admin-home-375');
    await signIn(page, KATRIN);
    await page.goto('/people/users');
    const btn = page.getByRole('button', { name: 'Actions for Aarav Menon' });
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    await expect(page.getByRole('menu', { name: 'Actions for Aarav Menon' }).getByRole('menuitem', { name: 'Job level' })).toBeVisible();
    await noSideways(page, '/people/users');
    await shot(page, 'people-menu-375');
    await page.keyboard.press('Escape');
    await page.getByLabel('User list file').setInputFiles({ name: 'users.csv', mimeType: 'text/csv', buffer: Buffer.from('Full name,Work email,Department,Job title,Job level,AI compliance role\nIda Lund,ida.lund@meridian.example,Engineering,Analyst,Level 1,Contributor\nBo Kim,bo.kim@meridian.example,Nowhere,,,Contributor\n') });
    await expect(page.locator('.import-preview').getByText("Row 3: Department 'Nowhere' is not in the department list.")).toBeVisible();
    await noSideways(page, 'upload preview');
    await shot(page, 'import-preview-375');
  });
});
