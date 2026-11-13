---
title: Futran Audit Platform — test cases
tags: [futran, audit-platform, testing]
build: 1a7482c (Release 2)
updated: 2026-11-13
status: ready to run
---

# Futran Audit Platform: test cases

255 manual test cases for the Futran and client sides, written for the data on the laptop as it is on 13 November 2026. The same cases are in `Futran_Audit_Platform_Test_Cases_2026-11-13.xlsx`, which has status drop-downs and a summary tab.

## Before you start

1. Do SET-01 first: copy the data folder. Testing adds records, and some steps (approving Northwind, for example) cannot be undone.
2. Never run `demo.bat` or `run.bat --reset-demo`; they delete everything.
3. Use a normal window for staff (`/staff/login`) and a private window for clients (`/login`).
4. Demo accounts use `Demo-Password-2026`. Set the same password for the people added in Setup.
5. Emails wait in Administration › Email log › Outbox. Open invitation, questionnaire and proposal links from there.
6. Run the Setup cases before the rest. 'Before' on each case names what it depends on.
7. Priority: P1 must work, P2 should work, P3 when there is time.

## Logins

| Side | Email | Name | Role | Client | Comes from |
|---|---|---|---|---|---|
| Futran | `chief@futran.demo` | Dana Whitfield | Chief Auditor | Futran Solutions | Already on your laptop |
| Futran | `admin@futran.demo` | Ada Brennan | Admin | Futran Solutions | Already on your laptop |
| Futran | `auditor1@futran.demo` | Alex Moreno | Auditor (on every demo client) | Futran Solutions | Already on your laptop |
| Futran | `auditor2@futran.demo` | Priyanka Rao | Auditor (Meridian and Futran internal only) | Futran Solutions | Already on your laptop |
| Futran | `qa@futran.demo` | Quinn Taylor | QA Reviewer | Futran Solutions | Already on your laptop |
| Futran | `em@futran.demo` | Elena Brooks | Engagement Manager | Futran Solutions | Already on your laptop |
| Futran | `sales@futran.demo` | Sam Seller | Sales Officer | Futran Solutions | Created in SET-02 |
| Futran | `salesmanager@futran.demo` | Riya Mehta | Sales Manager | Futran Solutions | Created in SET-03 |
| Futran | `ceo@futran.demo` | Jordan Ellis | Pricing Approver and Price List Owner | Futran Solutions | Created in SET-04 |
| Futran | `president@futran.demo` | Morgan Hale | Price List Owner | Futran Solutions | Created in SET-05 |
| Futran | `legal@futran.demo` | Casey Grant | Legal/Compliance Reviewer | Futran Solutions | Created in SET-06 |
| Client | `maria.lopez@abccorp.example` | Maria Lopez | Chief AI Compliance Officer (CAICO) | ABC Corp (audit completed) | Already on your laptop |
| Client | `robert.chen@abccorp.example` | Robert Chen | Executive Sponsor | ABC Corp | Already on your laptop |
| Client | `sam.okafor@abccorp.example` | Sam Okafor | Client Admin | ABC Corp | Already on your laptop |
| Client | `daniel.kim@abccorp.example` | Daniel Kim | Data Protection Officer | ABC Corp | Already on your laptop |
| Client | `priya.shah@abccorp.example` | Priya Shah | Department Compliance Lead, HR | ABC Corp | Already on your laptop |
| Client | `grace.liu@abccorp.example` | Grace Liu | Department Compliance Lead, Finance | ABC Corp | Already on your laptop |
| Client | `tom.reyes@abccorp.example` | Tom Reyes | Contributor, HR | ABC Corp | Already on your laptop |
| Client | `katrin.vogel@meridian.example` | Katrin Vogel | CAICO and Client Admin | Meridian GmbH (stage 3, discovery) | Already on your laptop |
| Client | `jonas.weber@meridian.example` | Jonas Weber | Data Protection Officer | Meridian GmbH | Already on your laptop |
| Client | `aarav.menon@meridian.example` | Aarav Menon | Department Compliance Lead, Engineering | Meridian GmbH | Already on your laptop |
| Client | `lena.fischer@meridian.example` | Lena Fischer | Department Compliance Lead, Data Science | Meridian GmbH | Already on your laptop |
| Client | `hannah.cole@internal.futran.example` | Hannah Cole | CAICO and Client Admin | Futran Solutions (internal) (stage 2, setup) | Already on your laptop |
| Client | `hannah.ortiz@northwind.example` | Hannah Ortiz | CAICO and Client Admin | Northwind Logistics (waiting for approval) | Invited in F-ONB-05; set the password from the invitation |
| Client | `pat.romero@parentco.example` | Pat Romero | CAICO | Parent Co (test group) | Created in SET-08 |
| Client | `sid.okafor@subco.example` | Sid Okafor | CAICO | Sub Co (test group) | Created in SET-08 |


## Setup

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| SET-01 | P1 | Admin<br>`admin@futran.demo` | Take a copy of your data before testing | run.bat is closed | 1. Close the black run.bat window.<br>2. Copy %LOCALAPPDATA%\FutranAuditPlatform\data (or ask Claude to back it up).<br>3. Start run.bat again. | A dated copy of app.db exists. If testing leaves the data in a state you don't want, this copy can be put back. |
| SET-02 | P1 | Admin<br>`admin@futran.demo` | Add a Sales Officer | Signed in at /staff/login | 1. Administration › Users › Add user.<br>2. Name Sam Seller, email sales@futran.demo, role Sales Officer.<br>3. Choose Add and send invitation.<br>4. Administration › Email log › Outbox tab: open the invitation and its link in a private window.<br>5. Set the password (use Demo-Password-2026 to keep it simple). | Sam appears on Users as Invited, then Active once the password is set. Sam lands on Sales home after signing in. |
| SET-03 | P1 | Admin<br>`admin@futran.demo` | Add a Sales Manager | SET-02 done | Repeat SET-02 for Riya Mehta, salesmanager@futran.demo, role Sales Manager. | Riya lands on Sales home, with a Mine / Team switch that a Sales Officer does not have. |
| SET-04 | P1 | Admin<br>`admin@futran.demo` | Add a person with two roles: Pricing Approver and Price List Owner | SET-02 done | 1. Add Jordan Ellis, ceo@futran.demo, role Pricing Approver, and set the password.<br>2. On Users, open Jordan's row and use Add role to add Price List Owner. | Users shows both roles on Jordan. Jordan lands on the Price list, and the Sales menu shows Opportunities, Price list, Proposals and Approvals (the union of both roles). |
| SET-05 | P2 | Admin<br>`admin@futran.demo` | Add a second Price List Owner | SET-02 done | Add Morgan Hale, president@futran.demo, role Price List Owner, and set the password. | Morgan lands on the Price list and sees no other Sales entries. |
| SET-06 | P1 | Admin<br>`admin@futran.demo` | Add a Legal/Compliance Reviewer | SET-02 done | Add Casey Grant, legal@futran.demo, role Legal/Compliance Reviewer, and set the password. | Casey lands on My work. The Law library menu shows Refresh and review, Obligations to review and Regulatory updates only. |
| SET-07 | P1 | Auditor<br>`auditor1@futran.demo` | Create two test clients for the workspace tests | Signed in as Alex | 1. Home › New client. Company: Contoso Copilot Test. Engagement type: Microsoft 365 Copilot readiness. CAICO: Carla Ruiz, carla.ruiz@contoso.example. Team: Chief Auditor, Engagement Manager, Alex.<br>2. Submit.<br>3. Repeat for Eurotech EU Test, engagement type EU AI Act conformity readiness, a location in Germany, CAICO Erik Lund, erik.lund@eurotech.example. Add Casey Grant (Legal/Compliance Reviewer) to the team.<br>4. As chief@futran.demo, approve both (Review initiation package › tick the checklist › approve). | Both clients appear on Clients as waiting for the client. Invitations for Carla and Erik are in Email log › Outbox. |
| SET-08 | P2 | Admin<br>`admin@futran.demo` | Create a parent and a subsidiary for the group tests | Signed in as Ada | 1. Create two clients through New client (as auditor1): Parent Co (CAICO Pat Romero, pat.romero@parentco.example) and Sub Co (CAICO Sid Okafor, sid.okafor@subco.example). Approve both as the Chief.<br>2. Open each invitation from the Outbox and set the passwords. | Pat and Sid can sign in at /login and land on Getting started for their own company. |

