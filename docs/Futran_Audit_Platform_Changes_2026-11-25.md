---
type: change-log
tags: [futran, audit-platform, eu-ai-act, bug-fixes, testing, performance, security]
updated: 2026-11-26
branch: build/v1
---

# Futran Audit Platform: changes of 25 Nov 2026

Four pieces of work: the EU AI Act risk level beside the Futran tier, the fixes for the 14 bugs from the 13 Nov test run, a second test wave (functional, coverage, permissions, security, accessibility and load) with its fixes, and on 26 November the website library API and Claude on AWS. The mail architecture reference for the AWS team is a separate note: [[Futran_Audit_Platform_Mail_Architecture]].

## 1. EU AI Act risk level beside the tier

### Why
The Futran tier (1 Baseline, 2 Elevated, 3 High-risk) rates harm from the data, the account and decisions about people. The EU AI Act sorts AI by what it is used for. The two don't map one to one, so renaming the tiers to EU terms would put the wrong legal label on some systems. A Tier 2 shadow ChatGPT account is not "limited risk" for that reason, and a Tier 1 customer chatbot is. The tier stays, and the EU level sits beside it.

### The four levels (the EU's own terms)
| Level | When | Source |
|---|---|---|
| Prohibited | An Art. 5 practice, such as emotion recognition at work or social scoring | Art. 5 |
| High-risk | A product-safety component under Annex I, or use in an Annex III area such as hiring, credit or public services | Art. 6, Annex I and III |
| Limited risk | Talks to people, generates content, recognises emotions or biometric categories, or makes deepfakes or public-interest text | Art. 50 |
| Minimal risk | None of the above | The Commission's term; the Act sets no duties |

"Low risk" is not an EU term; the EU uses "minimal risk". General-purpose AI is a flag on the system, not a level.

### How the level is set
- Three screening questions, first match wins: an Art. 5 practice; then Annex I or an Annex III area; then an Art. 50 situation; otherwise minimal.
- A documented Art. 6(3) assessment (a narrow procedural or preparatory task, with no profiling of people) takes an Annex III use out of high-risk. It never covers an Annex I product.
- On the register, a classification signed off by the legal reviewer in the EU AI Act workspace overrides the screening. If that classification is changed after sign-off, the screening applies again until it is re-signed.
- Until all three questions are answered, the level shows "Not screened".
- The wording of the questions and the labels lives in `backend/seeds/eu_ai_act.yaml`, so it can change without code.

### Where it shows
- **Use case form:** a new "EU AI Act screening" card, and an "EU AI Act risk level" panel next to the proposed tier that updates as you answer.
- **Futran correction:** after the client submits, the auditor can correct the screening with a reason. The reason goes in the audit log, and sign-off 5 locks it with the final tiers.
- **Lists:** an EU AI Act column on the AI inventory, the inventory review and the AI systems grid (with a filter), plus counts by level.
- **Register system:** an "EU AI Act risk level" card on the details tab and on step 4 of Add an AI system. Every change to the answers or the level is in the change history.
- **Other places:** the fieldwork header, the Futran register record, the report's per-system table (the most severe level among the system's use cases), the register CSV export, the public API (`eu_risk_level`) and the glossary.
- **Label changes:**
  - The EU AI Act workspace now says "Limited risk · transparency (Art. 50)" and "Minimal risk".
  - The register's tier names now match the inventory: "Tier 1 · Baseline", "Tier 2 · Elevated" and "Tier 3 · High-risk". They were Low, Medium and High.

### Data and upgrade
- One additive migration (`58f307875d99`): `eu_screening`, `eu_risk_level` and `eu_risk_reason` on `use_cases` and `register_systems`. Existing records show "Not screened" until someone answers.
- Rehearsed on a copy of the laptop database: the migration applied cleanly to 6 use cases and 10 register systems.
- The report template gains one row and the glossary gains the EU terms. On the laptop these arrive when you run `python -m app.cli seed-reference` after `run.bat` (corrected after the second test wave: they do not refresh on start). The hosted container runs seed-reference itself. Edited templates keep their text.

### Not changed
- Risk scoring still takes its EU input from the assessment answers (the high-risk floor of 70 on inherent risk), not from this level. Linking the two is a possible follow-up.

## 2. The 14 bugs from the 13 Nov test run

Two fixers worked in parallel. Each fix has a test that failed first. [[Futran_Audit_Platform_Test_Run_Report_2026-11-13]] has the original write-ups.

