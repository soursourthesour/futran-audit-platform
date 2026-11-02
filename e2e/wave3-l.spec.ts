import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Wave 3 WS-L on ABC Corp (start-server.sh … late): comments and mentions with the bell's filters (F18), the client's API
   clients and webhooks with secrets shown once and a token from the public API (F17), the register's Agent tab and the
   auditor's decision sample (F14), and the Futran Admin's platform trust register (F19). Webhooks run in fake mode. */

const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const MARIA = `maria.lopez@${ABC}`;
const SAM = `sam.okafor@${ABC}`;
const ROBERT = `robert.chen@${ABC}`;
const SHOTS = process.env.WSL_SHOTS || '/mnt/user-data/outputs/wave3/ws-l';
mkdirSync(SHOTS, { recursive: true });
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string };

function iso(minutes: number) {
  return new Date(Date.now() + minutes * 60_000).toISOString().slice(0, 19);
}

async function signIn(page: Page, portal: '/staff/login' | '/login', email: string) {
  await page.context().clearCookies();
  await page.goto(portal);
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
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

test('comments: internal and shared threads, an @mention from the suggestions, and the bell filters', async ({ page }) => {
  test.setTimeout(180_000);
  const abc = late().abc;
  await signIn(page, '/staff/login', 'auditor1@futran.demo');
  const findings = (await api(page, 'GET', `/clients/${abc}/findings`)).findings as { id: string; ref: string; status: string }[];
  const f = findings.find((x) => x.status === 'approved') ?? findings[0];
  await page.goto(`/clients/${abc}/findings`);
  await page.getByText(f.ref, { exact: false }).first().click();
  const box = page.getByRole('region', { name: `Comments on ${f.ref}` });
  await expect(box).toBeVisible();
  // internal by default; mention the Chief Auditor from the suggestion list
  const input = box.getByRole('combobox', { name: 'New comment' });
  await input.fill('Severity check please ');
  await input.pressSequentially('@Chr');
  await box.getByRole('option', { name: /Chris Chief/ }).click();
  await input.pressSequentially('does medium stand?');
  await box.getByRole('button', { name: 'Post comment' }).click();
  await expect(box.getByText('does medium stand?')).toBeVisible();
  await expect(box.getByRole('article').first().getByText('Internal')).toBeVisible();
  // a shared comment, when the finding is approved
  if (f.status === 'approved') {
    await box.getByRole('combobox', { name: 'New comment' }).fill('Please send the vendor contract clause on bias audits.');
    await box.getByLabel('Shared with the client').check();
    await box.getByRole('button', { name: 'Post comment' }).click();
    await expect(box.getByText('Please send the vendor contract clause')).toBeVisible();
  }
  await shoot(page, 'f18-comments-finding');

  // the client never receives the internal thread, whatever the stage
  await signIn(page, '/login', MARIA);
  const r = await page.request.get(`/api/v1/comments?object_type=finding&object_id=${f.id}`);
  if (r.status() === 200) expect(JSON.stringify(await r.json())).not.toContain('does medium stand');
  else expect([403, 404]).toContain(r.status());

  // the Chief Auditor's bell: Mentions filter
  await signIn(page, '/staff/login', 'chief@futran.demo');
  await page.getByRole('button', { name: /Notifications/ }).click();
  const bell = page.getByRole('dialog', { name: 'Notifications' });
  await bell.getByRole('tab', { name: /Mentions/ }).click();
  await expect(bell.getByText(/mentioned you on finding/)).toBeVisible();
  await bell.getByRole('tab', { name: 'Unread' }).click();
  await expect(bell.getByText(/mentioned you on finding/)).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await noSidewaysScroll(page, 'bell at 375px');
  await page.screenshot({ path: `${SHOTS}/f18-bell-mentions-375.png` });
  await page.setViewportSize({ width: 1280, height: 900 });
});

test('API and webhooks: the Client Admin creates a client and a webhook, secrets show once, the token works', async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, '/login', SAM);
  await page.goto('/admin/api');
  await expect(page.getByRole('heading', { name: 'API and webhooks' })).toBeVisible();
  await page.getByRole('button', { name: 'New API client' }).click();
  const dlg = page.getByRole('dialog', { name: 'New API client' });
  await dlg.getByLabel('Name *').fill('ServiceNow GRC sync');
  await dlg.getByText('findings:read').click();
  await dlg.getByText('inventory:read').click();
  await dlg.getByRole('button', { name: 'Create and show secret' }).click();
  const shown = page.getByRole('dialog', { name: /API client ServiceNow GRC sync created/ });
  const secret = (await shown.getByLabel('Client secret').textContent())!.trim();
  expect(secret).toMatch(/^fapsk_/);
  await shown.getByRole('button', { name: 'I have saved it' }).click();
  await expect(page.getByText(secret)).toHaveCount(0);
  const clientId = (await page.locator('code', { hasText: /^fap_/ }).first().textContent())!.trim();

  // a token from the public API, then a scoped call; cookies alone are refused
  const tok = await page.request.post('/api/public/v1/oauth/token', { form: { grant_type: 'client_credentials', client_id: clientId, client_secret: secret } });
  expect(tok.status()).toBe(200);
  const { access_token } = await tok.json();
  expect((await page.request.get('/api/public/v1/findings', { headers: { Authorization: `Bearer ${access_token}` } })).status()).toBe(200);
  expect((await page.request.get('/api/public/v1/findings')).status()).toBe(401);
  expect((await page.request.get('/api/public/v1/remediation', { headers: { Authorization: `Bearer ${access_token}` } })).status()).toBe(403);

  // a webhook: a private address is refused, a public one gets a signing secret, and a test delivery is logged
  await page.getByRole('button', { name: 'Add webhook' }).click();
  const hd = page.getByRole('dialog', { name: 'Add webhook' });
  await hd.getByLabel('Address *').fill('https://169.254.169.254/latest/meta-data');
  await hd.getByRole('button', { name: 'Add and show signing secret' }).click();
  await expect(hd.getByText(/private network/)).toBeVisible();
  await hd.getByLabel('Address *').fill('https://grc.abccorp.example/futran/events');
  await hd.getByRole('button', { name: 'Add and show signing secret' }).click();
  const ss = page.getByRole('dialog', { name: 'Webhook added' });
  await expect(ss.getByLabel('Signing secret')).toContainText('whsec_');
  await ss.getByRole('button', { name: 'I have saved it' }).click();
  const grid = page.getByRole('table', { name: 'Webhooks' });
  await grid.getByRole('button', { name: /More actions|Actions|⋯/ }).first().click();
  await page.getByRole('menuitem', { name: 'Send a test delivery' }).click();
  await expect(page.getByText('Test delivery sent.')).toBeVisible();
  await shoot(page, 'f17-api-and-webhooks');
  await page.goto('/admin/api/reference');
  await expect(page.getByText('/api/public/v1/findings').first()).toBeVisible();
  await shoot(page, 'f17-api-reference');
});

