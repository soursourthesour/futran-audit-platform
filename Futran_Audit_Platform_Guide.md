---
title: Futran Audit Platform — tester and operator guide
tags: [futran, ai-governance, audit-platform, guide, testing]
version: v1
updated: 2026-10-19
---

# Futran Audit Platform — tester and operator guide

This guide covers four things:

1. Installing the platform.
2. Running the demo.
3. Using it for a real audit.
4. Testing it.

Section 7 is a reference covering roles, sign-offs, rules and screen addresses.

> **Using this guide with Claude.** Add this file to a Claude chat or Project, then ask questions such as "how do I approve a new client?" or "why can't I send sign-off 5?".
>
> **Note for Claude:** answer from this guide. Name the screen, the button and the role needed. If the guide does not cover something, say so rather than guess. The platform's own messages, such as the "What's left in this stage" list on a client page, are the best source for why something is blocked.

---

## 1. What the platform does

The Futran Audit Platform runs Futran's AI governance audits. It covers everything from setting up a new client to closing the last remediation item. Futran staff and client staff each sign in to their own pages. Every client's data is kept apart, every action is checked against the person's role, and every change is recorded in an audit log that cannot be edited.

An audit (an "engagement") moves through nine stages. The platform moves to the next stage by itself once the current one is finished.

| Stage | Name | What happens | Finished when |
|---|---|---|---|
| 1 | Onboarding | A Futran auditor sets up the client in the wizard. The Chief Auditor approves it and sends the initiation package. The client's Chief AI Compliance Officer (CAICO) signs the engagement letter. | Sign-off 1 is signed by the CAICO and the Chief Auditor |
| 2 | Setup | The client adds departments and users. | Every department has a Department Compliance Lead and the department list is confirmed |
| 3 | Discovery | The client answers the governance request. Staff fill in the attestation form. Departments list their AI use cases. | The campaign is closed, governance is submitted and no use case is left as a draft |
| 4 | Client review | Departments, the DPO, the CAICO and the Executive Sponsor sign off the inventory. | Sign-offs 2, 3 and 4 are approved; the inventory is then locked |
| 5 | Fieldwork | Futran sets final tiers, assesses each AI system, requests evidence, scores risk and drafts findings. | Every high-risk use case maps to a system, each system is answered and scored, and every finding is submitted |
| 6 | Futran QA | The Chief Auditor approves findings and signs sign-off 5. The draft report is signed by Futran and released. | Sign-off 5 is approved and the client draft (v1.0) is released |
| 7 | Response | The client responds to each finding. Futran checks the responses are adequate. The client accepts the plan. | Sign-off 6 is approved |
| 8 | Final report | The Chief Auditor signs the final report. The client acknowledges it. Where NYC Local Law 144 applies, the CAICO approves the public summary. | Sign-off 7, the acknowledgement and (if needed) sign-off 8 are done |
| 9 | Remediation | Owners mark actions done, an auditor verifies them and the Chief Auditor closes them. | Every item is closed; the engagement is then completed |

---

## 2. Getting it running

### What you need

- A Windows laptop with **Python 3.11 or later** from python.org. Tick "Add python.exe to PATH" when installing.
- The file **Futran_Audit_Platform.zip**.

### Install (once)

1. Unzip the file into a folder, for example `Documents\Futran Audit Platform`.
2. Open the folder and double-click **`setup.bat`**.
   - It installs the platform, creates the database and loads the law matrix, question bank and templates. This takes a few minutes the first time.
   - When it asks for an administrator email, press **Enter** to skip it for the demo.
   - The database and uploaded files are kept in `%LOCALAPPDATA%\FutranAuditPlatform`, not in the folder.

### Start the demo

1. Close any other black Futran Audit Platform window.
2. Double-click **`demo.bat`** and press **Y**. This deletes the local database and loads the demo clients.
3. Wait about a minute for the line "Demo data loaded…". Your browser then opens at http://localhost:8000.
4. Keep the black window open while you work. Closing it stops the platform.

### Start it again later

