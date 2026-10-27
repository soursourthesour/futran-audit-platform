---
title: Futran Audit Platform — change requests from 27 October 2026
tags: [futran, audit-platform, change-log]
source: futran_AI_audit_platform_fixes_10-27.docx
status: done except one item on hold
updated: 2026-10-27
---

# Change requests from 27 October 2026

Source document: `futran_AI_audit_platform_fixes_10-27.docx`. The document will grow over time. Each time it comes back, new items are added here and the status of existing items is updated, so this file is the record of what has been changed and what is still to do.

Tested as: Chief Auditor (staff side); Chief AI Compliance Officer with Client Admin rights (client side); an IT Director and a Contributor for additional views.

Status key: **Done**, **Partly done**, **Not started**, **On hold** (the document says not to act yet).

## 1. Staff side

### 1.1 New client set-up

| # | Request | Status | What was done |
|---|---|---|---|
| 1.1.1 | Company: address suggestions as you type | Done | Suggestions appear after 3 characters on the company street and each site's city, and fill street, city, state, postal code and country. Default source is OpenStreetMap (Photon), free and keyless; Google Places is used when `GOOGLE_PLACES_API_KEY` is set (`ADDRESS_AUTOCOMPLETE=photon\|google\|off`). Typing by hand still works if suggestions are unavailable. |
| 1.1.2 | Locations and laws: "Same as company address" for the headquarters | Done | Ticking it makes site 1 the headquarters at the company address and keeps it in step with the company details until unticked. |
| 1.1.3a | Conflict-of-interest line should name the position | Done | Reads, for example, "Dana Whitfield has confirmed no conflict of interest as Chief Auditor (Lead Auditor), Auditor and QA Reviewer". The roles confirmed are stored with the confirmation and audit-logged. |
| 1.1.3b | The same person appears several times | Done | Each person is listed once with all their roles: wizard review, client page team card, package summary, engagement letter and getting started guide. Adding a role clears their confirmation until they confirm again. |
| 1.1.3c | Each auditor signs their own conflict-of-interest confirmation | On hold | Not built, as instructed. Proposal: each team member gets a notice and a "Confirm independence" page showing the client, their roles and the declaration, and signs by typing their name (time, IP and text hash recorded, as with sign-offs). The wizard shows each person as requested, confirmed or declined, and submission waits until everyone has confirmed. |
| 1.1.4 | Phone country code finder | Done | Searchable country and dial-code picker next to the number, starting on the headquarters country. Numbers are checked, stored in international format (+1…) and shown formatted. Older numbers without a code still load. |

### 1.2 After the client is created

| # | Request | Status | What was done |
|---|---|---|---|
| 1.2.1 | Laws in scope as a table | Done | Columns: law or framework, jurisdiction, citation, effective date. Many cells show "—" because the law matrix has citations for about half the laws and no effective dates yet. |
| 1.2.2 | View and edit the documents at the client overview | Done | "Documents at this stage" lists the initiation package with View and Edit. The Chief Auditor can edit until a document is signed; a signed engagement letter shows that changes need a sign-off correction. Saving regenerates the PDF and Word files, is audit-logged, and tells the client's CAICO and Client Admin in the app. |
| 1.2.3 | Clickable engagement stages with who signed and when | Done | Each stage opens a detail panel: start and finish dates, each sign-off with preparer, signers and times, key events with who and when, open gate conditions for the current stage, and what is to come for future stages. Staff only. |

### 1.3 Outbox

| # | Request | Status | What was done |
|---|---|---|---|
| 1.3.1 | Larger message view that closes when you click away | Done | Messages open in a large pop-up (full screen on a phone) with clickable links and a "Copy link" button for invitations. Escape, clicking outside or Close shuts it. |

## 2. Client side

### 2.1 Getting started