## F · Sign-in and homes

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-AUTH-01 | P1 | Chief Auditor<br>`chief@futran.demo` | Staff sign-in |  | Go to /staff/login and sign in. | Lands on Chief Auditor home with the dashboard: clients, counters and filters (All, In progress, Completed, Drafts). |
| F-AUTH-02 | P1 | Chief Auditor<br>`chief@futran.demo` | Staff email on the client sign-in page is refused |  | Go to /login and sign in with chief@futran.demo. | Refused with a message pointing to the staff sign-in page. No session is created. |
| F-AUTH-03 | P1 | Any<br>`chief@futran.demo` | Wrong password |  | Sign in with a wrong password. Then try an email that does not exist. | Both show the same message, 'Email or password is incorrect.' Nothing says whether the email exists. |
| F-AUTH-04 | P2 | Any<br>`(signed out)` | Signed-out visitor goes to the right sign-in page | Signed out | 1. Open http://localhost:8000/clients.<br>2. Open http://localhost:8000/register. | The first sends you to /staff/login, the second to /login. After signing in you are returned to the page you asked for. |
| F-AUTH-05 | P2 | Any<br>`chief@futran.demo` | A next address pointing to another site is ignored | Signed out | Open http://localhost:8000/staff/login?next=//evil.example/x and sign in. Repeat with next=/..//evil.example/x. | You land on your own home page both times, never on evil.example. |
| F-HOME-01 | P1 | Admin<br>`admin@futran.demo` | Admin home and grouped menus |  | Sign in. Open each menu in the top bar. | Lands on Admin home. Menus: Home and work, Law library, Business, Sales, Assurance, Administration. Sales shows only Price list and Partners. Administration includes Email and groups and Billing export. |
| F-HOME-02 | P1 | Auditor<br>`auditor2@futran.demo` | Auditor sees only assigned engagements |  | Sign in. Look at My work and Clients. | Only Meridian GmbH and Futran Solutions (internal) appear. ABC Corp and Northwind are not listed. |
| F-HOME-03 | P1 | Auditor<br>`auditor2@futran.demo` | Unassigned engagement address is refused | Copy the ABC Corp client page address while signed in as the Chief | Sign in as auditor2 and paste the ABC Corp address. | The page says it is not found or not available. No ABC Corp data shows. |
| F-HOME-04 | P2 | QA Reviewer<br>`qa@futran.demo` | QA lands on the QA queue |  | Sign in. | Lands on QA queue. With nothing waiting it shows a plain empty message. No admin or sales menus. |
| F-HOME-05 | P2 | Engagement Manager<br>`em@futran.demo` | Engagement Manager home and menu |  | Sign in and open each menu. | Lands on My work. Menus show My work, Clients, Time and hours and Audit log only. |
| F-HOME-06 | P1 | Sales Officer<br>`sales@futran.demo` | Sales Officer sees no engagement information | SET-02 | 1. Sign in.<br>2. Try /clients and /audits in the address bar. | Lands on Sales home. Menus: Time and hours, Litigation, Insights and Sales. /clients and /audits do not show any audit data. |
| F-HOME-07 | P2 | Your own login<br>`vsourya@futransolutions.com` | Two roles on one person |  | Sign in with your own account (Auditor and Chief Auditor). | Lands on Chief Auditor home (the higher role). Menus are the union of both roles. |
| F-HOME-08 | P3 | Admin<br>`admin@futran.demo` | Menus fold behind a button on a narrow window |  | Narrow the browser below 600 px (or use the phone view in the browser tools). Open the menu button, then each group. | Navigation folds behind a menu button. Every group opens inside the window. Works with the keyboard (Tab, Enter, Esc). |
| F-HOME-09 | P2 | Chief Auditor<br>`chief@futran.demo` | Notifications bell | Some items waiting (for example after F-ONB-01) | Open the bell. Open an item. | The bell shows a count. Opening an item takes you to it and marks it read; the count drops. |
| F-HOME-10 | P2 | Any<br>`chief@futran.demo` | Sign out |  | Sign out, then press the browser Back button. | You are on the sign-in page. Back does not show protected data. |

## F · Onboarding a client

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-ONB-01 | P1 | Auditor<br>`auditor1@futran.demo` | New client wizard, all five steps |  | Home › New client. Fill Company, Locations and laws (add a New York and a Texas site), Scope and team (type Initial assessment), Client contacts (CAICO required; DPO not appointed), then Review and submit. | Laws are suggested from the locations (NYC LL144 appears for New York). Every team member confirms no conflict. After submit the client shows as waiting for the Chief Auditor. |
| F-ONB-02 | P2 | Auditor<br>`auditor1@futran.demo` | Wizard refuses missing required fields |  | Start New client and try to move on from each step with required fields empty, and with a period end before the period start. | Each step names the missing or wrong fields beside them. You cannot submit until they are fixed. |
| F-ONB-03 | P3 | Auditor<br>`auditor1@futran.demo` | Wizard keeps a draft |  | Fill steps 1 and 2, leave the wizard, then open the draft client from Clients (Drafts filter). | The draft opens on the step you left with your entries kept. |
| F-ONB-04 | P1 | Chief Auditor<br>`chief@futran.demo` | Preview the initiation package | Northwind Logistics is waiting for approval | Open Northwind Logistics › Review initiation package. Open each document. | Seven documents preview (engagement letter, roles note, CSV templates, data notice, getting-started guide, governance request). Texts carry Northwind's details. |
| F-ONB-05 | P1 | Chief Auditor<br>`chief@futran.demo` | Approve Northwind (one-time on your data) | F-ONB-04 | Tick the checklist and approve. | Status changes to waiting for the client. An invitation for hannah.ortiz@northwind.example is in Email log › Outbox. |
| F-ONB-06 | P2 | Chief Auditor<br>`chief@futran.demo` | Return a draft with a comment | The client you created in F-ONB-01 | Open it › Review initiation package › Return with a comment. | The draft goes back to the auditor with the comment shown. Alex sees it on My work. |
| F-ONB-07 | P1 | Auditor<br>`auditor1@futran.demo` | Auditor cannot approve their own client | F-ONB-01 | Open the client you submitted and look for an approve action. | No approve action is offered to the auditor. |
| F-ONB-08 | P1 | Chief Auditor<br>`chief@futran.demo` | Chief signs the engagement letter (sign-off 1) | C-AUTH-01 and C-HOME-03 done for Northwind | Open Northwind › the sign-off 1 panel › Sign. | Northwind moves to stage 2, Setup. The sign-off shows both signers, dates and times. |
| F-ONB-09 | P3 | Admin<br>`admin@futran.demo` | Resend an invitation | An invited client user who has not signed in | Open the client's people page › Resend invitation. | A new invitation is in the Outbox and its link opens the invitation steps. |

