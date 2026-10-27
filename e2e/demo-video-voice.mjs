// Records the captioned walkthrough with timing for a voice-over.
// Usage: node demo-video-voice.mjs <base-url> <out-dir> <durations.json>
// Same scenes and captions as demo-video.mjs. Each caption and title card is held for at least its narration
// clip length plus 0.6 s (durations.json maps narration id to seconds), and the start time of each one,
// measured from the start of the recording, is written to <out-dir>/captions.json for muxing.
// The narration text for each id is in demo-voiceover-script.md.
// The server must have fresh demo data (python -m app.cli reset-demo).
import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

const base = process.argv[2] || 'http://127.0.0.1:8797';
const outDir = process.argv[3] || './video';
const PW = 'Demo-Password-2026';
const W = 1440, H = 900;
const failures = [];
const durations = process.argv[4] ? JSON.parse(readFileSync(process.argv[4], 'utf8')) : {};
const GAP = 600;
// [narration id, caption prefix]; title cards are keyed 'card:<title>'.
const NARRATION = [
  ["k01", "card:Futran Audit Platform"],
  ["k02", "card:Part 1 · Futran staff"],
  ["n01", "Futran staff sign in on their own page."],
  ["n02", "The Dashboard shows every engagement"],
  ["n03", "Recent activity across all clients"],
  ["n04", "The Clients page lists each client"],
  ["n05", "Each client has a page with the nine-stage tracker."],
  ["n06", "Locations decide which laws apply."],
  ["n07", "Client contacts and the Futran team"],
  ["n08", "Work areas link to every part of the audit."],
  ["n09", "Stage 3 · Governance structure."],
  ["n10", "Stage 3 · Employee attestation."],
  ["n11", "Stage 3 · AI inventory."],
  ["n12", "Stage 5 · Fieldwork on a high-risk use case"],
  ["n13", "Stage 5 · AI systems in scope."],
  ["n14", "The assessment follows the Futran audit template"],
  ["n15", "A \"No\" on a key control"],
  ["n16", "The risk score: inherent risk 76"],
  ["n17", "The Lead Auditor sets the final maturity score"],
  ["n18", "The document request register"],
  ["n19", "Stage 6 · Findings."],
  ["n20", "The report goes from Draft v0.1"],
  ["n21", "Futran's declarations are signed"],
  ["n22", "Sign-off 7, the final report"],
  ["n23", "Stage 7 · Management responses."],
  ["n24", "Stage 9 · Remediation."],
  ["n25", "Administration · Reference data"],
  ["n26", "Document templates, such as"],
  ["n27", "The audit log records every action"],
  ["k03", "card:Part 2 · The client's view"],
  ["n28", "Client users sign in here."],
  ["n29", "Getting started: the initiation checklist"],
  ["n30", "Stage 4 · Client review."],
  ["n31", "The client sees only the released versions"],
  ["n32", "The LL144 public summary"],
  ["n33", "The client's responses to each finding."],
  ["n34", "The client's remediation tracker"],
  ["k04", "card:Part 3 · Doing the work"],
  ["n35", "Back to the Chief Auditor."],
  ["n36", "The initiation package:"],
  ["n37", "The Chief Auditor confirms the checklist"],
  ["n38", "Approved. Northwind now waits"],
  ["n39", "Meridian GmbH is in stage 3"],
  ["n40", "First, she acknowledges"],
  ["n41", "She launches the attestation campaign"],
  ["n42", "The tracker shows responses by department"],
  ["n43", "An employee opens the link"],
  ["n44", "Which AI tools, and on what kind of account."],
  ["n45", "What they use it for"],
  ["n46", "Submitted. The answer is recorded"],
  ["n47", "On the tracker, department counts appear"],
  ["n48", "Adding an AI use case."],
  ["n49", "A personal ChatGPT account"],
  ["n50", "Because it affects decisions about people"],
  ["k05", "card:What comes next"],
];
const timeline = [];
function narration(key) { return NARRATION.find(([, k]) => key.startsWith(k)); }
function hold(key, ms) {
  const n = narration(key);
  if (!n) return { id: null, ms };
  const d = durations[n[0]];
  return { id: n[0], ms: d ? Math.max(ms, Math.ceil(d * 1000) + GAP) : ms };
}

