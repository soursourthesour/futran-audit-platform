import { mkdirSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

// Email, groups and sync (spec §26, §27.1) on the "late" server: Meridian has an open attestation campaign and Katrin
// Vogel is its Chief AI Compliance Officer and Client Admin. Providers are the in-process fakes (test mode).
const SHOTS = process.env.WS_C_SHOTS || 'screenshots/ws-c';
mkdirSync(SHOTS, { recursive: true });

async function shot(page: Page, name: string) {
  const size = page.viewportSize();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: `${SHOTS}/${name}-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(150);
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    const clipped = (el: HTMLElement) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'hidden' || o === 'scroll') return true; } return false; };
    const over = [...document.querySelectorAll<HTMLElement>('body *')].filter((el) => el.getBoundingClientRect().right > w + 1 && !clipped(el) && getComputedStyle(el).position !== 'fixed')
      .slice(0, 8).map((el) => `${el.tagName.toLowerCase()}.${el.className} ${Math.round(el.getBoundingClientRect().right)}`);
    return { by: document.documentElement.scrollWidth - w, over };
  });
  expect(wide.by, `${name}: the page scrolls sideways at 375 px: ${wide.over.join(' | ')}`).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${SHOTS}/${name}-375.png`, fullPage: true });
  if (size) await page.setViewportSize(size);
}

async function signIn(page: Page, email: string, staff = false) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
  for (let i = 0; i < 3; i++) {
    const p = new URL(page.url()).pathname;
    if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
    else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
    else break;
    await page.waitForURL((u) => !u.pathname.startsWith(p));
  }
}

const KATRIN = 'katrin.vogel@meridian.example';

/** Choose the option whose text starts with `text` (options carry a member count after the name). */
async function pick(page: Page, select: string, text: string) {
  const sel = page.getByRole('combobox', { name: select });
  const value = await sel.locator('option', { hasText: text }).first().getAttribute('value');
  await sel.selectOption(value!);
}

test.describe.configure({ mode: 'serial' });

test('E1: the Futran Admin connects the Futran mailbox with the test provider', async ({ page }) => {
  await signIn(page, 'admin@futran.demo', true);
  await page.getByRole('link', { name: 'Email and groups' }).click();
  await expect(page.getByRole('heading', { name: 'Futran email and groups' })).toBeVisible();
  await expect(page.getByText(/Test mode: connections use a simulated Microsoft 365/)).toBeVisible();
  await page.locator('.mail-card').filter({ hasText: 'Microsoft 365' }).getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Approve access for your organization' })).toBeVisible();
  await shot(page, 'test-consent');
  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('The Futran mailbox is connected.')).toBeVisible();
  await expect(page.getByText('Connected as aiaudit@futransolutions.com', { exact: false })).toBeVisible();
  await expect(page.getByRole('table', { name: 'Futran groups' }).getByText('ChiefAuditors')).toBeVisible();
  await shot(page, 'E1-futran-email');
  // keep the other specs' outbox subjects unchanged: go back to the outbox channel
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Disconnect' }).click();
  await expect(page.getByText('Disconnected.')).toBeVisible();
});

test('E2: the Client Admin works through the four onboarding steps', async ({ page }) => {
  await signIn(page, KATRIN);
  await page.goto('/start');
  await expect(page.getByRole('heading', { name: 'Connect your email' })).toBeVisible();
  await shot(page, 'getting-started-connect-email');
  await page.getByRole('link', { name: 'Connect', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/email$/);
  await page.getByLabel('Mailbox to send from *', { exact: true }).fill('ai-governance@meridian.example');
  await page.locator('.mail-card').filter({ hasText: 'Microsoft 365' }).getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByRole('textbox', { name: 'Mailbox the emails come from' }).fill('ai-governance@meridian.example');
  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('Access approved. Your email system is connected.')).toBeVisible();
  await expect(page.getByRole('heading', { name: /1 · Your email system/ }).getByText('Done')).toBeVisible();
  await page.getByLabel('Sender name *', { exact: true }).fill('Meridian AI Governance');
  await page.getByRole('button', { name: 'Save sender' }).click();
  await expect(page.getByText('Sender saved.')).toBeVisible();
  await page.getByRole('button', { name: 'Sync now' }).click();
  await expect(page.getByText('Directory synced.')).toBeVisible();
  await expect(page.locator('.mail-note').getByText(/people/)).toBeVisible();
  await page.getByRole('button', { name: 'Send test' }).click();
  await expect(page.getByText(/Test email sent to/)).toBeVisible();
  await expect(page.locator('.mail-steps li.done')).toHaveCount(4);
  await shot(page, 'E2-connect-your-email');
  await page.getByRole('button', { name: 'Save and continue to groups' }).click();
  await expect(page).toHaveURL(/\/admin\/groups$/);
});