| Bug | Severity | Fix |
|---|---|---|
| BUG-04 | High | Every seed and template file is read and written as UTF-8. A guard test fails if any text read in the code leaves out the encoding. Also the repair script below. |
| BUG-08 | High | Publishing first builds missing applicability for clients set up before the law library. Earlier updates are matched when a law comes into scope or a geography is added. New command: `python -m app.cli rematch-reg-updates` (dry run; `--apply` to write). |
| BUG-05 | Medium | The Chief Auditor can add a team member, such as a QA Reviewer, to a running engagement from the client page (Add team member). The wizard's checks apply, and the addition is logged. |
| BUG-07 | Medium | Referrals can be recorded for prospects; Futran's own organisation is still refused. |
| BUG-12 | Medium | No attestation email for a closed campaign, from any screen. Reminders stop, and a send scheduled before an early close is cancelled when its time comes. The email log shows "Cancelled: campaign closed". |
| BUG-03 | Medium | A draft that was never submitted can be deleted by its creator or the CAICO while the inventory is open (Delete draft). |
| BUG-02 | Low | The Tier 3 reason names Local Law 144 only for New York City employment use, or when the use case is determined to be an AEDT. |
| BUG-09 | Low | "Correct with a reason" is offered only while a correction is allowed. |
| BUG-06 | Low | Report headings read "High findings (severity 4)" so they are not read as counts. A v0.2 signed before the upgrade stays valid. |
| BUG-10 | Low | Unknown addresses show a "Page not found" page. |
| BUG-14 | Low | Closing a dialog returns keyboard focus to what opened it, including from a row menu. |
| BUG-13 | Low | The upload message says "This file is over the 50 MB limit." |
| BUG-11 | Low | 44 px touch targets on the Estimator and Copilot readiness at phone width. |
| BUG-01 | Low | A stored file that is missing gives a plain message (410), not a server error. |

### The garbled-text repair script (laptop only, not yet run)
`backend/scripts/repair_mojibake.py` reverses text that was saved garbled on Windows before the BUG-04 fix.
- It changes only sequences that decode to characters the platform's text uses, so correct accents ("résumé", "NESTLÉ’s") are left alone.
- It runs as a dry run by default. The dry run writes every before/after pair to `mojibake-repair-changes.txt` next to the database.
- `--apply` writes a backup first and does everything in one transaction with one audit entry.
- Released, final and signed reports are skipped unless you add `--include-signed`.
- On a copy of the laptop data: 116 values to repair (8 LL144 control codes, 4 NIST titles, 80 question texts, 2 checklist items, 1 client requirement, 5 templates, 15 package documents, 1 report), 3 signed reports held back, and 0 left after applying.
- Run it before the fixed version first starts on the laptop. Otherwise seed-reference would see the 8 garbled LL144 controls as new; the loader now guards against that as well.
- It mostly touches demo clients. A hosted (AWS) install starts clean and doesn't need it.

## 3. Independent review
[[Chitragupta]] reviewed the merged branch without seeing the build, and found 7 important and 7 minor issues. Fixed before shipping:
- The repair script could change correct accented text, and a second pass could undo a first.
- The upgrade would have made a signed v0.2 look changed.
- A scheduled attestation send went out after an early close.
- The client could quietly undo Futran's EU correction.
- A ticked prohibited practice showed "Not screened".
- Futran could correct a client's draft.
- Signed-off EU classifications were not carried into the register.
- Re-matching an old update would have reopened verified audit answers.
- The legal wording missed points of Art. 5(1)(g), Art. 6(3) and (4) and Annex III.

Deferred, as before this branch or minor:
- The Engagement Manager and Legal reviewer seats accept any non-admin Futran user, in the wizard and the new add-member route.
- The report's EU level ignores the linked register system's signed-off classification.
- Add team member can't reach the running engagement while an annual-review draft exists.

## 4. Second test wave (25 Nov)

You asked for workstreams A to F in parallel, with the load test at 2,000 to 10,000 people. Each agent worked on its own copy of the data, never the laptop's. [[Futran_Audit_Platform_Test_Log]] holds every case, result and bug.

