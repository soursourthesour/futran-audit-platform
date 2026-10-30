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

To load the demo clients, run `run.bat --reset-demo` from a command prompt in this folder. With the laptop's SQLite database this deletes the database and starts again with the demo data, so only use it on a test copy. Uploaded files from before are left in the data folder. On PostgreSQL it does not delete anything and adds the demo on top, so use an empty database.

If you lose the administrator link or forget a password, keep `run.bat` open and double-click `admin-link.bat`.

The database, uploaded files and Python packages live in `%LOCALAPPDATA%\FutranAuditPlatform`, not in this folder, so OneDrive never syncs a live database.

### From a fresh clone of the repository

The built web app is not stored in git. Build it once (Node.js 20 or later), then follow the Windows steps or the commands below.

```bash
cd frontend && npm ci && npm run build && cd ..          # writes backend/app/static
python -m venv .venv && .venv/bin/pip install -e "backend[dev]"   # on Windows: .venv\Scripts\pip
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
| Staff | legal@futran.demo | Legal and Compliance Reviewer |
| Staff | sales@futran.demo | Sales Team |
| Client (`/login`) | maria.lopez@abccorp.example | ABC Corp: Chief AI Compliance Officer |
| Client | sam.okafor@abccorp.example | ABC Corp: Client Admin |
| Client | priya.shah@abccorp.example | ABC Corp: Department Compliance Lead, HR |
| Client | robert.chen@abccorp.example | ABC Corp: Executive Sponsor |
| Client | daniel.kim@abccorp.example | ABC Corp: Data Protection Officer |
| Client | tom.reyes@abccorp.example | ABC Corp: Contributor |
| Client | katrin.vogel@meridian.example | Meridian GmbH: Chief AI Compliance Officer |

The demo contains:

- **ABC Corp** (New York, Chicago and remote staff): one engagement taken through every stage to completed, with four AI systems. SYS-001, the résumé screening tool, scores to the methodology's worked example (inherent 76, maturity 2.25, residual 58.2, rated High).
- **Northwind Logistics**: a new client drafted by the auditor and waiting for the Chief Auditor's approval.
- **Meridian GmbH** (Berlin and Bangalore): at stage 3, discovery, with the EU AI Act, GDPR and India's DPDP Act in scope.
- **Futran Solutions (internal)**: Futran auditing its own AI use, at stage 2.

## Configuration

Settings are read from `.env` (see `.env.example`).

| Setting | Laptop default | Hosted (pilot or production) |
|---|---|---|
| `DATABASE_URL` | SQLite in `%LOCALAPPDATA%\FutranAuditPlatform` | Postgres, for example `postgresql+psycopg://user:pass@host/db` |
| `FILE_STORE` | `local:` folder next to the database | leave the default `local:./data/files`; on Render this is the persistent disk mounted at `/app/backend/data` (Azure Blob is on the backlog) |
| `MFA_REQUIRED` | `false` (test mode) | `true` |
| `EMAIL_MODE` | `outbox` (emails stay in Admin > Outbox) | `smtp` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | empty | the sending mailbox |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | empty (law updates off) | set to switch on Admin > Law updates |
| `DATA_REGION_LABEL` | `us-east` | per installation |
| `SESSION_IDLE_MIN`, `SESSION_MAX_HOURS` | 30, 12 | 30, 12 |
| `RETENTION_YEARS_DEFAULT` | 7 | 7 |
| `VIRUS_SCAN` | `off` | `off` for now: ClamAV scanning is not connected yet (on the backlog). Uploads are checked against the EICAR test signature only |
| `BASE_URL` | `http://localhost:8000` | the public `https://` address (links in emails use it; cookies become secure) |
| `TRUST_PROXY_HEADERS` | `false` | `true` behind Render or Azure |
| `SECRET_KEY` | generated by `setup.bat` | a long random value, kept secret |
| `ADDRESS_AUTOCOMPLETE` | blank (Photon) | `photon`, `google` or `off`; blank uses Google when a key is set, otherwise Photon |
| `GOOGLE_PLACES_API_KEY` | empty | optional; a Google Maps Platform key with Places API (New) enabled |
| `MS_CLIENT_ID`, `GOOGLE_CLIENT_ID` and the other email settings | empty (simulated in test mode) | see *Email: Microsoft 365 and Google Workspace* below |

The platform is in **test mode** (red bar across the top) while `MFA_REQUIRED=false` or `EMAIL_MODE=outbox`. Demo data can only be loaded in test mode. Do not enter client data in test mode.