## F · Running the audit

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-AUD-01 | P1 | Chief Auditor<br>`chief@futran.demo` | What's left in this stage |  | Open Meridian GmbH (stage 3). | The stage tracker shows stage 3. 'What's left in this stage' lists what blocks moving on (campaign, governance, draft use cases). |
| F-AUD-02 | P1 | Auditor<br>`auditor1@futran.demo` | Send a document request | Meridian | Open Meridian › Documents › request a document from a named client person. Preview the email and send. | The request is listed with its due date. The email is in the Outbox. The client sees it on Documents. |
| F-AUD-03 | P3 | Auditor<br>`auditor1@futran.demo` | Record a chase on an overdue request | F-AUD-02 | Open the request › Record chase. | The chase is recorded with date and person on the request's history. |
| F-AUD-04 | P1 | Chief Auditor<br>`chief@futran.demo` | Risk score worked example | ABC Corp | ABC Corp › AI systems › SYS-001 ATS résumé screening › risk score. | Inherent 76, control maturity 2.25, residual 58.2, rating High. Two knock-outs triggered: no bias testing, and null-compliance risk High. |
| F-AUD-05 | P2 | Chief Auditor<br>`chief@futran.demo` | Findings on a finished audit | ABC Corp | ABC Corp › Findings. | Six approved findings with severity, controls and citations. Nothing can be edited (locked by sign-off 5). |
| F-AUD-06 | P1 | Chief Auditor<br>`chief@futran.demo` | Report versions and downloads | ABC Corp | ABC Corp › Report. Download Final v1.1 as PDF and as Word. | All versions from Draft v0.1 to Final v1.1 are listed. Both files open and contain the executive summary, findings table, system profiles, maturity scorecard, roadmap, laws in scope, declarations and appendices B and C. |
| F-AUD-07 | P2 | Chief Auditor<br>`chief@futran.demo` | Remediation on a finished audit | ABC Corp | ABC Corp › Remediation. | Every item shows verified by an auditor and closed by the Chief Auditor, with notes and dates. |
| F-AUD-08 | P2 | Auditor<br>`auditor1@futran.demo` | Set a final tier with a rationale | A client in fieldwork (stage 5). Take the test client or a new one through stages 1–4 first. | Open a use case › set Final tier › try saving without a rationale, then with one. | Saving without a rationale is refused. With one, the final tier and rationale are saved. The client also sees them, in a 'Final tier (Futran)' card. |
| F-AUD-09 | P2 | Auditor<br>`auditor1@futran.demo` | Map a Tier 3 use case to a system | Fieldwork | AI systems in scope › Add system, then Map use case. | The use case shows its system. A system added after initiation waits for the Engagement Manager's approval. |
| F-AUD-10 | P1 | Auditor<br>`auditor1@futran.demo` | System assessment answers create draft findings | Fieldwork, a mapped system | Open the system's assessment. Answer 'No' to a bias-testing question, naming who gave the answer. Mark the section verified. | A draft finding is offered. Create draft finding and Dismiss finding both work and are recorded. |
| F-AUD-11 | P2 | Engagement Manager<br>`em@futran.demo` | Approve a system added after initiation | F-AUD-09 | Open the waiting system and approve it. | The system becomes active in scope. The auditor cannot approve it themselves. |
| F-AUD-12 | P2 | Chief Auditor<br>`chief@futran.demo` | Score override over 1 needs a rationale | Fieldwork, Chief on the team | Open a system's risk score. Change a domain score by more than 1 from the proposed score; save without and then with a rationale. | Without a rationale the save is refused. With one it saves; the rating recalculates. |
| F-AUD-13 | P1 | Auditor<br>`auditor1@futran.demo` | Draft and submit a finding | Fieldwork | Findings › New finding: severity, controls, description, recommended action, owner › Submit for approval. | The finding shows as waiting for the Chief Auditor. |
| F-AUD-14 | P1 | Chief Auditor<br>`chief@futran.demo` | Approve or return a finding | F-AUD-13 | Open the finding. Return it with a note, then (after Alex resubmits) approve it. | Return sends it back with the note. Approve locks the wording. |
| F-AUD-15 | P1 | Chief Auditor<br>`chief@futran.demo` | A finding the Chief wrote goes to QA | Fieldwork | As the Chief, write or edit a finding and submit it. Then sign in as qa@futran.demo and open QA queue. | The Chief cannot approve it. It waits in the QA queue; QA can approve or return it. |
| F-AUD-16 | P1 | Auditor<br>`auditor1@futran.demo` | Sign-off 5 and the lock | Every finding approved | Send sign-off 5 to the Chief Auditor. As the Chief, sign it. | Findings, final tiers and scores become read-only. The stage moves to Futran QA complete. |
| F-AUD-17 | P2 | Auditor<br>`auditor1@futran.demo` | Executive summary needs Greatest strengths | After sign-off 5 | Report › write the executive summary leaving Greatest strengths observed empty › Save executive summary › generate the lead review version (v0.2). | The draft saves, but generating v0.2 is refused, naming Greatest strengths. With it filled, v0.2 is generated. |
| F-AUD-18 | P1 | Auditor<br>`auditor1@futran.demo` | Lead review and declarations | F-AUD-17 | Add a roadmap item › Generate lead review v0.2. Then the Lead Auditor, Engagement Manager and QA Reviewer each sign their declaration. | One person cannot sign two declarations. When all are signed, Release client draft v1.0 becomes available. |
| F-AUD-19 | P1 | Engagement Manager<br>`em@futran.demo` | Release the client draft | F-AUD-18 | Report › Release client draft v1.0. | v1.0 is released. The client CAICO sees it on Report; drafts v0.1 and v0.2 stay hidden from the client. |
| F-AUD-20 | P2 | Auditor<br>`auditor1@futran.demo` | Review client responses | Client responded (C-RSP-01) | Responses › mark one Adequate and one Ask for changes, each with a note. | The client sees the request for changes with your note on that finding only. |
| F-AUD-21 | P2 | Auditor<br>`auditor1@futran.demo` | Final report and public summary | Sign-off 6 approved on a client with NYC LL144 in scope (for example the client from F-ONB-01 taken through the stages) | Report › Prepare final v1.1 and send for signature. Fill the public summary (tool, audit date, data, impact ratios) › send to the CAICO for sign-off 8. | The Chief Auditor sees sign-off 7 waiting. The CAICO sees sign-off 8 on the client Report page. |
| F-AUD-22 | P2 | Auditor<br>`auditor1@futran.demo` | Verify a remediation item; the verifier cannot close it | Stage 9, an item marked done by the client | Verify the item with a note. Then sign in as your own account (Auditor and Chief) if you verified with it, and try to close it. | Verification is recorded. The person who verified cannot close it; another Chief Auditor must. |
| F-AUD-23 | P2 | Chief Auditor<br>`chief@futran.demo` | Move to the next stage | A stage whose list in 'What's left' is empty | Use Move to stage N on the client page. | The stage advances and the tracker updates. When something is still open, the button is not offered and the list says what is missing. |
| F-AUD-24 | P2 | Chief Auditor<br>`chief@futran.demo` | Comments: internal and shared threads | Any engagement | Add an internal comment and a shared comment on an item. @mention a colleague from the suggestions. | The internal thread is visible to Futran only; the shared one also to the client. The mentioned person gets a bell item. |
| F-AUD-25 | P3 | Chief Auditor<br>`chief@futran.demo` | Turn on AI help for a client with a consent note | Meridian | Open Meridian › AI features › turn on, entering the consent note. | AI help is on for Meridian only, with the note, who and when recorded. |
| F-AUD-26 | P3 | Auditor<br>`auditor1@futran.demo` | AI suggestions show their citations | F-AUD-25, an AI provider connected (F-ADM-10) | Open a Meridian assessment and ask for suggestions; open the AI log. | Suggestions list their source citations and need your decision. Each call is in the AI log. |

## F · Law library and QA

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-LAW-01 | P2 | Chief Auditor<br>`chief@futran.demo` | Browse the law library and open a law |  | Law library › search Colorado › open the law. | The law opens on its own page with its versions, sections and applicability. No section tabs; the menu stays. |
| F-LAW-02 | P1 | Admin<br>`admin@futran.demo` | An Admin edit becomes a proposed change |  | Open a law › Edit › change a field › save with a reason. | The published law does not change. A proposed change appears in Refresh and review. |
| F-LAW-03 | P1 | Chief Auditor<br>`chief@futran.demo` | Approve or reject a proposed change | F-LAW-02 | Refresh and review › open the change › approve one, reject another with a note. | Approved: a new law version. Rejected: recorded with the note. The author cannot approve their own change. |
| F-LAW-04 | P1 | Legal/Compliance Reviewer<br>`legal@futran.demo` | Second review on a low-confidence change | A low-confidence change in Refresh and review (the 16 EU AI Act articles are a good example) | Open the change and give the second review. | The Chief Auditor can approve only after the second review. The Legal Reviewer cannot give final approval alone. |
| F-LAW-05 | P3 | Chief Auditor<br>`chief@futran.demo` | Roles and committees pivot and CSV |  | Law library › Roles and committees › pick two regulations › export CSV. | A pivot of roles by regulation; 'Needed by' explained. The CSV opens in Excel with no formulas run from cell text. |
| F-LAW-06 | P2 | Legal/Compliance Reviewer<br>`legal@futran.demo` | Extract and approve obligations |  | Open a law record › extract obligations. Then Obligations to review › approve one. | Obligations wait for review with a count on the menu. Approved ones show on the law. |
| F-LAW-07 | P2 | Legal/Compliance Reviewer<br>`legal@futran.demo` | Regulatory update: draft, second reviewer publishes |  | Regulatory updates › draft an update. Sign in as chief@futran.demo and publish it. | The author cannot publish their own. Once published, impact shows for matching clients and a client alert waits for approval. |
| F-LAW-08 | P3 | Chief Auditor<br>`chief@futran.demo` | Client applicability and the introduction letter |  | Open a client › applicability › review › approve the intro letter and send it. | The letter goes to the Outbox; the approval is recorded with your name. |
| F-LAW-09 | P3 | Admin<br>`admin@futran.demo` | Re-import the law matrix with a preview |  | Reference data › law matrix import › preview › apply. | Preview shows what changes before anything is saved. Applying creates new versions, not overwrites. |
| F-QA-01 | P2 | QA Reviewer<br>`qa@futran.demo` | Return a finding and a rating override from the queue | F-AUD-15 | QA queue › open the item › Return to author with a note. | The item leaves the queue and the author sees the note. |

## F · Litigation, alerts, insights

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-BUS-01 | P3 | Chief Auditor<br>`chief@futran.demo` | Litigation tracker to a case |  | Business › Litigation › open a case. | The case shows its court, status and the clients with similar AI use. |
| F-BUS-02 | P3 | Chief Auditor<br>`chief@futran.demo` | Client briefing waits for approval | F-BUS-01 | From the case, prepare a client briefing. Open Client alerts › preview › send. | The briefing waits in the approval queue until the Chief sends it; then it is in the Outbox. |
| F-BUS-03 | P3 | Sales Officer<br>`sales@futran.demo` | Sales reads cases with laws as plain text | SET-02 | Litigation › open a case. | Laws are named as text without links into the law library. |
| F-BUS-04 | P3 | Chief Auditor<br>`chief@futran.demo` | Insights: benchmarking |  | Business › Insights. | Benchmarks show without naming any other client. |
| F-BUS-05 | P3 | Sales Officer<br>`sales@futran.demo` | Insights: practice view for Sales | SET-02 | Business › Insights. | The practice view shows, without client-level scores. |

