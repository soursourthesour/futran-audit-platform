---
title: Futran Audit Platform — start here
tags: [futran, ai-governance, audit-platform]
status: in build
updated: 2026-10-14
---

# Futran Audit Platform

Multi-tenant AI governance audit platform: onboarding through remediation in nine stages. This folder is a working copy of the build. It is refreshed as each phase lands; the source of record is the GitHub repository `soursourthesour/futran-audit-platform`, branch `build/v1`.

## What works in this copy

| Phase | Scope | State |
|---|---|---|
| 1 | Sign-in, MFA, roles and permissions, audit log, outbox, invitations, admin screens | Done |
| 2 | Global law matrix import and versions, jurisdictions, Claude law updates, question bank, templates | Done |
| 3 | New-client wizard, law suggestions, initiation package (Word and PDF), Chief Auditor approval, client checklist, sign-off 1 | Done |
| 4 | Client users and departments, governance request, attestation, AI inventory | In build |
| 5 | AI systems, per-system assessment, document register, risk scoring | Not started |
| 6 | Notifications, sign-offs 2–8, fieldwork, findings, reports, remediation | Not started |
| 7 | Demo data, end-to-end test, hand-over | Not started |

An engagement can be set up, approved and signed. It stops at stage 2 until Phase 4 adds client users and departments.

## Run it on this laptop

You need Python 3.11 or later (python.org, tick "Add python.exe to PATH").

1. Double-click `setup.bat`. It installs the packages, creates the database, loads the law matrix and templates, and asks for the first administrator's name and email. Copy the link it prints.
2. Double-click `run.bat`. The platform opens at http://localhost:8000.
3. Open the link from step 1 and set a password.

There is no default password. If you skipped the email question in setup, lost the link, or forgot your password, double-click `admin-link.bat` while `run.bat` is running, enter your email (and your name for a new account), and open the link it prints.

The Python packages, database and uploaded files are kept in `%LOCALAPPDATA%\FutranAuditPlatform`, not in this folder, so OneDrive never syncs a live database. Settings are in `.env` in this folder.

## Before real client data goes in

- The red test-mode bar must be gone: set `MFA_REQUIRED=true` in `.env` and restart.
- Emails stay in Admin > Outbox until SMTP settings are added to `.env` and `EMAIL_MODE=smtp`.
- Uploads are not virus-scanned yet, and the platform runs only on this laptop. Hosting (Render, then Azure) comes after the build.

## Where things are

- `docs/spec/` — developer spec v0.2, build schematic, AI system questionnaire addendum
- `docs/superpowers/plans/` — the 34-task build plan
- `backend/` — FastAPI application and tests
- `frontend/` — React screens (already built into `backend/app/static`)
