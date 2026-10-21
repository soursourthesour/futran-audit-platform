import { readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

// ABC Corp at stage 6 (every finding approved) from start-server.sh … late; this walks review to close in the browser.
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string; meridian: string; attest_link: string; confirm_link: string };
const PW = 'Demo-Password-2026';
const ABC = 'abccorp.example';
const shot = (page: Page, name: string) => page.screenshot({ path: `screenshots/${name}.png`, fullPage: true });

async function staff(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

async function clientUser(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill(PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Repetitive steps go straight to the API, signed in as the same user (the browser's session and CSRF token). */
async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, data?: unknown) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

async function sign(page: Page, name: string, card: string) {
  const panel = page.locator('.card').filter({ hasText: card });
  await panel.getByLabel('Type your full name to sign', { exact: true }).fill(name);
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button', { name: 'Sign', exact: true }).click();
}

test('review to close: sign-off 5, report and declarations, responses, final report, public summary, remediation', async ({ page }) => {
  test.setTimeout(240_000);
  const { abc } = late();

  // Stage 6: the auditor sends sign-off 5; the Chief Auditor signs it
  await staff(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/findings`);
  await expect(page.getByRole('heading', { name: 'Findings', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Send sign-off 5 to the Chief Auditor' }).click();
  await expect(page.getByText('Sign-off 5 sent to the Chief Auditor.')).toBeVisible();
  await shot(page, 'p6-findings-qa');
  await staff(page, 'chief@futran.demo');
  await page.goto(`/clients/${abc}/findings`);
  await sign(page, 'Dana Whitfield', 'Sign-off 5');
  await expect(page.locator('.card').filter({ hasText: 'Sign-off 5' }).getByText('Approved').first()).toBeVisible();

  // The report: executive summary, a roadmap item, the lead review version
  await staff(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/report`);
  await page.getByLabel('Most significant finding').selectOption({ index: 1 });
  await page.getByLabel('Its potential impact').fill('The résumé screening tool ranks New York applicants without a current bias audit.');
  await page.getByLabel('Greatest strengths observed', { exact: true }).fill('A monthly AI governance committee chaired by the CAICO, and quarterly validation of the invoice model.');
  await page.getByLabel('Immediate actions required (within 30 days)', { exact: true }).fill('Commission an independent bias audit before further use on New York roles.');
  await page.getByRole('button', { name: 'Save executive summary' }).click();
  await expect(page.getByText('Executive summary saved.')).toBeVisible();
  await page.getByRole('button', { name: 'Add item' }).click();
  await page.getByLabel('Recommended action', { exact: true }).fill('Commission an independent bias audit and publish the summary');
  await page.getByLabel('Responsible owner').fill('Head of HR');
  await page.getByLabel('How Futran can help').fill('Futran runs LL144 bias audits.');
  await page.getByRole('button', { name: 'Add to roadmap' }).click();
  await expect(page.getByRole('cell', { name: 'R-01' })).toBeVisible();
  await page.getByRole('button', { name: 'Generate lead review v0.2' }).click();
  await expect(page.getByText(/Lead review v0.2 generated/)).toBeVisible();
  await shot(page, 'p6-final-report');

  // Declarations by the Lead Auditor, the Engagement Manager and the QA Reviewer; the manager releases v1.0
  for (const [email, name, label] of [['chief@futran.demo', 'Dana Whitfield', 'Lead Auditor'], ['em@futran.demo', 'Elena Brooks', 'Engagement Manager'], ['qa@futran.demo', 'Quinn Taylor', 'Quality Reviewer']]) {
    await staff(page, email);
    await page.goto(`/clients/${abc}/report`);
    await page.getByLabel('Type your full name to sign', { exact: true }).fill(name);
    await page.getByRole('button', { name: 'Sign', exact: true }).click();
    await expect(page.getByText(`${label} declaration signed.`)).toBeVisible();
  }
  await page.context().clearCookies();
  await staff(page, 'em@futran.demo');
  await page.goto(`/clients/${abc}/report`);
  await page.getByRole('button', { name: 'Release client draft v1.0' }).click();
  await expect(page.getByText(/client draft \(v1.0\) is released/)).toBeVisible();

  // Stage 7: the client responds; Futran reviews adequacy; sign-off 6
  await clientUser(page, `maria.lopez@${ABC}`);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Responses' }).click();
  await expect(page.getByRole('heading', { name: 'Respond to findings' })).toBeVisible();
  const first = page.locator('.card').filter({ hasText: 'Finding 1' });
  await first.getByLabel('Agree', { exact: true }).check();
  await first.getByLabel('Planned action *').fill('Commission an independent bias audit and publish the summary.');
  await first.getByLabel('Owner *').selectOption({ label: 'Priya Shah' });
  await first.getByLabel('Due date *').fill(new Date(Date.now() + 40 * 864e5).toISOString().slice(0, 10));
  await first.getByRole('button', { name: 'Save response' }).click();
  await expect(page.getByText(/Response to F-\d+ saved\./)).toBeVisible();
  const rs = await api(page, 'GET', `/clients/${abc}/responses`);
  const priya = rs.people.find((x: { name: string }) => x.name === 'Priya Shah').id;
  for (const r of rs.responses.filter((x: { id: string | null }) => !x.id)) {
    await api(page, 'PUT', `/findings/${r.finding.id}/response`, { response: 'agree', planned_action: r.finding.recommended_remediation || 'Agreed action.', owner_user_id: priya, due_date: new Date(Date.now() + 45 * 864e5).toISOString().slice(0, 10) });
  }
  await page.reload();
  await shot(page, 'p6-management-response');
  await staff(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/responses`);
  await page.getByRole('button', { name: 'Adequate' }).first().click();
  await expect(page.getByText(/accepted\./)).toBeVisible();
  for (const r of (await api(page, 'GET', `/clients/${abc}/responses`)).responses.filter((x: { status: string }) => x.status === 'answered')) {
    await api(page, 'POST', `/responses/${r.id}/adequacy`, { adequate: true, note: 'The action addresses the cause.' });
  }
  await clientUser(page, `priya.shah@${ABC}`);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Responses' }).click();
  await page.getByRole('button', { name: 'Send for sign-off 6' }).click();
  await expect(page.getByText('The remediation plan was sent for sign-off 6.')).toBeVisible();
  for (const [email, name] of [[`maria.lopez@${ABC}`, 'Maria Lopez'], [`robert.chen@${ABC}`, 'Robert Chen']]) {
    await clientUser(page, email);
    await page.goto('/responses');
    await sign(page, name, 'Sign-off 6');
    await expect(page.locator('.card').filter({ hasText: 'Sign-off 6' }).getByText(name === 'Robert Chen' ? 'Approved' : /signed by Maria Lopez/).first()).toBeVisible();
  }

  // Stage 8: final report (sign-off 7), public summary (sign-off 8), the client's acknowledgement
  await staff(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/report`);
  await page.getByRole('button', { name: 'Prepare final v1.1 and send for signature' }).click();
  await expect(page.getByText('Final report v1.1 prepared and sent to the Chief Auditor.')).toBeVisible();
  await page.getByLabel('Tool', { exact: true }).fill('ScreenRank ATS (résumé screening)');
  await page.getByLabel('Audit date').fill(new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10));
  await page.getByLabel('Data used').fill('Historical applicant data for New York roles, January to June.');
  await page.getByRole('button', { name: 'Add impact ratio' }).click();
  await page.getByLabel('category', { exact: true }).fill('Sex');
  await page.getByLabel('group', { exact: true }).fill('Female');
  await page.getByLabel('selection rate', { exact: true }).fill('0.41');
  await page.getByLabel('impact ratio', { exact: true }).fill('0.91');
  await page.getByRole('button', { name: 'Save public summary' }).click();
  await expect(page.getByText('Public summary saved.')).toBeVisible();
  await page.getByRole('button', { name: 'Send to the CAICO for sign-off 8' }).click();
  await expect(page.getByText('Public summary sent to the CAICO for sign-off 8.')).toBeVisible();
  await staff(page, 'chief@futran.demo');
  await page.goto(`/clients/${abc}/report`);
  await sign(page, 'Dana Whitfield', 'Sign-off 7');
  await expect(page.locator('.card').filter({ hasText: 'Sign-off 7' }).getByText('Approved').first()).toBeVisible();
  await shot(page, 'p6-final-report-signed');
  await clientUser(page, `maria.lopez@${ABC}`);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Report' }).click();
  await expect(page.getByText('Signing confirms you have received and read this report. It does not mean you agree with every finding.')).toBeVisible();
  await sign(page, 'Maria Lopez', 'Public summary');
  await page.locator('.card').filter({ hasText: 'Acknowledge the final report' }).getByLabel('Type your full name to sign', { exact: true }).fill('Maria Lopez');
  await page.getByRole('button', { name: 'Sign acknowledgement' }).click();
  await expect(page.getByText('Acknowledged', { exact: true })).toBeVisible();
  await shot(page, 'p6-client-report');

  // Stage 9: owners mark items done, the auditor verifies, the Chief Auditor closes
  await clientUser(page, `priya.shah@${ABC}`);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Remediation' }).click();
  await page.getByLabel('What was done', { exact: true }).fill('Bias audit commissioned; summary published on the careers page.');
  await page.getByRole('button', { name: 'Mark done' }).click();
  await expect(page.getByText('Marked done. Futran has been told.')).toBeVisible();
  for (const it of (await api(page, 'GET', `/clients/${abc}/remediation`)).items.filter((x: { can_act: boolean; status: string }) => x.can_act && x.status !== 'awaiting_verification')) {
    await api(page, 'POST', `/remediation/${it.id}/done`, { note: 'Done; evidence uploaded.' });
  }
  await clientUser(page, `maria.lopez@${ABC}`);
  for (const it of (await api(page, 'GET', `/clients/${abc}/remediation`)).items.filter((x: { can_act: boolean; status: string }) => x.can_act && x.status !== 'awaiting_verification')) {
    await api(page, 'POST', `/remediation/${it.id}/done`, { note: 'Done.' });
  }
  await staff(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${abc}/remediation`);
  await page.getByLabel('Verification note', { exact: true }).fill('Evidence reviewed and accepted.');
  await page.getByRole('button', { name: 'Verify, send to Chief Auditor' }).click();
  await expect(page.getByText('Verified and sent to the Chief Auditor.')).toBeVisible();
  for (const it of (await api(page, 'GET', `/clients/${abc}/remediation`)).items.filter((x: { can_verify: boolean }) => x.can_verify)) {
    await api(page, 'POST', `/remediation/${it.id}/verify`, { note: 'Evidence reviewed.' });
  }
  await shot(page, 'p6-remediation');
  await staff(page, 'chief@futran.demo');
  await page.goto(`/clients/${abc}/remediation`);
  const items = (await api(page, 'GET', `/clients/${abc}/remediation`)).items;
  for (const it of items.slice(1)) await api(page, 'POST', `/remediation/${it.id}/close`);
  await page.reload();
  await page.getByRole('button', { name: 'Close item' }).click();
  await expect(page.getByText('Every item is closed. The engagement is complete.')).toBeVisible();
  await page.goto(`/clients/${abc}`);
  await expect(page.getByText('Completed').first()).toBeVisible();
  await shot(page, 'p6-completed');
});
