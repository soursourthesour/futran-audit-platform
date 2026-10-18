---
title: Futran Audit Platform — hand-over
tags: [futran, ai-governance, audit-platform, handover]
status: v1 complete
updated: 2026-10-18
---

# Futran Audit Platform — hand-over

Version 1 covers spec v0.3 §1–20 (the nine-stage workflow from onboarding to verified remediation) and the build schematic. The extended features in spec §21 (copilot, integrations, monitoring, trust centre and the rest) are planned for phases 2–4 of the roadmap in §22 and are not in v1.

Source of record: GitHub `soursourthesour/futran-audit-platform`, branch `build/v1`.

## What is in v1

| Area | What it does |
|---|---|
| Access | Separate staff and client sign-in, TOTP sign-in codes with recovery codes, client terms acceptance, invitations, sessions, permission matrix with separation-of-duties rules, append-only audit log |
| Reference data | Global law matrix with versions and Claude-assisted updates (accepted by an administrator), jurisdictions, frameworks, governance and document catalogs, question bank (template v1.0 and addendum 5.1a), risk methodology v1, editable document templates |
| Stage 1 | New-client wizard with law suggestions, initiation package in Word and PDF, Chief Auditor approval, client checklist, sign-off 1 |
| Stages 2–4 | Departments and users (with CSV import), governance structure request with commitments, employee attestation by phone, AI inventory with live tiering and named-user confirmation, sign-offs 2–4, locked inventory snapshot |
| Stage 5 | AI systems register, per-system questionnaire with auto-drafted findings, client pre-fill, document request register with chasing and escalation, evidence requests, risk scoring (inherent, maturity, residual, knock-outs), fieldwork review of each use case |
| Stages 6–8 | Findings approval (QA Reviewer for the Chief Auditor's own findings), sign-off 5, the report (draft v0.1, lead review v0.2, client v1.0, final v1.1) with executive summary, findings, system profiles, maturity scorecard, roadmap, laws, declarations and appendices, management responses with adequacy review, sign-offs 6 and 7, the client's acknowledgement, the LL144 public summary (sign-off 8) |
| Stage 9 | Remediation tracker for response actions and governance commitments: owners mark done, an auditor verifies, the Chief Auditor closes; the engagement then completes |
| Notifications | In-app notifications and emails per spec §14, daily jobs (invitation warnings and expiry, due-soon reminders, escalations) and the Monday overdue digest |

## How it was checked

- 489 backend tests, including the scoring worked example (SYS-001: inherent 76, maturity 2.25, residual 58.2, High), the permission matrix for every role, and a cross-tenant check that calls 114 id-bearing routes as another client's user and expects every one to be refused.
- The demo seed takes ABC Corp from draft to completed through the real API, signing in as each role. It runs on SQLite and on PostgreSQL 16.
- 12 browser tests (Playwright): sign-in, administration, the wizard through fieldwork on a fresh database, the review-to-close journey from sign-off 5 to a completed engagement, the attestation and named-user pages at 375 px (no sideways scroll, every control at least 44 px), and an accessibility scan of 11 screens with no serious or critical issues.
- The Docker image builds, migrates, loads reference data and serves the login page and `/api/v1/health`.
- Each build phase had an independent code review; every Critical and Important finding was fixed with a test that failed first.

Second and later engagements for the same client (annual reviews) are a later-phase feature: v1 screens show one engagement per client.

Screenshots: `e2e/screenshots/` (one per screen from the browser tests; `demo/` from the demo data). Refresh the demo set with `node e2e/demo-shots.mjs` against a server loaded with `reset-demo`.

## Decisions taken during the build

The build ledger records 130 decisions where the spec was silent or two parts of it pulled in different directions. The ones a Futran reviewer should confirm:

1. **Sign-offs 2–4 open during discovery (stage 3).** Departments can sign off as soon as their inventory is approved, rather than waiting for the campaign to close.
2. **The inventory locks at sign-off 4.** Later changes need the CAICO to correct sign-off 4, which re-locks a new snapshot version. Corrections are possible up to fieldwork (stage 5); fieldwork cannot finish, and sign-off 5 cannot be sent, while any of sign-offs 2–4 is reopened. From stage 6 the inventory is fixed.
3. **Nobody signs their own work.** A sign-off whose only possible signer is the person preparing it is refused, with a message naming the missing role. The DPO and Executive Sponsor fall back to the CAICO when not appointed (spec §8).
4. **Findings the Chief Auditor wrote or edited go to the QA Reviewer.** Without a QA Reviewer on the team, the Chief Auditor cannot submit them.
5. **Declarations bind the report content.** The Lead Auditor, Engagement Manager and (if assigned) QA Reviewer sign the lead review version; if the report changes afterwards, release is refused until it is signed again. One person cannot sign two Futran declarations. With no QA Reviewer, the report says so.
6. **The executive summary and roadmap lock when the client draft is released.** The final report adds the management responses.
7. **A "disagree" response records the reason and creates no remediation item.** Organization-wide findings are answered by the CAICO; department findings by that department's lead.
8. **The public summary is required when NYC Local Law 144, or a law flagged "public summary", is in scope.** Impact ratios are entered by hand from the bias audit.
9. **Department Leads do not download the whole report.** It covers every department; they work from their findings and remediation items.
10. **Clients see their own people's activity in the audit log**, plus shared milestones (sign-offs, releases, remediation). Futran's working steps (draft findings, scores, report drafts) and staff IP addresses are not shown to clients.
11. **Stages move on by themselves** when their exit gate is met; the client page also offers "Move to stage N" when the gate is met.

## Open items

Minor findings from the reviews that were not fixed in v1:

- Approve and Return buttons appear for editors and submitters of a finding, who then get a refusal.
- The response form stays visible after the remediation plan is signed (saving is refused).
- Response due dates are not pre-filled from the severity defaults (30, 90, 182, 365 days).
- Two people saving the first response or the next finding number at the same moment can get an error and need to retry.
- The weekly digest goes to the CAICO and the auditors, not to each item owner.
- The response owner picker lists every client user to any client user who can respond.
- Sign-offs 2, 3 and 5 sign the on-screen state rather than a document, so their signatures carry no document hash.
- Withdrawing a sign-off leaves the signers' "waiting for you" notifications in place; the sign-off 5 notification opens the client page rather than Findings.
- The cross-tenant route test accepts a validation error (422) for 22 calls; a manual re-run with valid bodies refused every one.
- GET score and scorecard views can write a recalculated row; escalation audit rows; several smaller items listed in the Phase 3–5 review notes.

Configuration still to do before client data goes in: switch on sign-in codes and SMTP, set a strong `SECRET_KEY`, and decide on virus scanning (`VIRUS_SCAN=clamav` needs a ClamAV daemon). See the README.

## Backlog after v1

- Hosting: Render (Docker web service with PostgreSQL and a persistent disk), then Azure (App Service, PostgreSQL, Blob storage, Key Vault). Per-tenant data residency.
- Single sign-on (SAML or OIDC) per client; Microsoft 365 sending mailbox.
- Vendor no-login due diligence link, extended vendor checks, vendor records across engagements, CSV load of systems and vendors.
- Annual review carry-forward (copy the prior inventory, systems and open commitments), monthly scheduled law refresh, automated bias statistics, e-signature providers if a client requires them.
- Spec v0.3 §21 features by phase (§22): copilot, regulatory change alerts, policy builder, impact assessments, bias calculator, heat map, control carry-forward and comments in phase 2; integrations, monitoring, lineage, trust centre, questionnaire automation, training and benchmarking in phase 3; obligation extraction, guardrail tests, agent monitoring and the public API in phase 4.
