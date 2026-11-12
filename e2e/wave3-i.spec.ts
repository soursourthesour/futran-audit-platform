import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Wave 3 WS-I on ABC Corp (start-server.sh … late). On a fresh late server the audit is at stage 6: the "Will create"
   commitment for the AI acceptable use policy is open and there is no signed report, so Futran cannot confirm Trust Center
   items. When the whole suite runs, the journey spec has completed the audit first: the commitment is closed and the final
   report is signed, so the policy starts from the library and the item is confirmed and published. Screen 27: policy
   builder, approval, acknowledgment links. Screen 33: assigning a module and an employee taking it on a phone.
   Screen 32: the Trust Center editor, the Chief Auditor's queue and the public page. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`; // Chief AI Compliance Officer
const TOM = `tom.reyes@${ABC}`; // Contributor, HR
const SHOTS = process.env.WSI_SHOTS || '/mnt/user-data/outputs/wave3/ws-i';
mkdirSync(SHOTS, { recursive: true });

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
  if (/\/welcome\/terms/.test(page.url())) {
    await page.getByRole('checkbox').first().check();
    await page.getByRole('button', { name: /Accept|Continue/ }).click();
    await expect(page).not.toHaveURL(/\/welcome\/terms/);
  }
}

async function staffUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function noSidewaysScroll(page: Page, what: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${what} scrolls sideways`).toBeLessThanOrEqual(1);
}

async function shoot(page: Page, name: string) {
  for (const [w, h] of [[1440, 1000], [375, 812]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(300);
    await noSidewaysScroll(page, `${name} at ${w}px`);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

async function rowMenu(page: Page, row: ReturnType<Page['getByRole']>, item: string) {
  const btn = row.getByRole('button', { name: /Actions for/ });
  await btn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await btn.click();
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

test.describe.serial('WS-I: policy builder, AI literacy training and Trust Center', () => {
  test('27: the CAICO builds the acceptable use policy from the Will create commitment, approves it and asks staff to acknowledge', async ({ page }) => {
    await clientUser(page, MARIA);
    await page.goto('/governance');
    await expect(page.getByRole('heading', { name: /\d+ commitments?/ })).toBeVisible();
    // the commitment is open while the audit is at stage 6; when the whole suite runs, the journey spec has closed it already
    const fromCommitment = (await page.getByRole('link', { name: 'Start from Futran template' }).count()) > 0;
    if (fromCommitment) await page.getByRole('link', { name: 'Start from Futran template' }).first().click();
    else { await page.goto('/policies'); await page.getByRole('button', { name: 'Start from Futran template' }).first().click(); }
    const dlg = page.getByRole('dialog', { name: 'Start from Futran template' });
    if (!fromCommitment) await dlg.getByLabel('Template', { exact: true }).selectOption('acceptable_use');
    await expect(dlg.getByLabel('Template', { exact: true })).toHaveValue('acceptable_use');
    await dlg.getByRole('button', { name: 'Start the draft' }).click();
    await expect(page).toHaveURL(/\/policies\/[\w-]+$/);
    await expect(page.getByRole('heading', { level: 1, name: 'AI acceptable use policy' })).toBeVisible();
    await page.getByLabel('Approved AI tools', { exact: true }).fill('Microsoft 365 Copilot (company account)\nScreenRank résumé screening');
    await page.getByLabel('Policy owner', { exact: true }).fill('Maria Lopez, Chief AI Compliance Officer');
    await page.getByRole('button', { name: 'Regenerate draft' }).click();
    await expect(page.getByText('Draft regenerated from your answers.')).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => page.locator('section[aria-labelledby="pb-draft-h"] textarea').evaluateAll((els) => els.some((e) => (e as HTMLTextAreaElement).value.startsWith('Microsoft 365 Copilot (company account)\nScreenRank')))).toBe(true);
    await shoot(page, 'policy-builder-draft');
    await page.getByRole('button', { name: 'Request Futran review' }).click();
    await page.getByRole('dialog').getByLabel('What would you like Futran to look at?', { exact: true }).fill('Please check the hiring section against our ScreenRank set-up.');
    await page.getByRole('dialog').getByRole('button', { name: 'Request Futran review' }).click();
    await expect(page.getByText('Futran has been asked to review this policy.')).toBeVisible();
    await page.getByRole('button', { name: 'Send for approval' }).click();
    await expect(page.getByText('Sent to the Chief AI Compliance Officer for approval.')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: 'Approve and publish' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Publish and send' }).click();
    await expect(page.getByText('Published. Staff have been asked to acknowledge it.')).toBeVisible({ timeout: 30_000 });
    if (fromCommitment) await expect(page.getByText('Commitment closed')).toBeVisible();
    await expect(page.getByRole('table', { name: 'Acknowledgments' })).toBeVisible();
    await shoot(page, 'policy-builder-published');
    await page.goto('/policies');
    await expect(page.getByRole('table', { name: 'Policies' }).getByText('Published')).toBeVisible();
    await shoot(page, 'policies');
  });

  test('33: the CAICO assigns a module to HR; an employee completes it on a phone', async ({ page }) => {
    await clientUser(page, MARIA);
    await page.goto('/training');
    await expect(page.getByRole('heading', { level: 1, name: 'AI literacy training' })).toBeVisible();
    await page.getByRole('button', { name: 'Assign modules' }).click();
    const dlg = page.getByRole('dialog', { name: 'Assign modules' });
    await dlg.getByLabel('Shadow AI and data leakage (10 min)', { exact: true }).check();
    await dlg.getByLabel('HR', { exact: true }).check();
    await dlg.getByRole('button', { name: 'Preview' }).click();
    await expect(dlg.getByText(/people? in HR/)).toBeVisible();
    await dlg.getByRole('button', { name: 'Assign and email links' }).click();
    await expect(page.getByText(/Assigned to \d+ (person|people)/)).toBeVisible({ timeout: 30_000 });
    await shoot(page, 'training');
    await clientUser(page, TOM);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/my-training');
    await page.getByRole('link', { name: 'Start' }).click();
    await expect(page.getByRole('heading', { name: 'Shadow AI and data leakage' })).toBeVisible();
    for (let i = 0; i < 5; i++) await page.getByRole('button', { name: 'Next' }).click();
    const answers = ['No. Use the approved tool with my company account', 'An unapproved browser extension that summarises the pages you visit',
      'Declare it, so it can be reviewed or replaced', "The company's contract controls how data is kept and stops it being used for training"];
    for (const [i, a] of answers.entries()) {
      await page.getByText(a, { exact: true }).click();
      await page.getByRole('button', { name: 'Check my answer' }).click();
      await expect(page.getByText('Correct.')).toBeVisible();
      if (i === 0) { await noSidewaysScroll(page, 'player at 375px'); await page.screenshot({ path: `${SHOTS}/employee-training-375.png`, fullPage: true }); }
      if (i < answers.length - 1) await page.getByRole('button', { name: 'Next' }).click();
    }
    await page.getByRole('button', { name: 'Finish' }).click();
    await expect(page.getByText('Completed with 100%. Thank you.')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('link', { name: 'Download your certificate' })).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  test('32: the CAICO sets up the Trust Center; Futran confirms only against a signed report; the public page shows only confirmed items', async ({ page }) => {
    await clientUser(page, MARIA);
    await page.goto('/trust');
    await page.getByRole('button', { name: /^(Set up the page|Page settings)$/ }).click();  // another spec on this server may have set it up
    const pd = page.getByRole('dialog', { name: 'Page settings' });
    await pd.getByLabel('Address', { exact: true }).fill('abc-corp');
    await pd.getByLabel('The page is live', { exact: true }).check();
    await pd.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Page settings saved.')).toBeVisible();
    await page.getByRole('button', { name: 'Add item' }).click();
    const it = page.getByRole('dialog', { name: 'Add item' });
    await it.getByLabel('What the item shows', { exact: true }).selectOption('governance');
    await it.getByLabel('Heading', { exact: true }).fill('Governance');
    await it.getByLabel('Text', { exact: true }).fill('An AI governance committee chaired by our Chief AI Compliance Officer approves every high-risk use of AI.');
    await it.getByRole('button', { name: 'Save draft' }).click();
    await expect(page.getByText('Item added as a draft.')).toBeVisible();
    const row = page.getByRole('table', { name: 'Trust Center items' }).getByRole('row', { name: /Governance/ });
    await rowMenu(page, row, 'Approve and send to Futran');
    await expect(page.getByText("'Governance' sent to Futran to confirm against the signed report.")).toBeVisible({ timeout: 30_000 });
    await shoot(page, 'trust-editor');
    await staffUser(page, 'chief@futran.demo');
    await page.goto('/trust-confirmations');
    const q = page.getByRole('table', { name: 'Items to confirm' });
    const govRow = q.getByRole('row', { name: /Governance/ });
    await expect(govRow).toBeVisible();
    // at stage 6 there is no signed report; when the whole suite runs, the journey spec has issued the final report
    const signed = (await govRow.getByText('No signed report').count()) === 0;
    await shoot(page, 'trust-confirmations');
    if (signed) {
      await rowMenu(page, govRow, 'Review and confirm');
      const cd = page.getByRole('dialog', { name: 'Confirm against the signed report' });
      await cd.getByLabel('Where the report supports it', { exact: true }).fill('Section 4.1 of the signed report.');
      await cd.getByRole('button', { name: 'Confirm and publish' }).click();
      await expect(page.getByText("Confirmed and published 'Governance'.")).toBeVisible({ timeout: 30_000 });
    }
    await page.goto('/client-policies');
    await expect(page.getByRole('table', { name: 'Client policies' }).getByText('AI acceptable use policy')).toBeVisible();
    await shoot(page, 'client-policies');
    await page.context().clearCookies();
    await page.goto('/trust/abc-corp');
    await expect(page.getByRole('heading', { level: 1, name: 'How ABC Corp governs its use of AI' })).toBeVisible();
    if (signed) await expect(page.getByRole('heading', { level: 2, name: 'Governance' })).toBeVisible();
    else await expect(page.getByText('Nothing has been published yet.')).toBeVisible();
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex');
    await shoot(page, signed ? 'trust-public' : 'trust-public-empty');
  });
});