Double-click **`run.bat`**. It opens the platform with the data you already have. Use `demo.bat` only when you want to wipe everything and start the demo fresh.

### On a Mac or Linux machine

Use a terminal in the unzipped folder:

```bash
python3 -m venv .venv && .venv/bin/pip install -e backend
cp .env.example .env                       # then set SECRET_KEY to a long random value
cd backend && cp ../.env .env && mkdir -p data
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.cli seed-reference
../.venv/bin/python -m app.cli reset-demo
../.venv/bin/uvicorn --factory app.main:create_app --port 8000
```

### If something goes wrong

| Problem | What to do |
|---|---|
| "Python 3.11 or later is required" | Install Python from python.org with "Add python.exe to PATH" ticked, then run `setup.bat` again. |
| Demo passwords don't work | The demo didn't load. Close every black platform window, run `demo.bat` again and wait for "Demo data loaded". |
| "The database is in use, so it could not be replaced" | Another platform window is still open. Close it and run `demo.bat` again. |
| Staff email refused on the sign-in page | Futran staff sign in at **/staff/login**; client users at **/login**. The message says which page to use. |
| The browser shows "can't reach this page" | The black window was closed. Start `run.bat` again. |
| You need a new admin login | Keep `run.bat` open, double-click `admin-link.bat`, enter the email and name, then open the printed link to set a password. |

---

## 3. Demo instructions

### Demo accounts

Every demo account uses the password **`Demo-Password-2026`**. No sign-in codes are asked for while the red **test mode** bar shows at the top.

Use a normal browser window for Futran staff and a private (InPrivate or Incognito) window for client users, so the two sign-ins don't clash.

| Sign-in page | Email | Who they are |
|---|---|---|
| http://localhost:8000/staff/login | chief@futran.demo | Dana Whitfield, Chief Auditor (approves engagements and findings, signs reports, closes remediation) |
| /staff/login | admin@futran.demo | Ada Brennan, Administrator (users, templates, reference data, outbox, audit log) |
| /staff/login | auditor1@futran.demo | Alex Moreno, Auditor (all four clients) |
| /staff/login | auditor2@futran.demo | Priyanka Rao, Auditor (Meridian and Futran internal only) |
| /staff/login | qa@futran.demo | Quinn Taylor, QA Reviewer |
| /staff/login | em@futran.demo | Elena Brooks, Engagement Manager |
| http://localhost:8000/login | maria.lopez@abccorp.example | ABC Corp, Chief AI Compliance Officer |
| /login | sam.okafor@abccorp.example | ABC Corp, Client Admin |
| /login | priya.shah@abccorp.example | ABC Corp, Department Compliance Lead, HR |
| /login | robert.chen@abccorp.example | ABC Corp, Executive Sponsor |
| /login | daniel.kim@abccorp.example | ABC Corp, Data Protection Officer |
| /login | katrin.vogel@meridian.example | Meridian GmbH, Chief AI Compliance Officer and Client Admin |
| /login | aarav.menon@meridian.example | Meridian GmbH, Department Compliance Lead, Engineering |
| /login | lena.fischer@meridian.example | Meridian GmbH, Department Compliance Lead, Data Science |

### What is in the demo

| Client | Where it stands | Good for showing |
|---|---|---|
| **ABC Corp** (New York, Chicago, remote staff) | Completed: all nine stages done | The finished audit: four AI systems, findings, the report in every version, responses, closed remediation, the LL144 public summary |
| **Meridian GmbH** (Berlin, Bangalore) | Stage 3, discovery | Running the attestation campaign and building the AI inventory live; the EU AI Act, GDPR and India's DPDP Act in scope |
| **Futran Solutions (internal)** | Stage 2, setup | A client still adding its users |
| **Northwind Logistics** | Waiting for the Chief Auditor's approval | Approving a new client and sending the initiation package |

### A 20-minute guided demo

**Part 1. Futran's view of a finished audit.** Sign in as `chief@futran.demo`.

