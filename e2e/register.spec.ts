import { test, expect, type Page } from '@playwright/test';

// ABC Corp from start-server.sh … late: the AI system register (R1–R6), seeded from the inventory, with NYC Local
// Law 144 and its role map and requirements from the regulatory master seed.
const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`;
const PRIYA = `priya.shah@${ABC}`;

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function addSystem(page: Page, name: string, law?: string) {
  await page.goto('/register/new');
  await page.getByLabel('Name *', { exact: true }).fill(name);
  await page.getByLabel('Type *', { exact: true }).selectOption({ label: 'AI agent' });
  await page.getByLabel('Built or bought *', { exact: true }).selectOption({ label: 'Bought from vendor' });
  await page.getByLabel('Stage *', { exact: true }).selectOption({ label: 'In development / procurement' });
  await page.getByLabel('Purpose *', { exact: true }).fill('Books interviews with shortlisted candidates by email.');
  await page.getByLabel('System owner', { exact: true }).selectOption({ label: 'Priya Shah · Head of HR' });
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'Vendor and model' })).toBeVisible();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'What the agent can do' })).toBeVisible();
  await page.getByLabel('Send email', { exact: true }).check();
  await page.getByLabel('Acts, but a person approves first-time or unusual actions').check();
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('Personal information', { exact: true }).check();
  await page.getByLabel('Job candidates', { exact: true }).check();
  await page.getByLabel('Was consent obtained?', { exact: true }).selectOption({ label: 'Yes, consent obtained' });
  await page.getByRole('button', { name: 'Next' }).click();
  if (law) {
    await page.getByLabel('Add a law', { exact: true }).fill(law);
    await page.getByRole('list', { name: 'Matching laws' }).getByRole('button').first().click();
  }
  await page.getByLabel('Supports a decision a person makes').check();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'History to date' })).toBeVisible();
}

test('register grid: import from inventory, bulk edit with a reason, row menu and change history', async ({ page }) => {
  await clientUser(page, MARIA);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'AI system register' }).click();
  await expect(page.getByRole('heading', { name: 'AI system register' })).toBeVisible();
  await page.getByRole('button', { name: 'Import from inventory' }).click();
  await expect(page.getByText(/AI systems added from the inventory as Proposed/)).toBeVisible();
  const grid = page.getByRole('table', { name: 'AI systems' });
  await expect(grid.getByRole('link', { name: 'ScreenRank ATS' })).toBeVisible();
  // running it again adds nothing
  await page.getByRole('button', { name: 'Import from inventory' }).click();
  await expect(page.getByText(/^0 AI systems added from the inventory/)).toBeVisible();

  // bulk edit: Live is never offered; a reason is required; only the changed field applies
  await grid.getByRole('checkbox', { name: 'Select ScreenRank ATS' }).check();
  await grid.getByRole('checkbox', { name: 'Select Invoice anomaly model' }).check();
  await page.getByRole('region', { name: 'Actions for selected rows' }).getByRole('button', { name: 'Edit selected' }).click();
  const dlg = page.getByRole('dialog');
  await expect(dlg.getByLabel('Stage', { exact: true }).locator('option', { hasText: /^Live$/ })).toHaveCount(0);
  await dlg.getByLabel('Stage', { exact: true }).selectOption({ label: 'In development / procurement' });
  await expect(dlg.getByText('2 changes across 2 systems.')).toBeVisible();
  await expect(dlg.getByRole('button', { name: 'Apply to 2 systems' })).toBeDisabled();
  await dlg.getByLabel('Reason for change *', { exact: true }).fill('Procurement started for both systems.');
  await dlg.getByRole('button', { name: 'Apply to 2 systems' }).click();
  await expect(page.getByText('2 changes applied across 2 systems.')).toBeVisible();
  await expect(grid.getByRole('row').filter({ hasText: 'ScreenRank ATS' }).getByText('In development / procurement')).toBeVisible();

  // the ⋯ menu and right-click open the same row menu; change history shows the bulk reason
  const row = grid.getByRole('row').filter({ hasText: 'ScreenRank ATS' });
  const btn = row.getByRole('button', { name: 'Actions for ScreenRank ATS' });
  await btn.click();
  const menu = page.getByRole('menu', { name: 'Actions for ScreenRank ATS' });
  for (const item of ['Open and edit', 'Edit governance roles', 'Record a bias test', 'Upload evidence', 'Submit for go-live approval', 'Duplicate', 'View change history', 'Retire this system']) {
    await expect(menu.getByRole('menuitem', { name: item })).toBeVisible();
  }
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  await row.getByRole('link', { name: 'ScreenRank ATS' }).click({ button: 'right' });
  await expect(menu).toBeVisible();
  await menu.getByRole('menuitem', { name: 'View change history' }).click();
  const changes = page.getByRole('table', { name: 'Changes' });
  await expect(changes.getByRole('row').filter({ hasText: 'Procurement started for both systems.' })).toBeVisible();
  await expect(changes.getByText('bulk edit').first()).toBeVisible();
});

test('roles editor and the go-live gate refusal', async ({ page }) => {
  await clientUser(page, PRIYA);
  await addSystem(page, 'Interview scheduling agent', 'Local Law 144');
  await page.getByRole('button', { name: 'Save and fill governance roles' }).click();
  await expect(page).toHaveURL(/\/register\/[^/]+\/roles$/);
  await expect(page.getByRole('heading', { name: 'Interview scheduling agent' })).toBeVisible();
  const own = page.getByRole('table', { name: 'Roles for this AI system' });
  await expect(own.getByRole('row').filter({ hasText: 'Bias testing lead' }).getByText('NYC Local Law 144')).toBeVisible();

  // the API refuses go-live while roles needed by go-live are unanswered, and says which
  await page.getByRole('button', { name: 'Submit for go-live approval' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Go-live is blocked until these are resolved' })).toContainText('Bias testing lead');

  // the role editor: a Department Head cannot mark a required role Not applicable
  await own.getByRole('button', { name: 'Actions for Bias testing lead / independent auditor' }).click();
  await page.getByRole('menuitem', { name: 'Edit role' }).click();
  const dlg = page.getByRole('dialog', { name: 'Bias testing lead / independent auditor' });
  await expect(dlg.getByRole('radio', { name: /Not applicable/ })).toBeDisabled();
  await dlg.getByRole('radio', { name: /Yes, an external party/ }).check();
  await dlg.getByRole('button', { name: 'Save role' }).click();
  await expect(dlg.getByText('Name the vendor, auditor firm or service provider.')).toBeVisible();
  await dlg.getByLabel('External party *', { exact: true }).fill('Fairness Audit LLP');
  await dlg.getByRole('button', { name: 'Save role' }).click();
  await expect(dlg).toHaveCount(0);
  const biasRow = own.getByRole('row').filter({ hasText: 'Bias testing lead' });
  await expect(biasRow.getByText('External party')).toBeVisible();
  await expect(biasRow.getByText('Fairness Audit LLP')).toBeVisible();
  // a second role as No such person shows as a gap that blocks go-live
  await own.getByRole('button', { name: 'Actions for Transparency and notice owner' }).click();
  await page.getByRole('menuitem', { name: 'Edit role' }).click();
  await page.getByRole('dialog').getByRole('radio', { name: /No such person/ }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Save role' }).click();
  await expect(own.getByRole('row').filter({ hasText: 'Transparency and notice owner' }).getByText('Blocks go-live')).toBeVisible();
  await page.getByLabel('Show only gaps').check();
  await expect(own.getByRole('row').filter({ hasText: 'Bias testing lead' })).toHaveCount(0);
});

test('history: first-entry questions, the no-incident statement and a history entry', async ({ page }) => {
  await clientUser(page, PRIYA);
  await addSystem(page, 'Candidate FAQ assistant');
  await page.getByLabel('No, none known. The system owner signs a statement.').check();
  await page.getByRole('group', { name: 'Have any bias tests been done?' }).getByLabel('No').check();
  await page.getByRole('group', { name: /Was it tested before release/ }).getByLabel('Yes').check();
  await page.getByRole('button', { name: 'Save and fill governance roles' }).click();
  await expect(page).toHaveURL(/\/roles$/);
  await page.getByRole('link', { name: 'History and requirements' }).click();
  // Priya is the system owner, so she signs the statement here
  await expect(page.getByText(/I know of no incidents, complaints or errors involving this system/)).toBeVisible();
  await page.getByLabel('Type your name to sign', { exact: true }).fill('Priya Shah');
  await page.getByRole('button', { name: 'Sign statement' }).click();
  await expect(page.getByText(/Signed by Priya Shah on/)).toBeVisible();

  await page.getByRole('button', { name: 'Add entry' }).click();
  await page.getByLabel('Kind of entry', { exact: true }).selectOption({ label: 'Deployment test' });
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  const dlg = page.getByRole('dialog', { name: 'Add deployment test' });
  await dlg.getByRole('button', { name: 'Save entry' }).click();
  await expect(dlg.getByText('Enter the date.')).toBeVisible();
  await dlg.getByLabel('Date *', { exact: true }).fill('2026-09-01');
  await dlg.getByLabel('Summary *', { exact: true }).fill('User acceptance test on 50 scheduling requests');
  await dlg.getByLabel('Kind of test', { exact: true }).selectOption({ label: 'User acceptance' });
  await dlg.getByLabel('Sample size', { exact: true }).fill('50');
  await dlg.getByRole('button', { name: 'Save entry' }).click();
  const log = page.getByRole('table', { name: 'History log' });
  await expect(log.getByRole('row').filter({ hasText: 'User acceptance test on 50 scheduling requests' })).toBeVisible();
  // the tracing add-on is shown locked, and recommended for an agent that takes actions
  await expect(page.getByText('Recommended for this system')).toBeVisible();
  await expect(page.getByText('an AI agent that takes actions')).toBeVisible();
});

test.describe('375 px', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  test('register screens fit a phone with no sideways scroll', async ({ page }) => {
    await clientUser(page, MARIA);
    for (const path of ['/register', '/governance/roles', '/register/new']) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await noSidewaysScroll(page);
    }
    await page.goto('/register');
    await page.getByRole('table', { name: 'AI systems' }).getByRole('link').first().click();
    for (const tab of ['Details', 'Governance roles', 'History and requirements', 'Tracing', 'Evidence', 'Change history']) {
      await page.getByRole('navigation', { name: 'AI system sections' }).getByRole('link', { name: new RegExp(`^${tab}`) }).click();
      await page.waitForLoadState('networkidle');
      await noSidewaysScroll(page);
    }
    const add = page.getByRole('link', { name: 'Add AI system' });
    await page.goto('/register');
    const box = await add.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
  });
});
