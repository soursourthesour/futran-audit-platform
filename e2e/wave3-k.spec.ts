import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { openNav } from './nav';

/* Wave 3 WS-K on ABC Corp at stage 6 (start-server.sh … late): the bias test calculator (screen 29) with a validation
   failure, a run, a draft finding and the guardrail sandbox; the heat map and lineage (35); benchmarking (34) with no
   signed report yet; the client's bias test data and last year's answers at phone width. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`;
const SHOTS = process.env.WSK_SHOTS || '/mnt/user-data/outputs/wave3/k/e2e';
mkdirSync(SHOTS, { recursive: true });

function applicants(): string {
  // Sex: male 50/100, female 30/80. Race: White 50/100, Hispanic or Latino 30/80. 20 people with no sex or race.
  const cells: [string, string, number, number][] = [['Male', 'White', 60, 30], ['Female', 'White', 40, 20], ['Male', 'Hispanic or Latino', 40, 20], ['Female', 'Hispanic or Latino', 40, 10]];
  const lines = ['id,selected,sex,race_ethnicity'];
  let n = 0;
  for (const [sex, race, total, sel] of cells) for (let i = 0; i < total; i++) lines.push(`A${++n},${i < sel ? 'yes' : 'no'},${sex},${race}`);
  for (let i = 0; i < 20; i++) lines.push(`A${++n},${i < 5 ? 'yes' : 'no'},,`);
  return lines.join('\n') + '\n';
}

async function staff(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function client(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function get(page: Page, path: string) {
  const r = await page.request.get(`/api/v1${path}`);
  expect(r.status(), `GET ${path}`).toBe(200);
  return r.json();
}

async function abcIds(page: Page) {
  const list = await get(page, '/clients');
  const abc = list.clients.find((c: { name: string }) => c.name === 'ABC Corp');
  const sys = await get(page, `/clients/${abc.id}/systems`);
  return { clientId: abc.id as string, sys1: sys.systems.find((s: { reference_id: string }) => s.reference_id === 'SYS-001').id as string };
}

async function shoot(page: Page, name: string) {
  for (const [w, h] of [[1440, 1000], [375, 812]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(250);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${name} at ${w}px scrolls sideways`).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

test.describe.serial('WS-K: bias calculator, heat map and lineage, benchmarking, carry-forward', () => {
  test('screen 29: validation report, a run, what it feeds, a draft finding and the guardrail sandbox', async ({ page }) => {
    await staff(page, 'auditor1@futran.demo');
    const { sys1 } = await abcIds(page);
    await page.goto(`/systems/${sys1}/assess`);
    await page.getByRole('link', { name: 'Bias test' }).click();
    await expect(page.getByRole('heading', { name: 'Bias test: NYC Local Law 144' })).toBeVisible();
    await page.getByRole('button', { name: 'Upload data' }).click();
    const dlg = page.getByRole('dialog', { name: 'Upload applicant data' });
    await dlg.getByLabel('Data file (CSV)', { exact: true }).setInputFiles({ name: 'bad.csv', mimeType: 'text/csv', buffer: Buffer.from('id,selected,sex,race\n1,yes,male,white\n2,perhaps,female,white\n') });
    await dlg.getByRole('button', { name: 'Validate and calculate' }).click();
    await expect(dlg.getByRole('region', { name: 'Validation report' })).toContainText('Row 3: enter selected as yes or no.');
    await dlg.getByLabel('Data file (CSV)', { exact: true }).setInputFiles({ name: 'applicants.csv', mimeType: 'text/csv', buffer: Buffer.from(applicants()) });
    await dlg.getByLabel('Source and explanation of the data', { exact: true }).fill('Historical applicant data for New York roles, January to June.');
    await dlg.getByRole('button', { name: 'Validate and calculate' }).click();
    await expect(page.getByText('Calculated on 200 rows.')).toBeVisible();
    await expect(page.getByText('Unknown sex or race/ethnicity')).toBeVisible();
    const table = page.getByRole('table').filter({ hasText: 'Hispanic or Latino' }).first();
    await expect(table.getByText('Below 0.80')).toBeVisible();
    await page.getByRole('tab', { name: 'Intersectional' }).click();
    await expect(page.getByRole('cell', { name: 'Hispanic or Latino female' })).toBeVisible();
    await expect(page.getByText('§6.2.06 disparate impact ratio:')).toContainText('0.50');
    await page.getByRole('button', { name: 'Create draft findings (1)' }).click();
    await expect(page.getByText('Draft finding created. It is in Findings for review.').or(page.getByText('Findings are locked: sign-off 5 is approved.'))).toBeVisible();
    await page.getByLabel('System under test', { exact: true }).fill('Careers chatbot (sandbox)');
    await page.getByRole('button', { name: 'Run the prompt set' }).click();
    await expect(page.getByText(/Prompt set [\d.]+: 9 passed, 2 failed\./)).toBeVisible();
    await page.getByRole('tab', { name: 'Race/ethnicity' }).click();
    await shoot(page, 'bias-test');
  });

  test('screen 35: heat map, lineage and what proves a control', async ({ page }) => {
    await staff(page, 'chief@futran.demo');
    const { clientId } = await abcIds(page);
    await page.goto(`/clients/${clientId}`);
    await page.getByRole('link', { name: 'Risk heat map and lineage' }).click();
    await expect(page.getByRole('heading', { name: 'Risk heat map and lineage' })).toBeVisible();
    await expect(page.getByRole('table', { name: /Risk heat map/ }).getByRole('cell', { name: /inherent 75–100: high, SYS-001/ }).getByRole('link', { name: /^SYS-001(\*| · High)$/ })).toBeVisible(); // provisional (*) until sign-off 5 locks the score; earlier specs on the shared late server may already have locked it
    await expect(page.getByRole('row', { name: /SYS-001/ }).filter({ hasText: 'Control effect' }).or(page.getByText(/76(\.0)? → 58\.2/)).first()).toBeVisible();
    await expect(page.getByText(/Lineage: why is F-\d+ a finding\?/)).toBeVisible();
    await expect(page.getByText('Finding and remediation')).toBeVisible();
    const proof = page.getByRole('button', { name: 'What proves this control?' }).first();
    if (await proof.count()) {
      await proof.click();
      await expect(page.getByRole('dialog', { name: /What proves control/ })).toContainText('The same evidence also satisfies');
      await page.getByRole('dialog').getByRole('button', { name: 'Close' }).last().click();
    }
    await page.getByLabel('Build type', { exact: true }).selectOption('vendor');
    await expect(page).toHaveURL(/build_type=vendor/);
    await shoot(page, 'heatmap');
    const png = await page.request.get(`/api/v1/clients/${clientId}/heatmap.png`);
    expect(png.headers()['content-type']).toBe('image/png');
  });

  test('screen 34: benchmarking for the Chief Auditor and the practice view for Sales', async ({ page }) => {
    await staff(page, 'chief@futran.demo');
    await openNav(page, 'Insights');
    await expect(page.getByRole('heading', { name: 'Benchmarking and practice insights' })).toBeVisible();
    await expect(page.getByText('Shown when at least 5 clients have consented to benchmarking.').or(page.getByText('No signed reports yet.', { exact: false })).first()).toBeVisible();
    await shoot(page, 'insights');
  });

  test('client: bias test data to keep, and last year’s answers, at phone width', async ({ page }) => {
    await client(page, MARIA);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/bias-data');
    await expect(page.getByRole('heading', { name: 'Bias test data' })).toBeVisible();
    const keep = page.getByRole('button', { name: 'Keep applicants.csv after the retention period' }).first();
    const box = await keep.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44); // touch target at phone width
    await keep.click();
    await expect(page.getByText('The raw data will be kept after the retention period.')).toBeVisible();
    await expect(page.getByText('Kept', { exact: true }).first()).toBeVisible();
    await shoot(page, 'client-bias-data');
    await page.goto('/carried');
    await expect(page.getByRole('heading', { name: 'Last year’s answers' })).toBeVisible();
    await expect(page.getByText('No answers were carried forward into this engagement.')).toBeVisible();
    await shoot(page, 'client-carried');
  });
});