1. **Dashboard.** Point out the four clients, the counters at the top and the filters (All, In progress, Completed, Drafts).
2. Open **ABC Corp**. The stage tracker shows all nine stages done. The **Work areas** card links to every part of the audit.
3. Open **AI systems in scope**, choose **SYS-001 ATS résumé screening**, then **View risk score**.
   - Inherent risk is 76, control maturity 2.25, residual risk 58.2 and the rating is **High**.
   - Two knock-out rules are triggered: no bias testing, and null-compliance risk High.
   - This is the worked example from the risk methodology.
4. **Findings**: six approved findings with their severity.
5. **Report**: every version from Draft v0.1 to Final v1.1. Download the **Final v1.1 PDF or Word** file. It contains the executive summary, findings table, system profiles, maturity scorecard, roadmap, laws in scope, declarations and appendices B and C.
6. **Remediation**: every action is verified and closed.

**Part 2. The client's view.** In a private window, sign in at `/login` as `maria.lopez@abccorp.example`.

1. The top menu shows only what the CAICO role allows.
2. **Report**: only the versions released to the client (v1.0 and v1.1). It also shows the acknowledgement and the approved public summary. The acknowledgement says that signing means the report was received and read, not that every finding is agreed.
3. **Responses** and **Remediation**: the same engagement from the client's side.
4. **Review**: the department sign-offs, sign-offs 3 and 4, and the locked inventory snapshot.

**Part 3. Things to do live.**

1. **Approve a new client.** As the Chief Auditor, open **Northwind Logistics** and choose **Review initiation package**.
   1. Preview the seven documents (engagement letter, roles note, CSV templates, data notice, getting-started guide, governance request).
   2. Tick the checklist and approve.
   3. Sign in as `admin@futran.demo` and open **Outbox** to see the invitation email sent to the client.
2. **Run discovery.** Sign in at `/login` as `katrin.vogel@meridian.example`.
   1. On **Getting started**, acknowledge the employee data notice.
   2. On **Attestation**, choose **Launch and get the staff link**, then **Copy staff link**.
   3. Open the link on your phone (or in another window) and answer as an employee. No sign-in is needed. Back on the tracker, the response appears.
3. **Live risk tiering.** Still as Katrin, open **AI inventory** and choose **Add use case**.
   - As you choose the data used and how the output affects people, the tier updates.
   - "Substantially assists or makes decisions about people" makes it **Tier 3**.
   - Tier 2 and 3 use cases need the named people who use them, with their work email.

---

## 4. Real-use instructions

### Before any real client data goes in

1. Run `setup.bat` and give **your own work email** when it asks for the administrator. Open the link it prints and set your password. Do not use `demo.bat` on a copy holding real data.
2. Open the `.env` file in the platform folder in Notepad and set:
   - `MFA_REQUIRED=true`. Everyone then sets up an authenticator app at their next sign-in and gets recovery codes.
   - `EMAIL_MODE=smtp` plus the `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM` values for the sending mailbox. For Microsoft 365 use `smtp.office365.com`, port 587.
   - `BASE_URL` set to the address people will use. Links in emails use it.
3. Restart with `run.bat`. The red test-mode bar disappears once both settings are on.
4. Optional: add `ANTHROPIC_API_KEY` to switch on **Reference data → Law updates**. Claude checks the law matrix against current sources and proposes changes for an administrator to accept or reject.

Hosting on a server (Render, later Azure) is described in `README.md`.

### Set up the Futran team

As the administrator, open **Users**. Add each Futran staff member with their role: Chief Auditor, Auditor, QA Reviewer, Engagement Manager, Legal/Compliance Reviewer or Admin. Each person gets an invitation email to set their password.

### Running an engagement, stage by stage

**Stage 1. Onboarding**

1. **Auditor.** Go to **Dashboard → New client** and complete the five wizard steps:
   1. **Company.**
   2. **Locations and laws.** Laws are suggested from the locations, and you tick the ones in scope.
   3. **Scope and team.** Period, frameworks, systems already known, departments, and the Futran team. Everyone on the team confirms they have no conflict of interest.
   4. **Client contacts.** The CAICO is required. DPO and Executive Sponsor can be marked "not appointed".
   5. **Review and submit.**
