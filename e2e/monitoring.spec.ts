import { test, expect, type Page } from '@playwright/test';

/* v0.6 WS-D: refresh and review (M3) with a second reviewer, refresh alerts (M6), litigation (L1, L2),
   the Sales Team and opportunities (S1), and automatic client alerts (A1). The server runs with REFRESH_CLIENT=fake,
   so a refresh proposes labelled test changes and never calls the network. */

const SHOTS = process.env.WSD_SHOTS || '/mnt/user-data/outputs/v061/ws-d';

async function signIn(page: Page, email: string, home = /\/audits$/) {
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(home);
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/login/);
}

/** Open a DataGrid row menu. The menu closes on scroll, so bring the button into view first. */
async function rowMenu(page: Page, row: ReturnType<Page['getByRole']>, item: string) {
  const btn = row.getByRole('button', { name: /Actions for/ });
  await btn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await btn.click();
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

async function shoot(page: Page, name: string) {
  for (const [w, h] of [[1440, 1000], [375, 812]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(200);
    const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(scroll, `${name} at ${w}px scrolls sideways`).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

test.describe.serial('refresh, alerts, litigation, sales and client alerts', () => {
  test('M3: a refresh proposes changes; a low-confidence change needs a second reviewer before approval', async ({ page }) => {
    await signIn(page, 'chief@futran.demo');
    await page.goto('/reg/refresh');
    await expect(page.getByRole('heading', { name: 'Refresh laws and review changes' })).toBeVisible();
    await page.getByLabel('Choose geographies').check();
    await page.getByRole('button', { name: 'Illinois', exact: true }).click();
    await page.getByRole('button', { name: 'Run refresh with Claude' }).click();
    await expect(page.getByText('The refresh has started.')).toBeVisible();
    const grid = page.getByRole('table', { name: 'Changes waiting for review' });
    await expect(grid.getByText('Test client proposal, not research: litigation note', { exact: false })).toBeVisible({ timeout: 30_000 });
    await expect(grid.getByText('Low: needs second review')).toBeVisible();
    await expect(page.getByText('2 waiting for Chief Auditor review')).toBeVisible({ timeout: 20_000 }); // the run has finished
    await page.waitForTimeout(1000);
    await shoot(page, 'm3-refresh-review');

    // The high-confidence change is approved straight away
    await rowMenu(page, grid.getByRole('row', { name: /litigation note/ }), 'Review');
    await expect(page.getByText('What this affects')).toBeVisible();
    await shoot(page, 'm3-change-detail');
    await page.getByRole('button', { name: 'Approve and publish' }).click();
    await expect(page.getByText(/Approved: Test client proposal/)).toBeVisible();

    // The low-confidence one is refused until a second reviewer concurs
    await rowMenu(page, grid.getByRole('row', { name: /effective date wording/ }), 'Review');
    await page.getByRole('button', { name: 'Approve and publish' }).click();
    await expect(page.getByText('This change needs a second reviewer')).toBeVisible();
    const url = page.url();
    await signOut(page);

    await signIn(page, 'qa@futran.demo');
    await page.goto(url.replace(/^https?:\/\/[^/]+/, ''));
    await page.getByRole('textbox', { name: 'Your review' }).fill('The source supports the change for this test.');
    await page.getByRole('button', { name: 'Concur' }).click();
    await expect(page.getByText('Your second review is recorded.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve and publish' })).toHaveCount(0); // QA reviews, never approves
    await signOut(page);

    await signIn(page, 'chief@futran.demo');
    await page.goto(url.replace(/^https?:\/\/[^/]+/, ''));
    await expect(page.getByText(/Quinn Taylor concurs/).first()).toBeVisible();
    await page.getByRole('button', { name: 'Approve and publish' }).click();
    await expect(page.getByText(/Approved: Test client proposal/)).toBeVisible();
    await expect(page.getByText('Nothing is waiting for review.')).toBeVisible();
  });

  test('M6: the refresh alert is under the bell and on the alerts page; settings save', async ({ page }) => {
    await signIn(page, 'chief@futran.demo');
    await page.getByRole('button', { name: /Notifications, \d+ unread/ }).click();
    await expect(page.getByRole('dialog', { name: 'Notifications' }).getByText(/Refresh done: 2 law changes need your review/)).toBeVisible();
    await page.getByRole('button', { name: 'All alerts and settings' }).click();
    await expect(page).toHaveURL(/\/staff\/alerts$/);
    await expect(page.getByText(/Refresh done: 2 law changes need your review/).first()).toBeVisible();
    await page.getByRole('combobox', { name: 'Remind if not reviewed after' }).selectOption('5');
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(page.getByText('Settings saved.')).toBeVisible();
    await shoot(page, 'm6-refresh-alerts');
  });

  test('L1 to L2: from the tracker to a case, its clients with similar AI, and a client briefing', async ({ page }) => {
    await signIn(page, 'chief@futran.demo');
    await page.getByRole('link', { name: 'Litigation', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'AI litigation tracker' })).toBeVisible();
    const grid = page.getByRole('table', { name: 'Cases' });
    await expect(grid.getByRole('link', { name: 'Moffatt v. Air Canada' })).toBeVisible();
    await shoot(page, 'l1-litigation');
    await grid.getByRole('link', { name: 'Mobley v. Workday, Inc.' }).click();
    await expect(page.getByRole('heading', { name: 'Mobley v. Workday, Inc.' })).toBeVisible();
    await expect(page.getByText('Where the case is')).toBeVisible();
    await expect(page.getByRole('table', { name: 'Clients using similar AI' }).getByText('Harbor Point Staffing')).toBeVisible();
    await expect(page.getByRole('link', { name: /Order granting preliminary collective certification/ })).toBeVisible();
    await shoot(page, 'l2-case-record');
    await page.getByRole('button', { name: 'Send client briefing' }).first().click();
    await expect(page.getByText(/1 client briefing waits for the Chief Auditor/)).toBeVisible();
  });

  test('A1: the briefing waits in the approval queue; the Chief Auditor previews and sends it', async ({ page }) => {
    await signIn(page, 'chief@futran.demo');
    await page.getByRole('link', { name: 'Client alerts' }).click();
    await expect(page.getByRole('table', { name: 'Alert rules' }).getByText('Effective date in 90 and 30 days')).toBeVisible();
    const queue = page.getByRole('table', { name: /Waiting: Case briefing: Mobley/ });
    await expect(queue.getByText('Harbor Point Staffing')).toBeVisible();
    await shoot(page, 'a1-client-alerts');
    await rowMenu(page, queue.getByRole('row', { name: /Harbor Point Staffing/ }), 'Preview email');
    await expect(page.frameLocator('iframe[title="Email preview"]').getByText('List every hiring tool that ranks, scores or filters applicants.')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Approve and send' }).click();
    await expect(page.getByText(/1 alert sent/)).toBeVisible();
    await expect(page.getByText('Nothing is waiting.')).toBeVisible();
  });

  test('S1: the Sales Team works opportunities and is refused audit findings', async ({ page }) => {
    await signIn(page, 'sales@futran.demo', /\/opportunities$/);
    await expect(page.getByRole('link', { name: 'Dashboard' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Add opportunity' }).click();
    await page.getByRole('combobox', { name: 'Client' }).selectOption({ label: 'Harbor Point Staffing' });
    await page.getByRole('textbox', { name: 'Service', exact: true }).fill('Bias audit including age, hiring tools');
    await page.getByRole('textbox', { name: 'Why now' }).fill('Mobley v. Workday');
    await page.getByRole('spinbutton', { name: 'Value (US dollars)' }).fill('18000');
    await page.getByRole('button', { name: 'Add opportunity' }).last().click();
    await expect(page.getByText('Opportunity added.')).toBeVisible();
    const grid = page.getByRole('table', { name: 'Opportunities' });
    await grid.getByRole('button', { name: 'Harbor Point Staffing' }).first().click();
    await page.getByRole('textbox', { name: 'Summary' }).fill('Called the Chief AI Compliance Officer; meeting booked.');
    await page.getByRole('button', { name: 'Log it' }).click();
    await expect(page.getByRole('dialog').getByText('Called the Chief AI Compliance Officer; meeting booked.')).toBeVisible();
    await shoot(page, 's1-opportunity-detail');
    await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await shoot(page, 's1-opportunities');
    // Sales sees cases but never findings, evidence, scores or reports
    await page.getByRole('link', { name: 'Litigation', exact: true }).click();
    await expect(page.getByRole('table', { name: 'Cases' })).toBeVisible();
    const clients = await page.request.get('/api/v1/opportunities');
    const clientId = (await clients.json()).clients[0].id;
    for (const path of [`/api/v1/clients/${clientId}/findings`, `/api/v1/clients/${clientId}/report`, `/api/v1/clients/${clientId}/scorecard`]) {
      const r = await page.request.get(path);
      expect([403, 404], path).toContain(r.status());
    }
  });
});
