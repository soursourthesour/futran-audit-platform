import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page, email: string) {
  await page.goto('/staff/login');
  await page.getByLabel('Work email', { exact: true }).fill(email);
  await page.getByLabel('Password').fill('Demo-Password-2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/audits$/);
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login/);
}

test('auditor sets up a client, the Chief Auditor approves and the client signs the engagement letter', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'auditor1@futran.demo');
  await page.getByRole('link', { name: 'New client' }).click();
  await expect(page).toHaveURL(/\/setup\/company$/);

  // Step 1
  await page.getByLabel('Legal name *').fill('ABC Corp Inc.');
  await page.getByLabel('Trading name', { exact: true }).fill('ABC Corp');
  await page.getByLabel('Industry *').selectOption('staffing');
  await page.getByLabel('250–999').check();
  await page.getByLabel('Number of AI systems in scope *').fill('2');
  await page.getByLabel('Street *').fill('1 Main Street');
  await page.getByLabel('City *').fill('New York');
  await page.getByLabel('State / region *').fill('NY');
  await page.getByLabel('Postal code *').fill('10001');
  await page.getByLabel('Country *').selectOption('US');
  await page.getByLabel('Primary countries of operation *').selectOption('US');
  await page.getByLabel('Why the client is engaging Futran', { exact: true }).fill('ABC uses AI to screen and rank job applicants in New York and Chicago.');
  await expect(page.getByRole('status')).toContainText('Saved');
  await page.getByRole('button', { name: 'Next: locations and laws' }).click();

  // Step 2
  await page.getByRole('button', { name: 'Add location' }).click();
  await page.getByLabel('Name of site 1').fill('Headquarters');
  await page.getByLabel('State or region of site 1').selectOption('US-NY');
  await page.getByLabel('City of site 1').fill('New York');
  await page.getByRole('button', { name: 'Add location' }).click();
  await page.getByLabel('Name of site 2').fill('Chicago office');
  await page.getByLabel('State or region of site 2').selectOption('US-IL');
  await page.getByLabel('City of site 2').fill('Chicago');
  await expect(page.getByRole('cell', { name: 'NYC Local Law 144', exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('cell', { name: /^NY Civil Rights Law §52-c/ })).toBeVisible();
  await expect(page.getByLabel('Include NYC Local Law 144')).toBeChecked();
  await page.screenshot({ path: 'screenshots/p3-wizard-step2.png', fullPage: true });
  await page.getByRole('button', { name: 'Next: scope and team' }).click();

  // Step 3
  await page.getByLabel('Initial AI governance assessment').check();
  await page.getByLabel('Audit period start *').fill('2026-01-01');
  await page.getByLabel('Audit period end *').fill('2026-12-31');
  await page.getByLabel('Engagement start *').fill('2026-11-02');
  await page.getByLabel('Target date for the draft report *').fill('2027-01-15');
  await page.getByLabel('Target date for the final report *').fill('2027-02-15');
  await page.getByLabel('HR and recruiting').check();
  await page.getByLabel('AI systems in scope *').fill('HireScore\nResume parser');
  await page.getByLabel('Business processes in scope *').fill('Candidate screening and ranking');
  await page.getByLabel('Production').check();
  await page.getByLabel('Geographic scope *').fill('United States: New York and Illinois');
  await page.getByLabel('NIST AI RMF 1.0').check();
  await page.getByLabel('Chief Auditor (Lead Auditor) *').selectOption({ label: 'Chris Chief' });
  await page.getByLabel('Engagement Manager *').selectOption({ label: 'Erin Manager' });
  for (const name of ['Chris Chief', 'Erin Manager', 'Alex Auditor']) await page.getByLabel(`${name} has confirmed no conflict of interest`).check();
  await page.getByRole('button', { name: 'Next: client contacts' }).click();

  // Step 4
  await page.getByLabel('Full name *').first().fill('Maria Lopez');
  await page.getByLabel('Job title *').fill('Chief AI Compliance Officer');
  await page.getByLabel('Work email *').first().fill('maria.lopez@abccorp.example');
  await page.getByLabel(/^Not appointed: Maria Lopez covers these duties/).check();
  await page.getByRole('button', { name: 'Next: review and submit' }).click();

  await page.getByRole('button', { name: 'Submit for approval' }).click();
  await expect(page).toHaveURL(/\/audits$/);
  await expect(page.getByText('ABC Corp was sent to the Chief Auditor for approval.')).toBeVisible();

  await signOut(page);

  // Chief Auditor reviews and approves
  await signIn(page, 'chief@futran.demo');
  await expect(page.getByRole('cell', { name: /ABC Corp/ })).toBeVisible();
  await page.screenshot({ path: 'screenshots/p3-dashboard.png', fullPage: true });
  await page.getByRole('table').getByRole('link', { name: 'ABC Corp' }).click();
  await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Preview' }).first().click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: /Engagement letter/ }).first()).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click();
  await page.getByLabel('Scope, laws and departments are appropriate for this client', { exact: true }).check();
  await page.getByLabel('The team has no conflict of interest', { exact: true }).check();
  await expect(page.getByLabel('I have previewed the engagement letter', { exact: true })).toBeChecked();
  await page.screenshot({ path: 'screenshots/p3-package-review.png', fullPage: true });
  await page.getByRole('button', { name: 'Approve and send' }).click();
  await expect(page.getByText('Approved and sent.')).toBeVisible();
  await expect(page.getByText('Sign-off 1 (engagement letter and scope) is not approved yet.')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p3-client-page.png', fullPage: true });

  // The CAICO's invitation is in the outbox (test mode)
  const outbox = await (await page.request.get('/api/v1/admin/outbox')).json();
  const invite = outbox.find((m: { to: string[]; template_key: string }) => m.to[0] === 'maria.lopez@abccorp.example' && m.template_key === 'client_invitation');
  const link = /\/invite\/[A-Za-z0-9_-]+/.exec(invite.body_html)![0];
  await signOut(page);

  // Client accepts, reads the guide and signs
  await page.goto(link);
  await expect(page.getByRole('heading', { name: 'Confirm your details' })).toBeVisible();
  await expect(page.getByText('Chief AI Compliance Officer').first()).toBeVisible();
  await page.screenshot({ path: 'screenshots/v03-accept-invitation.png' });
  await page.getByRole('button', { name: 'These are my details' }).click();
  await page.getByLabel('New password', { exact: true }).fill('Password12345');
  await page.getByLabel('Confirm password', { exact: true }).fill('Password12345');
  await page.getByRole('button', { name: 'Set password and continue' }).click();
  await expect(page.getByText(/too common or appears in breached-password lists/)).toBeVisible();
  await page.getByLabel('New password', { exact: true }).fill('Client-Password-2026');
  await page.getByLabel('Confirm password', { exact: true }).fill('Client-Password-2026');
  await page.getByRole('button', { name: 'Set password and continue' }).click();
  await expect(page.getByRole('heading', { name: 'Before you start' })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/I accept the terms of use/).check();
  await page.getByRole('button', { name: 'Accept and continue' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to your AI governance assessment' })).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Read and confirm' }).click();
  await expect(page.getByRole('region', { name: 'Read the getting started guide' })).toBeVisible();
  await page.getByRole('button', { name: 'I have read this guide' }).click();
  await expect(page.getByText('1 of 7 complete')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p3-client-checklist.png', fullPage: true });
  await page.getByRole('button', { name: 'Review and sign' }).click();
  await expect(page.getByRole('region', { name: 'Engagement letter and scope' })).toBeVisible();
  await page.getByLabel('Type your full name to sign', { exact: true }).fill('Maria Lopez');
  await page.getByLabel(/^I have read the document and agree/).check();
  await page.getByRole('button', { name: 'Sign', exact: true }).click();
  await expect(page.getByText('2 of 7 complete')).toBeVisible();

  // Client sets up departments and users (Phase 4)
  await page.getByRole('link', { name: 'People' }).click();
  for (const d of ['HR and recruiting', 'Engineering and IT']) {
    await page.getByLabel('New department', { exact: true }).fill(d);
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByText(d, { exact: true })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Confirm the department list' }).click();
  await expect(page.getByText('Department list confirmed.')).toBeVisible();
  await page.getByRole('navigation', { name: 'People sections' }).getByRole('link', { name: /^Users/ }).click();
  const csv = 'first_name,last_name,email,job_title,department,role,location\nPriya,Shah,priya.shah@abccorp.example,Head of HR,HR and recruiting,Department Compliance Lead,New York NY\nRaj,Iyer,raj.iyer@abccorp.example,CTO,Engineering and IT,Department Compliance Lead,Chicago IL\nLee,Park,lee.park@abccorp.example,Counsel,Legal,Contributor,Chicago IL\n';
  await page.getByLabel('User list CSV').setInputFiles({ name: 'user_list.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await expect(page.getByText("Row 4: Department 'Legal' is not in the department list.")).toBeVisible();
  await page.getByRole('button', { name: 'Import 2 ready rows' }).click();
  await expect(page.getByText('Imported 2 users.')).toBeVisible();
  await page.getByLabel('Not appointed', { exact: true }).first().click();
  await expect(page.getByText('Not appointed: the Chief AI Compliance Officer covers this role').first()).toBeVisible();
  await page.screenshot({ path: 'screenshots/p4-people.png', fullPage: true });

  // Governance structure request (Phase 4)
  await page.getByRole('link', { name: 'Governance' }).click();
  await expect(page.getByRole('heading', { name: 'AI governance structure' })).toBeVisible();
  const committee = page.getByRole('group', { name: 'Answer for AI governance committee' });
  await committee.getByRole('button', { name: 'In place' }).click();
  await page.getByLabel('Chair', { exact: true }).fill('Maria Lopez');
  await page.getByLabel('Member 1', { exact: true }).fill('Raj Iyer');
  await page.getByRole('button', { name: 'Save answer' }).click();
  await expect(page.getByText('In place · chair Maria Lopez, Raj Iyer')).toBeVisible();
  const bias = page.getByRole('group', { name: 'Answer for Bias and fairness review committee' });
  await bias.getByRole('button', { name: 'Will constitute' }).click();
  await page.getByLabel('Target date *').fill('2027-03-31');
  await page.getByLabel('Interim owner *').fill('Priya Shah');
  await page.getByRole('button', { name: 'Save answer' }).click();
  await expect(page.getByText('Constitute bias and fairness review committee')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p4-governance.png', fullPage: true });

  // Attestation campaign (Phase 4): acknowledge the notice, launch, staff answer on a phone
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Getting started' }).click();
  await page.getByRole('button', { name: 'Review and send' }).click();
  await page.getByRole('button', { name: 'Send to employees' }).click();
  await page.getByRole('button', { name: 'Send to employees' }).click();
  await expect(page.getByText(/Version 1 of the notice was emailed to/)).toBeVisible();
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attestation' }).click();
  await page.getByRole('button', { name: 'Launch and get the staff link' }).click();
  await expect(page.getByRole('button', { name: 'Copy staff link' })).toBeVisible();
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const tracker = await (await page.request.get(`/api/v1/clients/${me.organization.id}/attestation`)).json();
  const phone = await page.context().browser()!.newContext({ viewport: { width: 390, height: 844 }, baseURL: page.url().split('/attestation')[0] });
  const p2 = await phone.newPage();
  for (const [i, name] of ['Sam Lee', 'Ana Diaz', 'Tom Reyes'].entries()) {
    await p2.goto(tracker.campaign.link);
    await p2.getByLabel('Your name', { exact: true }).fill(name);
    await p2.getByLabel('Department', { exact: true }).selectOption({ label: 'HR and recruiting' });
    await p2.getByRole('button', { name: 'Next' }).click();
    await p2.getByLabel('ChatGPT').check();
    await p2.getByLabel('Personal, free').check();
    if (i === 0) await p2.screenshot({ path: 'screenshots/p4-phone-attestation.png', fullPage: true });
    await p2.getByRole('button', { name: 'Next: what you use it for' }).click();
    await p2.getByLabel('Writing and editing').check();
    await p2.getByLabel('Client or customer data').check();
    await p2.getByRole('button', { name: 'Next', exact: true }).click();
    await p2.getByLabel('I have read the AI use policy', { exact: true }).check();
    await p2.getByRole('button', { name: 'Submit' }).click();
    await expect(p2.getByRole('heading', { name: 'Thank you' })).toBeVisible();
  }
  await phone.close();
  await page.reload();
  await expect(page.getByRole('cell', { name: 'ChatGPT · personal, free', exact: true }).first()).toBeVisible();
  await page.screenshot({ path: 'screenshots/p4-attestation-tracker.png', fullPage: true });

  // AI inventory (Phase 4): a Tier 3 use case with a named user, then the auditor sets the final tier
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'AI inventory' }).click();
  await page.getByRole('link', { name: 'Add use case' }).click();
  await page.getByLabel('Use case name *').fill('Résumé screening for NYC roles');
  await page.getByLabel('Department *').selectOption({ label: 'HR and recruiting' });
  await page.getByLabel(/OpenAI ChatGPT/).check();
  await page.getByLabel('Purpose *').fill('Recruiters paste CVs and ask ChatGPT to rank applicants before interviews.');
  await page.getByLabel('Personal information (PII)').check();
  await page.getByLabel(/Substantially assists or makes decisions/).check();
  await expect(page.getByText('Tier 3 · High-risk')).toBeVisible();
  await page.getByLabel('Role', { exact: true }).first().fill('Recruiter');
  await page.getByLabel('Headcount', { exact: true }).fill('4');
  await page.getByRole('button', { name: 'Add named user' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Lee Park');
  await page.getByLabel('Work email', { exact: true }).fill('lee.park@abccorp.example');
  await page.getByLabel('Human oversight role *').fill('Reviews the ranked list before interviews');
  await page.screenshot({ path: 'screenshots/p4-use-case.png', fullPage: true });
  await page.getByRole('button', { name: 'Submit to Department Lead' }).click();
  await expect(page.getByRole('link', { name: 'Résumé screening for NYC roles' })).toBeVisible();
  await page.screenshot({ path: 'screenshots/p4-inventory.png', fullPage: true });
  await signOut(page);
  await signIn(page, 'auditor1@futran.demo');
  await page.getByRole('table').getByRole('link', { name: 'ABC Corp' }).click();
  await page.getByRole('link', { name: 'AI inventory and tiers' }).click();
  await page.getByRole('link', { name: 'Résumé screening for NYC roles' }).click();
  await page.getByLabel('Rationale', { exact: true }).fill('Ranks applicants for NYC roles; likely an AEDT under Local Law 144.');
  await page.getByLabel('AEDT determination (NYC employment use)', { exact: true }).selectOption('in_scope');
  await page.getByRole('button', { name: 'Save final tier' }).click();
  await expect(page.getByText('Final tier (Futran)')).toBeVisible();

  // Phase 5: the Tier 3 use case becomes a system in scope, with the Engagement Manager's approval
  const clientId = page.url().match(/\/clients\/([^/]+)\//)![1];
  await page.goto(`/clients/${clientId}/systems`);
  await expect(page.getByText('1 Tier 3 use case is not mapped to a system')).toBeVisible();
  await page.getByRole('button', { name: 'Map use case' }).click();
  await page.getByLabel('Built by', { exact: true }).selectOption({ label: 'Vendor' });
  await page.getByRole('button', { name: 'Send for approval' }).click();
  await expect(page.getByText('Sent to the Engagement Manager for approval.')).toBeVisible();
  await signOut(page);
  await signIn(page, 'manager@futran.demo');
  await page.goto(`/clients/${clientId}/systems`);
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('System added to the scope.')).toBeVisible();
  await signOut(page);

  // The auditor works through the assessment; a "No" raises a draft finding
  await signIn(page, 'auditor1@futran.demo');
  await page.goto(`/clients/${clientId}/systems`);
  await page.getByRole('table').getByRole('link', { name: 'Résumé screening for NYC roles' }).click();
  const card = (code: string) => page.locator(`[id="q-${code}"]`);
  await card('3.1.01').getByLabel('Answer', { exact: true }).fill('ScreenRank for Recruiting');
  await card('3.1.01').getByRole('button', { name: 'Save' }).click();
  await expect(card('3.1.01').getByText('Saved')).toBeVisible();
  await page.getByRole('navigation', { name: 'Sections' }).getByRole('button', { name: /§3.3 / }).click();
  await card('3.3.02').getByLabel(/Human-assisted/).check();
  await card('3.3.02').getByLabel('Source person', { exact: true }).fill('Priya Shah');
  await card('3.3.02').getByLabel('Source title', { exact: true }).fill('Head of HR');
  await card('3.3.02').getByLabel('Verified', { exact: true }).check();
  await card('3.3.02').getByRole('button', { name: 'Save' }).click();
  await expect(card('3.3.02').getByText('Verified', { exact: true }).first()).toBeVisible();
  await page.getByRole('navigation', { name: 'Sections' }).getByRole('button', { name: /§6.2 / }).click();
  await card('6.2.01').getByLabel('No', { exact: true }).check();
  await card('6.2.01').getByRole('button', { name: 'Save' }).click();
  await expect(card('6.2.01').getByText(/Draft finding F-001/)).toBeVisible();
  await page.screenshot({ path: 'screenshots/p5-assessment.png', fullPage: true });
  await page.getByRole('link', { name: 'View risk score' }).click();
  await expect(page.getByRole('heading', { name: /Risk score:/ })).toBeVisible();
  await expect(page.getByText('Triggered · at least High')).toBeVisible();
  await page.screenshot({ path: 'screenshots/p5-score.png', fullPage: true });
  await page.goto(`/clients/${clientId}/systems`);
  await expect(page.getByRole('cell', { name: /SYS-003/ })).toBeVisible();
  await page.screenshot({ path: 'screenshots/p5-systems-register.png', fullPage: true });

  // Document request register: preview the email, send it
  await page.goto(`/clients/${clientId}/documents`);
  await page.getByRole('button', { name: 'Preview and send request' }).click();
  await expect(page.getByText('To: maria.lopez@abccorp.example')).toBeVisible();
  await page.getByRole('button', { name: /Send request/ }).click();
  await expect(page.getByText(/Request sent\./)).toBeVisible();
  await page.screenshot({ path: 'screenshots/p5-documents.png', fullPage: true });
});

