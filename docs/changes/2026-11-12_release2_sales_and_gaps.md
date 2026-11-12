---
title: Futran Audit Platform — Release 2, sales module and commercial gaps
tags: [futran, audit-platform, change-log, release-2]
source: Release 2 spec v0.4 (11 November 2026), screens SM-01 to SM-15 and G-01 to G-11; plan docs/superpowers/plans/2026-11-12-release2-sales-and-gaps.md
status: built, independently reviewed and fixed
updated: 2026-11-12
---

# Release 2: sales module and commercial gaps

What was built for each screen, the choices taken, what the independent reviews found and fixed, and what is left. If the Release 2 spec is shared again with more notes, this page is updated rather than replaced.

## Your decisions (11 November)

- Build everything at once: SM-01 to SM-15 and G-01 to G-11.
- The master price list workbook (93 items) and the Sales Collateral questionnaire are not in hand. Only the sample items and questions shown in the screen designs are loaded, marked as starter data. Load the real workbook through Price list › Import (preview, then save with a reason); the question bank is editable.
- Open questions R2-Q1 to Q11 take the defaults, each changeable later:
  - Sales Manager discount limit 15%.
  - Click-to-accept only.
  - Billing export as a generic CSV.
  - No price ranges on the client questionnaire.
  - The Sales Manager owns the question bank.
  - The platform is the sales system of record (no CRM sync).
  - Agent Assure 15-point items left blank for FATF to fill in.
  - Soft plan limits, hard only for API access and the Trust Center.
  - Standard cost per hour entered by the Futran Admin.
  - Lost prospects deleted after 24 months unless reopened.
  - CEO/President second check off.
- No switch to turn Release 2 off. Database changes only add; nothing in existing data is changed.
- The product is called Futran Audit Platform everywhere.

## Module A: sales

| Screen | Status | What was built |
|---|---|---|
| Roles | Done | The existing sales role is now labelled Sales Officer. New roles: Sales Manager, Pricing Approver, Price List Owner (a person can hold several; the Futran Admin assigns them on Users). On sign-in: Sales Officer and Sales Manager land on Sales home, Pricing Approver on Approvals, Price List Owner on the price list. |
| SM-01 Sales home | Done | KPIs, pipeline by stage, next steps and tasks, approvals waiting, stale deals, new automatic opportunities, recent wins; Sales Managers can switch to the team view. |
| SM-02 Opportunities | Done | List and board by stage, filters, bulk assign, stage change and export. The old /opportunities address opens it with its filters. |
| SM-03 Log opportunity | Done | Prospect or existing client; duplicate warning on name, website domain and contact email (save refused until "different company" is confirmed); independence preview; partner picker. |
| SM-04 Opportunity record | Done | Stage bar, BANT (qualified needs budget, authority and timeline; lost needs a reason), contacts, activity timeline with emails sent from the rep's own mailbox and replies threaded back, scoping questionnaire, estimates, proposals, order, independence panel with Chief Auditor approval. Stale after 14 days without activity; weekly digest to the owner and the Sales Managers. |
| Prospects | Done | Kept out of every client list; never get users or client data; become a draft client on a win. Lost prospects are deleted after 24 months unless reopened, with their contacts, emails, questionnaires, estimates, proposals and files, unless under legal hold. |
| SM-05 Scoping call | Done | Sections A–H and red flags; each answer Confirmed, Estimate or Unknown with a note; autosave; suggested price list lines with their reasons and a running estimate; removing a suggested line needs a reason. |
| SM-06 Send questionnaire | Done | Contact, sections and questions, due date, reminders on day 3 and 7, forwarding on or off, editable message; sent from the rep's mailbox. Internal questions (budget, competitors, independence notes, red flags) never go to the client. |
| SM-07 Client questionnaire | Done | Phone-first page on a personal link (14 days, closes on lock); "Not sure" on every question; saved as they go; can be forwarded to up to 5 colleagues, each forwarded link closing with the original. |
| SM-08 Review and lock | Done | Rep and client answers side by side; conflicts shown with their effect on price and settled before locking; unknowns become proposal assumptions; locking builds the proposal; unlocking makes a new version. |
| Mapping rules and question bank | Done | 39 starter questions ("Starter — replace with the Sales Collateral questionnaire") and 39 rules covering the spec's 19 rule rows. 10 rules match the 13 sample price list items; 29 are flagged as pointing at items not yet in the price list and will work once the workbook is imported. Rule edits, including switching a rule off, wait for the Pricing Approver; a rule that cannot run is skipped and flagged, never breaking the screens. |
| SM-09 Proposal builder | Done | Package picker; lines with source, quantity, list and edited price, status badges; %-items as their own lines; removing a rule line needs a reason; totals (one-time, one-time discount, recurring year 1, discount on recurring, year-1 total, annual recurring); terms; sections built from each item's deliverables; versions fixed once sent, with a diff; "list prices changed since this draft" banner. Proposal templates are on the price list's Proposal templates tab. |
| SM-10 Preview and send | Done | Section preview, PDF and Word; sent from the rep's mailbox with a personal acceptance link; reminders; send log; link-opened tracking (no tracking pixels). Every price and independence rule is checked again on the server at send. |
| SM-11 Approvals | Done | Queues by rule; Low, List, price used and High; margin note; independence context; approve or return with a note. Nobody who created, edited, requested or owns a proposal can approve it. |
| SM-12 Client acceptance | Done | Phone page on the personal link: summary, full document, prices and terms; Accept (name, title, email, authority tick, optional PO number and upload) or Request changes. Accepting marks the deal won and starts the hand-off; a failed hand-off never loses the acceptance and can be finished from the opportunity. |
| SM-13 Hand-off | Done | Prospect becomes a draft client; order with the accepted prices (including the one-time discount); engagement drafts per kind of work; subscription and entitlements; hours banks and retainers; partner commission; notices to the Chief Auditor and Futran Admin, nothing to the client. Where independence needs a separate delivery team, the new engagement drafts wait for the Chief Auditor to confirm it. |
| SM-14 Master price list | Done | Spreadsheet-style grid with every column including deliverables; column presets and filters; edits saved in a batch with a reason, now or from a future date; side panel; add, duplicate, retire and restore; bulk edit with preview; validation; history per item and a change log; Excel import with preview (and the second check when it is on) and formula-safe export; "Suggest a change" for sales roles; packages. |
| SM-15 Estimator | Done | Packages or single items; edited prices shown against list; discounts, term, region; guardrail warnings; each save a new version on an opportunity; convert to a proposal. Works on a phone. |

