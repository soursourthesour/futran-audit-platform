---
title: Futran Audit Platform — wave 3 extended features (spec v0.3 §21, F1 to F19)
tags: [futran, audit-platform, change-log]
source: Futran_Audit_Platform_Developer_Spec_v0.3.md §21–22 and screens 25 to 35
status: built, independently reviewed and fixed; final test runs below
updated: 2026-11-02
---

# Wave 3: extended features

Wave 3 adds the §21 features (F1 to F19) and screens 25 to 35. Nothing in the nine-stage audit, the v0.6.1 modules or the register was replaced; the new work hangs off them. Six workstreams built it in parallel. Each workstream was then reviewed by a separate reviewer that had not seen the build, and the serious findings were fixed with a failing test first.

This file records what was built, the calls taken where the spec was silent, what the review found and fixed, what is deferred, and what needs doing before real client use. It will be updated as the work continues, like the earlier change logs.

Status key: **Done**, **Partly done**, **Not started**.

## What is new, by area

### AI copilot and AI foundation (F1, F5, F10; screen 25)

| Item | Status | Notes |
|---|---|---|
| AI rules | Done | Every AI output is a suggestion a person accepts, edits or rejects. Quotes are checked against the source text. Every call and every decision is logged. AI is off per engagement until the Chief Auditor turns it on with a consent note. |
| Pre-fill per section (screen 25) | Done | Suggestions show document, page, quote and confidence. The card shows the current answer and marks it verified or auditor-recorded. Accepting never replaces a verified answer without a "Replace" tick. |
| Evidence check, completeness review, ask the copilot, AI log | Done | The completeness review is advisory: it does not block a sign-off. |
| Draft finding text and summaries | Done | Using a summary in the report needs a "Replace" tick when a narrative exists; the old text is kept in the audit log. |
| Explain this question (client) | Done | Explains from the glossary and help text and never proposes an answer. The glossary is a 21-term working version; Appendix C should replace it. |
| Obligation extraction (F5) | Done | The Legal Reviewer approves or rejects each extracted obligation from their own queue. Long laws are read in parts. |
| Questionnaire automation (F10) | Done | Upload XLSX, DOCX or PDF; answers drafted 20 at a time from the answer library, published policies and the signed report. "Audited by Futran" is only proposed when the quote comes from the signed report, and only kept when the approver ticks to confirm it. |
| Copilot on the engagement-level (§4) assessment | Not started | System assessments only. |

### Regulatory change alerts and impact assessment (F4, F8; screens 26 and 28)

| Item | Status | Notes |
|---|---|---|
| Regulatory updates (screen 26) | Done | Entered by hand. The author cannot publish; a second person reviews. An update with an open verify note cannot be published until the reviewer clears the note (logged). Withdrawing an update cancels pending client alerts, closes its triggers and shows the client it was withdrawn and why. |
| What this means for you (client) | Done | Affected systems, open findings, due dates and a to-do list. Department Leads see their own department's systems. |
| Weekly digest | Done | Off by default. |
| New AI project impact assessment (screen 28) | Done | Department Compliance Lead review, then DPO (if any), then the CAICO decides. Nobody reviews or decides a project they started, edited or submitted. Approval adds the system to the register at "proposed". |
| Reassessment triggers | Done | Eight trigger types. A trigger reopens only the affected sections and never a locked system or closed engagement. The 12-month trigger counts a Futran audit as an assessment and never reopens anything. Every cleared verification is recorded in the audit log. |
| Export to the thought leadership pipeline | Partly done | CSV only. |

### Policy builder, AI literacy training and Trust Center (F7, F9, F12; screens 27, 32, 33)

| Item | Status | Notes |
|---|---|---|
| Policy builder (screen 27) | Done | Ten Futran templates; drafts built from guided answers with no AI. Approved by the CAICO, published as a PDF, sent to staff for acknowledgment. Publishing closes the "Will create" commitment it was started from, and only that kind. |
| Independence | Done | Futran people recorded as authors of a client's policy cannot be Lead Auditor for that client, in the wizard or in an annual review. Nobody can remove themselves from the author list; removing anyone needs a reason. |
| AI literacy training (screen 33) | Done | Five modules, quizzes scored on the server (80% pass), certificates, SCORM 1.2 export, reminders. |
| Trust Center (screen 32) | Done | Public page at /trust/<name>. Every item, and the heading and introduction, go public only after CAICO approval and Chief Auditor confirmation against a signed report. A retired policy leaves the page until the item is moved to the new version and confirmed again. NDA click-through for policy documents. |
| Template licensing | Not started | Any client can use the templates. |