## F · Sales

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-SAL-01 | P1 | Sales Officer<br>`sales@futran.demo` | Sales home | SET-02 | Open Sales home. | KPIs, pipeline by stage, next steps, approvals waiting, stale deals and recent wins. Empty sections say so plainly. |
| F-SAL-02 | P1 | Sales Officer<br>`sales@futran.demo` | Log an opportunity for a prospect | SET-02 | Log opportunity › A prospect › Fabrikam Freight, fabrikamfreight.example, contact Lee Ng, lee.ng@fabrikamfreight.example › save. | The opportunity opens on its record at the first stage, owned by Sam. Fabrikam does not appear on Clients. |
| F-SAL-03 | P1 | Sales Officer<br>`sales@futran.demo` | Duplicate check on name, website and email | F-SAL-02 | Log opportunity again for 'Fabrikam Freight Inc', same website. | A duplicate warning names the match. Save is refused until you confirm it is a different company. |
| F-SAL-04 | P1 | Sales Officer<br>`sales@futran.demo` | Opportunity for an existing audit client needs the Chief | SET-02 | Log opportunity › An existing client › ABC Corp. | An independence preview shows and the record asks for Chief Auditor approval (Ask Chief Auditor to approve). |
| F-SAL-05 | P2 | Chief Auditor<br>`chief@futran.demo` | Approve the independence request | F-SAL-04 | Open the opportunity from the bell or Opportunities › approve with a note. | The independence panel shows approved, by whom and when. |
| F-SAL-06 | P1 | Sales Officer<br>`sales@futran.demo` | Qualified needs BANT; lost needs a reason | F-SAL-02 | Move Fabrikam to Qualified without budget, authority and timeline. Then on another deal choose Mark lost without a reason. | Both are refused, naming what is missing. With the fields filled, both save. |
| F-SAL-07 | P2 | Sales Officer<br>`sales@futran.demo` | List and board views, filters and export | A few opportunities | Opportunities › switch List and Board › filter by stage and owner › export. | Both views show the same deals. The export opens in Excel with no formulas run from text. |
| F-SAL-08 | P1 | Sales Officer<br>`sales@futran.demo` | Cannot change another rep's deal | A deal owned by Riya (log one as salesmanager@futran.demo) | Open Riya's deal and try to change its stage or fields. | Sam can read it but every change is refused or not offered. |
| F-SAL-09 | P2 | Sales Manager<br>`salesmanager@futran.demo` | Team view and reassignment | SET-03 | Sales home › Team. Opportunities › select a deal › reassign to Sam. | The team pipeline shows every rep. Sam now owns the deal and sees it under Mine. |
| F-SAL-10 | P2 | Sales Officer<br>`sales@futran.demo` | Activity timeline and email from the record | F-SAL-02 | Add a note and send an email to the contact from the record. | Both show on the timeline. Sending email first asks you to connect your own mailbox (test consent page); then it goes from your address and is in the Email log. |
| F-SAL-11 | P1 | Sales Officer<br>`sales@futran.demo` | Scoping call with live suggestions | F-SAL-02 | Open the record › Start scoping. Answer some questions as Confirmed, Estimate or Unknown, add a note. Remove a suggested price list line. | Answers autosave. Suggested lines show their reasons and a running estimate. Removing a line asks for a reason. |
| F-SAL-12 | P1 | Sales Officer<br>`sales@futran.demo` | Send the rest to the client | F-SAL-11 | Send rest to client: pick sections, due date, reminders, forwarding on › send. | The email (with a personal link) is in the Outbox. Internal questions (budget, competitors, red flags) are not in the client's list. |
| F-SAL-13 | P1 | (client contact, no login)<br>`link from the Outbox` | Client answers the questionnaire on a phone | F-SAL-12. Open Email log › Outbox as the Admin to get the link | Open the link on a phone. Answer some questions, choose Not sure on one, leave and come back. Forward to a colleague. | No sign-in needed. Fits the phone with no sideways scroll. Answers are kept. The forwarded link works and closes when the original closes. |
| F-SAL-14 | P1 | Sales Officer<br>`sales@futran.demo` | Review, settle conflicts and lock | F-SAL-13 | Open the scoping review. Settle a conflict between your answer and the client's. Lock and build proposal. | Conflicts show their price effect and must be settled before locking. Unknowns become proposal assumptions. A draft proposal opens. |
| F-SAL-15 | P3 | Sales Officer<br>`sales@futran.demo` | Unlocking makes a new version | F-SAL-14 | Unlock for edits, change an answer, lock again. | A new version is created; the earlier one is kept. |
| F-SAL-16 | P2 | Sales Officer<br>`sales@futran.demo` | Estimator on a phone | SET-02 | Estimator on a phone width: pick the Governed package, change a price, add a discount, save to Fabrikam, convert to proposal. | Edited prices show against list. Guardrail warnings appear. Each save is a new version. Convert to proposal opens the builder. |
| F-SAL-17 | P1 | Sales Officer<br>`sales@futran.demo` | Proposal builder totals | F-SAL-14 or F-SAL-16 | Add a package, edit a line price, add a one-time discount and a recurring discount of 10%. | Totals show one-time, one-time discount, recurring year 1, recurring discount, year-1 total and annual recurring, and add up. |
| F-SAL-18 | P1 | Sales Officer<br>`sales@futran.demo` | A discount needs approval before sending | F-SAL-17 | Try to send. Then Send for approval. | Send is blocked until approved. The request goes to the right queue (10% recurring: Sales Manager). |
| F-SAL-19 | P1 | Sales Manager<br>`salesmanager@futran.demo` | Approve within the 15% limit | F-SAL-18 | Approvals › open the request › Approve for this proposal. | Approved with your name. Sam can now send. |
| F-SAL-20 | P1 | Sales Manager<br>`salesmanager@futran.demo` | Nobody approves a proposal they touched | A proposal Riya edited | Edit any line of a waiting proposal as Riya, then try to approve it. | Refused: someone who created, edited, requested or owns it cannot approve. |
| F-SAL-21 | P1 | Pricing Approver<br>`ceo@futran.demo` | Over 15% or below floor goes to the Pricing Approver | SET-04 | As Sam, set a recurring discount of 20% (or a price under the floor) and send for approval. As Jordan, open Approvals and approve. | The Sales Manager cannot decide it; Jordan can. Each line shows Low, List, price used and High with a margin note. |
| F-SAL-22 | P2 | Sales Officer<br>`sales@futran.demo` | Changing a client-facing term cancels approval | An approved proposal | Change the payment terms after approval. | The approval is cancelled and the proposal needs approval again. |
| F-SAL-23 | P1 | Sales Officer<br>`sales@futran.demo` | Preview and send | Approved proposal | Preview each section, download PDF and Word, then send to the contact. | Files open with the right totals. The email with the acceptance link is in the Outbox. The sent version can no longer be edited; a new version shows a diff. |
| F-SAL-24 | P1 | (client contact, no login)<br>`link from the Outbox` | Client accepts on a phone | F-SAL-23 | Open the acceptance link on a phone. Read the summary and prices. Accept with name, title, email, authority tick and a PO number. | Accepted. The opportunity shows Won. Request changes is offered as the alternative. |
| F-SAL-25 | P1 | Sales Officer<br>`sales@futran.demo` | Hand-off after the win | F-SAL-24 | Open the opportunity › hand-off. | Shows what was created: a draft client, an order with the accepted prices (including the one-time discount), engagement drafts, subscription. The Chief Auditor and Admin get notices; the client gets nothing. |
| F-SAL-26 | P2 | Sales Officer<br>`sales@futran.demo` | List prices changed since the draft | A draft proposal; then change that item's price as the Price List Owner (F-PRC-01) | Reopen the draft. | A banner says list prices changed and offers Update to current list prices. |

## F · Price list and scoping set-up

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-PRC-01 | P1 | Price List Owner<br>`ceo@futran.demo` | Edit prices with a reason | SET-04 | Price list › edit two prices in the grid › save with a reason, effective today. | Saved as one batch with the reason. Each item's history shows the old and new values. |
| F-PRC-02 | P2 | Price List Owner<br>`ceo@futran.demo` | Future-dated change | SET-04 | Edit a price effective next month. | Today's price is unchanged; the future price shows with its date. |
| F-PRC-03 | P2 | Price List Owner<br>`ceo@futran.demo` | Add, duplicate, retire and restore an item | SET-04 | Use the side panel to add an item, duplicate it, retire it and restore it. | Each action is in the change log. Retired items stop appearing in the Estimator. |
| F-PRC-04 | P2 | Price List Owner<br>`ceo@futran.demo` | Export then import without changes | SET-04 | Export the price list. Import the same file › preview. | Preview shows no changes. Text starting with - or + is not altered. |
| F-PRC-05 | P2 | Price List Owner<br>`ceo@futran.demo` | Import a bad workbook | SET-04 | Import a file with a missing price and a text value in a price column. | The preview lists each problem with its row. Nothing is saved. |
| F-PRC-06 | P1 | Sales Officer<br>`sales@futran.demo` | Suggest a price list change | SET-02 | Price list › Suggest a change on an item. | Sam cannot edit cells. The suggestion reaches the Price List Owners. |
| F-PRC-07 | P2 | Admin<br>`admin@futran.demo` | Price list is read-only to the Admin |  | Open Price list and try to edit a cell. | No editing. Packages can be maintained by the Admin. |
| F-PRC-08 | P3 | Sales Manager<br>`salesmanager@futran.demo` | Question bank | SET-03 | Price list › Questions tab › Add a question. | Saved to the bank. Starter questions are marked as starter content. |
| F-PRC-09 | P2 | Admin<br>`admin@futran.demo` | Mapping rule changes wait for the Pricing Approver | SET-03, SET-04 | Rules tab › edit a rule or switch one off. Then as Jordan, approve it. | The change does nothing until Jordan approves. Ada cannot approve her own change. The Sales Manager cannot edit rules. |
| F-PRC-10 | P3 | Admin<br>`admin@futran.demo` | Proposal templates |  | Price list › Proposal templates tab › edit wording › Save wording. | New proposals use the new wording; sent proposals keep theirs. |

