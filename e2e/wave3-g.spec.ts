import { mkdirSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

/* Wave 3 WS-G (spec §21 F1, F5, F10; screen 25) on the late world (start-server.sh … late): the Chief Auditor turns AI
   on for Meridian with the client's consent; the auditor runs the copilot on the credit risk model's documents and
   accepts, rejects and routes suggestions; the completeness review and "Ask the copilot"; the AI interaction log; the
   client's "Explain this question"; obligations on a law record; and a customer questionnaire at phone width.
   The model is the in-process demonstration model (test mode, no key). */

const PW = 'Demo-Password-2026';
const MERIDIAN = 'meridian.example';
const ABC = 'abccorp.example';
const SHOTS = process.env.WSG_SHOTS || '/mnt/user-data/outputs/wave3/ws-g';
mkdirSync(SHOTS, { recursive: true });
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { abc: string; meridian: string };

const STANDARD = `Model Risk Management Standard
2.1 All credit models are developed and deployed through the MLOps pipeline in Azure Machine Learning with staged approval gates (development, UAT, production).
2.2 Feature engineering is documented in the feature catalogue, including the source and derivation of each input feature.
2.4 Hyperparameter tuning uses Bayesian optimisation over 200 trials, and every trial is recorded in the experiment log.
4.1 Validation is performed by the model owner within the Data Science team before each release.
`;
const MONITORING = `Credit scorecard monitoring report
Drift monitoring for the credit scorecard runs monthly against the development sample.
`;

async function signIn(page: Page, email: string, staff: boolean) {
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

async function api(page: Page, method: 'GET' | 'POST' | 'PUT' | 'PATCH', path: string, data?: unknown, multipart?: Record<string, any>) {
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const r = await page.request.fetch(`/api/v1${path}`, { method, data, multipart, headers: { 'X-CSRF-Token': me.csrf_token } });
  expect(r.status(), `${method} ${path}: ${await r.text()}`).toBe(200);
  return r.json();
}

async function noSidewaysScroll(page: Page, what: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${what} scrolls sideways`).toBeLessThanOrEqual(1);
}

async function shoot(page: Page, name: string, phone = true) {
  for (const [w, h] of (phone ? [[1440, 1000], [375, 812]] : [[1440, 1000]]) as [number, number][]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(300);
    if (w === 375) await noSidewaysScroll(page, `${name} at ${w}px`);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

test.describe.serial('AI copilot, obligations and questionnaires', () => {
  let systemId = '';
  let engagementId = '';

  test('the Chief Auditor turns AI on for Meridian with the consent note', async ({ page }) => {
    await signIn(page, 'chief@futran.demo', true);
    const { meridian } = late();
    await page.goto(`/clients/${meridian}`);
    const card = page.getByRole('heading', { name: 'AI features' }).locator('xpath=ancestor::section[contains(@class,"card")][1]');
    await expect(card.getByText('Off', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Turn on AI features' }).click();
    await card.getByRole('button', { name: 'Turn on', exact: true }).click();
    await expect(card.getByText(/Record where the client consented/)).toBeVisible();  // the consent note is required
    await card.getByLabel('Where the client consented', { exact: true }).fill('Engagement letter clause 11.3, signed by Katrin Vogel.');
    await card.getByRole('button', { name: 'Turn on', exact: true }).click();
    await expect(card.getByText('On', { exact: true })).toBeVisible();
    await shoot(page, 'client-page-ai-switch', false);
    const page_ = await api(page, 'GET', `/clients/${meridian}`);
    engagementId = page_.engagement.id;
    const systems = await api(page, 'GET', `/clients/${meridian}/systems`);
    systemId = (systems.systems ?? systems).find((s: { name: string }) => s.name === 'Credit risk scoring model').id;
  });

  test('screen 25: the auditor reviews copilot suggestions with their citations', async ({ page }) => {
    await signIn(page, 'auditor1@futran.demo', true);
    await api(page, 'PATCH', `/systems/${systemId}`, { built_by: 'in_house' });
    for (const [name, text] of [['Model_Risk_Management_Standard_v3.txt', STANDARD], ['Credit_Model_Monitoring_Report_Q3.txt', MONITORING]]) {
      await api(page, 'POST', `/systems/${systemId}/evidence`, undefined, { file: { name, mimeType: 'text/plain', buffer: Buffer.from(text) } });
    }
    await api(page, 'PUT', `/systems/${systemId}/responses/8.2.05`, { status: 'answered', value: 'weekly', source_person_name: 'Lena Fischer', source_person_title: 'Head of Data Science' });
    await page.goto(`/systems/${systemId}/assess`);
    await page.getByRole('button', { name: /§6\.1 Model development/ }).click();
    const panel = page.locator('.cp-panel');
    await expect(panel.getByText('Copilot suggestions: §6.1 Model development process')).toBeVisible();
    await panel.getByRole('button', { name: 'Suggest answers from documents' }).click();
    const method = page.getByRole('article', { name: 'Suggestion for 6.1.01' });
    await expect(method.getByText('MLOps pipeline', { exact: true })).toBeVisible();
    await expect(method.getByText(/All credit models are developed and deployed through the MLOps pipeline/)).toBeVisible();
    await expect(method.getByText(/Model_Risk_Management_Standard_v3\.txt · page 1/)).toBeVisible();
    await expect(page.getByRole('article', { name: 'Suggestion for 6.1.07' }).getByText('Unsupported')).toBeVisible();
    await shoot(page, 'screen25-copilot-suggestions');
    // reject one with a reason, accept all high-confidence, route an unsupported one to the interview list
    const tuning = page.getByRole('article', { name: 'Suggestion for 6.1.05' });
    await tuning.getByRole('button', { name: 'Reject' }).click();
    await page.getByRole('dialog').getByLabel('Reason', { exact: true }).fill('Confirmed in interview: tuning changed in version 4.2.');
    await page.getByRole('dialog').getByRole('button', { name: 'Reject' }).click();
    await expect(tuning.getByText(/Rejected/)).toBeVisible();
    await panel.getByRole('button', { name: /Accept all high-confidence \(\d+\)/ }).click();
    await expect(panel.getByText(/high-confidence suggestions? accepted/)).toBeVisible();
    await expect(method.getByText(/Accepted · /)).toBeVisible();
    await page.getByRole('article', { name: 'Suggestion for 6.1.07' }).getByRole('button', { name: 'Add to interview list' }).click();
    await expect(page.getByRole('article', { name: 'Suggestion for 6.1.07' }).getByText('On the interview list')).toBeVisible();
    // the accepted answer is the auditor's own, unverified, with the citation
    await expect(page.getByText(/Copilot citation: Model_Risk_Management_Standard_v3\.txt/).first()).toBeVisible();
  });

  test('completeness review, ask the copilot, and the AI log', async ({ page }) => {
    await signIn(page, 'auditor1@futran.demo', true);
    await page.goto(`/systems/${systemId}/assess`);
    await page.getByRole('button', { name: /Copilot review/ }).click();
    await page.getByRole('button', { name: 'Run completeness review' }).click();
    await expect(page.getByText('8.2.05 · contradiction')).toBeVisible();
    await expect(page.getByText(/Drift monitoring for the credit scorecard runs monthly/).first()).toBeVisible();
    await page.getByLabel('Question', { exact: true }).fill('Who validates the credit scorecard before release, and is that validation independent?');
    await page.getByRole('button', { name: 'Ask a question' }).click();
    await expect(page.getByText(/Validation is performed by the model owner/).first()).toBeVisible();
    await shoot(page, 'screen25-completeness-and-ask');
    await expect(page.getByRole('link', { name: 'view AI interaction log' })).toHaveCount(0);  // the auditor does not read the log
    await signIn(page, 'chief@futran.demo', true);
    await page.goto(`/engagements/${engagementId}/ai-log`);
    await expect(page.getByRole('heading', { name: 'AI interaction log' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Document pre-fill' }).first()).toBeVisible();
    await shoot(page, 'ai-interaction-log', false);
  });

  test('the client sees "Explain this question" and never the copilot', async ({ page }) => {
    await signIn(page, `katrin.vogel@${MERIDIAN}`, false);
    await page.goto(`/systems/${systemId}`);
    await page.getByRole('button', { name: /§7\.1/ }).click();
    await expect(page.locator('.cp-panel')).toHaveCount(0);
    await page.getByRole('button', { name: 'Explain this question' }).nth(1).click();
    await expect(page.getByRole('note')).toContainText('This question asks about');
    await expect(page.getByRole('note')).toContainText('Human oversight');
    await shoot(page, 'client-explain-this-question');
  });

  test('obligations: extract on the law record and approve', async ({ page }) => {
    await signIn(page, 'chief@futran.demo', true);
    const laws = await api(page, 'GET', '/reg/laws');
    const ll144 = laws.groups.flatMap((g: { laws: { id: string; short_name: string }[] }) => g.laws).find((l: { short_name: string }) => /144/.test(l.short_name));
    await page.goto(`/reg/${ll144.id}`);
    await page.getByRole('button', { name: 'Extract obligations' }).click();
    await expect(page.getByText(/obligations? proposed/)).toBeVisible();
    const grid = page.getByRole('table', { name: 'Proposed obligations' });
    await grid.getByRole('button', { name: /Actions for|More actions|⋯/ }).first().click();
    await page.getByRole('menuitem', { name: 'Approve' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click();
    await expect(page.getByText(/Approved by Cara|Approved by/).first()).toBeVisible();
    await shoot(page, 'law-record-obligations', false);
  });

  test('a customer questionnaire at phone width', async ({ page }) => {
    await signIn(page, 'chief@futran.demo', true);
    const abcPage = await api(page, 'GET', `/clients/${late().abc}`);
    await api(page, 'PUT', `/engagements/${abcPage.engagement.id}/ai`, { enabled: true, consent_note: 'Engagement letter clause 9.2.' });
    await signIn(page, `maria.lopez@${ABC}`, false);
    await api(page, 'POST', '/answer-library', { question: 'Do you maintain an inventory of AI systems?', answer: 'Yes. ABC Corp keeps an AI system register with an owner and a risk tier for every system.' });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/questionnaires');
    await noSidewaysScroll(page, 'questionnaires');
    await page.getByRole('button', { name: 'Upload a questionnaire' }).click();
    const xlsx = Buffer.from(readFileSync(`${__dirname}/fixtures/ai-ddq.xlsx`));
    await page.getByLabel('Questionnaire file', { exact: true }).setInputFiles({ name: 'Northwind_AI_DDQ.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: xlsx });
    await page.getByLabel('Customer', { exact: true }).fill('Northwind Bank');
    await page.getByRole('button', { name: 'Upload and find questions' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Northwind');
    await page.getByRole('button', { name: 'Draft answers' }).click();
    await expect(page.getByText('Draft to review').first()).toBeVisible();
    await noSidewaysScroll(page, 'questionnaire detail');
    await page.getByRole('button', { name: 'Approve', exact: true }).first().click();
    await expect(page.getByText('Approved', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: 'Export XLSX' })).toBeVisible();
    await shoot(page, 'client-questionnaire');
  });
});