2. **Chief Auditor.** On the Dashboard the client shows as awaiting approval. Open it, choose **Review initiation package**, check or edit the documents, tick the checklist and approve. Invitations go to the CAICO and the Client Admin. Alternatively, return the draft with a comment.
3. **Client CAICO.**
   1. Accept the invitation: confirm details, set a password, set up the authenticator, accept the terms.
   2. On **Getting started**, work through the checklist and sign the engagement letter (sign-off 1).
   3. The Chief Auditor then signs it on the client page.

**Stage 2. Setup.** Done by the Client Admin, on **People**.

1. Add the departments and choose **Confirm the department list**.
2. Add users one at a time or import the user CSV from the initiation package. Each department in scope needs a **Department Compliance Lead**.
3. Name the DPO and Executive Sponsor, or mark them **Not appointed**. When they are not appointed, the CAICO signs in their place.

**Stage 3. Discovery**

1. **CAICO, on Governance.** Answer each item:
   - **In place**: give the names.
   - **Will constitute**: give a target date and an interim owner. This creates a commitment that is tracked through to remediation.
   - **Not applicable**: give a reason.

   Then submit and confirm the answers are accurate.
2. **CAICO, on Getting started and Attestation.** Acknowledge the employee data notice. Then launch the campaign, share the staff link, and choose **Close campaign** when enough people have answered.
3. **Contributors and Department Leads, on AI inventory.** Add each use case with its tool, purpose, data and impact. Tier 2 and 3 use cases list the people who use them; anyone without an account gets a confirmation link by email. Submit each use case to the Department Lead, who approves it or returns it.
4. **Futran.** Under **Document requests**, preview and send the document request email.

   **Client.** Upload documents under **Documents**, and pre-fill system answers under **AI systems**.

**Stage 4. Client review.** All of this happens on the client's **Review** page.

1. **Sign-off 2, for each department.** A Contributor or the CAICO prepares it and the Department Lead signs it. Every use case must be approved, and every named person must have confirmed or been marked unable to confirm, with a reason.
2. **Sign-off 3, data categories.** A Department Lead or the CAICO prepares it. The DPO signs first, then the CAICO.
3. **Sign-off 4, management representation.** The CAICO prepares it. The DPO signs first, then the Executive Sponsor.
4. When sign-off 4 is approved, the inventory snapshot locks. To change the inventory afterwards, the CAICO corrects sign-off 4, which is possible up to fieldwork and re-locks a new snapshot version.

**Stage 5. Fieldwork.** Done by Futran.

1. **Auditor, on AI inventory and tiers.** Open each use case and set the **final tier** with a rationale, plus the AEDT decision for NYC hiring tools. The use case's fieldwork page holds evidence requests, the null-compliance check and findings.
2. **Auditor, on AI systems in scope.** Map every Tier 3 use case to a system; the Engagement Manager approves new systems. Then open each system's **assessment**:
   - Answer and verify the questions, naming the person who gave each answer.
   - Some "No" answers create draft findings, which you confirm or dismiss.
3. **Lead Auditor (the Chief Auditor on the team), on the risk score.** Set the final score for each of the eight domains. A change of more than 1 from the proposed score needs a rationale.
4. **Auditor, on Findings.** Draft findings with severity, controls, description, recommended action and owner, then submit them.

**Stage 6. Futran QA**

1. **Chief Auditor, on Findings.** Approve or return each finding. A finding the Chief Auditor wrote or edited goes to the QA Reviewer instead.
2. **Auditor.** When every finding is approved, choose **Send sign-off 5 to the Chief Auditor**. When the Chief signs it, the findings, tiers and scores are locked.
3. **Auditor, on Report.**
   1. Write the executive summary. **Greatest strengths observed** is required.
   2. Add roadmap items.
   3. Choose **Generate lead review v0.2**.
