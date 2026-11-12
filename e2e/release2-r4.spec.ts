import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Release 2 R4: the proposal builder with a version diff (SM-09), approvals (SM-11), preview and send (SM-10) and the
   client's acceptance page on a phone (SM-12). Run on the fresh server:
   E2E_PORT=8945 bash e2e/run.sh -c playwright.r4.config.ts release2-r4.spec.ts */

const PW = 'Demo-Password-2026';
const SHOTS = process.env.R4_SHOTS || '/mnt/user-data/outputs/release2/r4';
mkdirSync(SHOTS, { recursive: true });

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT' | 'PATCH', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

/** The acceptance link in the last proposal email (test mode keeps the outbox readable). */
function lastLink(): string {
  const py = `import sqlite3,re;c=sqlite3.connect('data/e2e.db');t=c.execute("select body_text from outbox_messages where template_key='proposal_send' order by created_at desc limit 1").fetchone()[0];print(re.search(r'/p/[A-Za-z0-9_\\-]+',t).group(0))`;
  return execFileSync('python3', ['-c', py], { cwd: `${__dirname}/../backend` }).toString().trim();
}

async function noSideways(page: Page, what: string) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(wide, `${what} scrolls sideways`).toBeLessThanOrEqual(1);
}

async function approveAll(page: Page, email: string, proposalId: string) {
  await signIn(page, email);
  const q = await api(page, 'GET', '/sales/approvals?tab=mine');
  for (const item of q.items.filter((i: { proposal_id: string }) => i.proposal_id === proposalId)) {
    await api(page, 'POST', `/sales/approvals/${item.id}/decide`, { decision: 'approve', note: 'Fine for a first-year client.' });
  }
}

