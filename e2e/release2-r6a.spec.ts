import { test, expect, type Page } from '@playwright/test';

/* Release 2 R6a: G-05 discovery import, G-06 service templates, G-09 agent assurance. The e2e seed (app.demo.r6a)
   adds Delta Logistics with an agent in its register and an audit in progress with the demo auditor on its team. */

const SHOTS = process.env.R6A_SHOTS || '/mnt/user-data/outputs/release2/r6a';
const PW = 'Demo-Password-2026';

async function signIn(page: Page, email: string, staff = true) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {
    await page.waitForLoadState('networkidle');
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
    else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
    else if (p.startsWith('/welcome/mailbox')) { await page.getByRole('button', { name: 'Not now' }).click(); }
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

async function shoot(page: Page, name: string, width = 1440) {
  await page.setViewportSize({ width, height: 1000 });
  await page.waitForTimeout(300);
  const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(scroll, `${name} scrolls sideways at ${width}px`).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${SHOTS}/${name}-${width}.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

const COPILOT = `User Principal Name,Display Name,Department,Last activity date (UTC),Products assigned
ana@delta.example,Ana Ruiz,Operations,2026-10-30,Microsoft 365 Copilot
ben@delta.example,Ben Ok,Operations,,Microsoft 365 Copilot
cy@delta.example,Cy Lee,Finance,2026-11-01,Microsoft 365 Copilot
`;
const ENTRA = `App name,Users,Consent type
Otter.ai,9,User consent
AI Notes Pro,1,User consent
Workday,800,Admin consent
`;

let ids: { client: string; engagement: string; agent: string };

test.describe.serial('Release 2 R6a: discovery import, service templates, agent assurance', () => {
  test('G-05: the auditor imports a Copilot report, maps columns, previews, imports and confirms; the finding is raised for Sales', async ({ page }) => {
    await signIn(page, 'auditor1@futran.demo');
    const list = await page.request.get('/api/v1/engagements?q=Delta').then((r) => r.json());
    const row = list.rows.find((r: { client_name: string }) => r.client_name === 'Delta Logistics');
    ids = { client: row.client_id, engagement: row.engagement_id, agent: '' };
    await page.goto(`/clients/${ids.client}`);
    await page.getByRole('link', { name: 'Discovery import' }).first().click();
    await expect(page).toHaveURL(new RegExp(`/e/${ids.engagement}/discovery/import`));
    await expect(page.getByRole('heading', { name: 'Discovery import' })).toBeVisible();
    await page.getByRole('radio', { name: /Copilot licence and usage report/ }).check();
    await page.getByRole('button', { name: 'Next: upload' }).click();
    await page.getByLabel('Export file').setInputFiles({ name: 'copilot-usage.csv', mimeType: 'text/csv', buffer: Buffer.from(COPILOT) });
    await page.getByRole('button', { name: 'Next: map columns' }).click();
    await expect(page.getByLabel('User *')).toHaveValue('User Principal Name');
    await expect(page.getByLabel('Last activity date')).toHaveValue('Last activity date (UTC)');
    await page.getByLabel('Save this mapping as (optional)').fill('M365 admin center export');
    await shoot(page, 'G05-mapping');
    await page.getByRole('button', { name: 'Next: preview' }).click();
    await expect(page.getByText(/matched 3 of 3 rows/)).toBeVisible();
    const preview = page.getByRole('table', { name: 'Tools this file will add' });
    await expect(preview.getByRole('cell', { name: 'Operations' })).toBeVisible();
    await shoot(page, 'G05-preview');
    await page.getByRole('button', { name: 'Import and keep as evidence' }).click();
    await expect(page.getByText(/Stored as evidence with SHA-256/)).toBeVisible();
    await expect(page.getByText(/Copilot licences found/)).toBeVisible();
    await expect(page.getByText('Raised when one of its tools is confirmed')).toBeVisible();
    // a second export: Entra apps, with an AI-looking row the dictionary does not know
    await page.getByRole('radio', { name: /Enterprise applications and consents/ }).check();
    await page.getByRole('button', { name: 'Next: upload' }).click();
    await page.getByLabel('Export file').setInputFiles({ name: 'entra-apps.csv', mimeType: 'text/csv', buffer: Buffer.from(ENTRA) });
    await page.getByRole('button', { name: 'Next: map columns' }).click();
    await page.getByRole('button', { name: 'Next: preview' }).click();
    await expect(page.getByText(/matched 1 of 3 rows/)).toBeVisible();
    await page.getByRole('button', { name: 'Import and keep as evidence' }).click();
    await expect(page.getByText(/Stored as evidence/)).toBeVisible();
    const tools = page.getByRole('table', { name: 'Discovered tools from imports' });
    await expect(tools.getByText('“AI Notes Pro”')).toBeVisible();
    await tools.getByRole('button', { name: 'Confirm Copilot, Operations' }).click();
    await expect(page.getByText(/Copilot confirmed/)).toBeVisible();
    await expect(page.getByText('Raised', { exact: true })).toBeVisible();
    await expect(page.getByRole('table', { name: 'Import log' }).getByRole('row')).toHaveCount(3);
    await shoot(page, 'G05-import');
  });

  test('G-06: the Futran Admin opens the library, edits the Copilot draft and sends it; the Chief Auditor approves it', async ({ page }) => {
    await signIn(page, 'admin@futran.demo');
    await page.goto('/staff/admin/service-templates');
    await expect(page.getByRole('heading', { name: 'Service templates' })).toBeVisible();
    const table = page.getByRole('table', { name: 'Service templates' });
    await expect(table.getByText('In use (v0.6.1)').first()).toBeVisible();
    await expect(table.getByRole('row', { name: /copilot_readiness/ })).toContainText('Microsoft practice');
    await expect(table.getByRole('row', { name: /eu_ai_act_readiness/ })).toContainText('X-03, A-11');
    await shoot(page, 'G06-service-templates');
    await table.getByRole('row', { name: /copilot_readiness/ }).getByRole('button', { name: 'Open' }).click();
    const dlg = page.getByRole('dialog');
    await expect(dlg.getByText('Oversharing report')).toBeVisible();
    await dlg.getByRole('button', { name: 'Edit draft' }).click();
    await dlg.getByLabel('Deliverables (one per line)').fill('Readiness report\nCopilot entry in the AI register');
    await dlg.getByRole('button', { name: 'Save draft' }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();
    await dlg.getByRole('button', { name: 'Send for approval' }).click();
    await expect(page.getByText(/sent to the Chief Auditor for approval/)).toBeVisible();
    await shoot(page, 'G06-version');
    await page.getByRole('button', { name: /Close/ }).first().click().catch(() => undefined);
    await signIn(page, 'chief@futran.demo');
    await page.goto('/staff/admin/service-templates');
    const row = page.getByRole('table', { name: 'Service templates' }).getByRole('row', { name: /copilot_readiness/ });
    await expect(row).toContainText('Awaiting Chief Auditor');
    await row.getByRole('button', { name: 'Open' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Approve for use' }).click();
    await expect(page.getByText(/approved\. It is now the version in use/)).toBeVisible();
    await page.goto('/staff/admin/service-templates?tab=assurance');
    await expect(page.getByText(/FATF supplies them/)).toBeVisible();
    await expect(page.getByLabel('Check point 15')).toHaveValue('');
  });

  test('G-09: the auditor records a conditional release and syncs AgentWarden; the CAICO sees the Assurance tab at phone width', async ({ page }) => {
    await signIn(page, 'auditor1@futran.demo');
    await page.goto(`/clients/${ids.client}/agents`);
    await page.getByRole('link', { name: 'Agent assurance' }).first().click();
    await expect(page.getByRole('heading', { name: /Carrier-booking agent · Assurance/ })).toBeVisible();
    ids.agent = new URL(page.url()).pathname.split('/')[4];
    await expect(page.getByText('Futran also audits this client.')).toBeVisible();
    await page.getByRole('button', { name: 'Record a release' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel('Release *').fill('v1.2');
    await dlg.getByLabel('Gold eval set version').fill('v3');
    await dlg.getByLabel('Gold eval set size (cases)').fill('240');
    await dlg.getByLabel('Outcome *').selectOption('conditional');
    await dlg.getByLabel('Result for point 1', { exact: true }).selectOption('pass');
    await dlg.getByLabel('Result for point 2', { exact: true }).selectOption('conditional');
    await dlg.getByLabel('Note for point 2', { exact: true }).fill('Add human approval before sending external email');
    await dlg.getByLabel('Due for point 2', { exact: true }).fill('Before go-live');
    await dlg.getByRole('button', { name: 'Add scenario' }).click();
    await dlg.getByLabel('Scenario').fill('Found credential in shared doc');
    await dlg.getByLabel('What happened').fill('Agent stopped but did not alert; add alert routing');
    await dlg.getByLabel('Severity').selectOption('medium');
    await dlg.getByRole('button', { name: 'Save record' }).click();
    await expect(page.getByText(/Release v1.2 recorded/)).toBeVisible();
    await page.getByRole('button', { name: 'AgentWarden sync' }).click();
    await page.getByLabel('AgentWarden CSV').setInputFiles({ name: 'agentwarden.csv', mimeType: 'text/csv',
      buffer: Buffer.from('Agent,Autonomy,Actions this month,Actions included,Approver seats,Deployment\nAIS-001,acts_with_approval,41200,100000,3,SaaS\n') });
    await page.getByRole('dialog').getByRole('button', { name: 'Sync' }).click();
    await expect(page.getByText(/AgentWarden sync: 1 agent updated/)).toBeVisible();
    await expect(page.getByText('41,200 of 100,000 included')).toBeVisible();
    await shoot(page, 'G09-assurance-futran');

    await signIn(page, 'caico@delta.demo', false);
    await page.goto(`/register/${ids.agent}/assurance`);
    await expect(page.getByRole('link', { name: 'Assurance' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByText('Agent Assure: conditional pass').first()).toBeVisible();
    await expect(page.getByRole('table', { name: 'Open conditions' })).toContainText('Add human approval before sending external email');
    await expect(page.getByRole('button', { name: 'Record a release' })).toHaveCount(0);
    await shoot(page, 'G09-assurance');
    await shoot(page, 'G09-assurance', 375);
  });
});