## Module B: commercial and service gaps

| Screen | Status | What was built |
|---|---|---|
| G-01 Plans, entitlements and usage | Done | Plan tab on the client: tier, term, entitlements; usage measured daily; at 90% the CAICO and account owner are told and an opportunity opens; over 100% shows "over plan" and adds an overage row; hard limits only on API access and the Trust Center (clients already using them keep them); renewals open an opportunity 90 days ahead; monthly billing CSV. |
| G-02 Engagement commercials and change orders | Done | Order lines, fee, milestones and deliverables on the engagement; change orders priced from the price list, approved by the right approver and then the client's CAICO; an approved change order is billed once. Adding a system after the audit starts raises a change order only on engagements that came from an order. |
| G-03 Time and hours | Done | Weekly timesheets; submit locks the week; approval by the Engagement Manager (Chief Auditor for bank, retainer and internal time), never the author; hours banks alert at 80%; retainers; incident engagements as drafts for the Chief Auditor; standard cost and margins for the Chief Auditor and Sales Manager. Fees and rates only to people who may see fees. |
| G-04 Client hierarchy | Done | Parent, subsidiary and end-client links; each stays its own client. A parent sees a subsidiary's counts and statuses only while that subsidiary's CAICO consents (revocable, logged). NYC LL144 scope per end-client. |
| G-05 Discovery import | Done | Seven admin exports (Copilot licences and usage, Entra apps and consents, Google app access, Gemini usage, Gemini Enterprise apps and agents, expense, proxy); column mapping with saved presets; preview; vendor matching; same confirm or dismiss step; each import kept as evidence with its fingerprint. Expense and proxy keep only AI vendor rows. Findings open sales opportunities that the client never sees. |
| G-06 Service templates | Done | Ten new engagement types; a template per type with sections, checklists, deliverables, stages, report template and price list codes; the Futran Admin writes, the Chief Auditor approves (never their own); approved versions fixed. Board readout pack as PDF. |
| G-07 Copilot readiness | Done | Imports of the Copilot licence and usage, Purview oversharing and SharePoint permission reports (kept as evidence); site risk list; rollout waves with go or hold; controls checklist from the approved template; readiness report PDF; links or creates the Copilot entry on the AI systems list. The client's CAICO can update owner, status and note on sites. |
| G-08 EU AI Act | Done | Per system: EU exposure, role and classification with reasoning; applicable articles and deadlines worked out from them (Annex III high-risk 2 December 2027, Annex I 2 August 2028, from the spec; the general-purpose AI date is marked for the legal reviewer to confirm); obligations checklist; Annex IV tracker; FRIA where required. Only the legal reviewer on an open engagement for that client signs off; changing anything the sign-off covers cancels it. 16 missing EU AI Act articles are proposed in Law library › Refresh and review and change nothing until a Futran reviewer approves them. |
| G-09 Agent assurance | Done | Assurance tab on agent records: evaluation set, 15-point check (blank for FATF), red-team results, pass, conditional or fail, signed letter. Status worked out from the latest record; re-certification on model, version or vendor change; AgentWarden licence CSV feeds plan usage. |
| G-10 Evidence vault | Done | Retention 3, 7 or 10 years (default 7), never shorter than the engagement letter's period; legal holds placed and released by the Chief Auditor, honoured by every deletion; 90-day notice before deletion; storage feeds plan usage. |
| G-11 Partners | Done | Partners, referrals in and out, commissions on wins (never for law firms; voided if a partner becomes a law firm; one per opportunity). Amounts only for the Sales Manager, Futran Admin and Chief Auditor. |

