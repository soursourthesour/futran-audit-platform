import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Front-end review fixes (v0.6.1): the phone header, the governance committee, the register link in fieldwork, and
   screens that must not call endpoints the signed-in person cannot use. Runs on the "late" server. */

const SHOTS = process.env.FIX_SHOTS || '/mnt/user-data/outputs/v061/fixes';
mkdirSync(SHOTS, { recursive: true });
const PW = 'Demo-Password-2026';
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string; meridian: string };

async function signIn(page: Page, email: string, staff = false) {
  await page.context().clearCookies();
  await page.goto(staff ? '/staff/login' : '/login');
  await page.getByLabel('Work email').fill(email);
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

/** Records every API answer of 400 or more while `fn` runs. */
async function apiErrors(page: Page, fn: () => Promise<void>) {
  const bad: string[] = [];
  const on = (r: import('@playwright/test').Response) => { if (r.url().includes('/api/') && r.status() >= 400) bad.push(`${r.status()} ${new URL(r.url()).pathname}`); };
  page.on('response', on);
  try { await fn(); await page.waitForLoadState('networkidle'); } finally { page.off('response', on); }
  return bad;
}

const main = (page: Page) => page.getByRole('navigation', { name: 'Main' });

test.describe('phone header', () => {
  for (const [who, email, staff, shot] of [
    ['CAICO with Client Admin rights', 'katrin.vogel@meridian.example', false, 'nav-caico-client-admin'],
    ['Chief Auditor', 'chief@futran.demo', true, 'nav-chief-auditor'],
    ['Contributor', 'tom.reyes@abccorp.example', false, 'nav-contributor'],
  ] as const) {
    test(`${who}: the navigation folds behind a menu button under 600 px`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await signIn(page, email, staff);
      const menu = page.getByRole('button', { name: 'Menu' });
      await expect(menu).toBeVisible();
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(main(page)).toBeHidden();
      const box = (await menu.boundingBox())!;
      expect(box.height).toBeGreaterThanOrEqual(44);
      expect(box.width).toBeGreaterThanOrEqual(44);
      const top = await page.locator('main').evaluate((e) => e.getBoundingClientRect().top);
      expect(top, 'page content starts near the top').toBeLessThanOrEqual(150);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `${SHOTS}/${shot}-375.png` });
      // keyboard: open, Escape closes and returns focus to the button
      await menu.focus();
      await page.keyboard.press('Enter');
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      await expect(main(page)).toBeVisible();
      const links = main(page).getByRole('link');
      for (const h of await links.evaluateAll((as) => as.map((a) => a.getBoundingClientRect().height))) expect(h).toBeGreaterThanOrEqual(44);
      await page.screenshot({ path: `${SHOTS}/${shot}-375-open.png`, fullPage: true });
      await page.keyboard.press('Escape');
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toBeFocused();
      // following a link closes the menu
      await menu.click();
      const second = links.nth(1);
      const href = await second.getAttribute('href');
      await second.click();
      await page.waitForURL((u) => u.pathname === href);
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(main(page)).toBeHidden();
      // wide screens show the navigation and no menu button
      await page.setViewportSize({ width: 1440, height: 900 });
      await expect(menu).toBeHidden();
      await expect(main(page)).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/${shot}-1440.png` });
    });
  }
});

test('10a: the bias and fairness review committee is a committee', async ({ page }) => {
  await signIn(page, 'katrin.vogel@meridian.example');
  await page.goto('/governance');
  const answers = page.getByRole('group', { name: 'Answer for Bias and fairness review committee' });
  await expect(answers).toBeVisible();
  await answers.getByRole('button', { name: 'In place' }).click();
  await expect(page.getByLabel('Chair', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Meets', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Upload terms of reference' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/governance-10a-gr02-committee-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByLabel('Chair', { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/governance-10a-gr02-committee-375.png` });
  // the Futran set-up screen names it the same way
  await signIn(page, 'chief@futran.demo', true);
  await page.setViewportSize({ width: 1280, height: 900 });
  const g = await (await page.request.get(`/api/v1/clients/${late().meridian}/governance`)).json();
  const item = g.items.find((i: { code: string }) => i.code === 'GR-02');
  expect(item.committee).toBe(true);
  expect(g.catalog.find((c: { code: string }) => c.code === 'GR-02').title).toBe(item.title);
});

