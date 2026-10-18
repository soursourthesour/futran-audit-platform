---
title: Futran Audit Platform
tags: [futran, ai-governance, audit-platform]
status: v1 complete
updated: 2026-10-18
---

# Futran Audit Platform

A multi-tenant web application for Futran's AI governance audits. It takes a client from the first draft of an engagement to verified remediation in nine stages:

1. Onboarding: new-client wizard, law suggestions, initiation package, Chief Auditor approval, sign-off 1
2. Setup: client departments and users
3. Discovery: governance structure request, employee attestation, AI inventory with live tiering
4. Client review: sign-offs 2–4 and the locked inventory snapshot
5. Fieldwork: AI systems, the per-system questionnaire, evidence and document requests, risk scoring, findings
6. Futran QA: findings approval, sign-off 5, the draft report with declarations
7. Response: management responses, Futran's adequacy review, sign-off 6
8. Final report: sign-off 7, the client's acknowledgement and, where NYC Local Law 144 applies, the public summary (sign-off 8)
9. Remediation: owners mark items done, Futran verifies, the Chief Auditor closes; the engagement is then complete

Futran staff and client users sign in to separate portals. Every client's data is kept to its own tenant, every action is checked against the permission matrix, and the audit log cannot be edited.

## Run it on Windows

You need Python 3.11 or later from python.org (tick "Add python.exe to PATH" when installing).

1. Double-click `setup.bat`. It installs the packages, writes `.env` with a new secret key, creates the database, loads the law matrix, question bank and templates, and asks for the first administrator. Copy the link it prints.
2. Double-click `run.bat`. The platform opens at http://localhost:8000.
3. Open the link from step 1 and set your password.

To load the demo clients, run `run.bat --reset-demo` from a command prompt in this folder. This deletes the database and starts again with the demo data, so only use it on a test copy.

If you lose the administrator link or forget a password, keep `run.bat` open and double-click `admin-link.bat`.

The database, uploaded files and Python packages live in `%LOCALAPPDATA%\FutranAuditPlatform`, not in this folder, so OneDrive never syncs a live database.

### From a fresh clone of the repository

The built web app is not stored in git. Build it once (Node.js 20 or later), then follow the Windows steps or the commands below.

```bash
cd frontend && npm ci && npm run build && cd ..          # writes backend/app/static
python -m venv .venv && .venv/bin/pip install -e backend    # on Windows: .venv\Scripts\pip
cd backend
cp ../.env.example ../.env && cp ../.env .env               # then set SECRET_KEY
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.cli seed-reference
../.venv/bin/python -m app.cli reset-demo                   # optional demo data (test mode only)
../.venv/bin/uvicorn --factory app.main:create_app --port 8000
```

## Demo sign-ins

All demo accounts use the password `Demo-Password-2026`. Sign-in codes are off in test mode.

| Portal | Email | Role |
|---|---|---|
| Staff (`/staff/login`) | chief@futran.demo | Chief Auditor |
| Staff | admin@futran.demo | Administrator |
| Staff | auditor1@futran.demo, auditor2@futran.demo | Auditor |
| Staff | qa@futran.demo | QA Reviewer |
| Staff | em@futran.demo | Engagement Manager |
| Client (`/login`) | maria.lopez@abccorp.example | ABC Corp: Chief AI Compliance Officer |
| Client | sam.okafor@abccorp.example | ABC Corp: Client Admin |
| Client | priya.shah@abccorp.example | ABC Corp: Department Compliance Lead, HR |
| Client | robert.chen@abccorp.example | ABC Corp: Executive Sponsor |
| Client | daniel.kim@abccorp.example | ABC Corp: Data Protection Officer |
| Client | katrin.vogel@meridian.example | Meridian GmbH: Chief AI Compliance Officer |

The demo contains:

- **ABC Corp** (New York, Chicago and remote staff): one engagement taken through every stage to completed, with four AI systems. SYS-001, the résumé screening tool, scores to the methodology's worked example (inherent 76, maturity 2.25, residual 58.2, rated High). A second engagement, "Annual review 2027", is waiting for the Chief Auditor's approval.
- **Meridian GmbH** (Berlin and Bangalore): at stage 3, discovery, with the EU AI Act, GDPR and India's DPDP Act in scope.
- **Futran Solutions (internal)**: Futran auditing its own AI use, at stage 2.