| # | Request | Status | What was done |
|---|---|---|---|
| 2.1.1 | Download icons next to PDF and Word | Done | |
| 2.1.2 | Read the document inside "Review and sign" | Done | The engagement letter is shown above the signing fields, with PDF and Word links. |
| 2.1.3 | Remove the Read links beside the downloads on items 1–7 | Done | |
| 2.1.3.1 | Item 1: "Read and confirm" | Done | Opens the guide with "I have read this guide" at the end. |
| 2.1.3.2 | Item 2: reading inside "Review and sign" | Done | See 2.1.2. |
| 2.1.3.3 | Item 3: reading on the nominate screen | Done | People > Users has a "What each role does" section with the roles note. |
| 2.1.3.4 | Item 4: "Confirm departments", goes to the Departments tab | Done | Template downloads removed from the item. |
| 2.1.3.5 | Item 5: "Add employees", goes to the Users tab | Done | Template downloads removed from the item. |
| 2.1.3.6 | Item 6: employee data notice — every user acknowledges, only the CAICO edits and circulates by email | Done | Only the CAICO can edit. "Send to employees" emails the notice to everyone on the user list and completes the item. Each user with a login must read and acknowledge it at their next sign-in; a new version means acknowledging again. People > Users shows who has acknowledged. |
| 2.1.3.7 | Item 7 ("Describe your AI governance structure") | Done | Not in the document; only its Read link was removed. |

### 2.2 People

| # | Request | Status | What was done |
|---|---|---|---|
| 2.2.1 | Split People into Departments and Users | Done | Two tabs: People > Departments and People > Users. |
| 2.2.1a | Departments: template and CSV upload at the top; add, confirm, include, exclude; editable grid with bulk actions and a row menu | Done | Edit name, head and headcount in the cell; bulk include, exclude and delete; ⋯ menu (also on right-click). Delete is only possible during setup and while nothing refers to the department. |
| 2.2.1b | Users: edit employee details, sort and filter, editable grid with bulk actions and a row menu | Done | Sort by any column; filter by department, role, invitation status and data notice status; search. Bulk resend invitation, change department and remove; ⋯ menu with edit, resend, change role and remove. People with history are deactivated rather than deleted. |

### 2.3 Governance — attestation link

| # | Request | Status | What was done |
|---|---|---|---|
| 2.3.1 | Question 2: "Which AI tools and agents", with a list of agents | Done | Agents listed under their own heading (Microsoft 365 Copilot and Copilot Studio agents, ChatGPT agent and custom GPTs, Claude, Gemini, Salesforce Agentforce, ServiceNow AI agents, Zapier or Make, GitHub Copilot coding agent, in-house agents, other). Agents carry an "Agent" badge in the inventory and tracker. |
| 2.3.2 | Question 3: text box for "Something else" | Done | Required, up to 200 characters, shown in answers and exports. |
| 2.3.3 | Individual answers: editable grid with bulk actions and a row menu | Done | Filters, search, bulk mark reviewed, export CSV and remove (with a reason). Edits by the CAICO or DPO are logged with before and after and never change what the employee ticked. |

### 2.4 Attestation

| # | Request | Status | What was done |
|---|---|---|---|
| 2.4.1 | Employees with a login complete the attestation in the app | Done | "My AI attestation" page for every client user, with the form pre-filled with their name, email and department. Answers are matched on work email so nobody counts twice. |
| 2.4.2 | "Send attestation" button for the admin | Done | Client Admin and CAICO. Gives everyone who has accepted their invitation a line item, an in-app notice and an email; people who join later while the campaign is open get it automatically. |

## Also fixed in this round

- The engagement letter's address ran into "Dear …" on one line. The address and salutation are now separate paragraphs.
- The attestation screen now says the employee data notice must be sent first (it said "acknowledge").
- The notification bell is 44 px on a phone, the minimum touch size.

## Still to do

- 1.1.3c: each auditor signs their own conflict-of-interest confirmation (on hold until the go-ahead).
- Sign-off 1 (engagement letter) has no correction route, so a signed letter cannot be changed in the platform.
- The law matrix needs effective dates and the missing citations so the laws table is complete.
- An attestation answered through the staff link without an email cannot be matched to a user, so that person could be counted twice.
