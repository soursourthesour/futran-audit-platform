import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Wave 3 WS-H on ABC Corp (start-server.sh … late): regulatory change alerts with a second reviewer, impact for the client
   and the alert through A1 (screen 26), the client's "What this means for you", a new AI project from intake to a
   conditional approval (screen 28) and a reassessment trigger on the register record and the CAICO's home. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`;
const MARCO = `marco.diaz@${ABC}`;
const DANIEL = `daniel.kim@${ABC}`;
const SHOTS = process.env.WSH_SHOTS || '/mnt/user-data/outputs/wave3/ws-h';
mkdirSync(SHOTS, { recursive: true });
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string };

async function signIn(page: Page, portal: '/staff/login' | '/login', email: string) {
  await page.context().clearCookies();
  await page.goto(portal);
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT' | 'PATCH', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
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

async function smallTargets(page: Page, scope: string) {
  await page.setViewportSize({ width: 375, height: 812 });
  const small = await page.evaluate((sel) => {
    const out: string[] = [];
    document.querySelectorAll(`${sel} button, ${sel} input[type=radio], ${sel} input[type=checkbox], ${sel} select, ${sel} a.btn`).forEach((el) => {
      const r = (el.closest('label') ?? el).getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.height < 43.5) out.push(`${el.tagName} ${el.textContent?.trim().slice(0, 30) || (el as HTMLInputElement).name} ${Math.round(r.height)}`);
    });
    return out;
  }, scope);
  await page.setViewportSize({ width: 1280, height: 900 });
  return small;
}