## F · Partners

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-PAR-01 | P2 | Admin<br>`admin@futran.demo` | Add a partner |  | Sales › Partners › Add partner (type referral partner). | The partner is listed with its type and status. |
| F-PAR-02 | P2 | Sales Manager<br>`salesmanager@futran.demo` | Record a referral and pick the partner on a deal | F-PAR-01 | Record referral to Fabrikam's opportunity, or pick the partner when logging a new one. | The referral shows on the partner and on the opportunity. |
| F-PAR-03 | P2 | Sales Manager<br>`salesmanager@futran.demo` | Commission on a win, marked paid | A referred deal that was won (F-SAL-24 with a partner) | Partners › commissions › Mark paid. | One commission per opportunity with its amount. Marked paid with date and person. |
| F-PAR-04 | P2 | Admin<br>`admin@futran.demo` | No commission for a law firm |  | Add a partner of type law firm and record a referral on a deal that is then won. Separately, change an existing partner with an open commission to law firm. | No commission is created for the law firm. The open commission is voided. |
| F-PAR-05 | P1 | Sales Officer<br>`sales@futran.demo` | Sales Officer sees no commission amounts | F-PAR-03 | Open Partners. | Partners and referrals are visible; commission amounts are not. |
| F-PAR-06 | P2 | Auditor<br>`auditor1@futran.demo` | Auditor has no Partners entry |  | Look for Partners in the menus; then type /staff/partners. | No menu entry, and the address shows nothing. |

## F · Plans, money and time

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-COM-01 | P2 | Admin<br>`admin@futran.demo` | Put a client on a plan |  | Open ABC Corp › Plan › Edit plan settings › choose Monitor › save. | Plan, term and entitlements show with usage. The change is in the audit log. |
| F-COM-02 | P2 | Admin<br>`admin@futran.demo` | Monthly billing export | F-COM-01 | Administration › Billing export › choose a month › Export all clients. | A CSV downloads with order lines, overage rows and approved change orders. It opens in Excel with no formulas run from text. |
| F-COM-03 | P2 | Engagement Manager<br>`em@futran.demo` | Engagement fee and milestones | Meridian | Open Meridian's engagement › commercial page › Edit fee and milestones › add a milestone. | Fee, milestones and deliverables save and show. |
| F-COM-04 | P1 | Auditor<br>`auditor1@futran.demo` | Auditor sees no fees | F-COM-03 | Open the same commercial page. | No fee, rate or retainer amounts are shown. |
| F-COM-05 | P2 | Auditor<br>`auditor1@futran.demo` | Raise a change order | Meridian | Commercial page › Raise change order (priced from the price list). Only extra systems, jurisdictions, documents, readouts or vendors can be change orders; try A-05 as well. | It waits for the Engagement Manager. A-05 is refused with the list of allowed kinds. |
| F-COM-06 | P2 | Engagement Manager<br>`em@futran.demo` | Approve the change order, then the client | F-COM-05 | Approve as Engagement Manager. Then complete C-R2-01 as Katrin. | Status moves to waiting for the client, then approved. It is billed once as its own milestone. |
| F-COM-07 | P1 | Auditor<br>`auditor1@futran.demo` | Weekly timesheet |  | Time and hours › log hours on two days for Meridian › Submit week. | The week locks after submit. Previous week and Next week move between weeks. |
| F-COM-08 | P1 | Engagement Manager<br>`em@futran.demo` | Approve a timesheet; never your own | F-COM-07 | Approve Alex's week. Then log and submit a week of your own and try to approve it. | Alex's week is approved. Your own is refused. |
| F-COM-09 | P2 | Auditor<br>`auditor2@futran.demo` | Hours only to assigned clients |  | Time and hours › try to log hours to ABC Corp. | ABC Corp is not offered; only Priyanka's assigned clients. |
| F-COM-10 | P3 | Chief Auditor<br>`chief@futran.demo` | Banks, retainers and margins |  | Time and hours › banks and margins views. | Hours banks, retainers and margins show. Banks show an alert at 80% used. |
| F-COM-11 | P3 | Admin<br>`admin@futran.demo` | Standard cost per hour |  | Time and hours › set Cost per hour (US$). | Saved. Margins recalculate for the Chief Auditor and Sales Manager. |
| F-COM-12 | P3 | Chief Auditor<br>`chief@futran.demo` | Approve an incident engagement | An incident engagement draft | Open it › Approve incident engagement. | The engagement becomes active with your approval recorded. |

## F · Workspaces and groups

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-WS-01 | P2 | Auditor<br>`auditor1@futran.demo` | Discovery import with column mapping | Meridian; any CSV of Copilot licences or expenses | Engagement › discovery import › pick the export type › map columns › preview › import › confirm or dismiss each tool. | Matched vendors show before import. The import is kept as evidence with its fingerprint. Expense and proxy imports keep only AI vendor rows. |
| F-WS-02 | P2 | Auditor<br>`auditor1@futran.demo` | A discovery finding opens a sales opportunity the client never sees | F-WS-01 | Confirm a tool that maps to a service. Check Opportunities as Sam, and the client as Katrin. | An automatic opportunity appears for Sales. Katrin sees nothing about it. |
| F-WS-03 | P2 | Auditor<br>`auditor1@futran.demo` | Copilot readiness workspace | SET-07 (Contoso Copilot Test) | Open Contoso › Copilot readiness › Start the workspace. Import a licence report and a SharePoint permissions report. Add wave. Tick controls. Add Copilot to the AI register. Download the readiness report. | Site risk list builds from the imports. Waves have go or hold. Controls come from the approved template. The PDF downloads. |
| F-WS-04 | P1 | Auditor<br>`auditor1@futran.demo` | EU AI Act classification | SET-07 (Eurotech EU Test) with a registered system | Open the EU AI Act workspace › pick a system › set EU exposure, role and classification with reasoning › Send for legal sign-off. | Applicable articles and deadlines are worked out from your choices. The auditor cannot sign it off. |
| F-WS-05 | P1 | Legal/Compliance Reviewer<br>`legal@futran.demo` | Legal sign-off, and changes cancel it | F-WS-04 | Sign off the classification. Then as Alex change the role. | Signed off by Casey. Changing anything it covers cancels the sign-off. |
| F-WS-06 | P3 | Auditor<br>`auditor1@futran.demo` | Agent assurance record | A registered agent on a client | Open the agent › Assurance › record evaluation, red-team results and a conditional pass. | The agent's status is worked out from the latest record. The client sees the Assurance tab. |
| F-WS-07 | P2 | Chief Auditor<br>`chief@futran.demo` | Evidence vault and legal hold |  | Open ABC Corp › vault › Place legal hold with a matter reference › Release hold. | Hold placed and released with dates and your name. While held, nothing can be deleted. |
| F-WS-08 | P2 | Admin<br>`admin@futran.demo` | Retention never shorter than the letter |  | Vault › set retention to 3 years on a client whose letter says 7 › Save tier. | Saved, but nothing covered by the letter is deleted early: the vault shows items kept longer by the letter. History lists the change. |
| F-WS-09 | P2 | Admin<br>`admin@futran.demo` | Admin cannot place a legal hold |  | Open the vault. | Place legal hold is not offered. |
| F-WS-10 | P2 | Admin<br>`admin@futran.demo` | Build a client group | SET-08 | Open Parent Co › entities › Add entity › Sub Co as subsidiary › Save relationship. Add an end-client. | The group tree shows parent, subsidiary and end-client. Each stays its own client. |
| F-WS-11 | P3 | Admin<br>`admin@futran.demo` | A group cannot loop | F-WS-10 | Try to make Parent Co a subsidiary of Sub Co. | Refused with a plain message. |