### Integrations, AI discovery and monitoring (F2, F3; screens 30 and 31)

| Item | Status | Notes |
|---|---|---|
| Connectors | Done | Okta, Entra ID, Microsoft 365 (including Copilot usage) and Google Workspace (including Gemini), read-only. Expense and proxy CSV uploads, read once and not kept. |
| Proving the tenant | Done | After Microsoft admin consent the administrator signs in once; the tenant on that sign-in must match. The same check now protects the email connection. Only users who have signed in count towards a company's own domains. |
| Discovery | Done | Tools by department. People's names only for auditors on the client's open engagement and the Chief Auditor, only for Tier 2–3 tools, and every view is logged. |
| Monitoring (screen 31) | Done | Monthly, after each sync, and on demand. Alerts once per new failure. One client's error no longer stops the others. "Request new report" never reopens a closed engagement's records. Futran's plan note is shown to Futran only. |

### Bias calculator, heat map, lineage, benchmarking, annual review (F6, F11, F13, F15, F16; screens 29, 34, 35)

| Item | Status | Notes |
|---|---|---|
| Bias calculator (screen 29) | Done | Follows 6 RCNY §5-301; the rule's two worked examples are tests. Separate ethnicity and race columns are combined the EEO-1 way. Bad values are refused with the row number. Excluded categories appear as rows with their justification; a table with no selections keeps its rows as "not calculable". |
| Raw bias data | Done | Deleted daily unless the client keeps it, including any text the copilot extracted from it. |
| Heat map (screen 35) | Done | PNG download; a table in the report (the report renderer does not allow images). |
| Lineage (F6) | Done | Appendix E in the report. |
| Benchmarking (screen 34) | Done | Shown only with at least five consenting active clients in the peer group; peers are never named. |
| Annual review (F16) | Done | Creates a draft engagement from last year's. Only answers the client gave are carried, and only on client questions; auditor answers are not carried. The Lead Auditor goes through the independence check. "Confirm all for this system" confirms only that system. |
| Guardrail tests | Partly done | Fake adapter and the live gate are built; the live service has never been called. |

### Comments, public API, agent oversight, platform trust (F14, F17, F18, F19)

| Item | Status | Notes |
|---|---|---|
| Comments and mentions (F18) | Done | On any question (answered or not), evidence and document requests, findings and remediation. Futran comments are internal unless shared. Comments are never deleted; "withdraw" hides the text. |
| Public API (F17) | Done | /api/public/v1 with OAuth client credentials, scopes and rate limits. API clients can be transferred to another Client Admin; writes stop if the owner is no longer one. |
| Webhooks | Done | Signed, retried, HTTPS to public addresses only. The connection is pinned to the address that passed the check. Sends never hold the database. |
| Agent oversight (F14) | Done | Agent registration with change alerts (including autonomy), decision sampling with recorded seeds, override-rate trend, nine "Agentic AI" questions. |
| Platform trust (F19) | Done | SOC 2 readiness register and Futran's own AI features in Futran's register. |

## Calls taken where the spec was silent

Each is cheap to change if it is wrong.

1. With no Anthropic key and the platform in test mode, the copilot uses a built-in demonstration model and labels its suggestions as such (`AI_CLIENT=auto`). Set `AI_CLIENT=anthropic` to require a key. **Your decision.**
2. Independence blocks only the Lead Auditor role for Futran people who wrote a client's policy. The spec's wording ("same team cannot audit") could mean the whole team. **Your decision.**
3. Copilot quotes must be at least 25 characters and four words to count as verified.
4. The CAICO may approve a policy they drafted.
5. Publishing a policy closes its commitment straight away; a linked remediation item still waits for Futran to verify it.
6. The "Agentic AI" questions are optional, so engagements already running are not blocked at sign-off. Completion percentages for agent systems drop slightly because the questions now apply.
7. Okta connects with a client-entered client ID and secret; Entra ID and Microsoft 365 share one app registration.
8. API writes are recorded against the Client Admin who owns the API client, marked "Through API client …".
9. Pushing agent decision logs through the API needs the tracing add-on.
10. Override rate is escalated actions divided by all actions.
11. Bias unknowns are excluded per table; small categories (under 2%) are excluded by default, with a justification required.
12. Benchmark peer groups widen from industry and size, to industry, to size, to all consenting clients.
13. Annual reviews do not carry auditor answers; the auditor answers again and last year's answers stay on last year's engagement.

## Independent review

Each workstream was reviewed by a fresh reviewer against the spec and the code. The serious findings were fixed with a test that failed first.

