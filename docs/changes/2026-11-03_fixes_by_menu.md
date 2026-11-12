---
title: Futran AI audit platform fixes 11-03, by menu
tags: [futran, audit-platform, change-request]
source: "futran AI audit platform fixes 11-03.docx" (regrouped 10 November 2026)
updated: 2026-11-12
---

# Futran AI audit platform fixes 11-03, by menu

Your 11-03 notes, rearranged under the new menu groups. Each screen shows where it sat before, what you asked for, and whether it was done. Screens you haven't commented on yet say so, so you can see what is left to look at.

Status: **Done** = made and tested. **To test** = you marked it Test. **Yours** = not a build item. **Open** = decided or deferred; still to settle. **No notes yet** = nothing said about this screen.

Updated 12 November 2026 with the 10 November feedback (marked "10 Nov") and Release 2 (marked "Release 2"). Full change logs in the platform folder: docs/changes/2026-11-03_platform_fixes.md, docs/changes/2026-11-10_feedback.md and docs/changes/2026-11-12_release2_sales_and_gaps.md.

# FUTRAN SIDE

## Whole menu

### Forms and templates folder

*New (10 Nov)*

- (10 Nov) All forms and templates in separate folders, one client and one Futran, labelled by section with subfolders. **[Done]** "Forms and templates/Client" and "Forms and templates/Futran", each with a subfolder per menu and screen and a README listing every file and its use. Answer keys and Futran-only templates are only in the Futran folder.

### Menu grouping

*Was: one long row of tabs*

- Tabs need better grouping. Regulatory master takes you to the law library, and Refresh and review are part of that. Roles and committees have no tab. Give the law library its own tab and group the other tabs. **[Done]** Five menus: Home and work, Law library, Business, Assurance, Administration. Regulatory master is now Law library; Roles and committees has its own entry. On phones the menus fold into Menu.

## Home and work

### Admin home

*Was: Admin home (top menu)*

- (10 Nov) The dashboard in Home and work should show the same information; the actual dashboard is on Dashboard. Change that. **[Done]** This home now shows the Dashboard's KPIs, engagement table and recent activity below its own lists, filtered to what you could already see.

### QA queue

*Was: QA queue (top menu)*

- (10 Nov) The dashboard in Home and work should show the same information; the actual dashboard is on Dashboard. Change that. **[Done]** This home now shows the Dashboard's KPIs, engagement table and recent activity below its own lists, filtered to what you could already see.

### My work

*Was: My work (top menu)*

- (10 Nov) The dashboard in Home and work should show the same information; the actual dashboard is on Dashboard. Change that. **[Done]** This home now shows the Dashboard's KPIs, engagement table and recent activity below its own lists, filtered to what you could already see.

### Dashboard

*Was: Dashboard (top menu)*

- (10 Nov) Homes should show the dashboard. **[Done]** The Dashboard menu entry is gone; its content is on every Futran home, and the Chief Auditor has a new Chief Auditor home. The old address opens your home.

### Clients

*Was: Clients (top menu)*

- Nothing noted yet. **[No notes yet]**

## Law library

### Law library

*Was: Regulatory master › Law library*

- Refresh laws with Claude → refresh with the LLM of choice. Connect AI. **[Done]** Settings › AI provider: Claude, OpenAI, Azure OpenAI or Gemini, with model and key, and Test connection. Every AI feature uses it. Untested against a real OpenAI, Azure or Gemini account.

- Law library vs reference data? Better grouping? What are the differences? **[Done]** Each screen now says what it holds and links to the other: the law library holds the laws, versions, requirements and scope tests; reference data holds the lists around them and the refresh runs.
- (10 Nov) Hovering the Law library menu shows Law library, Roles and committees and Refresh and review, and the page shows them again as tabs. Pick one. **[Done]** Kept the menu; the tabs inside the Law library pages are gone.

### Refresh and review

*Was: Refresh and review (top menu); now under Law library*

- Part of the law library, not a separate tab. **[Done]** Moved into the Law library menu.

