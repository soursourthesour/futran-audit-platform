---
title: Futran Audit Platform — changes from the 11-03 review notes
tags: [futran, audit-platform, change-log]
source: "futran AI audit platform fixes 11-03.docx" (updated 10 November 2026); item ids in 2026-11-03_fixes_source.md
status: built, independently reviewed and fixed; all tests pass; installed on the laptop 10 November
updated: 2026-11-10
---

# Changes from the 11-03 review notes

This records what was done for each item in the 11-03 document, the calls taken where the note left a choice, what the independent review found and fixed, and what is left. It will be updated when the document is shared again, like the earlier change logs.

Status key: **Done**, **Partly done**, **Not started**, **Your test** (items you marked "Test", not built).

## Futran side

| Id | Item | Status | What was done |
|---|---|---|---|
| F1 | Refresh with the LLM of choice; connect AI | Done | Platform settings › AI provider: choose Claude, OpenAI, Azure OpenAI or Gemini, the model and the API key, then Test connection. The key is stored encrypted and only its last four characters are shown. Every AI feature uses the connected provider: law refresh, Draft with AI, litigation tracker, copilot, obligations, questionnaires, Explain this question. With nothing connected the platform behaves as before. Rate limits and brief outages are retried; a failed geography no longer stops a law refresh (the run ends "Finished with errors" and lists what to run again). |
| F2 | "Needed by" in the roles catalogue | Done | Explained on the catalogue and in an (i) on every Needed by column: the point in the AI system's life by which the role should be filled. Every required role needed at set-up, procurement, development or go-live is checked when the system is submitted for go-live; an empty one blocks approval, and on a live system it is raised as a finding. Ongoing and yearly roles are not checked at go-live. |
| F3 | Law library vs reference data | Done | Each screen now says what it holds and links to the other. Law library: the laws, their versions, requirements and scope tests. Reference data: the lists around them (jurisdictions, catalogues, the AI model list) and the law refresh runs. |
| F4 | Tabs and grouping | Done | The top menu is grouped: Home and work; Law library (Law library, Refresh and review, Roles and committees, Obligations to review, Regulatory updates); Business; Assurance; Administration. "Regulatory master" is now "Law library", and Roles and committees has its own entry. On phones the groups fold into the Menu. No page addresses changed. |
| F5 | Test emails | Your test | |
| F6 | Obligations to review: flag | Done | A count of obligations waiting for review on the menu entry and its group, for people who approve them. |
| F7 | AI litigation tracker with the Claude API | Your test | It now runs on whichever AI provider is connected. |
| F8 | Periodic opportunity scan | Done | Platform settings › Opportunity scan: every 7, 15, 30 or a chosen number of days, or off (off until you switch it on). Each scan opens one opportunity per client and reason for laws added or materially changed in the law library that apply to the client, regulatory updates matched to the client, and renewal audits due within 90 days. The independence rule and Chief Auditor approval apply as for other opportunities. "Run now" is there; the first scan looks back 30 days. |
| F9 | Client alerts | Your test | |
| F10 | Templates | Done | The text box grows to fit the template (and stays readable after a window resize); the v1 chip is gone; an (i) beside the name shows the revision, when it was saved and by whom. Opening templates now needs a template permission. |
| F11 | Reference data: law table on the right | Done | A law opens its full law record page. The Futran Admin's side editor stays, with a link to the full record. |
| F12 | Users: add users | Done | "Add user" on the Futran Users screen for the Futran Admin; others see who can add users. |
| F13 | Audit log: When column | Done | The column no longer wraps. |
| F14 | Outbox | Done (merge); your test (connectivity) | The outbox is now a tab of the email log ("Outbox (test mode)"); the old address goes there. |
| F15 | Platform trust: check with Darshan | Yours | |
| F16–F18 | Trust Center confirmation, client policy reviews, regulatory updates | Your test | |

## Client side