test('E3: group grid, nested groups and a loop that is refused', async ({ page }) => {
  await signIn(page, KATRIN);
  await page.goto('/admin/groups');
  const grid = page.getByRole('table', { name: 'Email groups' });
  await expect(grid.getByText('Employees · All')).toBeVisible();
  await expect(grid.getByText('DeptHeads')).toBeVisible();
  // a list we keep
  await page.getByRole('button', { name: 'Add group' }).click();
  await page.getByLabel('Group name *', { exact: true }).fill('AI-EUAct');
  await page.getByLabel('Purpose', { exact: true }).fill('EU AI Act working group');
  await page.getByRole('button', { name: 'Add group' }).last().click();
  await expect(page.getByText('Added AI-EUAct. Now add its members.')).toBeVisible();
  await page.getByLabel('Add a person', { exact: true }).fill('jonas');
  await page.getByRole('listbox', { name: 'People found' }).getByRole('button').first().click();
  await expect(page.locator('.group-panel').getByText('Members (1)')).toBeVisible();
  // a second list that includes the first
  await page.getByRole('button', { name: 'Add group' }).first().click();
  await page.getByLabel('Group name *', { exact: true }).fill('Working groups');
  await page.getByRole('button', { name: 'Add group' }).last().click();
  await expect(page.getByText('Added Working groups.', { exact: false })).toBeVisible();
  await page.getByLabel('Include another group', { exact: true }).selectOption({ label: 'AI-EUAct' });
  await page.locator('.group-panel').getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.locator('.group-panel').getByText('Group · 1 person')).toBeVisible();
  // the first may not include the second: that would be a loop
  await grid.getByRole('button', { name: 'Actions for AI-EUAct' }).click();
  await page.getByRole('menuitem', { name: 'Open and edit' }).click();
  await page.getByLabel('Include another group', { exact: true }).selectOption({ label: 'Working groups' });
  await page.locator('.group-panel').getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.locator('.group-panel').getByText(/would make a loop/)).toBeVisible();
  await shot(page, 'E3-email-groups');
});

test('E4: send to groups with the expansion counts, through the client mailbox', async ({ page }) => {
  await signIn(page, KATRIN);
  await page.goto('/send?template=training_ai_literacy');
  await page.getByLabel('Template *', { exact: true }).selectOption({ label: 'Training: AI literacy module' });
  await pick(page, 'Add a group', 'Employees · All');
  await pick(page, 'Add a group', 'Working groups');
  const box = page.locator('.expansion-box');
  await expect(box.getByRole('cell', { name: 'Employees · All' })).toBeVisible();
  await expect(box.getByRole('cell', { name: 'In more than one group (counted once)' })).toBeVisible();
  await expect(box.getByRole('cell', { name: 'Will receive' })).toBeVisible();
  const total = Number((await box.locator('tr.total td').last().innerText()).replace(/[^0-9]/g, ''));
  expect(total).toBeGreaterThan(10);
  await expect(page.frameLocator('iframe[title="Email preview"]').getByText('Start the module')).toBeVisible();
  await expect(page.locator('.mail-preview-head')).toContainText('ai-governance@meridian.example');
  await shot(page, 'E4-send-to-groups');
  await page.getByRole('button', { name: `Send to ${total.toLocaleString('en-US')} people` }).click();
  await expect(page.getByRole('heading', { name: 'Email sent' })).toBeVisible();
  await page.getByRole('link', { name: 'Open in the email log' }).click();
  await expect(page.getByRole('heading', { name: 'Email and admin log' })).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('tab', { name: new RegExp(`Recipients \\(${total}\\)`) })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('table').last().getByText('Sent email').first()).toBeVisible();
  await shot(page, 'E5-email-log');
});