**Critical, all fixed:**
- A client could connect another company's Microsoft tenant by editing the consent return link (AI discovery and email).
- Futran's internal monitoring plan note was visible to the client.
- Webhooks could be pointed at internal addresses through DNS rebinding.
- A slow webhook receiver could block every save on a SQLite installation.
- The 12-month reassessment job ignored Futran audits and would have cleared auditor verifications in an audit in progress.
- Annual reviews showed the client the auditor's answers and Futran's judgements as the client's own.
- Annual reviews copied the Lead Auditor without the independence check.

**Important, all fixed:** weak quote checking; "Audited by Futran" on unsupported answers; accepted suggestions overwriting verified answers; the AI-accepted marker being erased; large questionnaires failing (and costing money on retry); narrative overwritten without a copy; answers hidden in "Explain" term meanings; dismissed 12-month triggers coming back daily; false "new jurisdiction" alerts after a restart; withdrawn updates still going out; separation-of-duties bypasses on updates and projects; condition owners locked out; unverified updates published as fact; unconfirmed Trust Center heading text; policies closing the wrong commitment; authors removing themselves; retired policies staying public; ethnicity and race misread; stale exclusion notes in the LL144 summary; tables dropped from the summary; raw bias data left in the text cache; invalid scores accepted; "confirm all" confirming company-wide answers; deleted clients counted as benchmark peers; webhook timestamps 5 hours off; one bad webhook secret stopping all webhooks; API clients that could not be handed over; no comments on unanswered questions; autonomy changes without an alert; SOC 2 records of closed engagements reopened; a replaced SOC 2 report failing forever; one client's monitoring error stopping the others; a failed reconnection breaking a working connector; an endpoint without an authorisation check; past auditors seeing people's names.

## Deferred (minor)

- Bad reminder settings (non-numbers) give an error page instead of a message.
- Trust Center: a race on the first view of the day on PostgreSQL; the NDA token travels in the link; search-engine opt-in only works for crawlers that run JavaScript.
- First weekly digest after switching it on lists the whole backlog as "this week".
- A narrow reassessment resets the 12-month clock; the overdue check's button raises a narrow trigger.
- Published updates skip proposed systems whose impact assessment was approved.
- Department Leads see the company-wide deadline calendar.
- Re-running pre-fill leaves earlier suggestions acceptable; "Explain" has no cache; checklist-linked files skip the virus-scan filter before reaching the model.
- A peer median of exactly five clients equals one peer's score.
- Remediation comment rules differ slightly from the remediation screen; agent samples are tied to the current engagement; samples can be redrawn with a new seed; reply boxes do not say who will see the reply; `fec0::/10` counts as public.
- CSV uploads with extreme values give an error page; monitoring actions are not claimed atomically; some sync errors use mailbox wording; the plan note has no server-side length limit; "No run yet" names the wrong timing.
- Autonomy alerts from a bulk register edit are not emailed; webhooks try only the first public address.
- Withdrawing a regulatory update does not restore verifications its triggers cleared (they are in the audit log).
- The Microsoft sign-in step does not check that the person is an administrator (consent must already exist in that tenant).

## Before real client use

- **Microsoft app registrations.** The AI discovery app (`DISCOVERY_MS_CLIENT_ID`) needs the delegated `openid` permission. The email app needs nothing new. Google needs nothing new.
- **Live services never exercised:** the Okta, Microsoft and Google connectors, the Anthropic adapter, and the GuardRail adapter have only been tested against simulated responses. Try each against a test tenant or key first.
- **Demo regulatory updates:** Colorado SB 26-189 rests on a law-firm summary and waits for review with its verify note showing; California SB 947's signing date also comes from a law-firm summary and stays awaiting review.
- **Appendix C glossary** should replace the working 21-term glossary used by "Explain this question".

## Laptop update

- Your data was copied and upgraded in a rehearsal before anything was replaced. No existing table lost a row; AI systems and answers were unchanged. Changes on first start: one law added to the library, the nine "Agentic AI" questions added to the active question set, and Futran's own five AI features and 22 SOC 2 starter controls added in Futran's organisation.
- The first daily run sends invitation reminders and expiry notices for pending invitations. With `EMAIL_MODE=outbox` these go to the in-app outbox only. 22 people still have pending invitations; resend them from People > Users if they should stay open.
- demo.bat was not run. The .env file was not touched. No new Python packages are needed.

## Still to do

- Decisions 1 and 2 above.
- The six decisions listed in the v0.6.1 change log.
- The deferred items above.
- Copilot on the engagement-level assessment; template licensing; thought leadership export beyond CSV.