| Agent | Workstream | Result |
|---|---|---|
| [[Sakshi]] (two runs) | A · Run 2 of the 255 cases, Futran and client sides | 253 of 255 passed; the 18 retests of earlier bugs all passed |
| [[Kapila]] | B · Coverage: new cases for untested routes and the EU work | 76 new cases, 68 passed first time. Untested routes 26 → 15 of 171 |
| [[Yama]] | C · Permission matrix against all 841 routes | 6 findings; 5 fixed, 1 partly (Y02) |
| [[Hanuman]] | D · Security | No critical or high findings. Tenant isolation held. 11 medium/low findings; 8 fixed |
| [[Ganesha]] | E · Accessibility on three browser engines | Critical issues 12 → 0, serious 18 → 1 (a false positive) |
| [[Vayu]] | F · Load at 2,000, 6,500 and 10,000 people | The data notice timed out at about 6,500 people; 5 of 6 slow paths fixed |
| [[Ashvins]] (four fixers) | Fixes in separate branches | Merged into `build/v1` |
| [[Chitragupta]] | Review of the merged fixes | 6 fixed, 4 minor deferred |

58 bugs and observations in all: 52 fixed (after the evening fixes), 1 not a bug, 1 accepted (V06), 3 deferred (H08 and two minor review notes). Y02 was merged on 26 November, making 53 fixed. A fresh install on PostgreSQL 16 was proved end to end (BUG-K07, K08).

### Speed at 10,000 people (test machine, 2 CPUs)

| Action | Before | After |
|---|---|---|
| Send the employee data notice | 134 s (timed out) | 1.1 s |
| Email groups list | 68 s | 0.65 s |
| People search | 17 s | 0.07 s |
| Send to all | 20 s | 1.4 s |
| People list | 8 s | 1 s |
| Draft report, 100 systems | 13.4 s | 6.6 s |

## 5. Behaviour changes from the second wave

- **Data notice:** it now sends in the background after the request returns. A second send while one is running is refused ("already sending", 409).
- **Sign-in lock by address:** too many failed sign-ins from one address across different accounts locks that address for a while. Repeated tries at one account count once. To clear a lock: `python -m app.cli clear-login-lock <address>`.
- **run.bat** starts the server with `--no-proxy-headers`, so a client cannot fake its address to dodge the lock. Behind the AWS load balancer, `TRUST_PROXY_HEADERS=true` (the container default; keep it) makes the lock and rate limits use the address the load balancer adds (see [[Futran_Audit_Platform_Deployment_Architecture]]). Without it every user would share the load balancer's address and one bad actor could lock everyone out.
- **Upload size:** a request body over the upload limit (50 MB plus 1 MB of slack) is refused with 413 before it is read, including chunked uploads.
- **Security headers:** every page carries a content security policy, nosniff, X-Frame-Options and Referrer-Policy; HSTS on https. API answers carry `Cache-Control: no-store`. The unused ReDoc page is switched off; the API docs stay at `/api/docs`.
- **Separation of duties:** a CAICO cannot approve a policy they wrote, and the Chief Auditor cannot approve an intro letter they drafted or an offer they own. Where nobody else holds the role, the one holder may approve as a stand-in, and the audit log says so.
- **Admin** can no longer give themselves the Chief Auditor role.
- **Exports** neutralise spreadsheet formulas in client text (litigation CSV and two others).
- **Client text** can no longer add headings or tables to the report; backslashes are escaped too.
- **Expired invitations** show as expired, not pending.

### Migrations added in the wave (all additive)
- `66e4fe67c5ba`: widens the law text column (needed for PostgreSQL).
- The performance indexes follow it in one line of history. Head is `d6267bab780e`, checked on an empty database and on a copy of the laptop data (integrity ok).

## 6. Still open or deferred

- **Y02:** fixed and merged on 26 November (section 7).
- **V06:** in outbox (demo) mode the attestation send runs inside the request. Hosted installs use `EMAIL_MODE=smtp`, so this only affects the laptop demo. Accepted: not fixing for now.
- **H07:** fixed in the evening (section 7).
- **H08:** no in-app password or MFA reset yet. The live (AWS) team will build it.
- **H09:** fixed in the evening (section 7).
- **Review minors:** two tests (cross-tenant and call-graph) can pass for the wrong reason; an old error message can stay on screen after a reload; two other small notes.
- **Not yet measured:** mailbox daily caps at volume and memory growth under sustained load. Both belong with the AWS sizing.

## 7. Evening fixes: H09, H07 and Y02

Your decisions on the open items: V06 is accepted (demo mode only), H08 goes to the live team, and H09, H07 and Y02 were fixed in the evening. All three are on `build/v1`; you approved the Y02 role changes on 26 November. Two [[Ashvins]] fixers worked in parallel and [[Chitragupta]] reviewed each fix, more than once where it found gaps.