test('proposal: build, diff, approve, send and accept on a phone', async ({ page, browser }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await signIn(page, 'sales@futran.demo');
  const list = await api(page, 'GET', '/opportunities');
  const opp = await api(page, 'POST', '/opportunities', { organization_id: list.clients[0].id, service: 'LL144 and AI governance', why_now: 'Bias audit due' });

  // v1 from the Governed package, a discount and an edited price; approved and sent
  let p = await api(page, 'POST', '/sales/proposals', { opportunity_id: opp.id, package: 'governed' });
  const v1 = p.id;
  p = await api(page, 'POST', `/sales/proposals/${v1}/lines`, { code: 'L-01', qty: 1 });
  p = await api(page, 'PATCH', `/sales/proposals/${v1}`, { discount_recurring_pct: 5 });
  await api(page, 'POST', `/sales/proposals/${v1}/approvals`);
  await approveAll(page, 'ceo@futran.demo', v1);
  await approveAll(page, 'chief@futran.demo', v1);  // the client is an audit client: I-2 for M-07a
  await signIn(page, 'sales@futran.demo');
  await api(page, 'POST', `/sales/proposals/${v1}/send`, { recipients: [{ name: 'Dana Buyer', email: 'dana@client.example' }] });

  // SM-09: start v2 in the builder, change a price and add a line, see the diff
  await page.goto(`/sales/proposals/${v1}`);
  await expect(page.getByRole('heading', { name: /Proposal v1/ })).toBeVisible();
  await expect(page.getByText('Version 1 is sent and can\'t change.')).toBeVisible();
  await page.getByRole('button', { name: 'Start v2' }).click();
  await expect(page.getByRole('heading', { name: /Proposal v2/ })).toBeVisible();
  const a05 = page.getByLabel('Edited price for A-05');
  await a05.fill('1200');
  await a05.blur();
  await expect(page.getByRole('row', { name: /A-05/ }).getByText('Edited', { exact: true })).toBeVisible();
  await page.getByLabel('Add line by code or name').fill('AA-02');
  await page.getByRole('button', { name: 'Add line' }).click();
  await expect(page.getByText('AA-02 added.')).toBeVisible();
  await page.getByRole('button', { name: 'Changes since v1' }).click();
  const diff = page.getByRole('region', { name: 'Changes from v1 to v2' });
  await expect(diff.getByText(/unit price: \$1,500 → \$1,200/)).toBeVisible();
  await expect(diff.getByText('AA-02')).toBeVisible();
  await expect(page.getByText(/P-1 · Pricing Approver needed\./)).toBeVisible();
  await noSideways(page, 'SM-09');
  await page.screenshot({ path: `${SHOTS}/SM09-proposal-builder-diff-1440.png`, fullPage: true });
  await page.getByRole('button', { name: /^Request approvals \(\d+\)$/ }).click();
  await expect(page.getByText(/Sent for approval:/)).toBeVisible();
  const v2 = page.url().split('/').pop()!;

  // SM-11: the Pricing Approver's queue
  await signIn(page, 'ceo@futran.demo');
  await page.goto('/sales/approvals');
  await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible();
  const detail = page.getByRole('region', { name: 'Selected request' });
  await expect(detail.getByRole('table', { name: 'Lines against the catalog' })).toBeVisible();
  await expect(detail.getByText(/Margin note\./)).toBeVisible();
  await noSideways(page, 'SM-11');
  await page.screenshot({ path: `${SHOTS}/SM11-approvals-1440.png`, fullPage: true });
  await detail.getByLabel(/Note/).fill('Approved for this proposal.');
  await detail.getByRole('button', { name: 'Approve for this proposal' }).click();
  await expect(page.getByText('Approved for this proposal version.')).toBeVisible();
  await approveAll(page, 'ceo@futran.demo', v2);
  await approveAll(page, 'chief@futran.demo', v2);

  // SM-10: preview and send v2 from the rep's mailbox
  await signIn(page, 'sales@futran.demo');
  await page.goto(`/sales/proposals/${v2}/send`);
  await expect(page.getByRole('navigation', { name: 'Sections' })).toBeVisible();
  await expect(page.locator('#sec-services')).toContainText('Shadow AI discovery sweep (A-05)');
  await page.getByLabel('To: name').fill('Dana Buyer');
  await page.getByLabel('Email', { exact: true }).fill('dana@client.example');
  await expect(page.getByText(/All approvals complete/)).toBeVisible();
  await noSideways(page, 'SM-10');
  await page.screenshot({ path: `${SHOTS}/SM10-proposal-send-1440.png`, fullPage: false });
  await page.getByRole('button', { name: 'Send from my mailbox' }).click();
  await expect(page.getByText(/Sent to 1 person/)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Send log' }).getByText('Sent').first()).toBeVisible();

  // SM-12: the client accepts on a phone
  const link = lastLink();
  const phone = await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, baseURL: page.url().split('/sales')[0] });
  const c = await phone.newPage();
  await c.goto(link);
  await expect(c.getByRole('heading', { name: /AI governance proposal/ })).toBeVisible();
  await expect(c.getByText("What's included")).toBeVisible();
  await expect(c.getByText('Total, year 1')).toBeVisible();
  await noSideways(c, 'SM-12');
  await c.screenshot({ path: `${SHOTS}/SM12-proposal-acceptance-375.png`, fullPage: true });
  await c.getByRole('button', { name: /Read the full proposal/ }).click();
  await expect(c.getByRole('heading', { name: /What we'll do/ })).toBeVisible();
  await noSideways(c, 'SM-12 full proposal');
  await c.getByLabel('Full name').fill('Dana Buyer');
  await c.getByLabel('Title').fill('Chief Operating Officer');
  await c.getByLabel('Work email').fill('dana@client.example');
  await c.getByRole('button', { name: 'Accept proposal' }).click();
  await expect(c.getByText(/Confirm you are authorised/)).toBeVisible();
  await c.getByLabel(/I am authorised to accept this proposal/).check();
  await c.getByLabel('PO number (optional)').fill('PO-2026-114');
  await c.getByRole('button', { name: 'Accept proposal' }).click();
  await expect(c.getByText('Thank you. Your acceptance is recorded.', { exact: false })).toBeVisible();
  await c.getByText('Thank you. Your acceptance is recorded.', { exact: false }).scrollIntoViewIfNeeded();
  await c.screenshot({ path: `${SHOTS}/SM12-proposal-accepted-375.png`, fullPage: false });
  await phone.close();

  await page.goto(`/sales/proposals/${v2}`);
  await expect(page.getByRole('heading', { name: /Proposal v2/ })).toContainText('Accepted');
});