4. **Lead Auditor, Engagement Manager and (if assigned) QA Reviewer.** Each signs their declaration on the Report page. One person cannot sign two.
5. **Engagement Manager or Auditor.** Choose **Release client draft v1.0**. If the report changed after it was signed, generate v0.2 again and sign it again first.

**Stage 7. Response**

1. **CAICO and Department Leads, on Responses.** For each finding choose agree, partially agree or disagree, then give the planned action, the owner and the due date. The CAICO answers findings that cover the whole organization. Finding text cannot be edited by the client.
2. **Auditor, on Responses.** Mark each response **Adequate** or **Ask for changes**, with a note.
3. **Client, on Responses.** A Department Lead (or the CAICO) chooses **Send for sign-off 6**. The CAICO signs first, then the Executive Sponsor.

**Stage 8. Final report**

1. **Auditor, on Report.** Choose **Prepare final v1.1 and send for signature**. The Chief Auditor signs sign-off 7.
2. **Auditor, if NYC Local Law 144 (or another law needing a public summary) is in scope.** Fill in the public summary: tool, audit date, data used, impact ratios. Then choose **Send to the CAICO for sign-off 8**. The CAICO approves it on the client **Report** page.
3. **CAICO or Executive Sponsor, on Report.** Acknowledge the final report. Choose the remediation commitment, or list the findings you dispute.

**Stage 9. Remediation**

1. **Item owners (or their Department Lead or the CAICO), on Remediation.** Mark each item in progress, then **done**, with a note.
2. **Auditor.** Verify each item with a note.
3. **Chief Auditor.** Close each item. The person who verified an item cannot close it. When the last item is closed, the engagement is **completed**.

Governance commitments from stage 3 appear in Remediation alongside the response actions.

### Where to look when something is blocked

- The client page (Futran) shows **What's left in this stage**. When a stage is complete it offers **Move to stage N**.
- Every sign-off panel shows who has signed and who is next. A signer can **Return** it with a comment, and the person who prepared it can **Withdraw** it.
- The **bell** at the top shows what is waiting for you.

---

## 5. Test instructions

### How to test

- Run the demo (section 2), use the accounts in section 3, and keep a normal window for staff and a private window for clients.
- In test mode, emails are not sent. They wait in **Outbox**, which the Admin and Chief Auditor can open. Invitation links in the Outbox can be opened directly.
- Record **Pass** or **Fail** and a note for each test. For a failure, take a screenshot and note the time, the account used and the page address.
- To start again from clean data, run `demo.bat`.

### Test script

