import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { expectNav, openNav } from './nav';

/* Release 2 R2 sales desk on the fresh server: the Sales Officer lands on the Sales home (SM-01), logs opportunities
   for prospects and an existing client with the duplicate check (SM-03), works the list and the board (SM-02) and an
   opportunity record (SM-04); the old /opportunities address redirects with its filters; the Sales Manager sees the
   team's pipeline and reassigns. Screenshots at 1440 px. */
const PW = 'Demo-Password-2026';
const SHOTS = process.env.R2_SHOTS || '/mnt/user-data/outputs/release2/r2';
mkdirSync(SHOTS, { recursive: true });
test.use({ viewport: { width: 1440, height: 1000 } });
test.describe.configure({ mode: 'serial' });

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

async function api(page: Page, method: 'GET' | 'POST' | 'PATCH', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.ok(), `${method} ${path}: ${await r.text()}`).toBeTruthy();
  return r.json();
}

let acmeId = '';

test('Sales Officer: Sales home, log opportunities with the duplicate check, list and board', async ({ page }) => {
  await signIn(page, 'sales@futran.demo');
  await expect(page).toHaveURL(/\/sales$/);
  await expect(page.getByRole('heading', { name: 'Sales home' })).toBeVisible();
  // the Sales menu: R2's lines beside R1's Estimator and Price list
  await expectNav(page, ['Sales home', 'Opportunities', 'Estimator', 'Price list', 'Proposals', 'Litigation'], ['Dashboard', 'Clients', 'Users']);

  // demo pipeline through the API (prospects and an existing client)
  const harbor = (await api(page, 'GET', '/sales/companies?q=Harbor')).items[0];
  const acme = await api(page, 'POST', '/sales/opportunities', {
    prospect: { name: 'Acme Recruiting Group', website: 'acmerecruiting.example', industry: 'Staffing & recruitment', size_band: '251–1,000', hq_state: 'NJ', hq_country: 'US' },
    contacts: [{ name: 'Jordan Pike', title: 'COO', email: 'jordan.pike@acmerecruiting.example', contact_role: 'champion' }],
    source: 'outbound_call', segment: 'staffing_hr', trigger_event: 'll144_due', products_of_interest: ['ll144', 'monitor'], est_value: 42000,
    next_step: 'Scoping call', next_step_due: new Date().toISOString().slice(0, 10),
  });
  acmeId = acme.id;
  await api(page, 'PATCH', `/opportunities/${acme.id}`, { bant: { budget: '$40–50k this year', authority: 'COO signs', need: 'NYC hiring AI with no bias audit on file', timeline: 'Audit summary posted before 31 January' }, stage: 'qualified' });
  const north = await api(page, 'POST', '/sales/opportunities', {
    prospect: { name: 'Cedar Ridge Credit Union', website: 'cedarridge.example', industry: 'BFSI', size_band: '1,000+', hq_state: 'CO', hq_country: 'US' },
    contacts: [], source: 'referral_partner', segment: 'enterprise_bfsi_health_ins', trigger_event: 'new_state_law', products_of_interest: ['audit', 'eu_ai_act'], est_value: 96000,
    next_step: 'Chase questionnaire', bant: { budget: 'Approved', authority: 'CRO', need: 'Colorado AI Act', timeline: 'Q1' },
  });
  await api(page, 'PATCH', `/opportunities/${north.id}`, { stage: 'qualified' });
  await api(page, 'PATCH', `/opportunities/${north.id}`, { stage: 'negotiation' });
  await api(page, 'POST', '/sales/opportunities', {
    prospect: { name: 'Brightline Freight', website: 'brightline.example', industry: 'Other', hq_state: 'IL', hq_country: 'US' },
    contacts: [], source: 'linkedin', segment: 'agents_copilot', trigger_event: 'agents_rollout', products_of_interest: ['agent_assure', 'agentwarden'], est_value: 58000, next_step: 'Discovery call',
  });
  await api(page, 'POST', '/sales/opportunities', { organization_id: harbor.id, contacts: [], source: 'existing_client', products_of_interest: ['monitor'], est_value: 24000, next_step: 'Confirm AEDT count' });

  await page.reload();
  await expect(page.getByText('Acme Recruiting Group').first()).toBeVisible();
  await expect(page.getByRole('list', { name: 'Pipeline by stage' })).toContainText('Qualified');
  await shot(page, 'sm01-sales-home');
  await page.setViewportSize({ width: 375, height: 812 });
  await noSidewaysScroll(page);
  await page.setViewportSize({ width: 1440, height: 1000 });

  // SM-02 list
  await openNav(page, 'Opportunities');
  await expect(page).toHaveURL(/\/sales\/opportunities/);
  const grid = page.getByRole('table', { name: 'Opportunities' });
  await expect(grid.getByRole('link', { name: 'Acme Recruiting Group' })).toBeVisible();
  await expect(grid.getByText('Prospect').first()).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'sm02-opportunities-list');

  // SM-02 board, moving a card
  await page.getByRole('tab', { name: 'Board' }).click();
  const board = page.getByLabel('Opportunities by stage');
  await expect(board.getByRole('region', { name: 'Negotiation' })).toContainText('Cedar Ridge Credit Union');
  await board.getByLabel('Move Brightline Freight to stage').selectOption('scoping');
  await expect(board.getByRole('region', { name: 'Scoping' })).toContainText('Brightline Freight');
  await shot(page, 'sm02-opportunities-board');

  // SM-03 with the duplicate warning
  await page.getByRole('tab', { name: 'List' }).click();
  await page.getByRole('button', { name: 'Log opportunity' }).click();
  const dlg = page.getByRole('dialog', { name: 'Log opportunity' });
  await dlg.getByRole('textbox', { name: 'Company' }).fill('Acme Recruiting Services');
  await dlg.getByRole('textbox', { name: 'Website' }).fill('www.acmerecruiting.example');
  await expect(dlg.getByTestId('duplicate-warning')).toContainText('Acme Recruiting Group');
  await expect(dlg.getByTestId('duplicate-warning')).toContainText('same domain acmerecruiting.example');
  await expect(dlg.getByRole('button', { name: 'Save and open' })).toBeDisabled();
  await dlg.getByRole('checkbox', { name: 'LL144' }).check();
  await shot(page, 'sm03-log-opportunity-duplicate');
  await dlg.getByRole('checkbox', { name: 'This is a different company' }).check();
  await expect(dlg.getByRole('button', { name: 'Save and open' })).toBeEnabled();
  await dlg.getByRole('button', { name: 'Cancel' }).click();
});

