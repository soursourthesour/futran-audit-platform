---
title: Futran Audit Platform — test run report
tags: [futran, audit-platform, testing, bugs]
build: 1a7482c (Release 2)
run_on: 2026-11-13
data: copy of the laptop data (not the data itself)
status: complete
---

# Futran Audit Platform: test run report, 13 November 2026

All 255 cases in `Futran_Audit_Platform_Test_Cases_2026-11-13.xlsx` were run on a copy of the laptop data, served separately on port 8010. Your own data was not used for testing. The filled-in results are in `Futran_Audit_Platform_Test_Results_2026-11-13.xlsx`.

## Result

| | Cases | Pass | Fail | Blocked |
|---|---|---|---|---|
| P1 | 93 | 93 | 0 | 0 |
| P2 | 105 | 102 | 2 | 1 |
| P3 | 57 | 55 | 1 | 1 |
| **Total** | **255** | **250** | **3** | **2** |

Every P1 case passed. The 3 failures and 2 blocked cases:

| Case | Status | Why |
|---|---|---|
| F-PAR-02 | Fail | Referral refused for a prospect (BUG-07). |
| F-SAL-16 | Fail | Estimator works, but fields are 40 px tall at phone width (BUG-11). |
| X-12 | Fail | No not-found page (BUG-10). |
| F-HOME-07 | Blocked | Needs your own password for vsourya@futransolutions.com. Two roles on one person is covered by SET-04 and C-HOME-09. |
| F-COM-12 | Blocked | Needs an incident-response retainer; none exists and the price list has no retainer item. |

14 bugs were found while running cases that otherwise passed. They are listed below, most serious first.

## Bugs

### BUG-04 · High · Garbled characters in generated reports

- **What happens:** Client reports show 'â€“' and 'â€”' where dashes should be, for example 'Overall maturity (1â€“5)'. Seen in ABC Corp's Final v1.1 PDF and Word files on the laptop.
- **Seen in:** F-AUD-06
- **Cause:** 22 places read seed and template files with read_text() and no encoding, so on Windows they are read as cp1252 instead of UTF-8. The report templates (reports/service.py:74, reference/templates.py:80 and :86) and the seed YAML (questionnaire/seed.py, reference/catalogs.py and others) are affected.
- **Proposed fix:** Add encoding="utf-8" to every read_text() call, with a test that loads a template containing a dash. Then repair the laptop data: text already stored from the misread templates needs the same correction. I will ask before touching the laptop data.

### BUG-08 · High · Regulatory updates silently skip some clients

- **What happens:** ABC Corp and Meridian had no law-applicability records (they were set up before the law library), so updates published today never reached them. They were matched only after someone opened ABC's applicability page, and earlier updates were never re-matched.
- **Seen in:** F-LAW-07, C-GOV-06
- **Cause:** regupdates/service.py match() and match_org() match only at publish time and only against client_law_applicability rows.
- **Proposed fix:** Build a client's applicability before matching when it is missing, re-match open updates when applicability is created, and warn the publisher when any active client has no applicability records.

### BUG-05 · Medium · No way to add a QA Reviewer to a running engagement

- **What happens:** On Meridian, submitting a finding is refused with 'Add a QA Reviewer to the engagement team first', but no screen or endpoint adds a team member once the engagement is running.
- **Seen in:** F-AUD-15, F-AUD-22
- **Cause:** Team members are set only in the new-client wizard and the annual review.
- **Proposed fix:** Add 'Add team member' to the engagement team page for the Chief Auditor, with the same conflict confirmation and independence checks the wizard uses.

### BUG-07 · Medium · Referrals refused for prospects

- **What happens:** 'Record referral' on Fabrikam's opportunity is refused with 'Choose a client.' because Fabrikam is still a prospect. Referrals usually arrive before a company is a client.
- **Seen in:** F-PAR-02
- **Cause:** partners/service.py record_referral accepts only organisations of type client (line 132).
- **Proposed fix:** Accept prospect organisations as well; keep refusing Futran's own organisation.

### BUG-12 · Medium · Attestation request can be sent for a closed campaign