test('screen 26: a Legal Reviewer drafts, a second reviewer publishes, impact for ABC and the alert waits in A1', async ({ page }) => {
  test.setTimeout(180_000);
  const abc = late().abc;
  await signIn(page, '/staff/login', 'legal@futran.demo');
  await page.goto('/reg/updates');
  await expect(page.getByRole('heading', { name: 'Regulatory change alerts' })).toBeVisible();
  await page.getByRole('button', { name: 'Add update' }).click();
  const dlg = page.getByRole('dialog', { name: 'Add update' });
  await dlg.getByLabel('Type of change *', { exact: true }).selectOption('enforcement_action');
  await dlg.getByLabel('Jurisdiction *', { exact: true }).selectOption({ label: 'New York City' });
  await dlg.getByLabel('Law, bill or rule as shown', { exact: true }).fill('NYC Local Law 144');
  await dlg.getByLabel('Headline *', { exact: true }).fill('State Comptroller audit finds DCWP enforcement of the AI hiring law weak');
  await dlg.getByLabel('Summary *', { exact: true }).fill('Report 2024-N-6 (2 December 2025): DCWP surveyed 32 companies and found one issue of non-compliance; the auditors found at least 17 potential instances.');
  await dlg.getByLabel('What clients should do', { exact: true }).fill('Confirm the bias audit is less than 12 months old\nCheck the published summary and the candidate notice');
  await dlg.getByLabel('Source link *', { exact: true }).fill('https://www.osc.ny.gov/state-agencies/audits/2025/12/02/enforcement-local-law-144-automated-employment-decision-tools');
  // no AI feature ticked: every client operating in New York City is matched (ABC Corp has no register systems at this stage)
  await dlg.getByRole('button', { name: 'Save and send for review' }).click();
  await expect(page.getByText(/waits for a second reviewer/)).toBeVisible();
  // the author cannot publish their own update
  const row = page.getByRole('row', { name: /State Comptroller audit/ });
  await row.getByRole('button', { name: /Actions for State Comptroller audit/ }).click();
  await expect(page.getByRole('menuitem', { name: 'Review' })).toHaveCount(0);
  await page.keyboard.press('Escape');

  await signIn(page, '/staff/login', 'chief@futran.demo');
  await page.goto('/reg/updates?tab=awaiting_review');
  await page.getByRole('row', { name: /State Comptroller audit/ }).getByRole('button', { name: /Actions for/ }).click();
  await page.getByRole('menuitem', { name: 'Review' }).click();
  await page.getByRole('dialog', { name: /Review RU-/ }).getByRole('button', { name: 'Publish' }).click();
  await expect(page.getByText(/published and matched to clients/)).toBeVisible();
  await page.goto('/reg/updates');
  const impact = page.getByRole('region', { name: 'Impact for a client' });
  await expect(impact.getByText('ABC Corp')).toBeVisible();
  await impact.getByRole('button', { name: 'Send alert to client' }).click();
  await expect(page.getByText(/waits for the Chief Auditor's approval in Client alerts/)).toBeVisible();
  await expect(impact.getByText('Alert waiting for approval')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Upcoming dates for your clients' })).toBeVisible();
  await shoot(page, '26-reg-updates');
  const sends = await api(page, 'GET', '/alerts/queue');
  expect(JSON.stringify(sends)).toContain('State Comptroller audit');
  // the client sees it as "What this means for you"
  await signIn(page, '/login', MARIA);
  await page.goto('/updates');
  await expect(page.getByRole('heading', { name: 'What this means for you' })).toBeVisible();
  await expect(page.getByText(/State Comptroller audit finds DCWP/)).toBeVisible();
  await expect(page.getByText('Confirm the bias audit is less than 12 months old')).toBeVisible();
  await shoot(page, '26-client-updates');
  expect(abc).toBeTruthy();
});

test('screen 28: intake with a live tier, reviews, a conditional approval and the register system it becomes', async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, '/login', MARCO);
  await page.goto('/projects/new');
  await expect(page.getByRole('heading', { name: 'New AI project: assess before go-live' })).toBeVisible();
  await page.getByLabel('Project name *', { exact: true }).fill('Website sales assistant');
  await page.getByLabel('Tool or vendor *', { exact: true }).fill('Intercom Fin AI agent');
  await page.getByLabel('Type of AI *', { exact: true }).selectOption('genai_chat_tool');
  await page.getByLabel('Purpose *', { exact: true }).fill('Answers questions about products and pricing on the website; a person takes over on request.');
  for (const place of ['New York', 'Illinois', 'California']) {
    await page.getByLabel('Find a place', { exact: true }).fill(place);
    await page.getByRole('button', { name: `Add ${place}`, exact: true }).click();
  }
  await page.getByLabel('Personal information', { exact: true }).check();
  await page.getByLabel('Customers', { exact: true }).check();
  await page.getByLabel('Informs people; a person can always take over', { exact: true }).check();
  await page.getByLabel('Yes, users chat with it', { exact: true }).check();
  const tier = page.getByRole('region', { name: 'Proposed tier' });
  await expect(tier).toContainText('Tier 2 · Elevated');
  await expect(tier).toContainText('8.1.05');
  await expect(page.getByText('CCPA/CPRA')).toBeVisible();
  expect(await smallTargets(page, 'main')).toEqual([]);
  await shoot(page, '28-new-project');
  await page.getByRole('button', { name: 'Submit for review' }).click();
  await expect(page.getByText('Submitted for review.')).toBeVisible();
  const pid = page.url().split('/').pop()!;
  await page.getByRole('button', { name: 'Record my review' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Record review' }).click();
  await expect(page.getByText('Review recorded.')).toBeVisible();
  await signIn(page, '/login', DANIEL);
  await api(page, 'POST', `/projects/${pid}/reviews`, { step: 'dpo', recommendation: 'approve_with_conditions', comment: 'A notice at the start of each chat is needed.' });
  await signIn(page, '/login', MARIA);
  await page.goto(`/projects/${pid}`);
  await page.getByRole('button', { name: 'Decide' }).click();
  const dlg = page.getByRole('dialog', { name: /Decide/ });
  await dlg.getByLabel('Approve with conditions', { exact: true }).check();
  await dlg.getByLabel('Condition 1', { exact: true }).fill('Show a notice at the start of every chat that the visitor is talking to an AI system');
  await dlg.getByLabel('Owner', { exact: true }).selectOption({ label: 'Marco Diaz' });
  await dlg.getByRole('button', { name: 'Record decision' }).click();
  await expect(page.getByText('Project approved and added to the AI system register.')).toBeVisible();
  await expect(page.getByText(/In the register as AIS-/)).toBeVisible();
  await shoot(page, '28-project-decided');
  await page.goto('/projects');
  await expect(page.getByRole('row', { name: /Website sales assistant/ })).toContainText('Approved with conditions');
  await shoot(page, '28-projects');
  // a register edit raises a reassessment trigger, shown on the record and the CAICO's home
  const p = await api(page, 'GET', `/projects/${pid}`);
  await api(page, 'PATCH', `/register/${p.register_system.id}`, { data: { data_categories: ['personal', 'health'] }, reason: 'Pilot extended to warranty claims' });
  await page.goto(`/register/${p.register_system.id}`);
  await expect(page.getByText('New type of data')).toBeVisible();
  await shoot(page, '28-register-trigger');
  await page.goto('/start');
  await expect(page.getByText(/Reassessment needed/)).toBeVisible();
  await page.getByRole('button', { name: 'Mark reassessed' }).first().click();
  await page.getByRole('dialog').getByLabel('What was reassessed *', { exact: true }).fill('DPIA updated for warranty claim data; DPO approved.');
  await page.getByRole('dialog').getByRole('button', { name: 'Mark reassessed' }).click();
  await expect(page.getByText('Marked reassessed and added to the history log.')).toBeVisible();
});
