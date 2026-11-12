import { test, expect, type Page } from '@playwright/test';
import { expectNav, openNav } from './nav';

/* 10 November feedback U1 and U3: one "AI systems" list for the register, the AI inventory and the current audit's
   systems, with filters and one Add; the old addresses redirect to it with a filter preset; the Integrations screen says
   where confirmed discovered tools go. ABC Corp at stage 6 and Meridian at stage 3 (start-server.sh … late). */
const PW = 'Demo-Password-2026';
const MARIA = 'maria.lopez@abccorp.example';
const TOM = 'tom.reyes@abccorp.example';
const KATRIN = 'katrin.vogel@meridian.example';
const SHOTS = '/mnt/user-data/outputs/feedback-1110/u';

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

const grid = (page: Page) => page.getByRole('table', { name: 'AI systems' });
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test('one AI systems list: one menu entry, the old pages redirect with a filter, audit questions open from a row', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, MARIA);
  await expectNav(page, ['AI systems'], ['AI inventory', 'AI system register']);
  await openNav(page, 'AI systems');
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole('heading', { name: 'AI systems', level: 1 })).toBeVisible();
  for (const h of ['Type', 'Where it came from', 'Stage or status', 'Current audit']) await expect(grid(page).locator('thead')).toContainText(h);

  // the AI inventory: tools and use cases, including those already in the register
  await page.goto('/inventory');
  await expect(page).toHaveURL(/\/register\?type=inventory&all=1$/);
  await expect(page.getByLabel('Type', { exact: true })).toHaveValue('inventory');
  await expect(grid(page).getByRole('link', { name: 'Résumé screening for NYC roles' })).toBeVisible();
  await expect(grid(page).getByRole('row').filter({ hasText: 'Résumé screening for NYC roles' }).getByText('Use case', { exact: true })).toBeVisible();
  await expect(grid(page).getByText('ATS résumé screening')).toHaveCount(0);  // the audit's systems are filtered out
  // a deep link to one use case still opens it
  await grid(page).getByRole('link', { name: 'Résumé screening for NYC roles' }).click();
  await expect(page).toHaveURL(/\/inventory\/[^/?]+$/);
  await expect(page.getByRole('heading', { name: 'Résumé screening for NYC roles', level: 1 })).toBeVisible();

  // the audit's AI systems: filtered to the current audit, with the audit questions on each row
  await page.goto('/systems');
  await expect(page).toHaveURL(/\/register\?audit=yes$/);
  await expect(page.getByLabel('Current audit', { exact: true })).toHaveValue('yes');
  await expect(page.getByRole('region', { name: 'About the current audit' })).toContainText('Describe each AI system in scope before fieldwork');
  const row = grid(page).getByRole('row').filter({ hasText: 'ATS résumé screening' });
  await expect(row.getByText('Audit', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: 'Actions for ATS résumé screening' }).click();
  await shot(page, '1440-row-actions-audit-system');
  await page.getByRole('menuitem', { name: 'Answer the audit questions' }).click();
  await expect(page).toHaveURL(/\/systems\/[^/]+$/);
  await expect(page.getByRole('heading', { name: 'ATS résumé screening', level: 1 })).toBeVisible();
  await page.getByRole('link', { name: 'AI systems' }).first().click();  // the crumb goes back to the filtered list
  await expect(page).toHaveURL(/\/register\?audit=yes$/);

  // one Add with choices
  await page.goto('/register');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  const menu = page.getByRole('menu', { name: 'Add' });
  await expect(menu.getByRole('menuitem')).toHaveText(['AI system', 'Tool or agent', 'Use case', 'Import AI systems from a file']);
  await shot(page, '1440-add-menu');
  await page.keyboard.press('Escape');
  await menu.waitFor({ state: 'detached' });

  // filters: where it came from, then the inventory's use case actions
  await page.getByLabel('Where it came from', { exact: true }).selectOption({ label: 'Audit' });
  await expect(grid(page).getByRole('row').filter({ hasText: 'Use case' })).toHaveCount(0);
  await shot(page, '1440-filters-source-audit');
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByLabel('Type', { exact: true }).selectOption({ label: 'Use case' });
  await grid(page).getByRole('button', { name: 'Actions for Résumé screening for NYC roles' }).click();
  await expect(page.getByRole('menuitem', { name: /^(Review and approve|Open the use case)$/ })).toBeVisible();
  await shot(page, '1440-row-actions-use-case');
  await page.keyboard.press('Escape');
});

