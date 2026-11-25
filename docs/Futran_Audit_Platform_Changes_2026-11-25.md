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
