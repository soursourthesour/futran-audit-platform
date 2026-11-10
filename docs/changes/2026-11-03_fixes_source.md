---
title: Futran Audit Platform — 11-03 review notes (source text with item ids)
tags: [futran, audit-platform, change-request]
source: "futran AI audit platform fixes 11-03.docx" (as updated by Sour on 10 November 2026)
---

# 11-03 review notes, with item ids

The text below is the user's document, lightly tidied for spelling. Item ids are added so the change log can refer to them. Items marked "Test" are the user's own testing.

## Futran side

- **F1** Law library: refresh laws with Claude → refresh with "LLM of choice". Connect AI.
- **F2** Role and committee catalogue: need clarity on "Needed by" for the user.
- **F3** Law library vs reference data? Better grouping? What are the differences?
- **F4** Tabs need better grouping. Regulatory master goes to the law library, and Refresh and review are part of that. Roles and committees have no tab. Give the law library its own tab and group the other tabs.
- **F5** Test emails. *(Test)*
- **F6** Obligations to review: flag.
- **F7** AI litigation tracker: test with the Claude API. *(Test)*
- **F8** Opportunities: if there are new laws, regulation or rule changes, or an audit comes up, run a periodic job, set from the admin settings every 7, 15 or x days, that fills this list as opportunities arise when new laws are introduced or a renewal audit comes.
- **F9** Client alerts. *(Test)*
- **F10** Templates: fix text box length; remove the v1 chip; add an (i) hover to show document revision and date (any better method is fine).
- **F11** Reference data: law library vs reference data? Clicking a law gives a poor table on the right that reads out the information → click to pop out in its own screen.
- **F12** Users: where is "add users"?
- **F13** Audit log: "When" column too narrow.
- **F14** Outbox: (a) test email connectivity *(Test)*; (b) can it be the same as the email log?
- **F15** Platform trust: check with Darshan. *(Not a build item)*
- **F16** Trust Center confirmation. *(Test)*
- **F17** Client policy reviews. *(Test)*
- **F18** Regulatory updates. *(Test)*

## Client side

- **C1** A lot of internal modules on both the client and staff side should move into different groups and tabs. Easier tabbing and better grouping.
- **C2** Admin home: change the role-change text ("gave XXX the role of YYY for ZZZ") to a scrollable grid with name, assigned role and department. When a user's role is changed you can look at the role change history, which is an audit capture, with who changed the role and when. Capture the same if the department is changed.
- **C3** People: when clicking the three dots, give the settings to edit instead of saying "Edit".
- **C4** People: be able to assign the head of department from an updated CSV, based on the names submitted, if needed.
- **C5** People: the department template must be a comprehensive template and easy to add to, not just a blank CSV. Each department has its own sheet, and the system should handle that. The client can upload users per department by selecting "upload users to department". One file for all is possible if needed.
- **C6** People, user template: call the role column "AI compliance role"; "Job title" is their existing working title within their company.
- **C7** AI system register: create the template so that the information to fill out aligns with the information the system needs.
- **C8** AI system register: where does "Import from inventory" come from?
- **C9** Adding an AI or agent system, "What it is": if the tool is multi-department but not all, give the option to select the ones needed.
- **C10** "Who uses it": by role levels → a dropdown from job title, by designation, by AI compliance roles (department heads, managers, level 1, 2 or 3 employees and so on, based on job role from the user and department CSVs). If named users are selected → a multi-select list with select and unselect, number of users calculated from the selection, and a select all button.
- **C11** System owner: sort users by department.
- **C12** Vendor and model: a list of models or algorithms based on the vendor, refreshed monthly; an "Other" option to fill in, saved for the client's future use.
- **C13** Data and consent, whose data: add an option for the company.
- **C14** Laws and risks: add a law library dropdown; give a place to enter the geography of the system (state, city) and the geography of the people whose data the system is used on (for example candidates or patients); based on that and the system's location, give the laws. Don't use AI for this; use the law library's own logic.
- **C15** Governance roles: add a column for the law's geography; the word "role" again should be "AI compliance role".
- **C16 to C35** Company roles, Add-ons, Governance, Attestation, My AI attestation, AI inventory, Review, AI systems, Documents, Report, Responses, Remediation, Email connection, Groups, Email log, Bias test data, API and webhooks, Customer questionnaires, AI literacy training, My training, Trust Center, New AI projects, Regulatory updates, Integrations, Monitoring, Getting started. *(Test)*