test('U3: the Integrations screen says where confirmed tools go and links to them in the list', async ({ page }) => {
  await signIn(page, MARIA);
  await page.goto('/integrations');
  const where = page.locator('#dsc-where');
  await expect(where).toContainText('Confirm adds the tool to the AI inventory as Unreviewed, with Discovery as its source');
  await expect(where).toContainText('It is not added to the AI system register');
  await where.getByRole('link', { name: 'AI systems' }).click();
  await expect(page).toHaveURL(/\/register\?source=discovery$/);
  await expect(page.getByLabel('Where it came from', { exact: true })).toHaveValue('discovery');
});

test('the inventory side of the list: add a tool or agent and approve it (Head of AI Compliance, open inventory)', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, KATRIN);
  await page.goto('/register');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Tool or agent' }).click();
  const dlg = page.getByRole('dialog', { name: 'Add an AI tool or agent' });
  const product = `Notes agent ${Date.now().toString(36)}`;
  await dlg.getByLabel('Vendor', { exact: true }).fill('Fireflies');
  await dlg.getByLabel('Product', { exact: true }).fill(product);
  await dlg.getByLabel('Tool or agent', { exact: true }).selectOption({ label: 'Agent' });
  await dlg.getByRole('button', { name: 'Add to the inventory' }).click();
  await expect(page.getByText(`Fireflies ${product} was added to the AI inventory.`)).toBeVisible();
  const row = grid(page).getByRole('row').filter({ hasText: product });
  await expect(row.getByText('Tool or agent', { exact: true })).toBeVisible();
  await expect(row.getByText('Inventory', { exact: true })).toBeVisible();
  await expect(row.getByText('Unreviewed', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: `Actions for Fireflies ${product}` }).click();
  await expect(page.getByRole('menuitem', { name: 'Import new inventory items into the register' })).toBeVisible();
  await shot(page, '1440-row-actions-tool');
  await page.getByRole('menuitem', { name: 'Approve', exact: true }).click();
  await expect(page.getByText(`Fireflies ${product} is marked approved.`)).toBeVisible();
  await expect(row.getByText('Approved', { exact: true })).toBeVisible();
});

test('a Contributor sees their department’s inventory and audit systems, and no register', async ({ page }) => {
  await signIn(page, TOM);
  await openNav(page, 'AI systems');
  await expect(grid(page).getByRole('link', { name: 'Résumé screening for NYC roles' })).toBeVisible();
  await expect(grid(page).getByText('Invoice anomaly detection')).toHaveCount(0);  // Finance's use case and audit system
  await expect(grid(page).locator('thead')).not.toContainText('Go-live gate');
  await expect(page.getByRole('button', { name: 'Import from inventory' })).toHaveCount(0);
  await expect(page.getByRole('list', { name: 'Register summary' })).toHaveCount(0);
});

test.describe('phone', () => {
  test.use({ viewport: { width: 375, height: 812 } });
  test('the list, its filters, the Add menu and a row menu at 375 px', async ({ page }) => {
    await signIn(page, MARIA);
    await page.goto('/register');
    await expect(page.getByRole('heading', { name: 'AI systems', level: 1 })).toBeVisible();
    await noSidewaysScroll(page);
    await shot(page, '375-list-and-filters');
    const add = page.getByRole('button', { name: 'Add', exact: true });
    expect((await add.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await add.click();
    await expect(page.getByRole('menuitem', { name: 'Use case' })).toBeVisible();
    await noSidewaysScroll(page);
    await page.screenshot({ path: `${SHOTS}/375-add-menu.png` });
    await page.keyboard.press('Escape');
    await page.getByLabel('Type', { exact: true }).selectOption({ label: 'Use case' });
    const btn = grid(page).getByRole('button', { name: 'Actions for Résumé screening for NYC roles' });
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    await expect(page.getByRole('menu', { name: 'Actions for Résumé screening for NYC roles' })).toBeVisible();
    await noSidewaysScroll(page);
    await page.screenshot({ path: `${SHOTS}/375-row-actions.png` });
  });
});