test('send to all employees and answer through a personal link', async ({ page }) => {
  await signIn(page, KATRIN);
  await page.goto('/attestation');
  await page.getByRole('button', { name: 'Send to all employees' }).click();
  const dlg = page.getByRole('dialog', { name: 'Send to all employees' });
  await expect(dlg.getByRole('cell', { name: 'Will receive' })).toBeVisible();
  // only people from the directory (an office filter), so the users with a login keep their own attestation for mobile.spec
  await dlg.getByLabel('Only this office', { exact: true }).selectOption('New York');
  await expect(dlg.getByRole('cell', { name: 'Not in the chosen locations' })).toBeVisible();
  await shot(page, 'tracker-send-to-all-employees');
  await dlg.getByRole('button', { name: /^Send to \d+ employees?$/ }).click();
  await expect(page.getByText(/Attestation sent to \d+ employees?, each with their own link/)).toBeVisible();
  // the personal link from the stored message (readable in test mode only)
  const sends = await page.request.get('/api/v1/mail/log/sends').then((r) => r.json());
  const s = sends.sends.find((x: { template_key: string }) => x.template_key === 'attestation_request');
  const detail = await page.request.get(`/api/v1/mail/log/sends/${s.id}`).then((r) => r.json());
  const link = /\/m\/[A-Za-z0-9_-]{40,}/.exec(detail.message.html)![0];
  await page.context().clearCookies();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(link);
  await expect(page.getByText('We filled these in from your company directory.')).toBeVisible();
  await shot(page, 'personal-link-attestation');
  const dept = page.getByLabel('Department', { exact: true });
  if (!(await dept.inputValue())) await dept.selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('ChatGPT', { exact: true }).check();
  await page.getByLabel('Personal, free').check();
  await page.getByRole('button', { name: 'Next: what you use it for' }).click();
  await page.getByLabel('Writing and editing').check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByLabel('I have read the AI use policy', { exact: true }).check();
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByRole('heading', { name: 'Thank you' })).toBeVisible();
  await signIn(page, KATRIN);
  const after = await page.request.get(`/api/v1/mail/log/sends/${s.id}`).then((r) => r.json());
  expect(after.completed).toBe(1);
});

test('the mailbox prompt and the clean-up', async ({ page }) => {
  await signIn(page, KATRIN);
  await expect(page.getByRole('region', { name: 'Connect your mailbox' })).toBeVisible();
  await page.goto('/welcome/mailbox');
  await expect(page.getByRole('heading', { name: 'Connect your mailbox' })).toBeVisible();
  await shot(page, 'mailbox-prompt');
  await page.getByRole('button', { name: 'Not now' }).click();
  await page.waitForURL(/\/start$/);
  await expect(page.getByRole('region', { name: 'Connect your mailbox' })).toHaveCount(0);
  // Futran sees the client's status at wizard step 6
  await signIn(page, 'chief@futran.demo', true);
  const clients = await page.request.get('/api/v1/clients?q=Meridian').then((r) => r.json());
  await page.goto(`/clients/${clients.clients[0].id}/setup/contacts`);
  await expect(page.getByRole('heading', { name: 'Client email' })).toBeVisible();
  await expect(page.getByText(/sends from ai-governance@meridian.example/)).toBeVisible();
  await shot(page, 'wizard-step6-client-email');
  // back to the outbox channel so the later specs see unchanged subjects
  await signIn(page, KATRIN);
  await page.request.post('/api/v1/mail/client/disconnect', { headers: { 'X-CSRF-Token': await page.evaluate(() => fetch('/api/v1/auth/me').then((r) => r.json()).then((m) => m.csrf_token)) } });
});