### H09: shared-link codes
- Any address gets the same answer, in the same time. Strangers get no code but meet the same limit of 3 requests per 10 minutes. The code email goes out after the response, so a recipient's answer is no slower than a stranger's.
- A used-up code reads the same as no code.
- Codes are 8 digits. A 6-digit code issued before the upgrade still works until it expires.
- Wrong codes are capped at 50 an hour per link and network address, so one person with a forwarded link can't lock out a campaign. A backstop of 1,000 an hour pauses the whole link and writes an entry to the email log.
- Addresses over 254 characters are refused.

### H07: limits on editable templates
One render of a document template is refused, with the reason in plain words, when it:
- takes more than 200,000 loop steps or calls;
- takes longer than 10 s (2 s for the trial render on save);
- builds one value over 1,000,000 characters or items, or more than 50,000,000 in total;
- writes more than 25,000,000 characters of output.

Template bodies over 500,000 characters are refused on save. Saving a runaway template gives "This template does too much work to render: … Simplify it." At generation the message is "The document template does too much work to render (…). An administrator can check the template."

The shipped report with 500 findings, 100 systems and 500 responses at about 1,600 characters a field renders in 0.24 s and uses about 5% of the total limit.

Not covered: a template holding many references to one value builds no new text and stays within memory, and is refused if it is turned into text. One very large sort can overrun the time limit by a few seconds. Only template editors can write templates.

### Y02: permission checks
The six matrix actions that no route checked are now enforced where the step happens:

| Action | Checked when | Who loses it |
|---|---|---|
| Propose tier | A department approves a use case | Nobody |
| Record named users | The named-user list on a use case changes (screen), and always refused through the public API | Auditor, through the API only |
| Approve governance | The CAICO submits the governance set-up | Nobody |
| Approve responses | A client signs sign-off 6 | Nobody (the CAICO still stands in for a missing Sponsor) |
| View initiation checklist | Getting started is opened or ticked | Executive Sponsor, DPO, Department Compliance Lead, Contributor (the menu already hid it) |
| View chief home | The Chief Auditor home loads | Nobody in practice |

The permission test that every matrix action is checked somewhere now passes. The public API also refuses named users: they are recorded in the platform. Two of the reviewer's notes stand as decided: Futran auditors could no longer change named users on a use case (the matrix doesn't grant it), and the Chief Auditor home check adds little, since other Futran staff see the same drafts on the dashboard within their own scope.

## 8. 26 November: the 20 November fixes merged, and a code trim

### The 20 November fixes
A separate line of work on 20 November (the first AWS hand-off package, never given to the team) fixed the same 13 November bugs as this branch and some more, but was never merged into GitHub. Everything it had that `build/v1` lacked is now merged, each with its own test:

- **OBS-04:** client change orders leave out Futran-internal fields (approval flag, approver names, internal references).
- **OBS-05:** uploads are checked by content, so a file must match its extension (a renamed `.exe` is refused). After review, real client files that the strict check refused are accepted: password-protected Office files, HTML or tab-separated `.xls` exports from web systems, RTF or HTML `.doc` files and UTF-16 text without a byte-order mark. A refused file's message says to save it again as PDF, Word, Excel or CSV.
- **OBS-06:** a monitoring result shows who took the action. **OBS-07:** a tool whose vendor and product match is named once. **OBS-08:** the client questionnaire page has a main heading.
- **API reference:** `/api/docs` and `/api/openapi.json` are served in test mode only. The reference is in the hand-off package.
- **PostgreSQL:** eight columns widened (seven short status and code columns and `monitor_checks.frequency`) and four lists given a fixed order (price list history, report context, finding lineage, a demo id). A test checks every text column's length against its model on PostgreSQL.
- **Follow-ups that make our earlier fixes complete:** BUG-12 (the email preview also refuses a closed campaign), BUG-08 (earlier updates reach a client whose applicability a later publish builds), BUG-03 (a draft named in an evidence request can't be deleted), BUG-02 (Local Law 144 named only for employment wording), BUG-06 (roadmap headings read "High priority (level 4)").
- **Commands:** `repair-text` and `rematch-updates` work as other names for the repair script and `rematch-reg-updates`. Both are dry runs unless `--apply`.

Migrations: the 20 November migrations keep their own ids, and a merge migration (`e3c1a9f0b742`) joins the two lines, so the chain has one head. Proved on an empty SQLite database, on a copy of the laptop data (integrity ok), and on PostgreSQL 16 from empty and from the 20 November head; the two PostgreSQL schemas came out identical.

### Code trim (bloat check)
An audit of the whole codebase found it lean: 1.17% duplication, no debug leftovers. Removed: 13 functions nothing calls, 27 unused imports, 7 unused frontend exports and a logo file, and three npm packages never imported (`react-hook-form`, `@hookform/resolvers`, `zod`). Python dependencies now declare what the app imports (`pypdf`, `Pillow`, already installed with `xhtml2pdf`) and drop two unused ones. The Docker image leaves out `backend/tests` (`backend/scripts` stays: `repair-text` loads the repair script from it).

Left for a later decision: code reached only by tests (for example the old law refresh path), three endpoints with no caller, the unused `ScopeItem` table, about 30 unused help strings and 14 CSS classes, and moving the 12 MB screens PDF out of the repo. The audit report is in the hand-off package's testing folder.

## 9. 26 November: the website library API and Claude on AWS

### Website library API
A public, read-only API lets the Futran website show the full law library and the AI court cases as the app shows them. Documentation: `docs/Futran_Audit_Platform_Website_Library_API.md`.

- **Endpoints** under `/api/public/v1/library`: `/laws` (search, the law library's filters, sort, pages), `/laws/{id}` (the full record: versions, requirements, approved obligations, scope, sources, related cases), `/cases` (the litigation tracker's filters), `/cases/{id}` (the full case with linked laws), and `/meta` (filter values, counts, last refresh).
- **Website keys:** Administration > Website API keys (Admin only). A key is shown once, stored only as a hash, limited to the website's own addresses (CORS) and to 120 requests a minute by default, and can be revoked. Creating and revoking keys is in the audit log.
- **Fast and safe:** responses carry ETag and `Cache-Control: public, max-age=300`, and the server keeps a small cache that refreshes when the records change.
- **What stays private:** anything that ties a law or case to a Futran client or staff member (client matches and applicability, opportunities, briefings, follows, reviewers and approvers, Futran-only talking points) and anything still awaiting review. A guard also replaces a client's name with "[client]" if one is typed into a published note.
- **Freshness:** both libraries keep updating through the existing scheduled refresh and its human review; the API serves what is published.

### Claude on AWS
The law and litigation refresh, and every AI feature, can now run on **Claude Platform on AWS**: Anthropic's own Claude API reached through the company's AWS account, billed through AWS Marketplace. Set-up: `docs/Futran_Audit_Platform_Claude_on_AWS.md`.

- **Why not Amazon Bedrock:** Claude on Bedrock does not support Anthropic's web search tool, which the refresh needs to find law changes and court cases. Claude Platform on AWS does.
- **Set-up:** Platform settings > AI provider > Claude Platform on AWS, with the AWS region and workspace id, signing with either an API key or the server's own AWS role (the ECS task role; no key stored). The Docker image includes what the AWS role needs. Or set `ANTHROPIC_AWS_REGION` and `ANTHROPIC_AWS_WORKSPACE_ID` (and `ANTHROPIC_AWS_API_KEY` for key mode) as environment settings.
- **IAM:** the task role needs `aws-external-anthropic:CreateInference` on the workspace. Egress: TCP 443 to `aws-external-anthropic.<region>.api.aws`.
- **Not yet tried against a live account.** First use: Test connection in Platform settings, then refresh one geography.

### Migrations
Two additive migrations: `f0ce163adcb2` (website API keys) and `130c86deb93f` (Claude Platform on AWS settings on the AI connection). One head: `130c86deb93f`.

## 10. Upgrade on the laptop (when you're ready)
Not installed yet. The steps, when you say go:
1. Stop the platform and back up the data folder.
2. Dry-run the repair script and read the changes file.
3. Apply the repair.
4. Run `run.bat`, which applies the migrations, then start the platform.
5. Run `python -m app.cli seed-reference` so the report template and glossary pick up the EU rows. (The laptop database is on `717087b4a6c3`, before both lines; it upgrades through both lines and on to `130c86deb93f`.)
6. Optionally, dry-run then apply `rematch-reg-updates`.

Your two earlier decisions (correct the signed ABC reports in place or not, and the acknowledged notices) only concern demo records. By default the script holds signed reports back.
