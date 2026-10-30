import { test, expect, type Page } from '@playwright/test';

const PW = 'Demo-Password-2026';

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w).toBeLessThanOrEqual(1);
}

test('Chief Auditor browses the law library, opens Colorado SB 26-189 and an Admin edit becomes a proposed change', async ({ page }) => {
  await signIn(page, 'chief@futran.demo');
  await page.getByRole('link', { name: 'Regulatory master' }).click();
  await expect(page.getByRole('heading', { name: 'Law library' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'NYC LL144' })).toBeVisible();
  await page.getByPlaceholder('Law, citation or requirement').fill('SB 26-189');
  await page.getByRole('link', { name: 'Colorado', exact: true }).click();

  await expect(page.getByRole('heading', { name: 'Colorado', exact: true })).toBeVisible();
  await expect(page.getByText('Enacted, not yet in force').first()).toBeVisible();
  await expect(page.getByText('Signed May 14, 2026')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Statutory requirements (8)' })).toBeVisible();
  await expect(page.getByText('WITHIN THIRTY DAYS AFTER MAKING THE DECISION', { exact: false })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Explainability contact' }).first()).toBeVisible();

  // An Admin's edit is a proposal: the live record does not change
  await signIn(page, 'admin@futran.demo');
  await page.goto('/reg');
  await page.getByPlaceholder('Law, citation or requirement').fill('SB 26-189');
  await page.getByRole('link', { name: 'Colorado', exact: true }).click();
  await page.getByRole('link', { name: 'Edit record' }).click();
  await page.getByLabel('Cure period', { exact: true }).fill('30 days after a notice of violation');
  await page.getByLabel('Reason for change', { exact: true }).fill('Checking the review queue');
  await page.getByRole('button', { name: 'Send for approval' }).click();
  await expect(page.getByText(/1 proposed change waiting for Chief Auditor approval/)).toBeVisible();
  await expect(page.getByText(/^60 days after a notice of violation/)).toBeVisible();

  // M4: the role matrix
  await page.getByRole('navigation', { name: 'Regulatory master' }).getByRole('link', { name: 'Roles and committees' }).click();
  await expect(page.getByRole('heading', { name: 'Role and committee catalogue' })).toBeVisible();
  await expect(page.getByRole('cell', { name: /Bias testing lead/ }).first()).toBeVisible();
  await noSidewaysScroll(page);
});

test('Chief Auditor reviews a client\'s applicability, approves the intro letter and sends it', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'auditor1@futran.demo');
  const { client_id: cid } = await api(page, 'POST', '/clients', {});
  await api(page, 'PUT', `/clients/${cid}/wizard/company`, {
    legal_name: 'Harbor Staffing Inc.', trading_name: 'Harbor Staffing', industry: 'staffing', employee_band: '250-999', hq_street: '1 Main St', hq_city: 'New York',
    hq_state: 'US-NY', hq_postal_code: '10001', hq_country: 'US', primary_jurisdictions: ['US'], ai_systems_in_scope_count: 1, engagement_reason: 'AI screening of job applicants',
  });
  await api(page, 'PUT', `/clients/${cid}/wizard/locations`, { locations: [
    { site_name: 'Headquarters', street: '1 Main St', city: 'New York', subdivision_code: 'US-NY', country_code: 'US', in_scope: true },
    { site_name: 'Chicago office', city: 'Chicago', subdivision_code: 'US-IL', country_code: 'US', in_scope: true },
  ] });
  await api(page, 'PUT', `/clients/${cid}/wizard/contacts`, { caico: { name: 'Maria Lopez', title: 'Chief AI Compliance Officer', email: 'maria@harbor.test' }, client_admin: { same_as_caico: true }, dpo: { not_appointed: true }, project_lead: { same_as_caico: true } });

  await signIn(page, 'chief@futran.demo');
  await page.goto(`/clients/${cid}/applicability`);
  await expect(page.getByRole('heading', { name: 'Client applicability and intro letter' })).toBeVisible();
  // wizard step 2 wrote the geographies
  await expect(page.getByText('New York City', { exact: false }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'NYC LL144' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Illinois HB 3773' })).toBeVisible();
  await page.getByText(/Not in scope \(\d+\) and why/).click();
  await expect(page.getByText('No Colorado operations or residents')).toBeVisible();

  await page.getByRole('button', { name: 'Draft the letter' }).click();
  await expect(page.getByTestId('letter-preview')).toContainText('AI governance requirements for your operations');
  await expect(page.getByTestId('letter-preview')).toContainText('General information, not legal advice');
  await expect(page.getByText('v1 · not sent')).toBeVisible();
  await page.screenshot({ path: 'screenshots/regmaster-m5-draft.png', fullPage: true });

  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('Letter approved. It goes with the initiation package.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await page.getByRole('button', { name: 'Send to Maria Lopez' }).click();
  await expect(page.getByText('Letter sent to Maria Lopez.')).toBeVisible();
  await expect(page.getByText('v1 · sent')).toBeVisible();

  await page.goto('/admin/outbox');
  await expect(page.getByText(/AI governance requirements for Harbor Staffing/).first()).toBeVisible();
});

test('regulatory master screens fit a phone without sideways scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, 'chief@futran.demo');
  for (const path of ['/reg', '/reg/roles', '/reg/new']) {
    await page.goto(path);
    await expect(page.locator('h1')).toBeVisible();
    await noSidewaysScroll(page);
  }
});
