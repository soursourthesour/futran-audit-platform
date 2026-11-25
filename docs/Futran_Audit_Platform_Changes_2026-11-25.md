---
type: change-log
tags: [futran, audit-platform, eu-ai-act, bug-fixes]
updated: 2026-11-25
branch: build/v1
---

# Futran Audit Platform: changes of 25 Nov 2026

Two pieces of work: the EU AI Act risk level beside the Futran tier, and the fixes for the 14 bugs from the 13 Nov test run. The mail architecture reference for the AWS team is a separate note: [[Futran_Audit_Platform_Mail_Architecture]].

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
- The report template gains one row. Unedited templates refresh automatically on start; edited ones keep their text.

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

## 4. Upgrade on the laptop (when you're ready)
Not installed yet. The steps, when you say go:
1. Stop the platform and back up the data folder.
2. Dry-run the repair script and read the changes file.
3. Apply the repair.
4. Run `run.bat`, which applies the migrations, then start the platform.
5. Optionally, dry-run then apply `rematch-reg-updates`.

Your two earlier decisions (correct the signed ABC reports in place or not, and the acknowledged notices) only concern demo records. By default the script holds signed reports back.