test('agents: the client registers an agent, the auditor samples its decisions and records verdicts', async ({ page }) => {
  test.setTimeout(240_000);
  const abc = late().abc;
  await signIn(page, '/login', MARIA);
  const reg = await api(page, 'GET', '/register');
  const fin = reg.departments.find((d: { name: string }) => d.name === 'Finance');
  const s = await api(page, 'POST', '/register', { name: 'Supplier onboarding agent', type: 'agent', sourcing: 'vendor', stage: 'in_development', department_id: fin.id,
    autonomy: 'acts_with_approval', purpose: 'Collects supplier bank details and tax forms and sets the supplier up in the ERP after a person approves.' });
  await page.goto(`/register/${s.id}/agent`);
  await page.getByRole('button', { name: 'Register this agent' }).click();
  await page.getByLabel('Tool 1 name').fill('erp.create_supplier');
  await page.getByLabel('What it does').first().fill('Creates the supplier record');
  await page.getByLabel('Access').first().selectOption('act');
  await page.getByLabel('Autonomy *').selectOption('acts_with_approval');
  await page.getByLabel('Kill switch', { exact: true }).fill('Finance systems lead disables the service account.');
  await page.getByRole('button', { name: 'Save registration' }).click();
  await expect(page.getByText(/Registration saved/)).toBeVisible();
  await expect(page.getByText('erp.create_supplier')).toBeVisible();
  await shoot(page, 'f14-agent-tab');

  // the tracing add-on and a decision log, so there is something to sample
  const addons = await api(page, 'GET', '/addons/tracing');
  const robert = addons.sponsors.find((x: { name: string }) => x.name === 'Robert Chen');
  const req = await api(page, 'POST', '/addons/tracing/requests', { system_ids: [s.id], plan: 'per_system', approver_id: robert.id, trial: true });
  await signIn(page, '/login', ROBERT);
  await api(page, 'POST', `/addons/requests/${req.id}/decide`, { approve: true });
  await signIn(page, '/login', MARIA);
  const csv = ['time,action,tool,decision,event id', ...Array.from({ length: 12 }, (_, i) => `${iso(-200 + i * 10)},Created supplier SUP-${400 + i},erp.create_supplier,${i % 4 === 0 ? 'escalated' : 'allowed'},sup-${i}`)].join('\n');
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const up = await page.request.post(`/api/v1/register/${s.id}/tracing/traces/import`, { multipart: { file: { name: 'supplier-agent.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } }, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(up.status(), await up.text()).toBe(200);

  await signIn(page, '/staff/login', 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/agents`);
  const card = page.locator('section.card', { hasText: 'Supplier onboarding agent' });
  await card.getByRole('button', { name: 'Sample decisions' }).click();
  const dd = page.getByRole('dialog', { name: /Sample decisions/ });
  await dd.getByLabel('Number of decisions').fill('3');
  await dd.getByLabel('Seed (optional)').fill('7');
  await dd.getByRole('button', { name: 'Draw sample' }).click();
  const sd = page.getByRole('dialog', { name: 'Decision sample' });
  await expect(sd.getByText(/random.Random\(7\)/)).toBeVisible();
  for (let i = 0; i < 3; i += 1) {
    await sd.getByRole('group', { name: 'Verdict' }).nth(i).getByRole('button', { name: 'Appropriate' }).click();
    await expect(sd.getByRole('listitem').nth(i).getByText('Appropriate').first()).toBeVisible();
  }
  await sd.getByLabel('Conclusion').fill('All three decisions within the registration.');
  await sd.getByRole('button', { name: 'Complete the review' }).click();
  await expect(sd.getByText(/Completed by/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/f14-sample-1440.png`, fullPage: true });
  await sd.getByRole('button', { name: /Close/ }).first().click();
  await shoot(page, 'f14-agent-oversight');
});

test('platform trust: the Futran Admin keeps the SOC 2 register; the platform\'s own AI is registered', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, '/staff/login', 'admin@futran.demo');
  await page.goto('/staff/admin/trust');
  await expect(page.getByRole('heading', { name: 'Platform trust' })).toBeVisible();
  await expect(page.getByText('Law refresh with Claude (M3)')).toBeVisible();
  const grid = page.getByRole('table', { name: 'SOC 2 controls' });
  await grid.getByRole('row', { name: /CC6\.1/ }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Edit' }).click();
  const dlg = page.getByRole('dialog', { name: /CC6\.1/ });
  await dlg.getByLabel('Status').selectOption('implemented');
  await dlg.getByLabel('Evidence').fill('MFA and tenant isolation tests in the release pipeline');
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('CC6.1 saved.')).toBeVisible();
  await shoot(page, 'f19-platform-trust');
});