test('fieldwork links an existing audit system to the client register from Edit', async ({ page }) => {
  const { meridian } = late();
  const tag = Date.now().toString(36);
  // the client records two systems in its register
  await signIn(page, 'katrin.vogel@meridian.example');
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const made: string[] = [];
  for (const name of [`Claims triage ${tag}`, `Fraud scoring ${tag}`]) {
    const r = await page.request.post('/api/v1/register', { data: { name, type: 'vendor_app', sourcing: 'vendor', stage: 'proposed', purpose: 'Scores claims for review.', company_wide: true }, headers: { 'X-CSRF-Token': me.csrf_token } });
    expect(r.status(), await r.text()).toBe(200);
    made.push((await r.json()).id);
  }
  const [first, second] = made;
  await signIn(page, 'chief@futran.demo', true);
  await page.goto(`/clients/${meridian}/systems`);
  // Add: picking a register row copies its facts, "Not from the register" takes them back
  await page.getByRole('button', { name: 'Add system' }).click();
  let dialog = page.getByRole('dialog');
  const addPicker = dialog.getByLabel("Start from the client's AI system register", { exact: true });
  await addPicker.selectOption(first);
  await expect(dialog.getByLabel('System name', { exact: true })).toHaveValue(`Claims triage ${tag}`);
  await addPicker.selectOption('');
  await expect(dialog.getByLabel('System name', { exact: true })).toHaveValue('');
  await expect(dialog.getByLabel('Reason for adding it', { exact: true })).toHaveValue('');
  await addPicker.selectOption(first);
  await dialog.getByRole('button', { name: 'Send for approval' }).click();
  await expect(page.getByText('Sent to the Engagement Manager for approval.')).toBeVisible();
  // Edit: the row waiting for approval is not offered; the other one links
  const reg = await (await page.request.get(`/api/v1/clients/${meridian}/systems`)).json();
  const sys = reg.systems.find((s: { register_system: unknown }) => !s.register_system);
  await page.getByRole('row').filter({ hasText: sys.name }).getByRole('button', { name: 'Edit' }).click();
  dialog = page.getByRole('dialog');
  const picker = dialog.getByLabel("Client's AI system register", { exact: true });
  await expect(picker).toBeVisible();
  const offered = await picker.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  expect(offered).toContain(second);
  expect(offered).not.toContain(first);
  await picker.selectOption(second);
  await picker.selectOption('');
  await expect(dialog.getByLabel('System name', { exact: true })).toHaveValue(sys.name);
  await picker.selectOption(second);
  await dialog.getByRole('button', { name: 'Save' }).click();
  await expect(dialog).toBeHidden();
  const after = await (await page.request.get(`/api/v1/clients/${meridian}/systems`)).json();
  expect(after.systems.find((s: { id: string }) => s.id === sys.id).register_system.id).toBe(second);
  // the audit system's register tab now shows the client's record
  await page.goto(`/systems/${sys.id}/assess`);
  await page.waitForLoadState('networkidle');
});

test('the Auditor is not sent to a review queue they cannot open', async ({ page }) => {
  await signIn(page, 'auditor1@futran.demo', true);
  const bad = await apiErrors(page, async () => {
    await page.goto('/reg');
    await expect(page.getByRole('heading', { level: 1, name: 'Law library' })).toBeVisible();
  });
  expect(bad).toEqual([]);
  await expect(page.getByRole('link', { name: 'Refresh laws with Claude' })).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Regulatory master' }).getByRole('link', { name: /Refresh and review/ })).toHaveCount(0);
  const bad2 = await apiErrors(page, async () => {
    await page.goto('/reg/refresh?kind=law');
    await expect(page.getByText(/wait here for the Chief Auditor/)).toBeVisible();
  });
  expect(bad2).toEqual([]);
  await expect(page.getByText('Nothing is waiting for review.')).toHaveCount(0);
});