- Refresh with the LLM of choice. **[Done]** Runs on the connected AI provider; one failed geography no longer stops the run.
- (10 Nov) Same note as Law library. **[Done]** The tabs are gone from this page. Its pending count is still on the Law library tile.

### Roles and committees

*Was: Role and committee catalogue, inside Regulatory master (no tab)*

- Give it its own tab. **[Done]** Its own entry in the Law library menu.

- Need clarity on "Needed by" for the user. **[Done]** Explained on the screen and in an (i) on every Needed by column: the point in the AI system's life by which the role should be filled, checked when the system is submitted for go-live.

- Should "Needed by" mean the audit stage instead of the system's life stage? **[Open]** Built as the system's life stage. Say if you want the audit stage.
- (10 Nov) Make the table a pivot table: select one or more regulations and the roles needed for them come up. **[Done]** Opens on the pivot: pick regulations (searchable, grouped by jurisdiction); roles and committees as rows, the selected regulations as columns, with required or recommended and Needed by in each cell; a summary of what any selected regulation needs; CSV export. The full catalogue is one click away.

### Obligations to review

*Was: Obligations to review (top menu)*

- Flag. **[Done]** A count of obligations waiting for review on the menu entry and on the Law library menu, for people who approve them.

### Regulatory updates

*Was: Regulatory updates (top menu)*

- Test. **[To test]**

## Business

### Litigation

*Was: AI litigation (top menu)*

- AI litigation tracker: test with the Claude API. **[To test]** It now runs on whichever AI provider is connected in Settings.

### Opportunities

*Was: Opportunities (top menu)*

- Run a periodic job, set from admin every 7, 15 or x days, that fills this list as new laws, rule changes or renewal audits come up. **[Done]** Settings › Opportunity scan: 7, 15, 30 or any number of days, or off (off until you switch it on). Opens one opportunity per client and reason for new or changed laws that apply, matched regulatory updates and renewal audits due within 90 days. Run now looks back 30 days.

- The manual "Create advisory opportunity" button can still open a second opportunity next to a law-change one. **[Open]** Deferred as minor.
- (Release 2) **[Done]** Moved to the new Sales menu as part of the sales module: Sales home, Opportunities (list and board), Log opportunity and the opportunity record. The old address opens the new screen. See the Release 2 change log.

### Client alerts

*Was: Client alerts (top menu)*

- Test. **[To test]**

### Insights

*Was: Insights (top menu)*

- Nothing noted yet. **[No notes yet]**

## Assurance

### Trust Center confirmations

*Was: Trust Center confirmation (top menu)*

- Test the feature. **[To test]**
- (10 Nov) Sort by client. **[Done]** Grouped by client (oldest first within each), with a client filter and a count per client.

### Client policy reviews

*Was: Client policy reviews (top menu)*

- Test. **[To test]**

### Platform trust

*Was: Platform trust (top menu)*

- Check with Darshan. **[Yours]**

## Administration

### Users

*Was: Users (top menu)*

- Where is add users? **[Done]** "Add user" on the Users screen for the Futran Admin; others see who can add users.
- (10 Nov) Administration should show users and their departments. **[Done]** Futran staff have departments (column, filter, set on add and edit; the Futran Admin manages the list here). New Administration › Client users: every client's users with client, department, job title, AI compliance roles and status; read-only; Futran Admin and Chief Auditor only.

### Templates

*Was: Templates (top menu)*

- Fix text box length. **[Done]** The box grows to fit the whole template and stays readable after a window resize.

- Remove the v1 chip. **[Done]**

- Add an (i) hover to show document revision and date. **[Done]** Shows the revision, when it was saved and by whom.

### Reference data

*Was: Reference data (top menu)*

- Law library vs reference data? **[Done]** See Law library above.

- Clicking a law gives a poor table on the right → pop out in its own screen. **[Done]** A law opens its full law record page. The Futran Admin's side editor stays, with a link to the full record.

- New: an AI models tab (the vendor and model list for the register). **[New]**

### Email and groups

*Was: Email and groups (top menu)*

- Test emails. **[To test]**

### Email log

*Was: Outbox and Email log (two top-menu tabs)*