| ID | Area | Steps | Expected result | Pass/Fail | Notes |
|---|---|---|---|---|---|
| T01 | Staff sign-in | Go to /staff/login and sign in as chief@futran.demo | The Dashboard lists ABC Corp (completed), Meridian GmbH (stage 3), Futran Solutions internal (stage 2) and Northwind Logistics (awaiting approval) | | |
| T02 | Wrong sign-in page | Go to /login and sign in as chief@futran.demo | Refused with "This is the client sign-in. Futran staff use the staff sign-in page." | | |
| T03 | Wrong password | Sign in with a wrong password | A plain error; nothing says whether the email exists | | |
| T04 | Client sign-in | In a private window, sign in at /login as maria.lopez@abccorp.example | The client menu appears (Getting started, People, Governance, Attestation, AI inventory, Review, AI systems, Documents, Report, Responses, Remediation) | | |
| T05 | Risk score | As the Chief: ABC Corp → AI systems in scope → SYS-001 → View risk score | Inherent 76, maturity 2.25, residual 58.2, rating High, two knock-outs triggered | | |
| T06 | Report files | As the Chief: ABC Corp → Report → Final v1.1 PDF and Word | Both open. They contain the findings table, maturity scorecard, roadmap, declarations, and Appendices B and C | | |
| T07 | Client sees only released versions | As Maria: Report | Only Client v1.0 and Final v1.1 are listed; no draft or lead review versions | | |
| T08 | Client can't reach staff pages | As Maria, go to http://localhost:8000/audits | Sent back to Getting started, the client home page | | |
| T09 | Unassigned auditor | Copy the ABC Corp page address as the Chief. Sign in as auditor2@futran.demo and open it | ABC Corp is not on auditor2's Dashboard, and the address is refused | | |
| T10 | Other client's data | Sign in at /login as katrin.vogel@meridian.example and open Report | Shows Meridian only, with nothing released yet; nothing from ABC Corp anywhere | | |
| T11 | Approve a new client | As the Chief: Northwind Logistics → Review initiation package → preview the documents → tick the checklist → approve | Status changes to awaiting the client; invitations are created | | |
| T12 | Invitation | As admin@futran.demo: Outbox → open the Northwind invitation → open its link in a private window | The invitation steps (confirm details, set a password, accept the terms) work, and Hannah lands on Getting started | | |
| T13 | Engagement letter | As Hannah, sign the engagement letter on Getting started. As the Chief, sign sign-off 1 on the Northwind page | Northwind moves to stage 2, Setup | | |
| T14 | Setup | As Hannah, on People: add two departments, confirm the list, add a Department Compliance Lead to each | The client page shows stage 3, Discovery | | |
| T15 | Attestation on a phone | As Katrin: Getting started → acknowledge the notice. Then Attestation → Launch and get the staff link → open the link on a phone and submit | The form fits the phone screen with no sideways scrolling, and the response appears on the tracker | | |
| T16 | Live tiering | As Katrin: AI inventory → Add use case → choose personal data and "Substantially assists or makes decisions" | Tier 3 · High-risk is shown, and named users with an oversight role are required to submit | | |
| T17 | No self-approval | As aarav.menon@meridian.example, add and submit a use case in Engineering, then try to approve it | Not allowed: someone else must approve it | | |
| T18 | Governance commitment | As Katrin: Governance → choose Will constitute for one item, with a date and an owner | A commitment is created and listed | | |
| T19 | Notifications | Sign in as any user with pending items | The bell shows a count, and opening an item marks it read | | |
| T20 | Audit log | As the Chief: Audit log | Your own actions from the earlier tests are listed with time and person | | |
| T21 | Settings | As admin@futran.demo: Settings | The current configuration is shown read-only, including test mode | | |
| T22 | Full journey (optional, 1–2 hours) | Create a brand-new client in the wizard and take it through all nine stages, using the Outbox links to sign in as each client user | Every stage completes and the engagement ends as completed. Note anything unclear or blocked | | |

### Reporting an issue

For each problem, send:

- the test ID (or "other");
- the account used;
- the page address;
- what you did;
- what you expected;
- what happened, with a screenshot.

---

## 6. Glossary

| Term | Meaning |
|---|---|
| Engagement | One audit of one client for one period |
| CAICO | Chief AI Compliance Officer: the client's lead contact, who signs most client sign-offs |
| Use case | One way a department uses an AI tool, such as résumé screening with ScreenRank |
| Tier | Risk tier of a use case. 1 is low; 2 means sensitive data or personal accounts; 3 means it affects decisions about people. The client proposes it and Futran sets the final tier |
| AI system | An AI product or model assessed in depth, covering one or more Tier 3 (or selected Tier 2) use cases |
| Attestation | The short form staff fill in, without signing in, to say which AI tools they use |
| Named user | A person named on a Tier 2 or 3 use case, who confirms their use by email |
| Commitment | A client promise from the governance request (for example, "create an AI policy by March"), tracked to closure |
| Sign-off | A typed-name electronic signature on a step. Each records who signed, when, from where, and the hash of what was signed |
| Inherent / residual risk | Risk before controls (0–100) and after control maturity is applied |
| Knock-out | A rule that forces a rating of at least High, such as no bias testing on a system that affects people |
| LL144 | New York City Local Law 144: bias audits and a public summary for automated hiring tools |
| Test mode | The red bar. Sign-in codes are off and emails go to the Outbox. Demo data can only be loaded in test mode, and real client data must not be entered |

## 7. Reference

### Roles

