import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import { openNav, expectNav } from './nav';

/* Release 2 R1 on the fresh server: the President (a Price List Owner) edits the master price list (SM-14) inline and in
   the side panel, saves with one reason, reads the row history and previews an Excel import; a Sales Officer views the
   list read-only, suggests a change and builds an estimate from the Governed package (SM-15). Screenshots at 1440 px
   (and 375 px for the Estimator). */
const PW = 'Demo-Password-2026';
const SHOTS = process.env.R1_SHOTS || '/mnt/user-data/outputs/release2/r1';
mkdirSync(SHOTS, { recursive: true });
test.use({ viewport: { width: 1440, height: 1000 } });

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/mailbox')) await page.getByRole('button', { name: 'Not now' }).click();
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w).toBeLessThanOrEqual(1);
}

/** A workbook in the importer's format: A-02a's List changes and A-14 is new; the rest of the price list is absent. */
function workbook(): string {
  const dir = mkdtempSync(join(tmpdir(), 'r1-import-'));
  const path = join(dir, 'Futran_Master_Price_List_R2.xlsx');
  const py = `
import sys
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = "Master Price List"
ws.append(["Code","Product","Line item","Billing","Basis","Periods/yr","Low","List","High","Price status","Sellable status"])
ws.append(["A-02a","Audit","Audit, up to 10 systems","One-time","$",1,12000,15500,18000,"Proposed","Available"])
ws.append(["A-14","Audit","Annual re-audit","Annual","%",1,50,60,70,"Proposed","Available"])
wb.save(sys.argv[1])`;
  execFileSync(join(__dirname, '../backend/.venv/bin/python'), ['-c', py, path]);
  return path;
}

test('SM-14: a Price List Owner edits inline and in the side panel, saves with a reason, reads history and previews an import', async ({ page }) => {
  await signIn(page, 'president@futran.demo');
  await expectNav(page, ['Price list'], ['Estimator']);
  await openNav(page, 'Price list');
  await expect(page).toHaveURL(/\/staff\/admin\/catalog$/);
  await expect(page.getByRole('heading', { name: 'Master price list' })).toBeVisible();
  await expect(page.getByText(/13 items · 11 available · 1 manual delivery · 1 roadmap · catalog version 1/)).toBeVisible();
  await expect(page.getByText(/starter items from the screen designs/)).toBeVisible();
  const grid = page.getByRole('table', { name: 'Master price list' });
  await expect(grid.getByRole('row')).toHaveCount(14);

  // inline edit: click a cell, type, press Enter; the cell is highlighted until saved
  await grid.getByRole('button', { name: /^List A-02b: 35,000/ }).click();
  const input = grid.getByRole('textbox', { name: 'List A-02b' });
  await input.fill('36,500');
  await input.press('Enter');
  await expect(grid.getByRole('button', { name: /^List A-02b: 36,500 \(unsaved\)/ })).toHaveClass(/cell-changed/);
  await expect(page.getByText('1 unsaved change')).toBeVisible();

  // side panel: the full deliverables editor
  await grid.getByRole('button', { name: 'Read all deliverables for A-02b' }).click();
  const panel = page.getByRole('complementary', { name: 'A-02b details' });
  await expect(panel.getByRole('heading', { name: 'A-02b · Audit, 11–50 systems' })).toBeVisible();
  const deliv = panel.getByLabel(/Deliverables — what the client gets/);
  await expect(deliv).toHaveValue(/Typical duration: 6–10 weeks\./);
  await deliv.fill(`${await deliv.inputValue()}\nIncludes one follow-up call after the readout.`);
  await expect(panel.getByText(/Unsaved: List \$35,000 → \$36,500; Deliverables text edited/)).toBeVisible();
  await shot(page, 'sm14-side-panel');
  await panel.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByText('2 unsaved changes')).toBeVisible();
  await shot(page, 'sm14-grid-unsaved');

  // save with one reason
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Give one reason for this batch of changes.')).toBeVisible();
  await page.getByLabel('Reason for these changes').fill('Q1 2027 price review; clearer deliverables for A-02b');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Saved as version 2: 2 change(s).')).toBeVisible();
  await expect(page.getByText(/catalog version 2 · last saved by Morgan Hale/)).toBeVisible();
  await expect(grid.getByRole('button', { name: /^List A-02b: 36,500$/ })).toBeVisible();

  // validation: Low above List is refused, the batch is not saved
  await grid.getByRole('button', { name: /^List A-02a: 15,000/ }).click();
  await grid.getByRole('textbox', { name: 'List A-02a' }).fill('11000');
  await grid.getByRole('textbox', { name: 'List A-02a' }).press('Enter');
  await page.getByLabel('Reason for these changes').fill('Try a low price');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText(/Low must not be above List/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Discard' }).click();

  // row menu → View history
  await grid.getByRole('button', { name: 'Actions for A-02b' }).click();
  await page.getByRole('menuitem', { name: 'View history' }).click();
  const hist = page.getByRole('dialog', { name: 'History · A-02b' });
  await expect(hist.getByRole('cell', { name: 'Q1 2027 price review; clearer deliverables for A-02b' }).first()).toBeVisible();
  await expect(hist.getByRole('cell', { name: '36,500' })).toBeVisible();
  await shot(page, 'sm14-history');
  await hist.getByRole('button', { name: 'Close' }).click();

  // Excel import: preview of adds, changes and retirements before anything is saved
  await page.getByRole('button', { name: 'Import Excel' }).click();
  const dlg = page.getByRole('dialog', { name: 'Import Excel' });
  await dlg.getByLabel('Workbook to import').setInputFiles(workbook());
  await dlg.getByRole('button', { name: 'Preview import' }).click();
  await expect(dlg.getByText('1 to add')).toBeVisible();
  await expect(dlg.getByText('12 to retire')).toBeVisible();
  await expect(dlg.getByRole('table', { name: 'Changes in the workbook' }).getByRole('cell', { name: '15,500' })).toBeVisible();
  await shot(page, 'sm14-import-preview');
  await dlg.getByRole('checkbox', { name: 'Retire items that are not in the workbook' }).uncheck();
  await expect(dlg.getByText('0 to retire')).toBeVisible();
  await dlg.getByLabel('Reason').fill('Load two rows from the R2 workbook');
  await dlg.getByRole('button', { name: 'Save import' }).click();
  await expect(page.getByText(/Imported as version 3: 1 added, 1 change, 0 retired/)).toBeVisible();
  await expect(grid.getByRole('cell', { name: 'A-14', exact: true })).toBeVisible();

  // Packages tab
  await page.getByRole('link', { name: /^Packages/ }).click();
  await expect(page.getByRole('heading', { name: 'Governed' })).toBeVisible();
  await expect(page.getByText('Year-1 value at list: $72,700')).toBeVisible();
  await shot(page, 'sm14-packages');
  await page.getByRole('link', { name: 'Mapping rules' }).click();
  await expect(page).toHaveURL(/\/staff\/admin\/catalog\/rules$/);
  await noSidewaysScroll(page);
});