- Outbox: can it be the same as the email log? **[Done]** The outbox is a tab of the email log, "Outbox (test mode)"; the old address goes there.

- Outbox: test email connectivity. **[To test]**

- The outbox tab is cramped at phone width. **[Open]** Deferred as minor.

### Audit log

*Was: Audit log (top menu)*

- "When" column too narrow. **[Done]** The column no longer wraps.

### Settings

*Was: Settings (top menu)*

- New: AI provider and Opportunity scan sections (from the two items above). **[New]**

# CLIENT SIDE

## Whole menu

### Forms and templates folder

*New (10 Nov)*

- (10 Nov) All forms and templates in separate folders, one client and one Futran, labelled by section with subfolders. **[Done]** "Forms and templates/Client" and "Forms and templates/Futran", each with a subfolder per menu and screen and a README listing every file and its use. Answer keys and Futran-only templates are only in the Futran folder.

### Menu grouping

*Was: one long row of tabs*

- A lot of internal modules on both the client and staff side should move into different groups and tabs. Easier tabbing and better grouping. **[Done]** Six menus: Home, Audit, AI governance, People and training, Data and integrations, Email. People only see what they can use.

## Home

### Getting started

*Was: Getting started (top menu)*

- Test. **[To test]**
- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

### Summary

*Was: Summary (top menu)*

- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

### Data review

*Was: Data review (top menu)*

- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

### Admin home

*Was: Admin home (top menu)*

- Change the role-change text ("gave X the role of Y for Z") to a scrollable grid with name, assigned role and department. **[Done]** Grid of name, AI compliance role, department, change, changed by and when, with filters.

- When a user's role is changed, show the role change history (who changed it and when). **[Done]** Clicking a name opens that person's full history.

- Capture the same when the department is changed. **[Done]** Department changes are recorded from the screen, bulk changes and uploads.
- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

### My department

*Was: My department (top menu)*

- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

### My tasks

*Was: My tasks (top menu)*

- (10 Nov) Home should show the audit stages as a timeline you can click. **[Done]** The nine stages of the current audit (done, current, upcoming, with dates) sit at the top; each opens its screen, or a short summary if you can't open that screen. Vertical on phones.

## Audit

### Review

*Was: Review (top menu)*

- Test. **[To test]**

### AI systems

*Was: AI systems (top menu)*

- Test. **[To test]**
- (10 Nov) AI systems, the AI system register and the AI inventory are too much; one place to input everything, then filter. **[Done]** One "AI systems" page (AI governance › AI systems) lists register systems, inventory tools and agents, use cases and the current audit's systems, with filters for type, source, department, stage, tier, in the current audit and not yet registered, and one Add button. This old address opens it with the matching filter. Nothing in your data was converted.

### Documents

*Was: Documents (top menu)*

- Test. **[To test]**

### Report

*Was: Report (top menu)*

- Test. **[To test]**

### Responses

*Was: Responses (top menu)*

- Test. **[To test]**

### Remediation

*Was: Remediation (top menu)*

- Test. **[To test]**

## AI governance

### AI system register

*Was: AI system registry (top menu)*

- Make the template match the information the system needs. **[Done]** 37 columns in the form's order, required ones marked, as CSV or Excel. Old files still import.

- Where does "Import from inventory" come from? **[Done]** Its help says exactly what it copies from the engagement's AI inventory.

- Adding an AI or agent system, what it is: a tool used by some departments → pick which ones. **[Done]** "Used by several departments" with a department picker.

- Who uses it, by role level: a dropdown from job title, designation and AI compliance role (department heads, managers, level 1–3 …) based on the user and department files. **[Done]** Job levels, AI compliance roles and job titles, each showing how many people it covers.

- Who uses it, named users: a multi-select list with select and unselect, a select all button, and the number of users counted. **[Done]** Searchable, with a department filter, Select all, Clear and a count.

- System owner: sort users by department. **[Done]** The list is grouped by department.

- Vendor and model: a list of models for the vendor, refreshed monthly; "Other" saved for the client's future use. **[Done]** Model dropdown per AI provider plus Other. The monthly check proposes additions for the Futran Admin to accept, or reminds them when no AI is connected.