const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
const context = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: outDir, size: { width: W, height: H } } });
const page = await context.newPage();
const t0 = Date.now();
page.setDefaultTimeout(8000);

let part = '';
async function overlay() {
  await page.evaluate(([p]) => {
    if (!document.getElementById('demo-cap')) {
      const cap = document.createElement('div');
      cap.id = 'demo-cap';
      cap.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:78%;z-index:2147483647;background:rgba(15,30,60,.93);color:#fff;font:500 21px/1.45 "IBM Plex Sans",Arial,sans-serif;padding:14px 22px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.25);text-align:center;pointer-events:none;transition:opacity .25s';
      document.body.appendChild(cap);
      const tag = document.createElement('div');
      tag.id = 'demo-part';
      tag.style.cssText = 'position:fixed;right:18px;top:46px;z-index:2147483647;background:#0e7490;color:#fff;font:600 13px/1 Arial,sans-serif;padding:8px 12px;border-radius:999px;pointer-events:none;letter-spacing:.02em';
      document.body.appendChild(tag);
    }
    document.getElementById('demo-part').textContent = p;
    document.getElementById('demo-part').style.display = p ? 'block' : 'none';
  }, [part]);
}
async function cap(text, ms = 4200) {
  const h = text ? hold(text, ms) : { id: null, ms };
  try {
    await overlay();
    await page.evaluate((t) => { const c = document.getElementById('demo-cap'); c.textContent = t; c.style.opacity = t ? '1' : '0'; }, text);
    if (h.id) timeline.push({ id: h.id, t: (Date.now() - t0) / 1000, hold: h.ms / 1000, text });
  } catch (e) { failures.push(`caption: ${text.slice(0, 40)}: ${e.message.split('\n')[0]}`); }
  await page.waitForTimeout(h.ms);
}
async function card(title, sub, ms = 4500) {
  const h = hold('card:' + title, ms);
  ms = h.ms;
  await page.evaluate(([t, s]) => {
    document.getElementById('demo-card')?.remove();
    const d = document.createElement('div');
    d.id = 'demo-card';
    d.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:linear-gradient(135deg,#0f1e3c,#1b3a6b);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:"IBM Plex Sans",Arial,sans-serif;text-align:center;padding:40px';
    d.innerHTML = `<div style="font-size:46px;font-weight:600;margin-bottom:18px">${t}</div><div style="font-size:22px;opacity:.85;max-width:900px;line-height:1.5">${s}</div>`;
    document.body.appendChild(d);
  }, [title, sub]);
  if (h.id) timeline.push({ id: h.id, t: (Date.now() - t0) / 1000, hold: ms / 1000, text: title });
  await page.waitForTimeout(ms);
  await page.evaluate(() => document.getElementById('demo-card')?.remove());
}
async function step(name, fn) {
  try { await fn(); } catch (e) { failures.push(`${name}: ${e.message.split('\n')[0]}`); }
}
async function go(path) { await page.goto(base + path); await page.waitForLoadState('networkidle'); await page.waitForTimeout(600); }
async function scroll(px, steps = 6) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, px / steps); await page.waitForTimeout(140); } await page.waitForTimeout(500); }
async function top() { await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await page.waitForTimeout(600); }
async function type(locator, text) { await locator.click(); await locator.pressSequentially(text, { delay: 35 }); }
async function signIn(portal, email, label) {
  await page.context().clearCookies();
  await go(portal);
  await cap(label, 2500);
  await type(page.getByLabel('Work email'), email);
  await type(page.getByLabel('Password'), PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL((u) => !u.pathname.includes('login'));
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(700);
}
const engagements = async () => (await (await page.request.get(base + '/api/v1/engagements?filter=all&q=')).json()).rows;

// ---------------------------------------------------------------- intro
await go('/staff/login');
await card('Futran Audit Platform', 'AI governance audits, from onboarding a client to verified remediation, in nine stages.<br><br>Demo walkthrough · about 10 minutes');

// ---------------------------------------------------------------- part 1: Futran staff
part = 'Part 1 · Futran staff view';
await card('Part 1 · Futran staff', 'The Chief Auditor reviews ABC Corp, an audit taken through all nine stages.', 3500);
await step('staff sign-in', async () => {
  await signIn('/staff/login', 'chief@futran.demo', 'Futran staff sign in on their own page. Client users have a separate sign-in. This demo runs in test mode, so no sign-in codes are asked for.');
});
let abc, northwind;
await step('dashboard', async () => {
  const rows = await engagements();
  abc = rows.find((r) => r.client_name.includes('ABC') && r.status === 'completed')?.client_id;
  northwind = rows.find((r) => r.client_name.includes('Northwind'))?.client_id;
  await cap('The Dashboard shows every engagement you can see: in progress, completed, awaiting approval and awaiting the client.', 4500);
  await page.getByRole('tab', { name: /Completed/ }).click(); await page.waitForTimeout(1200);
  await page.getByRole('tab', { name: /All/ }).click();
  await cap('Recent activity across all clients runs down the right-hand side. Auditors only see the clients they are assigned to.', 3800);
});
await step('clients page', async () => {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Clients' }).click();
  await page.waitForLoadState('networkidle');
  await cap('The Clients page lists each client with its headquarters, sites, people and where its current engagement stands.', 4200);
});
await step('client page', async () => {
  await go(`/clients/${abc}`);
  await cap('Each client has a page with the nine-stage tracker. ABC Corp has completed every stage.', 4000);
  await page.getByRole('tab', { name: 'Locations and laws' }).click(); await page.waitForTimeout(600);
  await cap('Locations decide which laws apply. New York brings in NYC Local Law 144 for AI hiring tools.', 4200);
  await page.getByRole('tab', { name: 'Contacts and users' }).click(); await page.waitForTimeout(600);
  await cap('Client contacts and the Futran team, with the role each person holds.', 3200);
  await page.getByRole('tab', { name: 'Overview' }).click(); await page.waitForTimeout(500);
  await scroll(500);
  await cap('Work areas link to every part of the audit. We will go through them in order.', 3500);
});
await step('governance', async () => {
  await go(`/clients/${abc}/governance`);
  await cap('Stage 3 · Governance structure. The client says which AI governance roles and documents are in place, planned or not applicable. Planned items become tracked commitments.', 5200);
  await scroll(700);
});
await step('attestation', async () => {
  await go(`/clients/${abc}/attestation`);
  await cap('Stage 3 · Employee attestation. Staff answer a short phone form, with no account needed, saying which AI tools they use and with what data.', 5000);
  await scroll(500);
});
await step('inventory', async () => {
  await go(`/clients/${abc}/inventory`);
  await cap('Stage 3 · AI inventory. Each department lists its AI use cases. The platform proposes a risk tier as they type, and Futran sets the final tier.', 5000);
  const link = page.getByRole('link', { name: /Résumé screening for NYC roles/ }).first();
  await link.click(); await page.waitForLoadState('networkidle'); await page.waitForTimeout(600);
  await cap('Stage 5 · Fieldwork on a high-risk use case: final tier with rationale, the NYC hiring-tool decision, evidence requests and draft findings.', 5000);
  await scroll(800);
});
let sys1;
await step('systems', async () => {
  await go(`/clients/${abc}/systems`);
  await cap('Stage 5 · AI systems in scope. Each high-risk use case maps to a system that is assessed in depth and scored.', 4500);
  const sys = await (await page.request.get(`${base}/api/v1/clients/${abc}/systems`)).json();
  sys1 = (sys.systems || sys).find((s) => s.reference_id === 'SYS-001')?.id;
  await go(`/systems/${sys1}/assess`);
  await cap('The assessment follows the Futran audit template section by section. Each answer records who gave it and can carry evidence.', 4800);
  await scroll(900);
  await cap('A "No" on a key control, such as bias testing, raises a draft finding automatically for the auditor to confirm or dismiss.', 4300);
});
await step('score', async () => {
  await go(`/systems/${sys1}/score`);
  await cap('The risk score: inherent risk 76, control maturity 2.25, residual risk 58.2. Two knock-out rules force a rating of at least High.', 5200);
  await scroll(700);
  await cap('The Lead Auditor sets the final maturity score for each of the eight domains, with a rationale when it moves far from the proposal.', 4500);
});
await step('documents', async () => {
  await go(`/clients/${abc}/documents`);
  await cap('The document request register: what was requested from the client, when it is due, what arrived, with chasing and escalation.', 4500);
});
await step('findings', async () => {
  await go(`/clients/${abc}/findings`);
  await cap('Stage 6 · Findings. The Chief Auditor approves each one. Findings the Chief wrote go to the QA Reviewer instead. Sign-off 5 then locks findings and scores.', 5500);
  await scroll(500);
});
await step('report', async () => {
  await go(`/clients/${abc}/report`);
  await cap('The report goes from Draft v0.1 to Lead review v0.2, Client v1.0 and Final v1.1, each downloadable as Word and PDF.', 4800);
  await scroll(900);
  await cap('Futran\'s declarations are signed on the lead review version. The client draft cannot be released until they are signed.', 4300);
  await scroll(900);
  await cap('Sign-off 7, the final report, signed by the Chief Auditor. The NYC LL144 public summary is approved by the client as sign-off 8.', 4800);
});
await step('responses', async () => {
  await go(`/clients/${abc}/responses`);
  await cap('Stage 7 · Management responses. The client answers each finding with an action, owner and due date. Futran checks each response is adequate.', 5000);
  await scroll(600);
});
await step('remediation', async () => {
  await go(`/clients/${abc}/remediation`);
  await cap('Stage 9 · Remediation. Owners mark actions done, an auditor verifies, and the Chief Auditor closes. When the last item closes, the audit is complete.', 5200);
});
await step('admin', async () => {
  await go('/admin/reference');
  await cap('Administration · Reference data: the global law matrix with versions, jurisdictions, and Claude-assisted law updates that an administrator accepts or rejects.', 5000);
  await go('/admin/templates');
  await cap('Document templates, such as the engagement letter and the report, are edited here. Each save is a new version.', 4000);
  await go('/admin/audit-log');
  await cap('The audit log records every action: who, what and when. It cannot be edited.', 3800);
});

// ---------------------------------------------------------------- part 2: client view
part = 'Part 2 · Client view';
await page.waitForLoadState('networkidle'); await page.waitForTimeout(800);
await card('Part 2 · The client\'s view', 'Maria Lopez, ABC Corp\'s Chief AI Compliance Officer, sees only her own organization and only what has been released to her.', 4000);
await step('client sign-in', async () => {
  await signIn('/login', 'maria.lopez@abccorp.example', 'Client users sign in here. Employees answering the attestation do not need an account.');
  await cap('Getting started: the initiation checklist, with the engagement letter the client signed (sign-off 1).', 4000);
});
await step('client review', async () => {
  await go('/review');
  await cap('Stage 4 · Client review. Each department signs off its inventory, then the data categories and the management representation. The inventory then locks.', 5000);
  await scroll(700);
});
await step('client report', async () => {
  await go('/report');
  await cap('The client sees only the released versions, v1.0 and v1.1. Signing the acknowledgement means the report was received and read, not that every finding is agreed.', 5500);
  await scroll(700);
  await cap('The LL144 public summary with impact ratios, approved by the client before it is published.', 4000);
});
await step('client responses', async () => {
  await go('/responses');
  await cap('The client\'s responses to each finding. Finding text is Futran\'s and cannot be edited by the client.', 4200);
  await go('/remediation');
  await cap('The client\'s remediation tracker: their actions and governance commitments, each verified by Futran.', 4000);
});

// ---------------------------------------------------------------- part 3: live actions
part = 'Part 3 · Live actions';
await card('Part 3 · Doing the work', 'Approving a new client, then running discovery for Meridian GmbH in Berlin and Bangalore.', 3800);
await step('approve northwind', async () => {
  await signIn('/staff/login', 'chief@futran.demo', 'Back to the Chief Auditor. Northwind Logistics has been drafted by an auditor and is waiting for approval.');
  await go(`/clients/${northwind}/setup/submit`);
  await cap('The initiation package: engagement letter, roles note, user and department templates, data notice, getting-started guide and governance request, all generated from the wizard.', 5500);
  await scroll(600);
  await page.getByLabel('Scope, laws and departments are appropriate for this client', { exact: true }).check(); await page.waitForTimeout(400);
  await page.getByLabel('The team has no conflict of interest', { exact: true }).check(); await page.waitForTimeout(400);
  await page.getByLabel('I have previewed the engagement letter', { exact: true }).check(); await page.waitForTimeout(400);
  await cap('The Chief Auditor confirms the checklist and approves. The client is invited by email.', 3000);
  await page.getByRole('button', { name: 'Approve and send' }).click();
  await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500);
  await cap('Approved. Northwind now waits for its Chief AI Compliance Officer to accept the invitation and sign the engagement letter.', 4200);
});
let attestLink;
await step('meridian notice and campaign', async () => {
  await signIn('/login', 'katrin.vogel@meridian.example', 'Meridian GmbH is in stage 3, discovery. Its Chief AI Compliance Officer signs in.');
  const ack = page.getByRole('button', { name: 'Acknowledge' }).first();
  if (await ack.isVisible().catch(() => false)) {
    await cap('First, she acknowledges the employee data notice from the initiation package.', 3000);
    await ack.click(); await page.waitForTimeout(1200);
  }
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attestation', exact: true }).click();
  await page.waitForLoadState('networkidle');
  await cap('She launches the attestation campaign and gets a link to share with staff.', 3200);
  await page.getByRole('button', { name: 'Launch and get the staff link' }).click();
  await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500);
  const me = await (await page.request.get(base + '/api/v1/auth/me')).json();
  const t = await (await page.request.get(`${base}/api/v1/clients/${me.organization.id}/attestation`)).json();
  attestLink = t.campaign.link;
  await cap('The tracker shows responses by department as they arrive.', 2800);
});
await step('attestation form', async () => {
  await page.goto(base + attestLink); await page.waitForLoadState('networkidle');
  await cap('An employee opens the link, usually on a phone. No account and four short steps; the page is built for a phone screen.', 3600);
  await type(page.getByLabel('Your name', { exact: true }), 'Mira Iyer');
  await page.getByLabel('Department', { exact: true }).selectOption({ label: 'Engineering' });
  await page.getByRole('button', { name: 'Next' }).click(); await page.waitForTimeout(700);
  await page.getByLabel('ChatGPT', { exact: true }).check(); await page.getByLabel('Personal, free').check();
  await cap('Which AI tools, and on what kind of account.', 2600);
  await page.getByRole('button', { name: 'Next: what you use it for' }).click(); await page.waitForTimeout(700);
  await page.getByLabel('Writing and editing').check(); await page.getByLabel('Client or customer data').check();
  await cap('What they use it for, and what data goes in.', 2600);
  await page.getByRole('button', { name: 'Next', exact: true }).click(); await page.waitForTimeout(700);
  await page.getByLabel('I have read the AI use policy', { exact: true }).check();
  await page.getByRole('button', { name: 'Submit' }).click(); await page.waitForTimeout(1200);
  await cap('Submitted. The answer is recorded against the department straight away.', 3000);
});
await step('use case tiering', async () => {
  await go('/attestation');
  await cap('On the tracker, department counts appear once at least three people have answered, so no one can be singled out.', 4200);
  await go('/inventory/new');
  await cap('Adding an AI use case. The proposed risk tier updates as the form is filled in.', 3500);
  await type(page.getByLabel('Use case name *'), 'Credit limit recommendations');
  await page.getByLabel('Department *').selectOption({ index: 1 });
  const tool = page.locator('label.check').filter({ hasText: /ChatGPT|Copilot/ }).first();
  if (await tool.isVisible().catch(() => false)) await tool.click();
  await type(page.getByLabel('Purpose *'), 'Suggests credit limits for new business customers.');
  await page.getByLabel('Personal information (PII)').check(); await page.waitForTimeout(900);
  await top();
  await cap('A personal ChatGPT account, or personal data going into the tool, makes it Tier 2. The proposed tier is on the right.', 3800);
  await scroll(600);
  await page.getByLabel(/Substantially assists or makes decisions/).check(); await page.waitForTimeout(900);
  await top();
  await cap('Because it affects decisions about people, it becomes Tier 3: high risk, assessed in depth, with named users and their oversight role.', 5200);
});

// ---------------------------------------------------------------- close
part = '';
await cap('', 300);
await card('What comes next', 'Department sign-offs, Futran fieldwork and scoring, findings, the report, the client\'s responses and remediation, exactly as shown for ABC Corp.<br><br>Futran Audit Platform · v1', 5500);

const recorded = (Date.now() - t0) / 1000;
await context.close();
await browser.close();
writeFileSync(`${outDir}/captions.json`, JSON.stringify({ recorded, timeline }, null, 1));
const missing = NARRATION.map(([id]) => id).filter((id) => !timeline.some((x) => x.id === id));
console.log(JSON.stringify({ failures, captions: timeline.length, missing }, null, 1));