### Before real client data goes in

1. Set `MFA_REQUIRED=true`. Every user then sets up an authenticator app at their next sign-in and receives recovery codes. The app refuses to start with a weak `SECRET_KEY` once sign-in codes are on.
2. Switch on email: set `EMAIL_MODE=smtp` and the `SMTP_*` settings for the sending mailbox (for Microsoft 365: `smtp.office365.com`, port 587, the mailbox's sign-in, and `SMTP_FROM` set to that mailbox).
3. Restart. The red test-mode bar disappears when both are set.

### Email: Microsoft 365 and Google Workspace (spec §26, §27.1)

Emails (invitations, the initiation package, reminders, the employee data notice, attestation requests and group sends) go out through a connected mailbox: Futran's (Admin > Email and groups, `/staff/admin/email`) and each client's (the Client Admin's "Connect your email", `/admin/email`). Until a mailbox is connected, or while the client IDs below are blank, email goes out exactly as before through `EMAIL_MODE` (the outbox in test mode, or SMTP). Every email is still listed in Admin > Outbox, and every send is in the email and admin log (`/admin/log`).

In test mode (`EMAIL_MODE=outbox`, or `MAIL_PROVIDER_MODE=fake`) both providers are simulated inside the platform: the consent page is the platform's own and the directory is a sample one. Nothing leaves the platform.

| Setting | Meaning |
|---|---|
| `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | the Entra ID app registration (blank: Microsoft 365 cannot be connected) |
| `MS_REDIRECT_URI` | blank uses `BASE_URL/api/v1/mail/oauth/microsoft365` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | the Google Cloud OAuth client (blank: Google Workspace cannot be connected) |
| `GOOGLE_REDIRECT_URI` | blank uses `BASE_URL/api/v1/mail/oauth/google` |
| `TOKEN_ENCRYPTION_KEY` | key for the stored OAuth tokens; blank derives one from `SECRET_KEY`. Changing either means mailboxes must be connected again |
| `MAIL_PROVIDER_MODE` | `auto` (simulated while `EMAIL_MODE=outbox`, real otherwise), `fake` or `live` |
| `MAIL_PACE_PER_MINUTE` | messages per minute per mailbox (default 30, the Exchange Online limit) |
| `MAIL_BCC_BATCH_SIZE` | recipients per BCC message (default 450; Exchange Online allows 500 by default) |
| `MAIL_LINK_DAYS` | default life of personal links (14) |

**What Futran IT registers once (Microsoft 365).** In the Microsoft Entra admin center: App registrations > New registration, "Futran Audit Platform", supported account types *Accounts in any organizational directory (multitenant)*, platform *Web*, redirect URI `https://<your host>/api/v1/mail/oauth/microsoft365`. Under API permissions add Microsoft Graph **application** permissions `Mail.Send`, `Mail.ReadWrite`, `User.Read.All`, `Group.Read.All`, `GroupMember.Read.All` (the organisation mailbox and directory sync) and **delegated** permissions `offline_access`, `openid`, `email`, `User.Read`, `Mail.Send`, `Mail.ReadWrite` (each user's own mailbox). Create a client secret and put the IDs in `.env`.

**What each organisation's IT approves (Microsoft 365).** A Global Administrator or Privileged Role Administrator grants admin consent once, from the platform's "Connect" button or the link the Client Admin emails them (it asks for `https://graph.microsoft.com/.default`, which is every application permission above). Application permissions to mail cover every mailbox in the tenant, so IT then limits the app to the one sending mailbox with RBAC for Applications in Exchange Online PowerShell:

```powershell
New-ServicePrincipal -AppId <application id> -ObjectId <enterprise application object id> -DisplayName "Futran Audit Platform"
New-ManagementScope -Name "Futran Audit Platform mailbox" -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'ai-governance@client.com'"
New-ManagementRoleAssignment -App <application id> -Role "Application Mail.Send" -CustomResourceScope "Futran Audit Platform mailbox"
New-ManagementRoleAssignment -App <application id> -Role "Application Mail.ReadWrite" -CustomResourceScope "Futran Audit Platform mailbox"
```

With the scoped assignments in place, IT may remove the tenant-wide Mail.Send and Mail.ReadWrite consent so only the scoped roles apply. (Application access policies, the older way to do this, are being replaced by RBAC for Applications.)

**What Futran IT registers once (Google Workspace).** In Google Cloud: enable the Gmail API and the Admin SDK API; OAuth consent screen with user type *External* (clients are other Workspace organisations); create an OAuth client ID of type *Web application* with redirect URI `https://<your host>/api/v1/mail/oauth/google`; add the scopes `gmail.send`, `gmail.modify`, `admin.directory.user.readonly`, `admin.directory.group.readonly`, `admin.directory.group.member.readonly`, `openid`, `email`. Put the IDs in `.env`.

**Google verification.** `gmail.send` is a *sensitive* scope and `gmail.modify` (needed to read replies back) is a *restricted* scope. Google requires app verification for sensitive scopes and, for restricted scopes, verification plus an annual third-party security assessment before users outside Futran's own Workspace can grant them. Until then, each client's Workspace admin can approve the app internally instead: Admin console > Security > Access and data control > API controls > Manage App Access, find the OAuth client ID, and set it to *Trusted*. A trusted app is not blocked as unverified for that organisation's users. The sending mailbox (a user account, not a group) then signs in from "Connect"; directory sync needs that account to hold an admin role that can read users and groups, or a second sign-in by such an admin.

**Sending limits** are configuration, not code: Exchange Online allows 30 messages a minute, 10,000 recipients a day and 500 recipients per message per mailbox; Gmail allows 2,000 messages a day per user and 2,000 recipients per message (500 external). Group sends are queued and paced (`MAIL_PACE_PER_MINUTE`); failures are retried after 1, 5 and 15 minutes and then show as bounced.

**Reply sync.** Every email sent through a connected mailbox carries a reference such as `[FAP-1042]` (FAP: Futran Audit Platform) in the subject. The platform reads back only the provider threads it started, and only messages whose subject still carries that reference; out-of-office replies and bounces update the recipient's status.

Documentation checked on 30 October 2026:
- Microsoft admin consent: https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent
- Microsoft delegated sign-in (authorization code): https://learn.microsoft.com/graph/auth-v2-user
- Graph create message (returns the conversation ID): https://learn.microsoft.com/en-us/graph/api/user-post-messages
- Graph sendMail: https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-beta
- RBAC for Applications for Mail.Send: https://office365itpros.com/2026/02/17/mail-send-rbac-for-applications/amp/
- Exchange Online sending limits: https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-sending-limits-troubleshoot
- Gmail API scopes and their classification: https://developers.google.com/workspace/gmail/api/auth/scopes
- Google OAuth for web server apps: https://developers.google.com/accounts/docs/OAuth
- Trusting an app in Google Workspace API controls: https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data
- Gmail sending limits: https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace
- Admin SDK Directory service: https://developers.google.com/apps-script/advanced/admin-sdk-directory

### Claude law updates

Add `ANTHROPIC_API_KEY` (and optionally `CLAUDE_MODEL`) to `.env` and restart. Admin > Law updates then asks Claude to check the law matrix against current sources and lists proposed changes for an administrator to accept or reject. Nothing changes until it is accepted.

### Address suggestions

When Futran staff type a client's address in the new-client wizard (the head office street, and the city of each site), the platform suggests full addresses and fills in the street, city, state or region, postal code and country from the one picked. Staff can always type the address by hand instead.

- **Photon** (default) uses OpenStreetMap data from `photon.komoot.io`. It is free and needs no key, but it is a shared public service with a fair-use policy: the platform asks only after three characters and a short pause in typing, and keeps answers for ten minutes. Only the text typed into the address field is sent.
- **Google Places** is used when `GOOGLE_PLACES_API_KEY` is set (or when `ADDRESS_AUTOCOMPLETE=google`). It calls Places Autocomplete while staff type and Place Details for the address picked, grouped into one billing session. Enable Places API (New) on the key and restrict the key to that API.
- `ADDRESS_AUTOCOMPLETE=off` switches suggestions off.

If the service cannot be reached, the field says "Suggestions unavailable" and works as a plain text field.

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

- Backend tests: `cd backend && ../.venv/bin/pytest` (about 490 tests; needs the `[dev]` extras).
- Browser tests: `bash e2e/run.sh` (Playwright: sign-in, admin, the wizard through fieldwork, the review-to-close journey, phone layouts and accessibility checks). Screenshots are written to `e2e/screenshots/`.
- Database changes: `backend/scripts/makemigration.sh "message"`.
- Specifications: `docs/spec/` (developer spec v0.3 and the build schematic). Build plan: `docs/superpowers/plans/`.

## After v1

The post-build backlog is in `docs/spec/Futran_Audit_Platform_Build_Schematic.md` §14 and the extended features in the developer spec §21–22. Open items from this build are in `docs/HANDOVER.md`.