- Whose data: add the company. **[Done]** "The company's own data".

- Laws: a law library dropdown; where the system runs (state, city) and where the people whose data it uses are; give the laws from the law library, not AI. **[Done]** Laws suggested from the law library's own rules with the reason; accept or remove each, add any law from the dropdown.

- Governance roles: add the law's geography; call the role "AI compliance role". **[Done]** A Geography of law column and the new heading.

- Register labels "Edit role", "Save role" and "Required roles". **[Done]** Kept as they are (your decision, 10 November).
- (10 Nov) AI systems, the AI system register and the AI inventory are too much; one place to input everything, then filter. **[Done]** One "AI systems" page (AI governance › AI systems) lists register systems, inventory tools and agents, use cases and the current audit's systems, with filters for type, source, department, stage, tier, in the current audit and not yet registered, and one Add button. This old address opens it with the matching filter. Nothing in your data was converted.

### AI inventory

*Was: AI inventory (top menu)*

- Test. **[To test]**
- (10 Nov) AI systems, the AI system register and the AI inventory are too much; one place to input everything, then filter. **[Done]** One "AI systems" page (AI governance › AI systems) lists register systems, inventory tools and agents, use cases and the current audit's systems, with filters for type, source, department, stage, tier, in the current audit and not yet registered, and one Add button. This old address opens it with the matching filter. Nothing in your data was converted.

### Governance

*Was: Governance (top menu)*

- Test. **[To test]**

### Company roles

*Was: Company roles (top menu)*

- Test. **[To test]**

### Policies

*Was: Policies (top menu)*

- Nothing noted yet. **[No notes yet]**

### New AI projects

*Was: New AI projects (top menu)*

- Test. **[To test]**

### Regulatory updates

*Was: Regulatory updates (top menu)*

- Test. **[To test]**

### Add-ons

*Was: Add-ons (top menu)*

- Test. **[To test]**

## People and training

### People

*Was: People (top menu)*

- Clicking the three dots should give the settings to edit, not "Edit". **[Done]** The menu shows Edit details, AI compliance role, Department, Job level, Resend invitation, Change history and Remove.

- Assign the head of department from an updated file, based on the names submitted. **[Done]** A Head of department column (email or full name); no match or more than one match is a warning, never a guess.

- Department template: a full template, one sheet per department; upload users per department or one file for all. **[Done]** Excel workbook with Instructions, Departments, one sheet per department and a Company-wide sheet; "Upload users to this department" on each department. Uploads are previewed and applied all at once or not at all.

- User template: call the role "AI compliance role"; Job title is their working title at the company. **[Done]** Columns: Full name, Work email, Department, Job title, Job level, AI compliance role. Old files still import.

### Attestation

*Was: Attestation (top menu)*

- Test. **[To test]**

### My AI attestation

*Was: My AI attestation (top menu)*

- Test. **[To test]**

### AI literacy training

*Was: AI literacy training (top menu)*

- Test. **[To test]**

### My training

*Was: My training (top menu)*

- Test. **[To test]**

## Data and integrations

### Bias test data

*Was: Bias test data (top menu)*

- Test. **[To test]**

### Integrations

*Was: Integrations (top menu)*

- Test. **[To test]**
- (10 Nov) Are the connections registered in the AI or system inventory? **[Done]** Answered on the screen: a tool an integration finds is a suggestion until confirmed; once confirmed it becomes an inventory tool with source "Discovery" and shows on the AI systems page. Dismissed tools are not added.

### Monitoring

*Was: Monitoring (top menu)*

- Listed in your notes with nothing under it. **[No notes yet]**

### Customer questionnaires

*Was: Customer questionnaires (top menu)*

- Test. **[To test]**

### API and webhooks

*Was: API and webhooks (top menu)*

- Test. **[To test]**

### Trust Center

*Was: Trust Center (top menu)*

- Test. **[To test]**

## Email

### Email connection

*Was: Email connection (top menu)*

- Test. **[To test]**

### Groups

*Was: Groups (top menu)*

- Test. **[To test]**

### Email log

*Was: Email log (top menu)*

- Test. **[To test]**