| Role | Side | Main powers |
|---|---|---|
| Admin | Futran | Users, templates, reference data (law matrix), outbox, audit log, settings. Makes no audit judgements |
| Chief Auditor | Futran | Approves new engagements, approves findings, signs sign-offs 1, 5 and 7, closes remediation; Lead Auditor when on the team |
| Auditor | Futran | Builds the engagement, does the fieldwork, drafts findings and the report, reviews responses, verifies remediation (assigned engagements only) |
| QA Reviewer | Futran | Approves findings the Chief Auditor wrote or edited; signs the quality declaration |
| Engagement Manager | Futran | Approves systems added in fieldwork, signs the manager declaration, can release the client draft |
| Legal/Compliance Reviewer | Futran | Read access to assigned engagements |
| Chief AI Compliance Officer (CAICO) | Client | Governance, attestation, inventory approvals, sign-offs 3, 4, 6 and 8, responses, report acknowledgement |
| Client Admin | Client | Departments and users |
| Executive Sponsor | Client | Approves sign-offs 4 and 6 (the CAICO stands in if none); can acknowledge the report |
| Data Protection Officer | Client | Reviews sign-offs 3 and 4 (the CAICO stands in if none) |
| Department Compliance Lead | Client | Approves use cases and signs sign-off 2 for their department, prepares sign-off 6, responds to their department's findings |
| Contributor | Client | Adds use cases in their department and fills in requested information |

### Sign-offs

| # | What | Prepared by | Signed by, in order |
|---|---|---|---|
| 1 | Engagement letter and scope | Futran auditor | CAICO and Chief Auditor |
| 2 | Department inventory (one per department) | Contributor or CAICO | Department Compliance Lead |
| 3 | Data categories for Tier 2–3 use cases | Department Lead or CAICO | DPO, then CAICO |
| 4 | Management representation | CAICO | DPO, then Executive Sponsor |
| 5 | Final risk tiers and findings | Auditor | Chief Auditor |
| 6 | Management responses and remediation plan | Department Lead or CAICO | CAICO, then Executive Sponsor |
| 7 | Final report | Auditor | Chief Auditor |
| 8 | Public summary (LL144) | Auditor | CAICO |

### Rules the platform enforces

- Nobody approves or signs something they prepared. If the only possible signer is the person preparing it, the platform refuses and names the missing role.
- A sign-off is checked again when signed. If something changed since it was sent, such as a new draft finding, the signer is told to return it.
- The inventory is locked by sign-off 4. Corrections are possible up to fieldwork; from stage 6 it is fixed.
- Findings, final tiers and scores are locked by sign-off 5.
- The report versions are Draft v0.1, Lead review v0.2, Client v1.0 and Final v1.1. The client sees only v1.0 and v1.1. Futran's declarations are signed on v0.2, and the executive summary and roadmap are fixed once v1.0 is released.
- Clients see findings and scores only from the draft report onwards, and never Futran's drafts, notes or staff IP addresses.
- A "disagree" response records the reason and creates no remediation item.
- v1 handles one engagement per client. Annual reviews are planned for a later phase.

### Screen addresses

| Screen | Futran address | Client address |
|---|---|---|
| Dashboard | /audits | — |
| New client wizard | /audits/new | — |
| Client page | /clients/{client} | /start (Getting started) |
| Governance | /clients/{client}/governance | /governance |
| Attestation | /clients/{client}/attestation | /attestation (staff form: /attest/{link}) |
| AI inventory | /clients/{client}/inventory | /inventory |
| Inventory review (sign-offs 2–4) | — | /review |
| AI systems | /clients/{client}/systems, /systems/{id}/assess, /systems/{id}/score | /systems |
| Documents | /clients/{client}/documents | /documents |
| Findings | /clients/{client}/findings | (shown in Responses) |
| Report | /clients/{client}/report | /report |
| Responses | /clients/{client}/responses | /responses |
| Remediation | /clients/{client}/remediation | /remediation |
| People | /clients/{client}/people | /users |
| Admin | /admin/users, /admin/templates, /admin/reference, /admin/audit-log, /admin/outbox, /admin/settings | — |
