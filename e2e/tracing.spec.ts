import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* v0.6 WS-E: the tracing add-on on ABC Corp (start-server.sh … late). R8 unlock: locked tab → request → the
   Executive Sponsor approves → unlocked. R7: import of an agent's actions, an incident with its regulator deadlines,
   the link to the history log, and the phone width. The GuardRail feed runs on its in-process fake. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`; // Chief AI Compliance Officer
const ROBERT = `robert.chen@${ABC}`; // Executive Sponsor
const SHOTS = process.env.WSE_SHOTS || '/mnt/user-data/outputs/v061/ws-e';
mkdirSync(SHOTS, { recursive: true });

const CSV = `time,session,action,tool,data touched,decision,policy,approver or note,agent,event id
${iso(-50)},S-88213,Search product knowledge base,kb.search,Public product docs,allowed,Chatbot-Sales-v2,,refund-chatbot,e2e-1
${iso(-48)},S-88213,Quote refund policy,kb.answer,Policy page v7,allowed,Chatbot-Sales-v2,,refund-chatbot,e2e-2
${iso(-40)},S-88214,Create lead in CRM,crm.create_lead,"Name, email",allowed,Chatbot-Sales-v2,,refund-chatbot,e2e-3
${iso(-30)},S-88215,Offer a discount,pricing.apply,Price list,blocked,Chatbot-Sales-v2,GuardRail: not delegated,refund-chatbot,e2e-4
${iso(-20)},S-88216,Customer asked for a person,handoff.human,Chat transcript,escalated,Chatbot-Sales-v2,Sales desk,refund-chatbot,e2e-5
`;

function iso(minutes: number) {
  return new Date(Date.now() + minutes * 60_000).toISOString().slice(0, 19);
}

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Set-up steps go straight to the API, as the signed-in user (the browser's session and CSRF token). */
async function api(page: Page, method: 'GET' | 'POST', path: string, data?: unknown) {
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
    await page.waitForTimeout(250);
    await noSidewaysScroll(page, `${name} at ${w}px`);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

async function newAgent(page: Page, name: string, withEu: boolean) {
  const reg = await api(page, 'GET', '/register');
  const sales = reg.departments.find((d: { name: string }) => d.name.startsWith('Sales'));
  const s = await api(page, 'POST', '/register', {
    name, type: 'agent', sourcing: 'vendor', stage: 'in_development', department_id: sales.id, autonomy: 'acts_with_approval', guardrail_policy_ref: 'Chatbot-Sales-v2',
    purpose: 'Answers customer questions about orders and refunds on the website, and hands over to the sales desk.',
  });
  if (withEu) {
    const groups = await api(page, 'GET', `/laws?q=${encodeURIComponent('AI Act')}`);
    const eu = groups.flatMap((g: { laws: { id: string; short_name: string }[] }) => g.laws).find((l: { short_name: string }) => l.short_name.includes('2024/1689'));
    expect(eu, 'EU AI Act in the law library').toBeTruthy();
    await api(page, 'POST', `/register/${s.id}/laws`, { regulation_id: eu.id });
  }
  return s.id as string;
}

test('tracing add-on: locked, requested, approved by the sponsor, then traces and an incident with deadlines', async ({ page }) => {
  test.setTimeout(240_000);
  await clientUser(page, MARIA);
  const id = await newAgent(page, 'Website refund chatbot', true);

  // R7 locked: recommended, with a working unlock button
  await page.goto(`/register/${id}/tracing`);
  const card = page.getByRole('region', { name: 'Tracing and incident module' });
  await expect(card.getByText('Add-on · locked')).toBeVisible();
  await expect(card.getByText('Recommended for this system')).toBeVisible();
  await expect(card.getByText(/an AI agent that takes actions/)).toBeVisible();
  await shoot(page, 'r7-locked');

  // R8: the dialog ticks this system; the sponsor is the only approver; trial by default
  await card.getByRole('button', { name: 'Unlock for this system' }).click();
  const dlg = page.getByRole('dialog', { name: 'Unlock the tracing and incident module' });
  await expect(dlg.getByRole('checkbox', { name: 'Trace Website refund chatbot' })).toBeChecked();
  await expect(dlg.getByLabel('Approver *', { exact: true })).toHaveValue(/.+/);
  await expect(dlg.getByRole('radio', { name: /30-day free trial, then paid/ })).toBeChecked();
  await dlg.getByLabel('Note to Futran (optional)', { exact: true }).fill('Need incident deadlines for the EU AI Act before the chatbot goes live.');
  await shoot(page, 'r8-unlock-dialog');
  await dlg.getByRole('button', { name: 'Send for approval' }).click();
  await expect(page.getByText(/Sent to Robert Chen for approval/)).toBeVisible();
  await expect(card.getByText('Waiting for approval').first()).toBeVisible();
  await shoot(page, 'r7-requested');

  // the Executive Sponsor approves on Add-ons
  await clientUser(page, ROBERT);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Add-ons' }).click();
  const waiting = page.getByRole('region', { name: 'Waiting for your approval' });
  await expect(waiting.getByText(/Website refund chatbot/)).toBeVisible();
  await shoot(page, 'r8-sponsor-approval');
  await waiting.getByRole('button', { name: 'Approve' }).first().click();
  await page.getByRole('dialog', { name: 'Approve the tracing module' }).getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText(/Approved\. Tracing is now open on/)).toBeVisible();
  await expect(page.getByRole('table', { name: 'Add-on requests' }).getByText('Active').first()).toBeVisible();

  // R7 unlocked: import an agent's actions
  await clientUser(page, MARIA);
  await page.goto(`/register/${id}/tracing`);
  await expect(page.getByText('Tracing module · active')).toBeVisible();
  await page.getByLabel('Import actions (CSV or JSON)', { exact: true }).setInputFiles({ name: 'chatbot-actions.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
  await expect(page.getByText('5 actions imported from chatbot-actions.csv.')).toBeVisible();
  const traces = page.getByRole('table', { name: 'Action trace' });
  const blocked = traces.getByRole('row').filter({ hasText: 'Offer a discount' });
  await expect(blocked.getByText('Blocked')).toBeVisible();
  const kpis = page.getByRole('list', { name: 'Tracing summary' });
  await expect(kpis.getByRole('listitem').filter({ hasText: 'Actions in last 24 hours' })).toContainText('5');
  // the same file again adds nothing
  await page.getByLabel('Import actions (CSV or JSON)', { exact: true }).setInputFiles({ name: 'chatbot-actions.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
  await expect(page.getByText(/0 actions imported from chatbot-actions\.csv; 5 already held were skipped/)).toBeVisible();
  // GuardRail sync through the in-process fake
  await page.getByRole('button', { name: 'Sync from GuardRail' }).click();
  await expect(page.getByText(/GuardRail: \d+ new actions?/)).toBeVisible();
  // right-click opens the row menu; the full trace shows the whole session
  await blocked.getByText('Offer a discount').click({ button: 'right' });
  const menu = page.getByRole('menu', { name: /Actions for Offer a discount/ });
  for (const item of ['Open full trace', 'Raise an incident', 'Export']) await expect(menu.getByRole('menuitem', { name: item })).toBeVisible();
  await menu.getByRole('menuitem', { name: 'Raise an incident' }).click();

  // an incident raised from the blocked action, classed as a serious incident under the EU AI Act
  const panel = page.getByRole('complementary', { name: 'Report an incident' });
  await expect(panel.getByText('Raised from 1 traced action')).toBeVisible();
  await panel.getByLabel('What happened *', { exact: true }).fill('Chatbot quoted a 60-day refund window to 23 customers; the policy is 30 days.');
  await panel.getByLabel('Serious incident under the EU AI Act?', { exact: true }).selectOption({ label: 'Yes: breach of EU law protecting fundamental rights (15 days)' });
  await panel.getByLabel('People affected', { exact: true }).fill('23');
  await panel.getByLabel('Containment', { exact: true }).fill('Old policy page removed from the knowledge base; affected customers to be contacted.');
  await panel.getByRole('button', { name: 'Record incident' }).click();
  await expect(page.getByText(/INC-\d{3} recorded and added to the history log\. 2 notices to make/)).toBeVisible();
  const open = page.getByRole('complementary', { name: /INC-\d{3}/ });
  const notices = open.getByRole('region', { name: 'Who must be told' });
  const provider = notices.getByRole('listitem').filter({ hasText: 'AI provider' });
  const msa = notices.getByRole('listitem').filter({ hasText: 'Market surveillance authority' });
  await expect(provider.getByText(/h \d+ min left|\d+ min left/)).toBeVisible();
  await expect(msa.getByText(/1[45] d \d+ h left/)).toBeVisible();
  await expect(msa.getByText('EU AI Act Art. 73(2), with Art. 26(5) · 15 days from becoming aware', { exact: false })).toBeVisible();
  await expect(msa.getByText(/Not yet binding: EU AI Act high-risk duties apply from 2 Dec 2027/)).toBeVisible();
  const incidents = page.getByRole('table', { name: 'Incidents' });
  await expect(incidents.getByRole('row').filter({ hasText: 'Chatbot quoted a 60-day refund window' }).getByText(/left/)).toBeVisible();
  await shoot(page, 'r7-active-incident');

  // record the provider notice
  await provider.getByRole('button', { name: 'Record as made' }).click();
  const nd = page.getByRole('dialog', { name: 'Record the notice to AI provider' });
  await nd.getByLabel('Reference', { exact: true }).fill('Vendor ticket 4411');
  await nd.getByRole('button', { name: 'Record notice' }).click();
  await expect(page.getByText('Notice to AI provider recorded.')).toBeVisible();
  await expect(provider.getByText(/ref\. Vendor ticket 4411/)).toBeVisible();

  // the incident is in the history log, linked both ways
  await open.getByRole('link', { name: 'Open the history log entry' }).click();
  await expect(page).toHaveURL(new RegExp(`/register/${id}/history`));
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'What happened *' })).toHaveValue(/Chatbot quoted a 60-day refund window/);

  // the Chief Auditor sees the unlock request as an opportunity
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email').fill('chief@futran.demo');
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto('/opportunities');
  await expect(page.getByText(/Tracing add-on: Per system/).first()).toBeVisible();
});

test('tracing at phone width: locked tab, unlock dialog and Add-ons fit 375 px with 44 px targets', async ({ page }) => {
  await clientUser(page, MARIA);
  const id = await newAgent(page, 'Invoice reminder agent', false);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/register/${id}/tracing`);
  const unlock = page.getByRole('button', { name: 'Unlock for this system' });
  await expect(unlock).toBeVisible();
  await noSidewaysScroll(page, 'locked tab');
  expect((await unlock.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await unlock.click();
  const dlg = page.getByRole('dialog', { name: 'Unlock the tracing and incident module' });
  await expect(dlg.getByRole('checkbox', { name: 'Trace Invoice reminder agent' })).toBeChecked();
  await noSidewaysScroll(page, 'unlock dialog');
  for (const name of ['Send for approval', 'Cancel']) expect((await dlg.getByRole('button', { name }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await dlg.getByRole('button', { name: 'Cancel' }).click();
  await page.goto('/addons');
  await expect(page.getByRole('heading', { name: 'Add-ons' })).toBeVisible();
  await noSidewaysScroll(page, 'Add-ons');
});