test('Sales Officer: the opportunity record and the old address', async ({ page }) => {
  await signIn(page, 'sales@futran.demo');
  await page.goto(`/opportunities?open=${acmeId}`);
  await expect(page).toHaveURL(new RegExp(`/sales/opportunities/${acmeId}$`));
  await expect(page.getByRole('heading', { name: /Acme Recruiting Group/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Stage' })).toContainText('Qualified');
  await expect(page.getByText('NYC hiring AI with no bias audit on file')).toBeVisible();
  await page.getByRole('button', { name: 'Log call' }).click();
  const d = page.getByRole('dialog');
  await d.getByRole('textbox', { name: 'Summary' }).fill('Spoke with Jordan; the ATS scores NYC roles. Scoping call booked.');
  await d.getByRole('textbox', { name: 'Outcome' }).fill('Interested');
  await d.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Spoke with Jordan; the ATS scores NYC roles.')).toBeVisible();
  await page.getByRole('tab', { name: /Contacts/ }).click();
  await page.getByRole('button', { name: 'Add contact' }).click();
  await page.getByRole('dialog').getByRole('textbox', { name: 'Name' }).fill('Lee Morgan');
  await page.getByRole('dialog').getByRole('combobox', { name: 'Role in deal' }).selectOption('legal');
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('cell', { name: 'Lee Morgan' })).toBeVisible();
  await page.getByRole('tab', { name: 'Overview' }).click();
  await expect(page.getByText('No flag', { exact: true })).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, 'sm04-opportunity-record');
  // the old list address keeps its filters
  await page.goto('/opportunities?stage=qualified');
  await expect(page).toHaveURL(/\/sales\/opportunities\?stage=qualified$/);
});

test('Sales Manager: team pipeline and reassignment', async ({ page }) => {
  await signIn(page, 'salesmanager@futran.demo');
  await expect(page).toHaveURL(/\/sales$/);
  await page.getByRole('tab', { name: 'Team' }).click();
  await expect(page.getByText("The team's pipeline")).toBeVisible();
  await expect(page.getByRole('link', { name: 'Acme Recruiting Group' }).first()).toBeVisible();
  await page.goto(`/sales/opportunities/${acmeId}`);
  await page.getByRole('button', { name: 'Edit' }).click();
  await page.getByRole('dialog').getByRole('combobox', { name: 'Owner' }).selectOption({ label: 'Riya Mehta' });
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Owner Riya Mehta')).toBeVisible();
});