## Choices taken

- The recurring discount runs for the whole term, not just year 1.
- Packages: "Agent-ready" has no items (the designs list none); "Starter" holds L-01.
- Term and data region do not change prices yet (the design's "2 years (5% off)" and "EU (+10%)" are not applied).
- A Pricing Approver can also decide Sales Manager rules.
- Scoping: L-02 quantity is AI hiring tools minus one, as the spec says; M-01a–c are Monitor and M-01d–f Monitor Plus; X-03 counts all high-risk systems.
- There is no finance role, so "finance" notices go to the Futran Admin.
- A plan limit the price list does not name is read from the tier name ("up to 10").
- Only adding a system changes an audit's scope automatically; other change orders tell the Engagement Manager.
- Automatic opportunities keep the v0.6 rule for Chief Auditor approval; logged ones need it whenever the independence flag is set.
- Every Sales Officer sees every rep's deals on Opportunities (the spec allows it); only the owner or a Sales Manager can change them.
- Register checklists: with no EU AI Act sign-off, every provider, importer and distributor item shows exactly as before. A signed-off deployer role hides unanswered provider items; answered items always stay.
- Every client CAICO sees a Copilot readiness menu entry, with an empty message when there is no Copilot engagement.
- Expense and proxy imports keep a summary of AI rows plus a fingerprint of the original file, not the file.

## What the independent reviews found and fixed

Five reviews found 2 critical and about 30 important problems. All were fixed with a test that failed first.

| Area | Finding | Fix |
|---|---|---|
| Proposals | Someone could approve a discount they set, if someone else edited last. | Every change on every version is recorded with who made it; none of them can approve. |
| Proposals | Typed-in payment terms needed no approval and could change after approval. | They need approval; changing any client-facing term cancels it. |
| Proposals | The send check used prices copied into the draft, not today's price list. | It uses today's prices; banner offers the update. |
| Proposals and price list | The one-time discount needed approval but changed nothing. | It comes off the totals, documents, client page, order, fees and billing. |
| Price list | Export then import added an apostrophe to text starting with "-" or "+". | Fixed. |
| Price list | Excel import skipped the second check. | Held for the other Price List Owner like grid edits. |
| Commercial | Approved change orders were never billed. | Billed once as their own milestone. |
| Commercial | Auditors saw retainer fees; anyone could log hours to any client's bank. | Fees only to people who may see them; hours only to assigned clients. |
| Commercial | Typing a fee on an old engagement changed its add-system rule. | Only engagements from an order. |
| Commercial | A hand-raised add-system change order could lead to a second charge. | It covers the next system added. |
| Scoping | Rules could be switched off without approval; one bad rule broke scoping for everyone. | Both fixed. |
| Scoping | Forwarded questionnaire links outlived the original. | They close with it. |
| EU AI Act | Missing articles were written straight into the approved law version at start-up, changing go-live status on existing systems. | Proposed for review instead; nothing changes until approved. |
| Register | Answered EU-10 items disappeared from bought systems. | Answered items always stay; nothing changes without a sign-off. |
| Vault | A short retention tier could delete evidence before the letter's date. | Never shorter than the letter. |
| Partners | No commission was created on a real win; a law firm could still be paid. | Both fixed. |
| Discovery import | Broke the existing monitoring alert check; the client admin saw Futran sales codes; personal spending text was kept. | All fixed. |
| Sales desk | A logged deal could lose its Chief Auditor approval requirement; old opportunities showed "No flag" on current clients; a Sales Officer could change another rep's deal; deleting a lost prospect left emails and files. | All fixed. |

## Left

- Load the real price list workbook (Price list › Import) and replace the starter questions.
- Board readout pack is PDF only (PowerPoint would need a new package on the laptop).
- Not seeded because the source is not in hand: the LL144 eight-case map, Annex IV items, the vendor-sponsored audit, workshop and advisory retainer templates, the Agent Assure 15 points.
- The email carries the proposal link, not an attached PDF (the mail system cannot attach files yet). Client reminders are sent by hand.
- Accepting a price suggestion does not fill in the grid; the owner makes the edit.
- An end-client cannot yet read the public summary that names it (recorded only).
- AgentWarden usage in plan limits counts approver seats per agent.
- Adding new tools to an agent does not yet prompt re-certification.
- Old audit-log entries keep the email addresses already written (the log is append-only).