## Configuration

Settings are read from `.env` (see `.env.example`).

| Setting | Laptop default | Hosted (pilot or production) |
|---|---|---|
| `DATABASE_URL` | SQLite in `%LOCALAPPDATA%\FutranAuditPlatform` | Postgres, for example `postgresql+psycopg://user:pass@host/db` |
| `FILE_STORE` | `local:` folder next to the database | `local:/data/files` on a persistent disk (Azure Blob is on the backlog) |
| `MFA_REQUIRED` | `false` (test mode) | `true` |
| `EMAIL_MODE` | `outbox` (emails stay in Admin > Outbox) | `smtp` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | empty | the sending mailbox |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | empty (law updates off) | set to switch on Admin > Law updates |
| `DATA_REGION_LABEL` | `us-east` | per installation |
| `SESSION_IDLE_MIN`, `SESSION_MAX_HOURS` | 30, 12 | 30, 12 |
| `RETENTION_YEARS_DEFAULT` | 7 | 7 |
| `VIRUS_SCAN` | `off` | `clamav` when a ClamAV daemon is available |
| `BASE_URL` | `http://localhost:8000` | the public `https://` address (links in emails use it; cookies become secure) |
| `TRUST_PROXY_HEADERS` | `false` | `true` behind Render or Azure |
| `SECRET_KEY` | generated by `setup.bat` | a long random value, kept secret |

The platform is in **test mode** (red bar across the top) while `MFA_REQUIRED=false` or `EMAIL_MODE=outbox`. Demo data can only be loaded in test mode. Do not enter client data in test mode.

### Before real client data goes in

1. Set `MFA_REQUIRED=true`. Every user then sets up an authenticator app at their next sign-in and receives recovery codes. The app refuses to start with a weak `SECRET_KEY` once sign-in codes are on.
2. Switch on email: set `EMAIL_MODE=smtp` and the `SMTP_*` settings for the sending mailbox (for Microsoft 365: `smtp.office365.com`, port 587, the mailbox's sign-in, and `SMTP_FROM` set to that mailbox).
3. Restart. The red test-mode bar disappears when both are set.

### Claude law updates

Add `ANTHROPIC_API_KEY` (and optionally `CLAUDE_MODEL`) to `.env` and restart. Admin > Law updates then asks Claude to check the law matrix against current sources and lists proposed changes for an administrator to accept or reject. Nothing changes until it is accepted.

## Deploy to Render

The repository includes a `Dockerfile` that builds the web app and serves it with the API from one container.

1. In Render, create a **PostgreSQL** database and copy its internal connection string.
2. Create a **Web Service** from this repository, runtime **Docker**.
3. Add a persistent **disk** mounted at `/app/backend/data` for uploaded files and generated reports.
4. Set the environment variables: `DATABASE_URL` (the Postgres string, with the `postgresql+psycopg://` prefix), `SECRET_KEY`, `BASE_URL` (the service's `https://` address), `MFA_REQUIRED=true`, `EMAIL_MODE=smtp` and the `SMTP_*` settings, `TRUST_PROXY_HEADERS=true`, and optionally `ANTHROPIC_API_KEY`.
5. Deploy. On start the container applies database migrations, loads any missing reference data and serves on Render's `PORT`. The health check is `/api/v1/health`.
6. Create the first administrator from the Render shell: `python -m app.cli admin-link --email you@futransolutions.com --name "Your Name"`, then open the printed link.

The move to Azure (App Service, Azure Database for PostgreSQL, Blob storage and Key Vault) follows the same container and is on the backlog.

## Development

- Backend tests: `cd backend && .venv/bin/pytest` (about 485 tests).
- Browser tests: `bash e2e/run.sh` (Playwright: sign-in, admin, the wizard through fieldwork, the review-to-close journey, phone layouts and accessibility checks). Screenshots are written to `e2e/screenshots/`.
- Database changes: `backend/scripts/makemigration.sh "message"`.
- Specifications: `docs/spec/` (developer spec v0.3 and the build schematic). Build plan: `docs/superpowers/plans/`.

## After v1

The post-build backlog is in `docs/spec/Futran_Audit_Platform_Build_Schematic.md` §14 and the extended features in the developer spec §21–22. Open items from this build are in `docs/HANDOVER.md`.