test('SM-14 for viewers, then SM-15: a Sales Officer suggests a change and builds an estimate from the Governed package', async ({ page }) => {
  await signIn(page, 'sales@futran.demo');
  await expectNav(page, ['Price list', 'Estimator'], []);
  await page.goto('/staff/admin/catalog');
  const grid = page.getByRole('table', { name: 'Master price list' });
  await expect(grid.getByRole('row').nth(1)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add item' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Import Excel' })).toHaveCount(0);
  await expect(grid.getByRole('button', { name: /^List A-05/ })).toHaveCount(0);
  await grid.getByRole('button', { name: 'Actions for A-05' }).click();
  await page.getByRole('menuitem', { name: 'Suggest a change' }).click();
  const sug = page.getByRole('dialog', { name: 'Suggest a change · A-05' });
  await sug.getByLabel('Suggested value').fill('1,750');
  await sug.getByLabel('Reason').fill('Clients ask for more sources per sweep.');
  await sug.getByRole('button', { name: 'Send suggestion' }).click();
  await expect(page.getByText('Suggestion sent to the Price List Owners.')).toBeVisible();

  await openNav(page, 'Estimator');
  await expect(page).toHaveURL(/\/sales\/estimate$/);
  await page.getByLabel('Start from package').selectOption({ label: 'Governed' });
  const lines = page.getByRole('table', { name: 'Estimate lines' });
  await expect(lines.getByRole('textbox', { name: 'Qty A-05' })).toHaveValue('3');
  const price = lines.getByRole('textbox', { name: 'Unit price A-02a' });
  await price.fill('13,500');
  await price.press('Enter');
  await expect(lines.getByText('Edited')).toBeVisible();
  await expect(lines.getByText('−$2,000')).toBeVisible();  // A-02a's list is $15,500 after the import in the first test
  const totals = page.getByRole('region', { name: 'Totals' });
  await expect(totals.getByText('$39,500')).toBeVisible();
  await expect(totals.getByText('$70,700')).toBeVisible();
  const guard = page.getByRole('region', { name: 'Approvals a proposal would need' });
  await expect(guard.getByText(/1 line edited, still inside the Low–High range: no extra approval\./)).toBeVisible();
  await expect(guard.getByText('P-1', { exact: true })).toBeVisible();

  // What the client gets, and roadmap items can't be added
  await lines.getByRole('button', { name: 'What the client gets' }).nth(1).click();
  await expect(lines.getByText(/Every AI tool your people use/)).toBeVisible();
  await expect(lines.getByText(/Assumption:/)).toBeVisible();
  await page.getByLabel('Add item by code or name').fill('M-09');
  await expect(page.getByRole('button', { name: 'Add M-09 Trust Center' })).toBeDisabled();
  await page.getByLabel('Add item by code or name').fill('');

  // discount: the Sales Manager approves up to 15%
  await page.getByLabel('Discount on recurring (%)').fill('10');
  await expect(totals.getByText('−$3,120')).toBeVisible();
  await expect(guard.getByText('P-2', { exact: true })).toBeVisible();

  await page.getByLabel('Estimate name').fill('Governed package, first pass');
  await page.getByRole('button', { name: 'Save estimate' }).click();
  await expect(page.getByText(/Saved as v1 by Sam Seller/)).toBeVisible();
  await expect(page).toHaveURL(/\/sales\/estimate\?id=/);
  await expect(page.getByRole('button', { name: 'Convert to proposal' })).toBeDisabled();
  await shot(page, 'sm15-estimator-1440');
  await noSidewaysScroll(page);

  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.getByRole('table', { name: 'Estimate lines' }).getByRole('textbox', { name: 'Unit price A-02a' })).toHaveValue('13,500');
  await noSidewaysScroll(page);
  await shot(page, 'sm15-estimator-375');
});