## F · Assurance and administration

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| F-ADM-01 | P1 | Admin<br>`admin@futran.demo` | Add a Futran user and see the invitation |  | Users › Add user › Add and send invitation. Open Email log › Outbox. | The invitation is in the Outbox and the action is in the audit log. |
| F-ADM-02 | P2 | Admin<br>`admin@futran.demo` | Remove a role and deactivate a user | A test user from SET | Remove one role from Jordan, then put it back. Deactivate Morgan, then try to sign in as Morgan. | Role changes show at Morgan's next page load. A deactivated user cannot sign in. |
| F-ADM-03 | P3 | Admin<br>`admin@futran.demo` | Futran departments |  | Users › Departments › add one › set a user's department. | The department shows on the user. |
| F-ADM-04 | P2 | Chief Auditor<br>`chief@futran.demo` | Client users is read-only |  | Administration › Client users. Filter by client. | Every client's users with roles and status. Nothing can be edited here. |
| F-ADM-05 | P2 | Admin<br>`admin@futran.demo` | Document template edit and versions |  | Templates › edit a document template: first with a broken merge field such as {{ client.name, then a valid change. | The broken field is refused with its line. The valid edit saves as a new version and the old one stays in its history. There is no approval step for document templates (service templates have one: F-ADM-06). |
| F-ADM-06 | P2 | Admin<br>`admin@futran.demo` | Service template edit and approval |  | Service templates › open the Copilot readiness template › edit › send. As the Chief, approve. | Approved versions are fixed; a further edit makes a new draft. |
| F-ADM-07 | P3 | Admin<br>`admin@futran.demo` | Reference data: AI model list |  | Reference data › AI models › add a model › run the check. | The model is listed and the check result shows. |
| F-ADM-08 | P1 | Admin<br>`admin@futran.demo` | Email log and Outbox |  | Email log › Outbox tab › open an email. | Each email shows recipient, subject, time and body; invitation links can be opened. |
| F-ADM-09 | P3 | Admin<br>`admin@futran.demo` | Futran mailbox and groups |  | Email and groups › connect with the test provider › add a group. | The mailbox shows connected; the group is listed. |
| F-ADM-10 | P3 | Admin<br>`admin@futran.demo` | AI provider key never shown again | An Anthropic API key, or skip | Settings › AI provider › connect › test › remove. | The key is never shown after saving, only that one is set. |
| F-ADM-11 | P3 | Admin<br>`admin@futran.demo` | Settings show test mode |  | Administration › Settings. | Settings show read-only, including test mode (MFA off, email to the Outbox). |
| F-ADM-12 | P1 | Chief Auditor<br>`chief@futran.demo` | Audit log records your actions | After a few tests | Administration › Audit log. Filter by your name. | Your actions are listed with date and time on one line, client and detail. There is no edit or delete. |
| F-ADM-13 | P3 | Admin<br>`admin@futran.demo` | Opportunity scan settings |  | Turn on the opportunity scan and run it now. | New automatic opportunities appear for Sales. A change already opened is not opened twice. |
| F-ASR-01 | P2 | Chief Auditor<br>`chief@futran.demo` | Trust Center confirmations | C-DATA-06 done | Assurance › Trust Center confirmations › filter by client › confirm an item. | Grouped by client with a count. Items can be confirmed only against a signed report. |
| F-ASR-02 | P3 | Chief Auditor<br>`chief@futran.demo` | Client policy reviews | C-GOV-02 done | Assurance › Client policy reviews › open the policy the client sent for review › record yourself as having tailored it › try to remove yourself › start an annual review for that client. | The policy shows with its status and the client's note. You cannot remove yourself from the tailoring team. The annual review does not copy you in as Lead Auditor, with a notice saying why. |
| F-ASR-03 | P3 | Admin<br>`admin@futran.demo` | Platform trust register |  | Assurance › Platform trust. | The SOC 2 register and the platform's own AI entry show and can be updated. |

## C · Sign-in and homes

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-AUTH-01 | P1 | CAICO<br>`hannah.ortiz@northwind.example` | Accept an invitation | F-ONB-05. Open the invitation link from Email log › Outbox (as Admin) in a private window | Confirm details › set a password › accept the terms. | Lands on Getting started for Northwind. The link cannot be used again. |
| C-AUTH-02 | P1 | CAICO<br>`maria.lopez@abccorp.example` | Client sign-in | Private window | Go to /login and sign in. | Lands on Getting started. Menus: Home, Audit, AI governance, People and training, Data and integrations, Email. |
| C-AUTH-03 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Client email on the staff sign-in page is refused |  | Go to /staff/login and sign in as Maria. | Refused with a message pointing to the client sign-in page. |
| C-AUTH-04 | P1 | CAICO<br>`maria.lopez@abccorp.example` | Client cannot open staff pages | Signed in as Maria | Type /audits, /clients and /staff/admin in the address bar. | Sent back to the client home, with no Futran data. |
| C-AUTH-05 | P2 | CAICO<br>`katrin.vogel@meridian.example` | Data notice acknowledged at sign-in | Katrin edits and resends the data notice (C-PPL-07) | Sign in as aarav.menon@meridian.example. | Aarav is asked to acknowledge the notice before going further; the acknowledgement is recorded. |
| C-HOME-01 | P1 | Executive Sponsor<br>`robert.chen@abccorp.example` | Executive Sponsor home |  | Sign in. | Lands on Summary. Menus: Summary, Review, Report, Responses, Remediation, AI systems, Governance, Policies, Add-ons, own attestation and training. |
| C-HOME-02 | P2 | Data Protection Officer<br>`daniel.kim@abccorp.example` | DPO home |  | Sign in. | Lands on Data review. No People, Integrations or Email menus. |
| C-HOME-03 | P1 | Client Admin<br>`sam.okafor@abccorp.example` | Client Admin home |  | Sign in. | Lands on Admin home: role and department changes in a grid; a name opens the history. No Report or Responses menu. |
| C-HOME-04 | P1 | Department Compliance Lead<br>`priya.shah@abccorp.example` | Department Lead home |  | Sign in. | Lands on My department showing HR only. |
| C-HOME-05 | P1 | Contributor<br>`tom.reyes@abccorp.example` | Contributor home |  | Sign in. | Lands on My tasks. Menus: Review, Documents, Remediation, AI systems, New AI projects, own attestation and training. |
| C-HOME-06 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Getting started shows the nine stages |  | Open Getting started. Choose a stage. | Nine stages with Meridian at stage 3. A stage opens its screen, or a summary where the person cannot open that screen. |
| C-HOME-07 | P3 | Contributor<br>`tom.reyes@abccorp.example` | Contributor gets stage summaries, by keyboard too |  | Getting started timeline (on My tasks) › Tab to a stage › Enter. | A summary opens instead of a screen Tom cannot use. Works without a mouse. |
| C-HOME-08 | P2 | CAICO<br>`katrin.vogel@meridian.example` | Phone layout of the home |  | Open Getting started at phone width (375 px). | Stages run down the page. Tap targets are at least 44 px. No sideways scroll. |
| C-HOME-09 | P2 | CAICO<br>`katrin.vogel@meridian.example` | CAICO with Client Admin powers |  | Sign in and open each menu. | Lands on Getting started and sees the union of both roles' menus. |

## C · People and set-up

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-PPL-01 | P1 | CAICO<br>`hannah.cole@internal.futran.example` | Add departments and confirm the list | Futran internal is at stage 2 | People › Departments › Add department (two) › Confirm the department list. | List confirmed with date and name. |
| C-PPL-02 | P1 | CAICO<br>`hannah.cole@internal.futran.example` | Add a Department Compliance Lead per department | C-PPL-01 | People › Users › Add user with role Department Compliance Lead for each department. | Invitations go to the Outbox. The client moves to stage 3 once every department has a lead. |
| C-PPL-03 | P2 | Client Admin<br>`sam.okafor@abccorp.example` | Upload the department workbook |  | People › download the department workbook › add two people › upload to one department. | A preview shows adds and changes before applying. Applying adds them. |
| C-PPL-04 | P2 | Client Admin<br>`sam.okafor@abccorp.example` | Upload a bad file |  | Upload a workbook with a bad email and a role that does not exist. | The preview lists each problem by row and refuses to apply. |
| C-PPL-05 | P3 | Client Admin<br>`sam.okafor@abccorp.example` | Grid: filter, sort, search, bulk and row menu |  | People › Users: filter, sort, search; select several for the bulk bar; open a row menu and set a job level. | Each works. The job level shows in the grid. |
| C-PPL-06 | P2 | CAICO<br>`hannah.cole@internal.futran.example` | DPO and Executive Sponsor not appointed |  | Mark DPO and Executive Sponsor as Not appointed. | Saved. Later sign-offs name the CAICO as stand-in. |
| C-PPL-07 | P3 | CAICO<br>`katrin.vogel@meridian.example` | Edit and resend the data notice |  | Getting started › data notice › edit › resend. | A new notice version is recorded; users are asked to acknowledge at their next sign-in. |
| C-PPL-08 | P2 | Department Compliance Lead<br>`priya.shah@abccorp.example` | Department Lead can read but not manage people |  | Type /people in the address bar. | No People menu entry. The page opens read-only with her own department only; no add or edit actions. |
| C-PPL-09 | P3 | CAICO<br>`katrin.vogel@meridian.example` | People screens on a phone |  | People and Getting started at 375 px. | No sideways scroll on the page; grids scroll inside their box. |

## C · Discovery

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-DIS-01 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Answer the governance request | Meridian stage 3 | Governance: one item In place (names), one Will constitute (date, interim owner), one Not applicable (reason). Submit and confirm. | Each needs its detail. Will constitute creates a tracked commitment. |
| C-DIS-02 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Launch the attestation campaign | Data notice acknowledged | Attestation › Launch and get the staff link › Copy staff link. | The link is copied; the tracker shows 0 responses. |
| C-DIS-03 | P1 | (employee, no login)<br>`staff link` | Attestation on a phone | C-DIS-02 | Open the staff link on a phone. Answer and submit. | No sign-in. Fits the phone. The response shows on Katrin's tracker. |
| C-DIS-04 | P2 | CAICO<br>`katrin.vogel@meridian.example` | Close the campaign | C-DIS-03 | Close campaign. | The link stops accepting answers. 'What's left' on the Futran side updates. |
| C-DIS-05 | P2 | Data Protection Officer<br>`jonas.weber@meridian.example` | DPO reads individual answers | C-DIS-03 | Attestation. | Jonas sees individual answers. A Client Admin sees totals only. |
| C-DIS-06 | P3 | Any client user<br>`aarav.menon@meridian.example` | My AI attestation in the app | Campaign open | My AI attestation › answer › submit (also try at phone width). | Submitted; counted on the tracker. |

## C · AI systems and inventory

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-INV-01 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Live risk tier while adding a use case | Meridian stage 3 | AI systems › Add › use case. Pick personal data and 'Substantially assists or makes decisions about people'. | The tier updates as you choose: Tier 3, high risk. Named users with work emails are required to submit. |
| C-INV-02 | P1 | Department Compliance Lead<br>`aarav.menon@meridian.example` | No self-approval of a use case |  | Add and submit a use case in Engineering, then try to approve it. | Refused: someone else must approve it. |
| C-INV-03 | P2 | Department Compliance Lead<br>`lena.fischer@meridian.example` | Approve or return another person's use case | A use case submitted in Data Science by someone else (Katrin) | Open it › return with a note, then approve after resubmission. | Return sends it back with the note; approve sets it approved. |
| C-INV-04 | P2 | (named user, no login)<br>`link from the Outbox` | Named-user confirmation on a phone | C-INV-01 with a named user who has no account | Open the confirmation link on a phone and confirm. | Confirmed; the use case shows the person as confirmed. |
| C-INV-05 | P2 | CAICO<br>`maria.lopez@abccorp.example` | One AI systems list |  | Open AI systems. Use the filters. Try the old addresses /inventory and /systems. | One list for the register, the inventory and the audit's systems. Old addresses redirect here with a filter. |
| C-INV-06 | P1 | Contributor<br>`tom.reyes@abccorp.example` | Contributor sees only their department |  | Open AI systems. | Only HR's inventory and audit systems; no register editing. |
| C-INV-07 | P2 | Contributor<br>`tom.reyes@abccorp.example` | No new use cases once the inventory is locked | ABC Corp (locked by sign-off 4) | Look for Add a use case. | Not offered. |
| C-INV-08 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Register a new system |  | AI systems › Add › new system: departments, who uses it, owner by department, model, whose data, places. Accept a suggested law. | Suggested laws appear from the places, each with its own Add button. Saving keeps the places and the law with its reason. |
| C-INV-09 | P2 | Client Admin<br>`sam.okafor@abccorp.example` | Import from inventory and bulk edit with a reason |  | Register grid › import from inventory › bulk edit two rows with a reason › open a row's change history. | One click makes one write. The bulk edit is in each row's history with the reason. |
| C-INV-10 | P2 | Department Compliance Lead<br>`priya.shah@abccorp.example` | Go-live gate refusal | A register system in development that is missing required roles or law requirements (for example one with NYC Local Law 144) | Submit it for go-live. Also try one still at Proposed. | Refused, listing each missing role and requirement. From Proposed it is refused because only systems in development can be submitted. |
| C-INV-11 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Roles editor and history |  | Open a system › Roles tab › assign roles. History › add a history entry or the no-incident statement. | Roles save. The history shows the entry. |
| C-INV-12 | P3 | CAICO<br>`katrin.vogel@meridian.example` | Register an agent |  | AI systems › Add › agent. | Listed as an agent. Futran can sample its decisions (F-WS-06). |
| C-INV-13 | P3 | CAICO<br>`katrin.vogel@meridian.example` | The list on a phone |  | AI systems at 375 px: filters, the Add menu and a row menu. | Everything fits with no sideways scroll; targets 44 px. |
| C-INV-14 | P3 | CAICO<br>`hannah.ortiz@northwind.example` | Explain this question; no copilot for clients | A client whose audit is open and has AI turned on (F-AUD-25). ABC Corp's audit is closed with AI off. | Open an audit question that the client can pre-fill. | 'Explain this question' is offered. No AI copilot suggestions are shown to the client. |

## C · Review and sign-offs

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-REV-01 | P1 | Department Compliance Lead<br>`aarav.menon@meridian.example` | Sign-off 2 for a department | Meridian at stage 4, every Engineering use case approved and named users confirmed | Review › sign-off 2 for Engineering (prepared by Katrin) › sign with your typed name. | Signed with name, date and time. Signing a sign-off you prepared is refused. |
| C-REV-02 | P1 | Data Protection Officer<br>`jonas.weber@meridian.example` | Sign-off 3 order: DPO then CAICO | Sign-off 3 sent | Jonas signs, then Katrin signs. | Katrin cannot sign before Jonas. Both signatures shown in order. |
| C-REV-03 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Sign-off 4 locks the inventory | Sign-off 3 done | Prepare sign-off 4. DPO signs, then the CAICO signs in place of the Executive Sponsor (not appointed). | The inventory locks and a snapshot version is kept. |
| C-REV-04 | P2 | Data Protection Officer<br>`jonas.weber@meridian.example` | Return and withdraw a sign-off | A sign-off waiting for Jonas | Return it with a comment. As the preparer, withdraw another one. | Return goes back with the comment; withdraw cancels it. Both are logged. |
| C-REV-05 | P2 | CAICO<br>`katrin.vogel@meridian.example` | Sign-off checked again at signing | A sign-off sent; then a new draft use case added | Try to sign. | Told something changed since it was sent and asked to return it. |
| C-REV-06 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Review on a finished audit |  | Open Review. | Department sign-offs, sign-offs 3 and 4 and the locked inventory snapshot are shown read-only. |

## C · Report, responses, remediation

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-DOC-01 | P1 | Data Protection Officer<br>`jonas.weber@meridian.example` | Upload a requested document | F-AUD-02 requested it from Jonas | Documents › upload a PDF against the request. | Shown as received; Futran sees it on the client's Documents. |
| C-DOC-02 | P2 | Contributor<br>`tom.reyes@abccorp.example` | Upload refused for a request not yours |  | Documents › look for other people's requests. | Only requests for Tom's system or department are listed. |
| C-RPT-01 | P1 | CAICO<br>`maria.lopez@abccorp.example` | Client sees only released versions |  | Report. | Only Client v1.0 and Final v1.1. No drafts, no lead review, no Futran notes or staff IP addresses. |
| C-RPT-02 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Acknowledgement and public summary |  | Report › read the acknowledgement and the approved public summary. | The acknowledgement says signing means received and read, not that every finding is agreed. |
| C-RPT-03 | P2 | Department Compliance Lead<br>`priya.shah@abccorp.example` | Department Lead has no Report menu |  | Type /report. | No access to the full report. |
| C-RPT-04 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Nothing from another client |  | Open Report, AI systems and Documents. | Only Meridian's data. Nothing from ABC Corp anywhere. |
| C-RSP-01 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Respond to findings | Meridian (or any client) at stage 7. ABC Corp is past this stage. | Responses › agree on one (planned action, owner, due date), disagree on another with a reason. | Disagree records the reason and creates no remediation item. Finding text cannot be edited. |
| C-RSP-02 | P2 | Department Compliance Lead<br>`aarav.menon@meridian.example` | Department Lead responds to their department only | Meridian at stage 7 | Responses. | Only Engineering's findings can be answered. |
| C-RSP-03 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Sign-off 6: CAICO then Executive Sponsor | Meridian at stage 7, all responses marked adequate | A Department Lead sends for sign-off 6. Katrin signs; with no Executive Sponsor appointed she is asked to sign in that place too. | Signed in order (CAICO, then Executive Sponsor or the CAICO standing in); the engagement moves to stage 8. |
| C-REM-01 | P2 | Department Compliance Lead<br>`aarav.menon@meridian.example` | Mark a remediation item done | Meridian at stage 9, an item owned by Engineering | Remediation › in progress › done with a note. | Status shows done; Futran sees it waiting for verification. |
| C-REM-02 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Commitments appear in Remediation |  | Remediation. | Governance commitments from stage 3 appear alongside response actions. |
| C-RPT-05 | P2 | CAICO<br>`(CAICO of the client in F-AUD-21)` | Approve the public summary (sign-off 8) | F-AUD-21, on a client with a New York site (for example the one from F-ONB-01) | Report › approve the public summary. | Approved with name and date; Futran sees sign-off 8 done. |

## C · Governance

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-GOV-01 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Company roles and committees |  | AI governance › Company roles › set a role holder › add a committee member. | Saved. The bias and fairness review committee shows as a committee. |
| C-GOV-02 | P2 | CAICO<br>`CAICO of your F-ONB-01 client` | Build a policy from a commitment, approve, ask for acknowledgement | A client with an open 'Create AI acceptable use policy' commitment (it appears once the client records its governance structure at stage 3). ABC Corp's is already closed, so use the client from F-ONB-01. | Policies › build the acceptable use policy from the Will create commitment › approve › ask staff to acknowledge. | The policy is approved and the commitment closes. Staff see an acknowledgement request. |
| C-GOV-03 | P2 | Data Protection Officer<br>`daniel.kim@abccorp.example` | DPO edits but cannot approve a policy |  | Policies › edit a draft › look for Approve. | Editing works; approve is not offered. |
| C-GOV-04 | P2 | Contributor<br>`tom.reyes@abccorp.example` | Submit a new AI project |  | New AI projects › new › fill the intake. | A live tier shows as you answer. The project is submitted for review. |
| C-GOV-05 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Decide a project with conditions | C-GOV-04, reviews done by the DPO and Department Lead | Open the project › conditional approval with conditions. | Approved with conditions; it becomes a register system. |
| C-GOV-06 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Regulatory updates for the client | F-LAW-07 published an update that affects ABC | AI governance › Regulatory updates. | The update shows with its impact for ABC. |
| C-GOV-07 | P2 | Executive Sponsor<br>`robert.chen@abccorp.example` | Request and approve an add-on |  | As Maria request the tracing add-on. As Robert approve it. | Maria can only request; Robert approves. The tracing tab unlocks. |
| C-GOV-08 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Tracing and an incident with deadlines | C-GOV-07 | Open a system › Tracing › add a trace › record an incident. | Incident deadlines are worked out and shown. |

## C · Change orders, Copilot, group

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-R2-01 | P1 | CAICO<br>`katrin.vogel@meridian.example` | Approve or reject a change order | F-COM-06 (approved by the Engagement Manager) | Audit › Change orders › open › approve. (On a second one, reject with a note.) | Approved shows the price; rejecting needs a note. Futran sees the decision. |
| C-R2-02 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Copilot readiness with no Copilot engagement |  | AI governance › Copilot readiness. | A plain message that there is no Copilot readiness work yet. |
| C-R2-03 | P2 | CAICO<br>`carla.ruiz@contoso.example` | Update Copilot sites on a phone | SET-07 (Carla's invitation accepted) and F-WS-03 | Copilot readiness at phone width › change a site's owner, status and note. | Saved; Futran sees the change. Futran-only notes are not shown. |
| C-R2-04 | P2 | CAICO<br>`erik.lund@eurotech.example` | Read a signed-off EU AI Act classification | F-WS-05 | Open the system. | The classification shows only once signed off. |
| C-R2-05 | P1 | CAICO<br>`sid.okafor@subco.example` | Subsidiary gives and withdraws roll-up consent | F-WS-10 | AI governance › Group › give consent › withdraw. | Messages: 'Consent given. The parent now sees the counts below, nothing else.' then 'Consent withdrawn…'. Both logged. |
| C-R2-06 | P1 | CAICO<br>`pat.romero@parentco.example` | Parent sees counts only, and only with consent | C-R2-05 (consent given) | AI governance › Group. | Sub Co's counts and statuses only; no names, systems or documents. After withdrawal, nothing. |
| C-R2-07 | P1 | CAICO<br>`maria.lopez@abccorp.example` | No Futran prices or margins anywhere |  | Look through Change orders, Add-ons and Report. | Only prices agreed with the client. No list prices, floors, margins or sales notes. |

## C · Data, training, email

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| C-DATA-01 | P2 | Client Admin<br>`sam.okafor@abccorp.example` | Integrations: expenses and Google Workspace |  | Integrations › upload an expense file › connect Google Workspace (test consent) › confirm or dismiss each discovered tool. | Confirmed tools go to the AI systems list with a link to them. |
| C-DATA-02 | P3 | CAICO<br>`maria.lopez@abccorp.example` | CAICO reads integrations without decisions |  | Integrations. | Read-only. Monitoring checks can be run. |
| C-DATA-03 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Monitoring alerts |  | Monitoring › run checks › act on an alert. | Results show; acting records who and when. |
| C-DATA-04 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Customer questionnaire at phone width |  | Customer questionnaires › new › answer from the answer library. | Answers are suggested from earlier answers. Fits a phone. |
| C-DATA-05 | P2 | Client Admin<br>`sam.okafor@abccorp.example` | API client and webhook; secrets show once |  | API and webhooks › create a client and a webhook. Leave and reopen. | The secret shows once only. The token works against the API reference page. |
| C-DATA-06 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Trust Center set-up and public page |  | Trust Center › set up items › publish. Open the public page in a private window. | The public page shows only items Futran has confirmed (F-ASR-01). |
| C-DATA-07 | P3 | CAICO<br>`CAICO of your F-ONB-01 client` | Bias test data: keep after retention | A bias test run on the client's system: as auditor1, open the system's Bias tests and upload an applicant file with id, selected, sex and race columns. ABC Corp has none. | Bias test data at phone width › Keep one set; leave the other. | The kept set shows 'Kept after the retention period' and the change is in the audit log. The other is deleted when the retention period ends; there is no delete-now button. |
| C-TRN-01 | P2 | CAICO<br>`maria.lopez@abccorp.example` | Assign a training module to HR |  | AI literacy training › assign a module to HR. | HR staff see it under My training. |
| C-TRN-02 | P2 | Contributor<br>`tom.reyes@abccorp.example` | Complete training on a phone | C-TRN-01 | My training › open the module › finish the quiz. | Completion recorded; Maria's tracker updates. |
| C-EML-01 | P3 | Client Admin<br>`sam.okafor@abccorp.example` | Connect the company mailbox |  | Email connection › connect with the test provider › test › remove. | Shows connected, then removed. |
| C-EML-02 | P3 | Client Admin<br>`sam.okafor@abccorp.example` | Groups: nested groups and a refused loop |  | Groups › add group A including group B, then try adding A inside B. | Nesting works; the loop is refused. |
| C-EML-03 | P3 | CAICO<br>`maria.lopez@abccorp.example` | Send to groups with counts | C-EML-02 | Send an attestation request to two groups. | The number of people reached is shown before sending; someone in both groups is counted and emailed once. |
| C-EML-04 | P3 | Department Compliance Lead<br>`priya.shah@abccorp.example` | Department Lead manages own groups only |  | Groups. | Only HR's groups can be changed. |

## X · Security and general

| ID | P | Sign in as | Test | Before | Steps | Expected |
|---|---|---|---|---|---|---|
| X-01 | P1 | CAICO<br>`maria.lopez@abccorp.example` | Tenant isolation by address | Copy a Meridian system address while signed in as Katrin | Paste it while signed in as Maria. | Not found. Nothing from Meridian. |
| X-02 | P2 | Any<br>`two windows` | Staff and client sessions don't clash |  | Sign in as chief in a normal window and as Maria in a private window. Work in both. | Each window keeps its own person. |
| X-03 | P1 | Sales Officer<br>`sales@futran.demo` | Sales cannot open audit findings |  | Type /clients/<ABC id>/findings. | Refused; no finding text shown. |
| X-04 | P1 | Any approver<br>`various` | Nobody approves their own work (sweep) |  | Try self-approval on: a template (Admin), a law change (author), a timesheet (EM), a proposal (Sales Manager), a mapping rule (Sales Manager), a use case (Department Lead), a regulatory update (Legal). | Every one is refused with a plain message. |
| X-05 | P1 | Admin<br>`admin@futran.demo` | Admin makes no audit judgements |  | Open a client in fieldwork as the Admin. | No approve finding, sign report or score actions. |
| X-06 | P2 | Chief Auditor<br>`chief@futran.demo` | Exports are safe to open in Excel |  | Put =1+1 as a name or note in a client item. Export a CSV that includes it (roles pivot, opportunities, billing). | Excel shows =1+1 as text, not 2. |
| X-07 | P3 | Any<br>`any` | Keyboard only |  | Sign in and use one full screen (People or Proposals) without a mouse. | Focus is visible; menus, dialogs and grids work with Tab, Enter, arrows and Esc. |
| X-08 | P2 | Any<br>`any` | Phone sweep |  | At 375 px open Getting started, AI systems, Review, Responses, the questionnaire and acceptance links, My training. | No sideways scroll; targets 44 px; text readable. |
| X-09 | P3 | Any<br>`any` | Session after restart |  | Close run.bat, start it again, refresh the browser. | Either still signed in or sent to sign-in; no error page. |
| X-10 | P3 | Admin<br>`admin@futran.demo` | Upload limits |  | Upload a file over 50 MB, and a file with a .exe extension, as evidence. | Both refused with a plain reason. PDF, Word, Excel, images, zip and email files are accepted. |
| X-11 | P2 | Chief Auditor<br>`chief@futran.demo` | Audit log covers client actions | After the client tests | Audit log › filter by a Meridian person or by Meridian's engagement. | Katrin's and Jonas's actions are listed. Entries cannot be edited or deleted. |
| X-12 | P3 | Any<br>`any` | Error pages |  | Open a made-up address such as /nothing-here. | A plain not-found page with a way home. |

## Reporting a failure

Give the case ID, the account, the page address, what you did, what you expected and what happened, with a screenshot.