| Id | Item | Status | What was done |
|---|---|---|---|
| C1 | Grouping and tabs | Done | Client menu grouped: Home; Audit; AI governance; People and training; Data and integrations; Email. People only see the entries they can use. |
| C2 | Admin home: role changes as a grid, with history | Done | A scrollable grid (name, AI compliance role, department, change, changed by, when) with filters. A name opens that person's full history of role and department changes. Department changes are now recorded in every path (screen, bulk change, uploads). |
| C3 | People ⋯ menu | Done | The menu shows the settings directly: Edit details, AI compliance role, Department, Job level, Resend invitation, Change history, Remove. |
| C4 | Head of department from the upload | Done | The department upload takes a "Head of department" column (email or full name). Email is matched first, then the exact full name among the client's own active people; no match or more than one match is a warning, never a guess. |
| C5 | Department workbook | Done | An Excel workbook: Instructions, Departments (department, parent, head, headcount), one sheet per department with its people, and a Company-wide sheet for people without a department. Upload the workbook or a CSV; "Upload users to this department" on a department's menu takes a file for that department only. Every upload is previewed and applied all at once or not at all. |
| C6 | User template | Done | Columns: Full name, Work email, Department, Job title (their working title), Job level, AI compliance role. Old column names still import. |
| C7 | Register template | Done | The template's 37 columns follow the form, required ones marked, as CSV or Excel (with an instructions sheet and dropdowns). Old files still import; extra columns are ignored with a warning. |
| C8 | Where "Import from inventory" comes from | Done | Its help says exactly what it copies: the AI tools and agents declared in the engagement's inventory (including those staff declared in attestations), and use cases the department approved; one proposed system per vendor and product. |
| C9 | Several departments | Done | "Used by several departments" with a department picker. |
| C10 | Who uses it | Done | By role level (job levels, AI compliance roles, job titles from the user list, each showing how many people it covers) or named users (searchable list with department filter, select all, clear, and a count). |
| C11 | System owner by department | Done | The owner list is grouped by department. |
| C12 | Vendor and model list | Done | A model dropdown for the chosen AI provider, plus "Other", which is saved for that client. The Futran Admin keeps the list in Reference data › AI models. Once a month, with an AI provider connected, the platform proposes additions for the Futran Admin to accept; without one, it reminds the Futran Admin to review the list. Nothing is added without a person accepting it. |
| C13 | Whose data: the company | Done | "The company's own data" added. |
| C14 | Laws from where the system runs and whose data it uses | Done | Record where the system runs (country, state or region, city) and where the people whose data it uses are. Laws are suggested from the law library's own scope rules, with the reason; no AI is used. Accept or remove each suggestion and add any law from the law library list. Company-level rulings by the CAICO are followed. Systems without places keep their laws. |
| C15 | Governance roles: geography and wording | Done | A "Geography of law" column, and "AI compliance role" as the heading. |
| C16–C35 | Remaining screens | Your test | |

## Calls taken where the note left a choice

1. One AI provider connection for the whole platform, set by the Futran Admin. With Gemini, OpenAI or Azure, law refresh cites the pages it used but not exact passages, so every proposed change from those providers gets a second review.
2. The opportunity scan only counts law versions a person approved, so laws added by a platform release do not open opportunities; a fixed set of wording-only fields does not count as a material change; renewals are counted from the date the last audit was completed.
3. People uploads are now all or nothing, including plain CSV files (before, good rows went in and bad ones were skipped).
4. An upload never moves someone who is already set up, and never gives them a department role in another department; it warns instead. Moves are made on the screen.
5. The vendor and model list is keyed by the underlying AI provider (OpenAI, Anthropic, Google …), not the client's own vendor register.
6. "By role level" counts anyone who matches any of the choices, within the system's departments unless the system is company-wide.
7. Laws without scope questions are suggested from the place and the system's features (statutes and regulations only); some suggestions may be broad. Nothing is added without the user accepting it.
8. A few short register grid and button labels still say "role" ("Required roles", "Edit role", "Save role"). Decided 10 November: keep them.

## Independent review

Each workstream was reviewed by a separate reviewer. Fixed, each with a test that failed first:

- **Critical, fixed:** a crafted or damaged Excel file could tie up the server for minutes during a People upload (now refused in under two seconds).
- **Important, fixed:** formulas in downloaded workbooks and templates (names starting with "="); department moves through uploads without an audit record; the workbook leaving out company-wide people; invitations sent before the upload was saved; the templates list without a permission check; long templates cut off after a window resize; menus running off narrow windows; wrong "Needed by" wording; a new law missed when a small correction was approved in the same scan period; duplicate opportunities from an update and the law change it proposed, and from a new law's effective date; the first scan flooding the list; daily jobs never running on a laptop that is not open at 05:00 New York time (they now catch up when the app is opened, once a day); Gemini sources shown as Google redirect links; no retry on rate limits; replies from reasoning models cut short; help text claiming more than the code does; the API key in debug output; unsaved places lost when accepting a suggested law; old register files with extra columns refused; deactivated people selectable as named users; removed suggestions not recorded; the monthly model check saying "nothing new" without an AI connected; company-level law rulings ignored.

## Deferred (minor)

- Outbox tab is cramped at phone width; Escape does not close a menu opened by mouse in Safari.
- The Futran Admin sees the "why now" text of opportunities the scan opened, though they cannot open the opportunities list.
- The manual "Create advisory opportunity" button on a regulatory update can still open a second opportunity alongside a law change one.
- If the server stops during the daily jobs, that day is not retried (the next day runs normally).
- Refresh alerts do not list failed geographies; changing the Azure endpoint keeps the saved key; web search counts can differ from the provider's bill; OpenAI citation links may carry a tracking parameter.
- Old "Head name"/"Head email" columns are applied without matching; a deactivated person in an upload is reported as an update; hidden sheets are read; merged cells and some non-UTF-8 files are handled loosely; the row menu offers Department and Job level for deactivated people.
- Two first requests at the same moment can both try to seed the model list (one error); a removed suggestion for a law that has since been replaced can be suggested again; the register bulk edit and export do not include the new fields.

## Before real client use

- Connect an AI provider and run Test connection, then one small feature. The OpenAI, Azure OpenAI and Gemini connections have been tested only against simulated responses.
- Switch on the opportunity scan if you want it.

## Also fixed during this round

- Every uploaded Excel workbook is now size-checked before it is read: People uploads, the register import, customer questionnaires and the copilot's document reader. A few kilobytes could declare a million rows and run the server out of memory.
- Daily jobs (invitation reminders, escalations, law refresh schedules, the 12-month reassessment, the opportunity scan) now run once a day the first time the app is open after 10:00 UTC (05:00 New York in winter, 06:00 in summer). Before, they only ran if the app happened to be open at that moment, so on a laptop they rarely ran.

## Test results

- Backend: 1,865 passed, 1 skipped, none failed.
- Browser (Playwright): 113 passed, none failed.
- One chain of database migrations (head `c8d2e3f4a5b6`); every new migration only adds tables or columns.
- Upgrade rehearsed on a copy of your 2 November data: no table lost a row; AI systems and answers unchanged. On first start: one law added to the library, the nine Agentic AI questions added, expiry notices for pending invitations (outbox only), and the day's daily jobs run once. The opportunity scan is off, no AI provider is connected, and Job level is blank for everyone until you set it.

## Laptop update

Installed on 10 November. Before installing: your data was backed up to `backups\\app-before-1103-fixes-2026-11-10.db` and `backups\\files-before-1103-fixes-2026-11-10`, and the upgrade was rehearsed on a copy of that day's data (no table lost a row; AI systems and answers unchanged; the first start adds one opportunity from the existing effective-date job). All 1,317 files were checked against the package, and both `.env` files were left untouched. demo.bat was not run. The package is kept as `backups\\Futran_Audit_Platform_1103-fixes_2026-11-10.zip`.

The steps, for next time:

1. Close the platform (close the run.bat window).
2. Back up your data: copy the `data` folder in `%LOCALAPPDATA%\FutranAuditPlatform` to `%LOCALAPPDATA%\FutranAuditPlatform\backups\data-before-1103-fixes`.
3. Unzip `Futran_Audit_Platform.zip` and copy the contents of its `Futran Audit Platform` folder over your app folder (`IT work\strategy development\Futran Audit Platform`), replacing files. The zip contains no `.env`, so your settings stay as they are.
4. Do not run demo.bat or setup.bat.
5. Start run.bat. The first start upgrades the database (about a minute) and runs the day's daily jobs once.

To go back: close the platform, put the backed-up `data` folder back, and unzip the previous package (`backups\Futran_Audit_Platform_wave3_2026-11-02.zip`) over the app folder.

## Still to do

- The deferred items above.
- Your answer on "Needed by": the system's life stage (as built) or the audit stage.
