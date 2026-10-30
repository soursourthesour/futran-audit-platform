import { test, expect, type Page } from '@playwright/test';

// Meridian at stage 3 (start-server.sh … late): People > Departments and People > Users grids, and the employee data
// notice edited and sent by the CAICO and acknowledged by another user at sign-in.
const PW = 'Demo-Password-2026';
const KATRIN = 'katrin.vogel@meridian.example';
const AARAV = 'aarav.menon@meridian.example';

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test('departments grid: inline edit, row menu by button, right-click and keyboard', async ({ page }) => {
  await clientUser(page, KATRIN);
  await page.goto('/people');
  await expect(page).toHaveURL(/\/people\/departments$/);
  const grid = page.getByRole('table', { name: 'Departments' });
  await expect(grid.getByText('Engineering', { exact: true })).toBeVisible();

  // inline edit: double-click, type, Enter saves; Escape cancels
  const row = grid.getByRole('row').filter({ hasText: 'Engineering' });
  await row.getByRole('cell').nth(2).dblclick();
  await page.getByLabel('Headcount for Engineering', { exact: true }).fill('abc');
  await page.getByLabel('Headcount for Engineering', { exact: true }).press('Enter');
  await expect(row.getByRole('alert')).toHaveText('Headcount must be a whole number.');
  await page.getByLabel('Headcount for Engineering', { exact: true }).fill('42');
  await page.getByLabel('Headcount for Engineering', { exact: true }).press('Enter');
  await expect(page.getByLabel('Headcount for Engineering', { exact: true })).toHaveCount(0);
  await expect(row.getByRole('cell', { name: /^42/ })).toBeVisible();
  await row.getByRole('cell').nth(1).dblclick();
  await page.getByLabel('Head of Engineering', { exact: true }).fill('Not saved');
  await page.getByLabel('Head of Engineering', { exact: true }).press('Escape');
  await expect(grid.getByText('Not saved')).toHaveCount(0);

  // the ⋯ button opens the row menu; arrow keys move; Escape closes and returns focus
  const btn = row.getByRole('button', { name: 'Actions for Engineering' });
  await expect(btn).toHaveAttribute('aria-haspopup', 'menu');
  await btn.click();
  const menu = page.getByRole('menu', { name: 'Actions for Engineering' });
  await expect(menu.getByRole('menuitem', { name: 'Edit' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  await expect(btn).toBeFocused();

  // right-click anywhere on the row opens the same menu at the pointer
  await row.getByRole('cell').nth(4).click({ button: 'right' });
  await expect(menu).toBeVisible();
  await menu.getByRole('menuitem', { name: 'Edit' }).click();
  await expect(page.getByRole('dialog', { name: 'Edit Engineering' })).toBeVisible();
  await page.getByLabel('Head of department', { exact: true }).fill('Sven Larsen');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(grid.getByText('Sven Larsen')).toBeVisible();
});

test('users grid: filter, sort, search, select and bulk bar', async ({ page }) => {
  await clientUser(page, KATRIN);
  await page.goto('/people/users');
  const grid = page.getByRole('table', { name: 'Users' });
  await expect(grid.getByText('Aarav Menon', { exact: true })).toBeVisible();
  await page.getByLabel('Department', { exact: true }).selectOption({ label: 'Engineering' });
  await expect(grid.getByText('Aarav Menon', { exact: true })).toBeVisible();
  await expect(grid.getByText('Lena Fischer', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByLabel('Search by name or email').fill('fischer');
  await expect(grid.getByText('Lena Fischer', { exact: true })).toBeVisible();
  await expect(grid.getByText('Aarav Menon', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Clear filters' }).click();

  const jobTitle = grid.locator('th', { has: page.getByRole('button', { name: 'Job title' }) });
  await expect(jobTitle).toHaveAttribute('aria-sort', 'none');
  await jobTitle.getByRole('button').click();
  await expect(jobTitle).toHaveAttribute('aria-sort', 'ascending');
  await jobTitle.getByRole('button').click();
  await expect(jobTitle).toHaveAttribute('aria-sort', 'descending');

  await grid.getByLabel('Select Aarav Menon').check();
  await grid.getByLabel('Select Lena Fischer').check();
  const bulk = page.getByRole('region', { name: 'Actions for selected rows' });
  await expect(bulk.getByText('2 selected')).toBeVisible();
  await expect(bulk.getByRole('button', { name: 'Change department' })).toBeVisible();
  await bulk.getByRole('button', { name: 'Remove' }).click();
  await expect(page.getByRole('dialog', { name: 'Remove 2 people' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();

  // inline edit of a job title, then keyboard: Enter opens the editor, Escape cancels
  const row = grid.getByRole('row').filter({ hasText: 'Lena Fischer' });
  await row.getByRole('cell').nth(3).dblclick();
  await page.getByLabel('Job title of Lena Fischer', { exact: true }).fill('Head of Data Science');
  await page.getByLabel('Job title of Lena Fischer', { exact: true }).press('Enter');
  await expect(page.getByLabel('Job title of Lena Fischer', { exact: true })).toHaveCount(0);
  await expect(row.getByText('Head of Data Science')).toBeVisible();

  // row menu from the keyboard
  await row.getByRole('button', { name: 'Actions for Lena Fischer' }).focus();
  await page.keyboard.press('Enter');
  const menu = page.getByRole('menu', { name: 'Actions for Lena Fischer' });
  await page.keyboard.press('ArrowDown');
  await expect(menu.getByRole('menuitem').nth(1)).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
});

test('the CAICO edits and resends the data notice; another user acknowledges it at sign-in', async ({ page }) => {
  await clientUser(page, KATRIN);
  await page.goto('/start');
  await page.getByRole('button', { name: 'Review or resend' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByRole('button', { name: 'Edit notice' }).click();
  const box = dlg.getByLabel('Notice text', { exact: true });
  await box.fill(`${await box.inputValue()}\n\nQuestions about this notice go to the Head of AI Compliance.`);
  await dlg.getByRole('button', { name: 'Save changes' }).click();
  await expect(dlg.getByText('Changed since it was sent')).toBeVisible();
  await dlg.getByRole('button', { name: 'Send the new version to employees' }).click();
  await dlg.getByRole('button', { name: 'Send to employees', exact: true }).click();
  await expect(page.getByText(/Version \d+ of the notice was emailed to/)).toBeVisible();

  await clientUser(page, AARAV);
  await expect(page).toHaveURL(/\/welcome\/notice(\?next=%2Fmy-department)?$/);
  await expect(page.getByRole('heading', { name: 'Read and acknowledge' })).toBeVisible();
  await expect(page.getByText('Questions about this notice go to the Head of AI Compliance.')).toBeVisible();
  await page.goto('/inventory');
  await expect(page).toHaveURL(/\/welcome\/notice\?next=%2Finventory$/);  // nothing else opens until it is acknowledged
  await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check();
  await page.getByRole('button', { name: 'Acknowledge and continue' }).click();
  await expect(page).toHaveURL(/\/inventory$/);  // the page he asked for survives the notice step

  await clientUser(page, KATRIN);
  await page.goto('/people/users');
  const aarav = page.getByRole('table', { name: 'Users' }).getByRole('row').filter({ hasText: 'Aarav Menon' });
  await expect(aarav.getByText(/^Acknowledged/)).toBeVisible();
});

test.describe('on a phone', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  test('People and Getting started do not scroll sideways; the grid scrolls inside its box', async ({ page }) => {
    await clientUser(page, KATRIN);
    for (const path of ['/start', '/people/departments', '/people/users']) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(wide, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
    }
    const btn = page.getByRole('button', { name: 'Actions for Aarav Menon' });
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    await expect(page.getByRole('menu', { name: 'Actions for Aarav Menon' })).toBeVisible();
  });
});