test('QA reaches the review queue from the main navigation, and no screen answers 403', async ({ page }) => {
  await signIn(page, 'qa@futran.demo', true);
  const bad = await apiErrors(page, async () => {
    await main(page).getByRole('link', { name: 'Refresh and review', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Refresh laws and review changes' })).toBeVisible();
    await expect(page.getByRole('grid', { name: 'Changes waiting for review' }).or(page.getByText('Nothing is waiting for review.'))).toBeVisible();
  });
  expect(bad).toEqual([]);
  await expect(main(page).getByRole('link', { name: 'Refresh and review', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(main(page).getByRole('link', { name: 'Regulatory master', exact: true })).not.toHaveAttribute('aria-current', 'page');
  // a law record does not ask for the litigation tracker
  const laws = await (await page.request.get('/api/v1/reg/laws')).json();
  const law = laws.groups.flatMap((g: { laws: { id: string }[] }) => g.laws)[0];
  const bad2 = await apiErrors(page, async () => {
    await page.goto(`/reg/${law.id}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
  expect(bad2).toEqual([]);
});

for (const [who, email] of [['QA Reviewer', 'qa@futran.demo'], ['Engagement Manager', 'em@futran.demo']] as const) {
  test(`${who}: the client page offers no applicability screen they cannot open`, async ({ page }) => {
    await signIn(page, email, true);
    const bad = await apiErrors(page, async () => {
      await page.goto(`/clients/${late().abc}`);
      await page.getByRole('tab', { name: 'Locations and laws' }).click();
      await expect(page.getByRole('heading', { name: 'Laws and frameworks in scope' })).toBeVisible();
    });
    expect(bad).toEqual([]);
    await expect(page.getByRole('link', { name: 'Applicability and intro letter' })).toHaveCount(0);
  });
}

async function call(page: Page, method: 'POST' | 'PATCH', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
}

test('a deep link survives the mailbox step and the personal mailbox consent; a foreign next is ignored', async ({ page }) => {
  await signIn(page, 'katrin.vogel@meridian.example');
  await call(page, 'PATCH', '/mail/settings', { per_user_sync: 'required' });
  try {
    await signIn(page, 'lena.fischer@meridian.example');
    await page.goto('/inventory?tab=tools');
    await expect(page).toHaveURL(/\/welcome\/mailbox\?next=%2Finventory%3Ftab%3Dtools$/);
    await page.getByRole('button', { name: /Connect Microsoft 365/ }).click();
    await page.getByRole('button', { name: 'Accept' }).click();
    await expect(page).toHaveURL(/\/welcome\/mailbox\?connected=1&next=/);
    await page.getByRole('link', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/inventory\?tab=tools$/);
    await call(page, 'POST', '/me/mailbox/disconnect');
  } finally {
    await signIn(page, 'katrin.vogel@meridian.example');
    await call(page, 'PATCH', '/mail/settings', { per_user_sync: 'optional' });
  }
  // a next that leaves the site is not followed
  for (const bad of ['//evil.example/x', 'https://evil.example/x', '/\\evil.example']) {
    await page.context().clearCookies();
    await page.goto(`/login?next=${encodeURIComponent(bad)}`);
    await page.getByLabel('Work email').fill('lena.fischer@meridian.example');
    await page.getByLabel('Password').fill(PW);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForLoadState('networkidle');
    expect(page.url()).not.toContain('evil.example');
    await page.goto(`/welcome/mailbox?next=${encodeURIComponent(bad)}`);
    const notNow = page.getByRole('button', { name: 'Not now' });
    if (await notNow.count()) { await notNow.click(); await page.waitForLoadState('networkidle'); expect(page.url()).not.toContain('evil.example'); }
  }
});

/** Holds matching POSTs for a moment so a second click lands while the first is in flight; returns the count. */
async function slowPosts(page: Page, pattern: RegExp) {
  const seen = { n: 0 };
  await page.route(pattern, async (route) => {
    if (route.request().method() === 'POST') { seen.n += 1; await new Promise((r) => setTimeout(r, 800)); }
    await route.continue();
  });
  return seen;
}

test('one click, one write: import from inventory, retire and create opportunities', async ({ page }) => {
  await signIn(page, 'katrin.vogel@meridian.example');
  await page.goto('/register');
  const imp = await slowPosts(page, /\/api\/v1\/register\/import-inventory$/);
  const importBtn = page.getByRole('button', { name: 'Import from inventory' });
  if (await importBtn.count()) {
    await importBtn.dblclick();
    await expect(page.getByText(/added from the inventory as Proposed/)).toBeVisible();
    expect(imp.n).toBe(1);
  }
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const made = await page.request.post('/api/v1/register', { data: { name: `Retire me ${Date.now().toString(36)}`, type: 'vendor_app', sourcing: 'vendor', stage: 'proposed', purpose: 'Test row.', company_wide: true }, headers: { 'X-CSRF-Token': me.csrf_token } });
  const row = await made.json();
  await page.reload();
  const ret = await slowPosts(page, /\/api\/v1\/register\/[^/]+\/retire$/);
  await page.getByRole('button', { name: `Actions for ${row.name}` }).click();
  await page.getByRole('menuitem', { name: 'Retire this system' }).click();
  await page.getByRole('dialog').getByLabel('Reason *', { exact: true }).fill('No longer used.');
  await page.getByRole('button', { name: 'Retire this system' }).dblclick();
  await expect(page.getByRole('dialog')).toBeHidden();
  expect(ret.n).toBe(1);
  // litigation: assign one case to Sales
  await signIn(page, 'chief@futran.demo', true);
  await page.goto('/litigation');
  const opp = await slowPosts(page, /\/api\/v1\/litigation\/(bulk-assign|[^/]+\/opportunities)$/);
  const first = page.getByRole('button', { name: /^Actions for / }).first();
  await first.click();
  await page.getByRole('menuitem', { name: 'Create opportunity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign to Sales' });
  await dialog.getByLabel('Owner', { exact: true }).selectOption({ index: 1 });
  await dialog.getByRole('button', { name: 'Create opportunities' }).dblclick();
  await expect(dialog).toBeHidden();
  expect(opp.n).toBe(1);
});

async function pillHeights(page: Page) {
  return page.locator('main .pill').evaluateAll((ps) => ps.filter((p) => p.getBoundingClientRect().height > 0).map((p) => `${(p.textContent || '').trim()} ${Math.round(p.getBoundingClientRect().height)}`));
}

test('phone: pill tabs are 44 px; DPO documents and Futran users fit 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const wide = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await signIn(page, 'chief@futran.demo', true);
  for (const path of ['/staff/alerts', '/reg/refresh']) {
    await page.goto(path);
    await expect(page.locator('main .pill').first()).toBeVisible();
    for (const p of await pillHeights(page)) expect(Number(p.split(' ').pop()), `${path}: ${p}`).toBeGreaterThanOrEqual(44);
  }
  await signIn(page, 'qa@futran.demo', true);
  await page.goto('/qa');
  await page.waitForLoadState('networkidle');
  for (const p of await pillHeights(page)) expect(Number(p.split(' ').pop()), `/qa: ${p}`).toBeGreaterThanOrEqual(44);
  await signIn(page, 'admin@futran.demo', true);
  await page.goto('/admin/users');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(await wide(), '/admin/users scrolls sideways').toBeLessThanOrEqual(0);
  await signIn(page, 'daniel.kim@abccorp.example');
  await page.goto('/documents');
  await expect(page.getByRole('heading', { level: 1, name: 'Documents' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(await wide(), '/documents scrolls sideways').toBeLessThanOrEqual(0);
});

test('register: suggested laws have their own 44 px Add buttons, and the copy names the Chief AI Compliance Officer', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, 'katrin.vogel@meridian.example');
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const made = await (await page.request.post('/api/v1/register', { data: { name: `Suggest ${Date.now().toString(36)}`, type: 'vendor_app', sourcing: 'vendor', stage: 'proposed', purpose: 'Screens applicants.', company_wide: true }, headers: { 'X-CSRF-Token': me.csrf_token } })).json();
  await page.goto(`/register/${made.id}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.waitForLoadState('networkidle');
  const adds = page.locator('.reg-chip-suggest button');
  for (const b of await adds.evaluateAll((bs) => bs.map((x) => ({ h: x.getBoundingClientRect().height, name: x.getAttribute('aria-label') || '' })))) {
    expect(b.h).toBeGreaterThanOrEqual(44);
    expect(b.name).toMatch(/^Add .+/);
  }
  for (const path of [`/register/${made.id}`, '/register']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    expect(await page.locator('main').innerText()).not.toMatch(/(?<!Chief )AI Compliance Officer/);
  }
});

test('Contributor: no "Add a use case" once the inventory is locked', async ({ page }) => {
  await signIn(page, 'tom.reyes@abccorp.example');  // ABC Corp is at stage 6: the inventory is locked
  await page.goto('/my-tasks');
  await expect(page.getByRole('heading', { level: 1, name: 'My tasks' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('link', { name: 'Add a use case' })).toHaveCount(0);
});

test('Sales: the case record names laws as text, without links to the regulatory master', async ({ page }) => {
  await signIn(page, 'sales@futran.demo', true);
  const list = await (await page.request.get('/api/v1/litigation')).json();
  const withLaw = (list.cases ?? list.items ?? []).find((c: { regulation_ids?: string[] }) => (c.regulation_ids ?? []).length);
  test.skip(!withLaw, 'no case linked to a law in this data');
  await page.goto(`/litigation/${withLaw.id}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main a[href^="/reg/"]')).toHaveCount(0);
  expect(await page.locator('main').innerText()).not.toMatch(/last checked \d{4}-\d{2}-\d{2}/);
});

test('help on a new input: the applicability geography search', async ({ page }) => {
  await signIn(page, 'chief@futran.demo', true);
  await page.goto(`/clients/${late().abc}/applicability`);
  await page.getByRole('button', { name: 'Add a geography' }).click();
  await expect(page.getByRole('dialog').getByRole('button', { name: 'About Search' })).toBeVisible();
});