- **What happens:** Email › Send let Maria send the attestation request to two groups although ABC Corp's campaign closed on 27 October. The 3 people got a link that says 'This check-in has closed'.
- **Seen in:** C-EML-03
- **Cause:** The attestation screen's own send checks that the campaign is open (attestation/mail_links.py send_all); the general send in mail/groups_router.py does not.
- **Proposed fix:** Refuse the attestation template in Email › Send when the campaign is not open, with the same message the attestation screen gives.

### BUG-03 · Medium · A draft use case cannot be deleted

- **What happens:** After sign-off 3 was sent, a draft use case added by the CAICO blocked the signature ('Draft added after sending is still a draft'). The draft cannot be deleted, so the only way on was to submit and approve it.
- **Seen in:** C-REV-05
- **Cause:** No delete or withdraw action for draft use cases in the screen or the API.
- **Proposed fix:** Let the creator or the CAICO delete a draft that was never submitted, logged in the audit log.

### BUG-02 · Low · Tier 3 reason always mentions NYC Local Law 144

- **What happens:** Any use case that makes decisions about people gets 'Employment use in New York City may be an AEDT under Local Law 144', even a German credit model.
- **Seen in:** C-INV-01
- **Cause:** inventory/service.py tier_reason() line 46 adds the sentence unconditionally.
- **Proposed fix:** Add the sentence only when the use case runs in New York City and concerns employment decisions.

### BUG-11 · Low · Touch targets under 44 px on two staff screens

- **What happens:** At 375 px the Estimator has 10 fields at 40 px, and Futran's Copilot readiness workspace has 23 controls at 19 to 36 px. The spec asks for 44 px touch targets on every screen.
- **Seen in:** F-SAL-16, X-08
- **Cause:** These screens use compact input and button styles.
- **Proposed fix:** Use the standard 44 px control height on these screens at phone width.

### BUG-09 · Low · 'Correct with a reason' offered when correction is no longer allowed

- **What happens:** On ABC Corp's finished audit, Review offers 'Correct with a reason' on sign-offs 2 to 4, but the server refuses it ('can no longer be corrected: later work relies on it').
- **Seen in:** C-REV-06
- **Cause:** signoffs/router.py line 116 sets can_correct without the stage limit that correct() applies.
- **Proposed fix:** Apply the same CORRECTABLE_UNTIL stage check when working out can_correct.

### BUG-06 · Low · Report headings can be misread as counts

- **What happens:** Section headings such as 'High findings (4)' show the severity level, not the number of findings (there are 2 high findings).
- **Seen in:** F-AUD-06
- **Cause:** The report template prints the severity level in brackets.
- **Proposed fix:** Show the count, or write 'High findings (severity 4)'.

### BUG-10 · Low · No not-found page

- **What happens:** A made-up address such as /nothing-here shows the sign-in page or the home page with no message.
- **Seen in:** X-12
- **Cause:** frontend/src/routes.tsx line 45 sends every unknown path to Home.
- **Proposed fix:** Add a plain 'Page not found' screen with a link home.

### BUG-14 · Low · Keyboard focus lost after closing a dialog

- **What happens:** On People › Users, a dialog opened from a row menu (Job level) closes with Esc, but focus goes to the top of the page instead of back to the row.
- **Seen in:** X-07
- **Cause:** The dialog does not return focus to the control that opened it.
- **Proposed fix:** Return focus to the row menu button when the dialog closes.

### BUG-13 · Low · Upload size message gives the wrong size

- **What happens:** A 51 MB upload is refused with 'This one is 50.0 MB'.
- **Seen in:** X-10
- **Cause:** files/service.py line 60 measures only the bytes read, which stop just past the limit.
- **Proposed fix:** Say 'This file is over 50 MB' without a measured size.

### BUG-01 · Low · A missing stored file causes a server error

- **What happens:** Signing sign-off 1 crashed with a server error when the letter PDF was missing from storage. On the laptop the file exists; the copy held 72 of 187 stored files.
- **Seen in:** F-ONB-08
- **Cause:** Reading a stored file does not handle a missing file.
- **Proposed fix:** Return a clear message ('The stored file is missing. Ask Futran to upload it again.') and log it.

