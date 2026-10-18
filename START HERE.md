---
title: Futran Audit Platform — start here
tags: [futran, ai-governance, audit-platform]
status: v1 complete
updated: 2026-10-18
---

# Futran Audit Platform

Multi-tenant AI governance audit platform: onboarding through remediation in nine stages. This folder is a working copy of the build. It is refreshed as each phase lands; the source of record is the GitHub repository `soursourthesour/futran-audit-platform`, branch `build/v1`.

## What works in this copy

All nine stages, from the new-client wizard to verified remediation and a completed engagement, plus demo data. See `README.md` for configuration and hosting and `docs/HANDOVER.md` for what was built, how it was checked, the decisions to confirm and the open items.

To look around with the demo clients, run `run.bat --reset-demo` from a command prompt in this folder (it replaces the database), then sign in at http://localhost:8000/staff/login as `chief@futran.demo` with the password `Demo-Password-2026`. Client users sign in at http://localhost:8000/login, for example `maria.lopez@abccorp.example`.

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
- Uploads are not virus-scanned unless `VIRUS_SCAN=clamav` is set with a ClamAV daemon. Hosting on Render is described in the README; Azure comes after.

## Where things are

- `docs/spec/` — developer spec v0.3, build schematic, AI system questionnaire addendum
- `docs/superpowers/plans/` — the 34-task build plan
- `backend/` — FastAPI application and tests
- `frontend/` — React screens (already built into `backend/app/static`)