## Observations

These work as built but need a decision from you.

| ID | Observation | Seen in | Suggestion |
|---|---|---|---|
| OBS-01 | With no Executive Sponsor appointed, the CAICO both prepares and signs sign-off 4, so it is signed by the person who prepared it. | C-REV-03, C-PPL-06 | Decide whether a second person (for example the DPO) must sign in that case. |
| OBS-02 | A Contributor sees every inventory tool, including other departments' tools, shown with department 'Not assigned'. The code does this on purpose (company tool catalogue). | C-INV-06 | Decide whether the tool catalogue should be limited to the viewer's department. |
| OBS-03 | A client CAICO can write and approve the same policy. Document templates (Admin) go live on save with no approval; the spec allows this, but service templates do need the Chief's approval. | C-GOV-02, F-ADM-05, X-04 | Decide whether either needs a second approver. |
| OBS-04 | The change order data sent to the client's browser includes needs_price_approval and the Futran approvers' names. The screen does not show them. | C-R2-07 | Drop these fields from the client response. |
| OBS-05 | The upload type check uses the file name only, so an .exe renamed report.pdf is stored. Virus scanning is off in test mode. | X-10 | Check the file's content type as well, and confirm scanning is on for live use. |
| OBS-06 | A monitoring result shows when an action was taken but not who took it (the audit log has the name). | C-DATA-03 | Show the person next to the time. |
| OBS-07 | A discovered tool shows its name twice when vendor and product are the same ('Otter.ai Otter.ai'). | C-DATA-01 | Show the name once in that case. |
| OBS-08 | The client questionnaire page has no main heading (h1), which screen readers rely on. | F-SAL-13 | Make the page title an h1. |

## Role guide corrections

The cases were written from the role guide; these points in the guide do not match the platform and should be corrected there. The test cases have already been corrected.

- Mapping rules are kept by the Futran Admin and approved by the Pricing Approver, not the Sales Manager (F-PRC-09).
- The DPO sees all organisation-wide document requests, not only those addressed to them (C-DOC-02).
- Document templates have no Chief Auditor approval step; only service templates do (F-ADM-05, F-ADM-06).
- The client sees the final tier and its rationale (F-AUD-08).
- A Department Compliance Lead can open People read-only for their own department (C-PPL-08).
- Sales emails need the rep's own mailbox; Futran's mailbox is not a fallback (F-SAL-10).

## Proposed fix plan

1. **BUG-04 first.** Add `encoding="utf-8"` to all 22 `read_text()` calls, with a test. Then repair the report text already stored on the laptop. I will ask before touching the laptop data, and back it up first.
2. **BUG-08 and BUG-12**, which stop clients receiving what they should (law updates) or send them dead links (attestation).
3. **BUG-05, BUG-07 and BUG-03**, which block normal work: adding a QA Reviewer mid-engagement, recording referrals for prospects, removing a stray draft use case.
4. **The low-severity bugs** (BUG-02, -06, -09, -10, -11, -13, -14, -01) in one pass.
5. **Observations** once you have decided on each.

Each fix gets a test that fails first, the full test suite runs before each commit, migrations stay additive, and `run.bat` keeps its current form.

## How the run was done

- **Where:** a copy of `LocalAppData\FutranAuditPlatform` from the laptop, served on its own port in test mode (MFA off, emails to the Outbox, no scheduler). The copy held 72 of the 187 stored files; placeholders stood in for the rest.
- **How:** API calls for each step and outcome, and a real browser (Chromium) for screens, phone width (375 px), keyboard use and public links.
- **On the laptop:** only the backup and the test logins (sales@, salesmanager@, ceo@, president@, legal@ futran.demo, password `Demo-Password-2026`) were added. No test case ran there.
- **Test clients made on the copy only:** Harbor Test Co, Contoso Copilot Test, Eurotech EU Test, Parent Co, Sub Co, Fabrikam Freight and Lawref Logistics (both won) and Phone Check Co. Northwind, which on the laptop is still waiting for approval, was approved and taken to stage 2 on the copy only.
