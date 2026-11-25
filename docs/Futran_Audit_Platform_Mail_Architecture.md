---
type: architecture
tags: [futran, audit-platform, email, aws]
updated: 2026-11-25
source: build/v1 code
---

# Futran Audit Platform: mail architecture and AWS runbook

Read from branch `build/v1` at commit `ce92beb`. File paths are relative to `backend/` unless they start with `docs/` or `frontend/`. "The code does X" means the code was read; "to confirm" means it was not. AWS placement is a target to confirm against the production account, which was not seen.

Related: [[Futran_Audit_Platform_Deployment_Architecture]] (`docs/`), README section "Email: Microsoft 365 and Google Workspace".

---

## 1. Summary

1. Every email the platform sends goes through one module, `app/mail/delivery.py`: it writes an `outbox_messages` row, then delivers through one channel: `outbox` (test mode, nothing leaves), `smtp`, `microsoft365` (Graph) or `google` (Gmail API).
2. System emails (invitations, notices, alerts, digests, codes) are sent **synchronously inside the request or daily job** that triggers them, with no retry; group sends (attestations, policy acknowledgments, training, regulatory alerts) are queued as `mail_recipients` rows and paced by an in-process APScheduler tick every minute, with two retries.
3. The sender is chosen per email: a client's own connected mailbox, else Futran's connected mailbox "on behalf of" the client, else SMTP. OAuth tokens are Fernet-encrypted in the database per organisation and per user.
4. On AWS the target is ECS on Fargate with RDS Postgres, Secrets Manager and egress on 443 to Microsoft and Google, plus SMTP on 587 to Amazon SES (or another relay) as the fallback channel.
5. **The one thing not to get wrong: run exactly one task, at all times, including during deployments.** A default ECS rolling deployment runs two tasks side by side (max 200 %), and ECS Express Mode uses canary deployments and CPU auto scaling up to 20 tasks by default; both put a second scheduler on the same outbox. Close behind: set `EMAIL_MODE=smtp` (the only setting that takes the platform out of test mode for mail) and reconnect every mailbox after the cut-over.

---

## 2. Flows

### 2.1 Outbound path

```mermaid
flowchart TD
  A["App action<br/>invite, notice, alert, digest, group send"] --> P{"Which entry point?"}
  P -->|"System email<br/>mail/service.py send()"| S1["Render Jinja file template<br/>resolve_sender()"]
  P -->|"Rep email<br/>sales, scoping, proposals"| S1
  P -->|"Group send<br/>mail/sending.py send_to_groups()"| G1["Expand groups to people<br/>MailSend + MailRecipient rows, status queued"]
  S1 --> R1["delivery.record()<br/>outbox_messages row"]
  R1 --> CH
  G1 --> D0["First dispatch() inline in the request<br/>up to MAIL_PACE_PER_MINUTE messages"]
  T["APScheduler mail tick, every 1 min<br/>run_mail_tick() then dispatch_due()"] --> D1
  D0 --> D1["_claim(): UPDATE status queued to sending<br/>only if still queued"]
  D1 --> R2["Issue personal link, render per person<br/>delivery.record() outbox row"]
  R2 --> CH{"Sender channel"}
  CH -->|"outbox (test mode)"| O["Stored only<br/>Email log, Outbox tab"]
  CH -->|smtp| SM["smtplib, STARTTLS<br/>SMTP_HOST:SMTP_PORT"]
  CH -->|microsoft365| MS["Graph: POST users/MAILBOX/messages<br/>then POST messages/ID/send"]
  CH -->|google| GM["Gmail: POST users/me/messages/send<br/>raw MIME"]
  SM --> OK{"Accepted?"}
  MS --> OK
  GM --> OK
  OK -->|yes| SENT["outbox row sent<br/>recipient sent, provider message and thread IDs"]
  SENT --> INBOX["Recipient mailbox"]
  OK -->|"no, system or rep email"| FB["recipient bounced, outbox row failed<br/>no retry"]
  OK -->|"no, group send"| RT{"attempts below 3?"}
  RT -->|yes| RQ["status queued again<br/>next_attempt_at now +1 min, then +5 min"]
  RQ --> T
  RT -->|no| BO["recipient bounced"]
```

Notes on the diagram:

- "Accepted" means the SMTP server or provider API accepted the message. Nothing in the SMTP path learns about later bounces (section 6.3). For Graph and Gmail, bounce messages that land in the sending mailbox are picked up by reply sync (2.3).
- The retry plan is `RETRY_MINUTES = (1, 5, 15)` in `app/mail/sending.py:53`, but the third failure marks the recipient bounced (`sending.py:416`), so the 15-minute step is never used: three attempts in total, at about t, t+1 and t+6 minutes. The README says "1, 5 and 15 minutes"; the code and `tests/mail/test_delivery.py::test_failed_sends_retry_then_show_as_bounced` say otherwise.
- A failure is recorded on the row, never raised, for `ProviderError` and SMTP errors. Other exceptions escape (gap G2 in section 10).

### 2.2 Mailbox connection (OAuth)

```mermaid
sequenceDiagram
  participant Admin as Futran Admin or Client Admin
  participant App as Platform (port 8000)
  participant IdP as Microsoft Entra ID or Google
  participant API as Graph or Gmail API
  Admin->>App: POST /api/v1/mail/futran/connect or /mail/client/connect
  App->>App: signed state (SECRET_KEY), nonce hash on the connection
  App-->>Admin: provider consent URL
  Admin->>IdP: consent (Microsoft: tenant admin consent, .default scope)
  IdP-->>App: GET /api/v1/mail/oauth/PROVIDER with state and code
  Note over App,IdP: Microsoft only: second step, admin signs in (OIDC) and the ID token must name the consenting tenant
  App->>IdP: token request (client credentials or authorization code)
  App->>API: read organization domains (Graph) or profile (Gmail)
  App->>App: check tenant verified the org's own domain, tenant not used by another org, mailbox in a verified domain
  App->>App: encrypt token set with TOKEN_ENCRYPTION_KEY, status connected, admin log entries
  App-->>Admin: redirect to BASE_URL/admin/email?connected=1
```

- Organisation mailbox: Futran's (E1, `/staff/admin/email`) and each client's (E2, `/admin/email`). A Client Admin can email an IT administrator a consent link (`it_consent_request`); the signed state is valid 7 days (`connections.py:28`).
- Personal mailbox (`/me/mailbox/connect`, spec §27.1): delegated OAuth, bound to the browser session that started it, valid 1 hour, and the signed-in mailbox must equal the user's own email (`connections.py:228-237`).
- Microsoft organisation tokens are app-only (client credentials) for the proven tenant; Graph sends to `/users/{mailbox}`. Microsoft delegated and all Google tokens carry a refresh token. Refreshed tokens are re-encrypted after each use (`tokens.save_if_refreshed`).

### 2.3 Inbound: reply sync (no inbound SMTP)

```mermaid
flowchart LR
  T["Mail tick, every 1 min"] --> DUE{"Any connected org mailbox<br/>past its sync interval?"}
  DUE -->|no| STOP["skip"]
  DUE -->|yes| LOOP["For each send in the last 60 days<br/>on channel microsoft365 or google"]
  LOOP --> READ["Read only the provider threads the platform started<br/>Graph conversationId or Gmail threadId"]
  READ --> FILTER{"Subject carries the send's reference<br/>e.g. FAP-1042?"}
  FILTER -->|no| SKIP["ignored"]
  FILTER -->|yes| CLASS{"classify()"}
  CLASS -->|bounce| B["MailReply kind bounce<br/>recipient bounced"]
  CLASS -->|"out of office"| OOO["MailReply kind out_of_office<br/>recipient flagged"]
  CLASS -->|reply| REP["MailReply kind reply<br/>audit log mail.reply, engagement activity"]
```

- There is no inbound SMTP, no webhook from Microsoft or Google, and no SES receiving. Replies are pulled by polling (`app/mail/replies.py`).
- Directory sync (Graph users and groups, Google Admin SDK Directory) also runs from the same tick when due (`app/mail/directory.py:167`), daily by default.

---

## 3. Components

| File or module | Job |
|---|---|
| `app/mail/delivery.py` | Core. `Sender`, `Envelope`, `resolve_sender()` (which mailbox sends), `record()` (outbox row), `deliver()` (channel dispatch), `_smtp()`, `_provider()`, `one_line()` header folding. |
| `app/mail/service.py` | `send()`: one system email from a Jinja file template; writes `MailSend` (kind `system`), `MailRecipient` rows and an admin log entry; `CLIENT_ORIGIN` lists templates that go from the client's mailbox. |
| `app/mail/sending.py` | Group sends: `send_to_groups()`, group expansion, rendering, personal and shared (BCC) links, `_claim()`, `dispatch()`, `dispatch_due()`, retry (`_apply`), pacing (`pace_limit`), `next_subject_ref()` (`FAP-n`). |
| `app/mail/reminders.py` | Reminder sends to non-responders on the send's `reminder_plan` days; claims each reminder with a conditional update. |
| `app/mail/jobs.py` | `run_mail_tick()`: dispatch, directory sync, reminders, reply sync, each in its own savepoint. |
| `app/notifications/jobs.py` | `start_scheduler()`: APScheduler `BackgroundScheduler` (UTC). Mail tick every 1 min; webhooks every 1 min; incident deadlines every 15 min; daily run at 10:00 UTC plus a 15-min catch-up and a run on start. Daily email jobs: invitation warnings, due-soon, Monday overdue digest, regulatory digest, scoping reminders, proposal follow-ups, others. |
| `app/notifications/service.py` | `notify()`: in-app notification, plus an email when the event is an email event (`notifications/events.py`) or the caller passes `email_template`, and only when `settings` is passed. |
| `app/mail/providers/__init__.py` | Adapter selection (`get_adapter`), fake vs live (`use_fake`), credential status, redirect URIs. |
| `app/mail/providers/microsoft.py` | Graph adapter: admin consent, tenant proof, app and delegated tokens, send (create draft then send), thread read, directory read. |
| `app/mail/providers/google.py` | Gmail and Admin SDK Directory adapter: OAuth with offline access, raw MIME send, thread read, directory read, revoke. |
| `app/mail/providers/http.py` | httpx client (20 s timeout, 10 s connect); maps HTTP errors to `ProviderError` (429 and 5xx flagged retryable, flag unused). |
| `app/mail/providers/fake.py` | In-process fake of both providers and a sample directory; used whenever `EMAIL_MODE=outbox` or `MAIL_PROVIDER_MODE=fake`. |
| `app/core/ms_signin.py` | OpenID Connect sign-in that proves the Microsoft tenant after admin consent. |
| `app/mail/tokens.py` | Fernet encryption of token sets; key from `TOKEN_ENCRYPTION_KEY`, else derived from `SECRET_KEY`; `token_ref` records which key. |
| `app/mail/connections.py` | Connection lifecycle: start and complete consent, domain and tenant checks, settings, disconnect, test email, IT request. |
| `app/mail/admin_router.py` | API: `/mail/futran/*`, `/mail/client/*`, `/mail/oauth/{provider}` callback, `/me/mailbox/*`, `/mail/settings`. |
| `app/mail/groups_router.py` | API: groups, templates, E4 send (`/send`, `/send/preview`, `/send/test`), email log. |
| `app/mail/public_router.py`, `app/mail/links.py` | No-sign-in link endpoints `/api/v1/public/m/...`: personal links (256-bit token, hash stored), shared BCC links with a 6-digit one-time code (10 min, 5 tries, 3 codes per 10 min). |
| `app/mail/replies.py` | Reply sync and bounce or out-of-office classification. |
| `app/mail/directory.py`, `groups.py`, `people.py` | Directory sync, platform groups and their expansion. |
| `app/mail/library.py` | Database email templates for group sends (versioned; client copies override Futran's). |
| `app/mail/templates/*.j2` | File templates for system emails: subject, HTML and text per key; `_layout.html.j2`, `group_message.html.j2`. |
| `app/mail/adminlog.py` | Email admin log (`admin_log`), append-only by ORM hooks and database triggers, kept 7 years. |
| `app/mail/domain_check.py` | SPF, DKIM, DMARC lookup for the sending domain through DNS over HTTPS (`dns.google`). |
| `app/mail/router.py` | Legacy `/admin/outbox` list (Futran admin or Chief Auditor). The UI shows the outbox as a tab of `/admin/log`. |
| `app/core/config.py` | Settings (section 5). |
| `tests/mail/` | 126 tests; all passed on 2026-11-25 against SQLite. |

---

## 4. Every kind of email

"Admin log" is the append-only email admin log (`admin_log`, 7 years). Every email in every row also gets an `outbox_messages` row and a `mail_sends` row with `mail_recipients`, shown in the email log. "Sender" is what `resolve_sender()` picks when mailboxes are connected; all fall back to SMTP or the outbox.

### 4.1 System emails (`mail/service.py send()`, file templates, synchronous, no retry)

| Event | Trigger (code) | Recipient | Template key | Sender | Audited |
|---|---|---|---|---|---|
| Account invitation | `invitations/service.py` `invite_user()` | Invited user | `invitation` | Futran | Admin log `system_send`; audit `invitation.sent`. Accept link redacted in the stored copy |
| Initiation package invitation | `initiation/service.py:223,246`, `tenancy/people.py:235` | Client contacts (CAICO, Client Admin, added users) | `client_invitation` | Futran | Same as above |
| Invitation expiring in 48 h | Daily job `run_invitation_warnings` (`notifications/jobs.py`) | Invitee | `invitation_expiring` | Futran | Admin log `system_send` |
| Engagement submitted | `engagements/wizard_router.py:126` | Chief Auditors | `engagement_submitted` | Futran | Admin log |
| Engagement returned | `engagements/wizard_router.py:138` | Engagement author | `engagement_returned` | Futran | Admin log |
| Employee AI audit and data notice | `initiation/notice.py:121` (CAICO sends), one email per person in a loop | Every user on the client's People > Users | `employee_data_notice` | Client mailbox (`CLIENT_ORIGIN`) | Admin log per email; audit `notice.send` |
| Named user confirmation | `inventory/service.py:269` | Named user on a use case | `named_user_confirm` | Client mailbox | Admin log |
| Attestation assigned in the app | `attestation/service.py:284` via `notify(email_template=...)` | Client user | `attestation_sent` | Client mailbox | Admin log |
| One-time code for a shared link | `mail/links.py:120` (public endpoint) | Address typed, must be a recipient of the send | `one_time_code` | Client mailbox | Admin log; code redacted in the outbox copy but not in `mail_sends.subject` (gap G7) |
| Document request and chase | `docrequests/service.py:138`, `:225` | Client CAICO, cc engagement managers | `document_request` | Futran | Admin log; audit `documents.issue` |
| IT consent request | `mail/connections.py:411` | IT admin email typed by the Client Admin | `it_consent_request` | Futran | Admin log `consent_requested` and `system_send`; link redacted |
| Generic notification email | `notify()` for: `sign_off_awaiting` (`signoffs/service.py:271`, `reports/service.py:546`), `sign_off_role_changed` (`tenancy/people.py:154`), `evidence_request` created and due in 3 days (`docrequests/evidence_requests.py`, daily due-soon job), incident deadline reminder, missed and new (`tracing/jobs.py`, `tracing/incidents.py:293`), `opportunity_assigned` (`sales/router.py`), `sales_stale_digest` (`sales/desk.py:203`), `monitoring_check_failed`, `addon_approval`, `addon_decided`, `agent_permissions_changed` (client side) | The user named by each event | `notification` | Futran | Admin log |
| Monday overdue digest | Daily job `run_weekly_digest` (Mondays) | CAICO and assigned auditors per client | `overdue_digest` | Futran | Admin log |
| Intro letter | `regmaster/letter.py:283` | Client CAICO contact | `client_alert` | Futran | Admin log |
| Client alert (fallback) | `clientalerts/service.py:289` when the rule's client groups are empty | CAICO | `client_alert` | Futran | Admin log `send` and `system_send` |
| Weekly regulatory digest | Daily job `regulatory_digest` (`regupdates/service.py:538`), claimed per week | Client CAICOs | `client_alert` | Futran | Admin log |
| Law refresh staff alert | `staffalerts/service.py:91` | Futran staff (to and cc) | `staff_refresh_alert` | Futran | Admin log |
| Mailbox test email | Admin › Email "Send test" (`connections.py:371`) | Address typed | `test_message` | The connection being tested | Admin log `test`, including failures |

Notification kinds that are in-app only (no email) include `invitation_expired`, `document_escalation`, `departments_confirmed`, `governance_submitted`, `retention_notice`, `addon_opportunity` (`notifications/events.py:26`: kinds not in the §14 table are in-app only unless the caller passes `email_template`).

### 4.2 Group sends (`send_to_groups()`, database templates, queued and paced, retried)

| Event | Trigger (code) | Recipients | Template key | Sender | Audited |
|---|---|---|---|---|---|
| AI use attestation | `attestation/mail_links.py:59` | "All employees" group, filtered | `attestation_request` | Client mailbox | Admin log `send` |
| Policy acknowledgment | `policies/service.py:281` | Chosen groups, default All employees | `policy_acknowledgment` | Client mailbox | Admin log; audit `policy.acknowledgment_send` |
| Training assignment | `training/service.py:178` | Chosen groups or departments | `training_module` | Client mailbox | Admin log; audit `training.assign` |
| Regulatory change alert | `clientalerts/service.py:283` | Rule's client groups | `regulatory_change_alert` | Client mailbox | Admin log |
| Any template, sent by hand | E4 Send to groups (`/send`, `groups_router.py:478`) | Chosen groups | Any library template (`dept_head_approval`, `ll144_notice`, `evidence_request`, `initiation_package`, `training_ai_literacy`, client copies) | Organisation, Futran or the sender's own mailbox | Admin log `send` |
| Reminder | `reminders.py` `run_reminders()` on the mail tick, days from `reminder_plan` (often 3 and 7) | Non-responders only | Same as the original | Same as the original | Admin log `reminder` |
| E4 "Send test to me" | `groups_router.py:491-506` | The sender | Chosen template | As chosen | Not in the admin log (outbox and email log only) |

Modes: `personal` (one message per person, one personal link each) or `bcc` (batches of `MAIL_BCC_BATCH_SIZE`, default 450, one shared link, one-time code before answering).

### 4.3 Rep emails (direct `delivery.deliver()`, synchronous)

| Event | Trigger | Recipient | Key | Sender | Audited |
|---|---|---|---|---|---|
| Sales email | `sales/desk.py:365` | Prospect addresses | `sales_email` | Rep's own connected mailbox (required) | Admin log, no addresses |
| Scoping questionnaire and reminders | `scoping/sending.py:85`; reminders in the daily `scoping_reminders` job | Prospect contact | `scoping_questionnaire` | Rep's mailbox, else Futran | Admin log |
| Proposal and reminders | `proposals/sending.py:90`, `remind()`; daily `proposal_followups` job | Proposal recipients | `proposal_send` | Rep's mailbox, else Futran | Admin log |

Attachments: none. `outbox_messages.attachments` is always `[]` (`delivery.py:129`); documents are reached by link.

---

## 5. Settings and secrets

All settings are environment variables read by `app/core/config.py` (pydantic-settings, case-insensitive). Example values are not real.

| Variable | Purpose | Example | Where on AWS |
|---|---|---|---|
| `EMAIL_MODE` | `outbox` keeps every email in the platform and also puts the whole platform in test mode (`config.py:84`), forces fake mail, connector and webhook adapters, and stores one-time links readable. `smtp` is the only live value, and it is required even when all mail goes through Graph or Gmail. | `smtp` | Task environment |
| `MAIL_PROVIDER_MODE` | `auto` (fake while `EMAIL_MODE=outbox`), `fake` or `live`. | `live` | Task environment |
| `SMTP_HOST` | SMTP relay for the fallback channel. | `email-smtp.us-east-1.amazonaws.com` | Task environment |
| `SMTP_PORT` | STARTTLS port. The code supports STARTTLS only (`smtplib.SMTP` then `starttls()`), not implicit TLS on 465 or 2465. | `587` | Task environment |
| `SMTP_USER` | SMTP user name (for SES: the IAM access key ID of a dedicated SMTP user). | `AKIAEXAMPLE0000000000` | Secrets Manager |
| `SMTP_PASSWORD` | SMTP password (for SES: derived from the IAM secret key, region-specific). | `example-smtp-password` | Secrets Manager |
| `SMTP_FROM` | From address and name for SMTP sends; its domain must be verified at the relay. | `Futran Audit Platform <no-reply@notify.futran.example>` | Task environment |
| `SMTP_STARTTLS` | Upgrade to TLS before login. Must stay `true` for SES. | `true` | Task environment |
| `MS_CLIENT_ID` | Entra ID multitenant app registration (mail). | `00000000-0000-0000-0000-000000000000` | Task environment |
| `MS_CLIENT_SECRET` | Its client secret. Expires (set a reminder). | `example~secret` | Secrets Manager |
| `MS_REDIRECT_URI` | Blank uses `BASE_URL/api/v1/mail/oauth/microsoft365`. | blank | Task environment |
| `GOOGLE_CLIENT_ID` | Google Cloud OAuth web client (mail). | `1234-example.apps.googleusercontent.com` | Task environment |
| `GOOGLE_CLIENT_SECRET` | Its secret. | `GOCSPX-example` | Secrets Manager |
| `GOOGLE_REDIRECT_URI` | Blank uses `BASE_URL/api/v1/mail/oauth/google`. | blank | Task environment |
| `TOKEN_ENCRYPTION_KEY` | Encrypts stored OAuth tokens; also keys the BCC shared-link token (`sending.py` `_shared_token`). Blank derives from `SECRET_KEY`. Changing it makes every stored token unreadable and breaks shared links already sent. | 48+ random characters | Secrets Manager |
| `SECRET_KEY` | Signs sessions and the OAuth `state` (consent links emailed to IT stop working if it changes); token key fallback. | 48+ random characters | Secrets Manager |
| `BASE_URL` | Every link in every email and the OAuth redirect URIs are built from it. Must be the public `https://` address. | `https://audit.futran.example` | Task environment |
| `MAIL_PACE_PER_MINUTE` | Messages per send per tick (not per mailbox; gap G5). | `30` | Task environment |
| `MAIL_BCC_BATCH_SIZE` | Recipients per BCC message. | `450` | Task environment |
| `MAIL_LINK_DAYS` | Default personal-link life shown in the send form. | `14` | Task environment |
| `DISABLE_SCHEDULER` | `true` stops all scheduled mail, including retries and reminders. | `false` | Task environment |
| `MFA_REQUIRED` | Also part of test mode. | `true` | Task environment |
| `TRUST_PROXY_HEADERS` | Rate limits on public link endpoints use `X-Forwarded-For` behind the ALB. | `true` (Dockerfile default) | Task environment |
| `DATABASE_URL` | Contains the RDS password. | `postgresql+psycopg://app:...@db.example:5432/fap` | Secrets Manager |

Per-tenant secrets live in the database, not in the environment: `mail_connections.token_encrypted` (one per organisation) and `user_mail_connections.token_encrypted` (one per user), Fernet-encrypted, with `token_ref` naming the key (`token_key:<fingerprint>` or `secret_key:<fingerprint>`).

Separate app registrations for AI discovery connectors (`DISCOVERY_MS_*`, `DISCOVERY_GOOGLE_*`) are not mail settings, but `CONNECTOR_MODE=auto` also follows `EMAIL_MODE` (`connectors/adapters/__init__.py:42`).

---

## 6. Provider options on AWS

How the channels combine today: for client-originated email, the client's own mailbox if connected (`sender_mode=own`), else Futran's mailbox with the display name "Client via Futran Audit Platform", else SMTP. For Futran email, Futran's mailbox, else SMTP. SMTP is therefore only used when no usable Graph or Gmail connection exists. A connection whose tokens have stopped working stays `connected` and does not fall back to SMTP (gap G6).

### 6.1 Comparison

| | (a) Microsoft 365 via Graph | (b) Gmail API | (c) SMTP through Amazon SES |
|---|---|---|---|
| Code support today | Full: org mailbox (app-only), personal mailbox (delegated), reply sync, bounce detection by NDR, directory sync | Full: same features | Send only, as the fallback channel. No bounce, complaint or reply handling. No configuration-set header. One global From address |
| Sends as | The client's or Futran's own mailbox | The signed-in Workspace account | `SMTP_FROM` (Futran's domain) |
| Credentials | `MS_CLIENT_ID`, `MS_CLIENT_SECRET`; per-tenant tokens in the DB | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; per-mailbox tokens in the DB | SES SMTP user and password (long-lived IAM user; temporary credentials such as a task role cannot be used) |
| Egress from Fargate | HTTPS 443 to `login.microsoftonline.com`, `graph.microsoft.com` | HTTPS 443 to `oauth2.googleapis.com`, `gmail.googleapis.com`, `admin.googleapis.com` | TCP 587 or 2587 to `email-smtp.<region>.amazonaws.com`, or an SES SMTP VPC interface endpoint |
| AWS DNS work | None (the tenant's own SPF, DKIM, DMARC apply) | None (the Workspace domain's own records apply) | Domain identity, 3 DKIM CNAMEs, custom MAIL FROM (MX, SPF), DMARC |
| Limits (from the code's comments and README) | 30 messages a minute, 10,000 recipients a day, 500 recipients a message per mailbox | 2,000 messages a day per user; 2,000 recipients a message, 500 external | Sandbox: 200 a day, 1 a second, verified recipients only; production quota set by AWS |
| Best use | Primary channel for Futran and Microsoft 365 clients | Google Workspace clients | Fallback for Futran system email when no mailbox is connected |

All three also need HTTPS 443 to `dns.google` for the SPF, DKIM, DMARC check on connect (`domain_check.py`); a failed lookup records "unknown", not a failure.

### 6.2 (a) Microsoft 365 via Graph

Setup (README has the full text):

1. Futran IT registers one multitenant Entra ID app (platform Web) with redirect URI `https://<host>/api/v1/mail/oauth/microsoft365`. Application permissions: `Mail.Send`, `Mail.ReadWrite`, `User.Read.All`, `Group.Read.All`, `GroupMember.Read.All`. Delegated: `offline_access`, `openid`, `email`, `User.Read`, `Mail.Send`, `Mail.ReadWrite`. Create a client secret.
2. Put `MS_CLIENT_ID` in the task environment and `MS_CLIENT_SECRET` in Secrets Manager.
3. Each organisation's Global Administrator grants admin consent from the platform, then signs in once to prove the tenant.
4. Each tenant's IT limits the app to the one sending mailbox with RBAC for Applications in Exchange Online (README PowerShell), then may remove tenant-wide mail consent.

DNS: none on the AWS side. The platform's domain check reads the sender domain's SPF, DMARC and the `selector1`/`selector2` DKIM records.

Egress: 443 only. If tasks run in private subnets, a NAT gateway is required (no VPC endpoint exists for Microsoft or Google).

What would need building: per-mailbox pacing (G5), retry and queueing for system emails (G1), marking a connection `error` when token refresh fails (G6).

### 6.3 (b) Gmail API

Setup:

1. Futran IT creates a Google Cloud project, enables the Gmail API and the Admin SDK API, configures an External OAuth consent screen, and creates a Web OAuth client with redirect URI `https://<host>/api/v1/mail/oauth/google`.
2. Scopes: `gmail.send` (sensitive), `gmail.modify` (restricted, needed for reply sync), the three Directory read-only scopes, `openid`, `email`.
3. Before clients outside Futran's own Workspace can consent, Google requires app verification and, for the restricted scope, an annual third-party security assessment. Until then each client's Workspace admin marks the client ID as Trusted under API controls (README).
4. The sending mailbox (a user, not a group) connects from the platform. With Google the sender is the account that signed in; it cannot be changed without reconnecting.

DNS: none on the AWS side. Egress: 443 only.

What would need building: same as Graph. Also note `MAIL_PACE_PER_MINUTE=30` per send is 43,200 a day in theory, far above Gmail's 2,000 a day per user; there is no daily cap in code.

### 6.4 (c) SMTP through Amazon SES

What the code supports today: `EMAIL_MODE=smtp` plus the `SMTP_*` settings. `_smtp()` (`delivery.py:149`) builds a multipart text and HTML message, connects with `smtplib.SMTP(host, port, timeout=20)`, calls `starttls()` when `SMTP_STARTTLS=true`, logs in, and sends. Use port 587 or 2587. Do not use 465 or 2465 (TLS wrapper; the code does not support it) or 25 (EC2 throttles it by default).

Setup steps (targets; confirm region and domain with Futran):

1. Choose the SES region, normally the one that hosts the platform (the platform's `DATA_REGION_LABEL` defaults to `us-east`; `us-east-1` is the likely target, to confirm). Sandbox status, SMTP credentials, identities, suppression list and quotas are all per region.
2. Create a domain identity for the From domain. A dedicated sending subdomain (for example `notify.futransolutions.com`) keeps SES reputation apart from Futran's Microsoft 365 mail. To confirm with Futran IT.
3. Enable Easy DKIM (2048-bit default) and publish the three CNAME records SES shows. Verification can take up to 72 hours.
4. Set a custom MAIL FROM domain (a subdomain used for nothing else, for example `bounce.notify.futransolutions.com`) with one MX record and one SPF TXT record. This makes SPF align for DMARC.
5. Publish or update DMARC on the From domain. Start with `p=none` and a `rua` address, then move to `quarantine`. Do not set `aspf=s`, or SPF will not align through SES.
6. Create a configuration set with event destinations (SNS or other) for bounce, complaint, delivery and reject, and assign it to the identity as the **default configuration set**. The code cannot add the `X-SES-CONFIGURATION-SET` header, so the default is the only way to apply it without a code change.
7. Set up bounce and complaint handling: SES requires SNS notifications, email feedback forwarding or event publishing. Create SNS topics for bounces and complaints and subscribe an operations mailbox for now. Confirm the account-level suppression list is on for bounces and complaints (default for accounts that started using SES after 25 November 2019). Note that SES accepts but does not send to a suppressed address, so the platform will show that recipient as sent.
8. Request production access (Transactional) for the region. AWS gives an initial response within 96 hours. In the sandbox SES sends only to verified addresses, 200 a day, 1 a second.
9. Create a dedicated IAM user allowed only `ses:SendRawEmail` (scope it to the identity ARN if possible, to confirm), create an access key, derive the SMTP password for the region, and store user and password in Secrets Manager. SES SMTP does not accept credentials derived from temporary credentials, so the ECS task role cannot be used for SMTP.
10. Network: either a NAT gateway or a public IP for the task, with the security group allowing outbound TCP 587, or an SES SMTP VPC interface endpoint (`email-smtp`) with a security group allowing 587 from the task's security group. SES does not support SMTP VPC endpoints in some Availability Zones (in us-east-1: `use1-az2`, `use1-az3`, `use1-az5`); place the endpoint subnets accordingly.
11. Set `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_FROM` and the two secrets; deploy; send a test (runbook step 9).

DNS records for SES (names are examples):

| Record | Name | Type | Value |
|---|---|---|---|
| DKIM 1 to 3 | `<token>._domainkey.notify.futransolutions.com` | CNAME | `<token>.<SigningHostedZone>` as shown by SES (region-specific; do not hand-type `dkim.amazonses.com`) |
| MAIL FROM MX | `bounce.notify.futransolutions.com` | MX | `10 feedback-smtp.us-east-1.amazonses.com` |
| MAIL FROM SPF | `bounce.notify.futransolutions.com` | TXT | `"v=spf1 include:amazonses.com ~all"` |
| DMARC | `_dmarc.notify.futransolutions.com` (or the organisational domain) | TXT | `"v=DMARC1; p=none; rua=mailto:dmarc-reports@futransolutions.com"`, tightened later |

What would need building for SES to be more than a dumb fallback:

- Bounce and complaint feedback into the platform: SNS to SQS, polled by the scheduler, setting `mail_recipients.status = bounced`. Correlation needs an ID the platform controls, for example a `Message-ID` header set in `_smtp()` and matched against the SES notification's `mail.commonHeaders.messageId` (to confirm field names when building).
- Alternatively, an SES API v2 adapter (`SendEmail` through boto3 with the task role, no long-lived SMTP key, returns the SES message ID, accepts a configuration set and tags) as a fourth channel beside `smtp`.
- Per-client sending domains through SES (a client's own domain) are not supported; clients who want mail from their own domain connect Microsoft 365 or Google.

---

## 7. The single-instance rule for mail

### 7.1 What the code does today

- The scheduler is APScheduler inside the web process. Every task that starts runs its own copy: mail tick, webhook tick, incident deadline tick and daily run. `max_instances=1` and `coalesce=True` only stop overlap within one process.
- Group-send recipients are claimed before the provider is called: `UPDATE mail_recipients SET status='sending' WHERE id=:id AND status='queued'`, checked by row count (`sending.py:307`). On Postgres under READ COMMITTED, a second transaction updating the same row waits for the first to commit, re-checks the condition and updates nothing, so the second task skips that recipient. This is the right pattern, but it is tested only on SQLite (`tests/mail/test_dispatch_claim.py`); on Postgres it is to confirm.
- Reminders (`reminders.py:267`) and incident deadline notices (`tracing/jobs.py:29`) use the same conditional-update claim. The daily run is claimed by a unique date row (`DailyJobRun`, `notifications/jobs.py`), and the weekly regulatory digest by a unique week row.
- The claim is held inside the tick's transaction, which commits only at the end of the whole tick (`notifications/jobs.py` `mail_tick`). The provider call happens before the commit. So delivery is at-least-once: if a task is stopped after Graph or SMTP accepted a message but before the commit, the claim rolls back and the next tick sends it again.

### 7.2 What still goes wrong with two tasks

| Risk | Where | Effect |
|---|---|---|
| Deployment overlap | ECS rolling default (max 200 %), Express Mode canary and bake time | Two schedulers; an old task stopped mid-tick resends what it had sent but not committed |
| Reply sync race | `replies.py:63` checks for an existing reply, then inserts; no unique key on `(thread_id, provider_message_id)` | Duplicate `mail_replies` rows and duplicate `mail.reply` audit entries |
| Directory sync race | `directory.py` matches people by directory ID or email, then inserts; no unique key | Duplicate `directory_people`, so a person can be counted twice until a later sync |
| Subject reference race | `next_subject_ref()` (`sending.py:147`) reads every `subject_ref`, takes the highest and adds one; `mail_threads.subject_ref` is unique (`models.py:308`) | Two concurrent sends get the same `FAP-n`; one fails with an integrity error. This can happen with one task too, when two requests send at once on Postgres |
| Row locks held across HTTP calls | `_claim` inside the tick transaction | The second task blocks for up to the length of the first tick |
| Rate limits | `core/ratelimit.py:18` in-memory | One-time code and link limits multiply by the number of tasks |
| Pacing | `pace_limit()` per send per tick | Two tasks can each send 30 a minute from the same mailbox |

### 7.3 What to set now

- Use a standard ECS service on Fargate with desired count 1, no Service Auto Scaling, deployment `maximumPercent=100` and `minimumHealthyPercent=0`. This stops the old task before the new one starts; deployments then have a short outage. (Inference from the ECS definitions; confirm in a test deployment.)
- If ECS Express Mode is kept: it uses canary deployments that cannot be changed and runs old and new task sets together during the bake time, and its default scaling range is 1 to 20 tasks on CPU. Set the maximum task count to 1. The canary overlap remains, so either accept at-least-once and the races above during each deployment, or move to a standard service. This needs a decision; the deployment architecture doc recommends Express Mode "for the simple path" without this caveat.
- Give the task a stop timeout long enough for a tick to finish (to confirm the value; ticks normally take seconds, but 30 Graph sends at up to 20 s each can take minutes).

### 7.4 What to change before scaling out

| Option | Change | Effort | Notes |
|---|---|---|---|
| A. Leader lock | Wrap each tick in `pg_try_advisory_lock(<job id>)`; only the holder runs it | Small | Fastest fix; web tasks can then scale. Still in-process. |
| B. `FOR UPDATE SKIP LOCKED` claim | Select a batch of due recipients with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n`, mark them `sending` with a `claimed_until` lease, commit, then call the provider in a separate transaction | Medium | Removes lock waits; add a sweeper that requeues expired leases. Pair with unique keys on `mail_replies(thread_id, provider_message_id)`, `directory_people(organization_id, directory_id)` and a database sequence for `FAP-n`. |
| C. Separate worker service | Same image, `DISABLE_SCHEDULER=true` on the web service (scalable), one worker service running only the scheduler | Medium | Matches the existing setting; still needs A or B for safe worker restarts. Rate limiter must move to the database or a cache for the web tier. |
| D. SQS | Producers write `mail_recipients` and an SQS message; workers consume, deliver, delete. FIFO queue with deduplication by recipient ID | Larger | Durable, scales; adds an AWS dependency and IAM. Still needs idempotent state updates. |

Recommended order: A now if more than one web task is ever needed, then C with B, and SQS only if volume calls for it. System emails (section 4.1) should move onto the same queue (G1) before any of this matters at scale.

---

## 8. Security

**OAuth token storage.** Tokens are Fernet-encrypted JSON in the database (`tokens.py`), with a key from `TOKEN_ENCRYPTION_KEY` or `SECRET_KEY`. Keep `TOKEN_ENCRYPTION_KEY` in Secrets Manager, separate from `SECRET_KEY`, and back it up with the database backups; a lost key means every mailbox reconnects. RDS encryption at rest adds a second layer. Microsoft has no revoke endpoint for these flows; disconnect deletes the token and the tenant's IT removes the enterprise app (`microsoft.py:193`). Google tokens are revoked on disconnect.

**Secrets.** `MS_CLIENT_SECRET`, `GOOGLE_CLIENT_SECRET`, `SMTP_USER`, `SMTP_PASSWORD`, `TOKEN_ENCRYPTION_KEY`, `SECRET_KEY` and `DATABASE_URL` belong in Secrets Manager, injected through the task definition `secrets` block. The task execution role needs `secretsmanager:GetSecretValue` on those ARNs only. The Entra client secret expires; add a rotation reminder.

**Tenant boundary.** What the code enforces:

- Each organisation has its own connection row; `resolve_sender()` looks up the connection by the email's `organization_id` (`delivery.py:77`) and otherwise uses Futran's, never another client's.
- At consent, the Microsoft tenant is proven by an ID token, not taken from the redirect (`microsoft.py:68`); the tenant must have verified one of the organisation's own user domains; a tenant already connected to another organisation is refused; the sending mailbox must be in a verified domain (`connections.py:244-257`).
- A personal mailbox must be the signed-in user's own address and is bound to the browser session that started the consent.
- Graph app permissions cover the whole tenant until IT scopes them with RBAC for Applications; make that step part of every client's onboarding checklist.
- Group expansion checks every group belongs to the organisation being sent for (`sending.py:73-80`). Tests: `test_send_isolation.py`, `test_directory_isolation.py`, `test_consent_binding.py`.
- To confirm: that every E4 send endpoint ties `organization_id` to the actor's session for client users (`groups_router._expand_args` was not read line by line).

**Link and phishing safety.**

- Links are built from `BASE_URL` only. Personal links are 256-bit random tokens stored as SHA-256 hashes, expire (1 to 90 days), and are replaced on resend. Shared BCC links need a 6-digit code mailed to a listed recipient.
- Header injection is blocked by `one_line()` on subjects and by `EmailMessage` refusing line breaks in other headers. File templates autoescape HTML; group template paragraphs are HTML-escaped.
- No tracking pixels; "opened" means the link was opened.
- Client Admins can edit template text and send from Futran's mailbox when `sender_mode=futran_on_behalf`. Plain-text URLs typed into a template are escaped but most mail clients still make them clickable. Consider refusing URLs in client-edited template bodies other than `[Link]`, or showing a warning.
- With SES, publish DMARC and move it to enforcement so the sending domain cannot be spoofed in a phishing copy of these emails.

**PII in logs and records.**

- Application logs (`log.exception` in `sending.py:442` and `jobs.py:29`) carry the send ID and the exception text. Provider error text can include addresses; CloudWatch retention should match the data policy.
- `outbox_messages` keeps the full rendered body (names, notice text) for every email; one-time links and codes are redacted in that copy when `EMAIL_MODE` is not `outbox`.
- The append-only admin log, kept 7 years, includes recipient addresses for system emails (`service.py:105`). The sales path deliberately omits them ("this log is append-only", `sales/desk.py:398`). An erasure request cannot remove those addresses. Decide whether system-email summaries should drop addresses too.
- The one-time code appears in `mail_sends.subject` (G7).

---

## 9. Cut-over runbook

Before you start: read section 7.3, confirm the AWS account, region, VPC and domain names, and agree a maintenance window. Steps marked "target" are AWS placements to confirm.

1. **Freeze the laptop.** Stop the laptop app so its scheduler sends nothing more. Check: no `uvicorn` process; the latest `outbox_messages.created_at` does not change.
2. **Inventory mail state in the laptop database.** Run, against a copy:
   `SELECT owner, provider, status, mailbox_address FROM mail_connections WHERE deleted_at IS NULL;`
   `SELECT status, provider, mailbox FROM user_mail_connections WHERE deleted_at IS NULL;`
   `SELECT status, count(*) FROM mail_recipients GROUP BY status;`
   `SELECT count(*) FROM directory_people WHERE directory_id LIKE 'fake-%';`
   Check: you have the list. Any `connected` row on the laptop was made by the test-mode fake and holds fake tokens. Any `fake-` directory person is a made-up address at a real client domain (`providers/fake.py:75`).
3. **Clean test-mode mail data** in the copy that will be restored (agree with the platform lead first; the code has no command for this): set every `mail_connections` and `user_mail_connections` row to `disconnected` with `token_encrypted` and `token_ref` null; soft-delete `directory_people` rows whose `directory_id` starts with `fake-` and the `directory_groups` that came with them; mark `mail_recipients` still `queued` or `sending` as `bounced` with an error "not sent: cut-over", so nothing old goes out on AWS. Check: the queries in step 2 return no `connected`, no `queued`, no `fake-` rows.
4. **Create secrets (target: Secrets Manager).** New `SECRET_KEY`, new `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, `MS_CLIENT_SECRET`, `GOOGLE_CLIENT_SECRET` (if used), `SMTP_USER`, `SMTP_PASSWORD`. Check: the task execution role can read each ARN (`aws secretsmanager get-secret-value` from a shell with that role).
5. **Set up SES (target) if SMTP fallback is wanted**: section 6.4 steps 1 to 10. Check: the identity shows DKIM "Successful" and MAIL FROM "Success" in the SES console; production access is granted, or, while waiting, the test recipients are verified identities.
6. **Register redirect URIs.** In the Entra app and the Google OAuth client, add `https://<host>/api/v1/mail/oauth/microsoft365` and `https://<host>/api/v1/mail/oauth/google`. Check: after deploy, Admin › Email shows Microsoft 365 and Google as configured with these URIs (`credentials_status` returns them).
7. **Network (target).** Task security group egress: TCP 443 to the internet (or through NAT) and TCP 587 to SES or the SES SMTP VPC endpoint. Check, from a one-off task with the same network settings: `python -c "import socket; socket.create_connection(('graph.microsoft.com',443),5); socket.create_connection(('email-smtp.us-east-1.amazonaws.com',587),5); print('ok')"` prints `ok`.
8. **Deploy one task** with `EMAIL_MODE=smtp`, `MAIL_PROVIDER_MODE=live`, `MFA_REQUIRED=true`, `BASE_URL=https://<host>`, `DISABLE_SCHEDULER=false`, the `SMTP_*` and provider settings, desired count 1, `maximumPercent=100`, `minimumHealthyPercent=0`, no auto scaling (section 7.3). Check: `GET /api/v1/health` is healthy; the red test-mode bar is gone; CloudWatch shows no "Email tick failed"; the ECS service shows exactly one running task.
9. **Test the SMTP fallback** while no mailbox is connected: Staff › Admin › Email and groups › Send test to an address you can read. Check: the email arrives with `From: SMTP_FROM`; in the email log the test shows status sent and channel `smtp`; the message headers show `dkim=pass`, `spf=pass` and `dmarc=pass` for the SES domain.
10. **Connect Futran's mailbox.** Staff › Admin › Email and groups › Connect Microsoft 365 (or Google), approve, sign in. Check: status Connected, sender address shown, SPF, DKIM and DMARC ticks; admin log has `consent` and `connected` entries; Send test arrives from the Futran mailbox with a `[FAP-n]` reference in the subject.
11. **Check paced group sending.** Send a small group email (two internal addresses) from E4. Check: within 2 minutes every recipient row moves from queued to sent in the email log; each recipient's personal link opens `https://<host>/m/...`, not `localhost`.
12. **Check reply sync.** Reply to the step 11 email. Check: within the connection's sync interval (default 15 minutes, plus one tick) the reply shows on the send in the email log, and the audit log has a `mail.reply` entry.
13. **Check retries and failure recording.** Send one group email to a non-existent address at a domain you control. Check: Graph accepts it (recipient sent), then the bounce NDR is classified at the next reply sync and the recipient turns bounced. For SMTP the platform keeps it as sent (no bounce path, section 6.4); confirm the bounce in the SNS subscription mailbox instead.
14. **Check system emails.** Invite a test user. Check: the invitation arrives at once (it is sent inside the request), the accept link works, and the outbox copy shows the link redacted.
15. **Ask each client to reconnect.** Client Admins reconnect from Email connection (`/admin/email`), run directory sync, send a test, and their IT applies RBAC for Applications. Users with personal mailboxes reconnect from My mailbox. Check: each client's connection is Connected with a recent test; `directory_people` for that client has real directory IDs.
16. **Watch the first daily run** (10:00 UTC). Check: `daily_job_runs` has one row for the day with status `completed`; invitation warnings and digests appear in the email log once, not twice.
17. **Deployment check.** Deploy a no-op change. Check: ECS stops the old task before starting the new one (events tab), and no group email in flight is delivered twice (compare `mail_recipients` sent count with the provider's sent items).

Rollback: set `EMAIL_MODE=outbox` and redeploy. Every email is then kept in the outbox and nothing leaves; note this also turns test mode back on for the whole platform.

---

## 10. Gaps and risks

| # | Severity | Gap or risk | Where | Suggested fix |
|---|---|---|---|---|
| G1 | High | System emails are sent synchronously in the request, with no retry. A transient Graph 429 or SMTP timeout loses the email (recipient marked bounced at once). Bulk loops such as the employee data notice (one email per person, two Graph calls each, 20 s timeout) can run longer than the ALB idle timeout (60 s by default, to confirm on the target ALB) and break Exchange's 30-a-minute limit. | `mail/service.py:94-96`; `initiation/notice.py:121`; `notifications/jobs.py` digests | Queue system emails as `mail_recipients` (status queued) and let the existing paced dispatcher and retry deliver them; return from the request at once. |
| G2 | High | `_provider()` catches only `ProviderError`. `TokenError` (stored token unreadable after a key change, or a fake token from the laptop) and `KeyError` on unexpected token responses escape. In a request this fails the business action (invitation, notice) with a 500; in the tick the whole send's savepoint rolls back and retries every minute forever. | `mail/delivery.py:184-192`; `tokens.py:440-447` | Catch `TokenError` and any `Exception` in `_provider()` and return `Result(ok=False)`; on `TokenError` or `invalid_grant` set the connection `status='error'`. |
| G3 | High | Test-mode data carried from the laptop: fake connections marked `connected`, and sample directory people with invented addresses at real client domains (`ana.ruiz@client.com`). With live mail on, a group send to All employees could email them. | `mail/providers/fake.py:75`; data | Runbook step 3; add a CLI command that resets mail state for go-live. |
| G4 | High | Deployment overlap on ECS: default rolling deployments and Express Mode canaries run two schedulers. | Hosting; `notifications/jobs.py:356-363` | Section 7.3 settings now; advisory lock (7.4 option A) next. |
| G5 | Medium | Pacing is per send per tick, not per mailbox, and system emails are not paced. Three concurrent group sends from one mailbox send 90 a minute against Exchange's 30. No daily cap (Exchange 10,000 recipients, Gmail 2,000 messages). BCC batches count as one message each against the pace, so 30 batches of 450 is 13,500 recipients a minute. | `mail/sending.py:300-304`, `dispatch_due` at `:432` | Track sends per sender mailbox per minute and per day in the database; count BCC recipients against the daily cap. |
| G6 | Medium | A mailbox whose token can no longer be refreshed (secret expired, consent removed) stays `connected`, so mail keeps failing instead of falling back to Futran or SMTP, and nobody is alerted. | `delivery.py:81-86` (`_usable` checks status only) | Flip to `error` on auth failures, notify the Futran admin and the Client Admin, fall back to the next sender. |
| G7 | Medium | The one-time code is stored readable in `mail_sends.subject` (the subject template includes the code and `MailSend` uses the unredacted subject), and is visible in the email log to admins of that client, who could then answer a shared-link attestation as another person. | `mail/service.py:78`; `templates/one_time_code.subject.j2` | Use the redacted subject for `MailSend.subject`, or remove the code from the subject line. |
| G8 | Medium | `next_subject_ref()` reads every thread reference and adds one; concurrent sends on Postgres collide on the unique key and the second request fails. It also scans the whole table on every send. | `mail/sending.py:147-150`; `models.py:308` | Use a Postgres sequence (or a counter row updated with `RETURNING`). |
| G9 | Medium | SMTP channel has no bounce, complaint or reply handling, and SES's suppression list makes suppressed recipients look sent. | `delivery.py:149-173` | SNS to SQS consumer (section 6.4), or an SES API adapter that returns message IDs. |
| G10 | Medium | Reply sync for personal mailboxes (sales, scoping, proposals) only runs when some organisation mailbox is due; with no org connection, rep replies are never read. | `mail/jobs.py:16-21` | Include `user_mail_connections` in `_replies_due`, or track `last_sync_at` per holder in the loop. |
| G11 | Medium | Reply and directory sync use check-then-insert without unique keys; two runs create duplicates. | `replies.py:63`; `directory.py` | Unique indexes on `mail_replies(thread_id, provider_message_id)` and `directory_people(organization_id, directory_id)`; insert with `ON CONFLICT DO NOTHING`. |
| G12 | Medium | `EMAIL_MODE` does three jobs: chooses the SMTP channel, switches provider adapters from fake to live under `auto`, and decides platform test mode. There is no value meaning "Graph only, no SMTP". The deployment doc's "`smtp` or a connected mailbox" reads as if a mailbox could replace `smtp`. | `core/config.py:16,84`; `providers/__init__.py:93-95`; `docs/Futran_Audit_Platform_Deployment_Architecture.md` line 92 | Document `EMAIL_MODE=smtp` as mandatory for live mail; later split test mode from the mail channel. |
| G13 | Low | Retry plan says 1, 5, 15 minutes; the code makes three attempts (t, +1, +5) and never uses 15. The `retryable` flag on `ProviderError` is ignored, so permanent 4xx errors are retried too. | `sending.py:53,416`; `providers/http.py:146` | Bounce at `attempts > len(RETRY_MINUTES)`; skip retries for non-retryable errors. Fix the README line. |
| G14 | Low | `reply_to_mode` (`chief_auditor`, `caico`) is saved but never used; Reply-To is always `reply_to` or the mailbox. | `delivery.py:91`; `connections.py:312-316` | Resolve Reply-To from the mode in `_from_connection`, or hide the option. |
| G15 | Low | Admin log keeps recipient addresses of system emails for 7 years in an append-only table (the sales path avoids this). | `mail/service.py:105` | Drop addresses from the summary; keep them only in the deletable `mail_recipients`. |
| G16 | Low | E4 "Send test to me" writes no admin log entry, unlike other sends. | `mail/groups_router.py:491-506` | Add an `adminlog.write(... action="test")`. |
| G17 | Low | `run_email()` sums the tick's results, which can include strings ("failed: ...") and would raise `TypeError`. Not called by the scheduler today. | `notifications/jobs.py:186-191` | Remove it or sum only integers. |
| G18 | Low | SMTP supports STARTTLS only; no implicit TLS (465/2465). | `delivery.py:162-164` | Add `SMTP_SSL` when `SMTP_PORT` is 465 or 2465, if ever needed. |
| G19 | Low | `/admin/outbox` checks roles inline instead of calling `authorize` (project rule: every endpoint calls `authorize`). | `mail/router.py:14-16` | Route through `authorize` with an outbox action. |

### Where this document differs from existing docs

- Deployment architecture doc, "Single instance only": says the scheduler runs "with no lock". The mail sends, reminders, incident deadlines and the daily run do have row claims; the remaining risks are in section 7.2. The single-instance rule still stands.
- Deployment architecture doc, AWS: recommends ECS Express Mode for the simple path. Express Mode's canary deployments and default auto scaling conflict with the single-instance rule (section 7.3).
- README, "failures are retried after 1, 5 and 15 minutes": the code retries twice (G13).
- Deployment architecture doc, `EMAIL_MODE` hosted value "`smtp` or a connected mailbox": `smtp` is required in both cases (G12).

---

## Sources

Code: `backend/app/mail/**`, `backend/app/notifications/{jobs,service,events}.py`, `backend/app/core/config.py`, callers listed in section 4, `backend/tests/mail/**`, `README.md`, `.env.example`, `Dockerfile`, `docs/Futran_Audit_Platform_Deployment_Architecture.md`. Microsoft and Google URLs used by the code are listed in `app/mail/providers/__init__.py`.

AWS documentation (checked 2026-11-25):

- SES sandbox and production access: https://docs.aws.amazon.com/console/ses/sandbox
- SES SMTP credentials, ports (STARTTLS 25, 587, 2587; TLS wrapper 465, 2465), port 25 throttling, region-specific credentials, no temporary credentials: https://docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html
- SES SMTP connection overview: https://docs.aws.amazon.com/ses/latest/DeveloperGuide/smtp-connect.html
- SES endpoints and default quotas: https://docs.aws.amazon.com/general/latest/gr/ses.html
- SES VPC endpoints (ports, unsupported Availability Zones): https://docs.aws.amazon.com/ses/latest/dg/send-email-set-up-vpc-endpoints.html
- SES domain identity and Easy DKIM CNAME records, 72-hour propagation: https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html
- Easy DKIM key length: https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy.html
- Custom MAIL FROM domain (MX, SPF): https://docs.aws.amazon.com/ses/latest/dg/mail-from.html
- DMARC with SES: https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dmarc.html
- Configuration set header for SMTP: https://docs.aws.amazon.com/ses/latest/dg/using-configuration-sets-in-email.html
- Default configuration set on an identity: https://docs.aws.amazon.com/ses/latest/DeveloperGuide/managing-configuration-sets-default.html
- Bounce and complaint notifications through SNS: https://docs.aws.amazon.com/ses/latest/dg/monitor-sending-activity-using-notifications-sns.html
- Account-level suppression list: https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list.html
- ECS rolling deployment parameters: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html
- ECS deployment configuration defaults (200 % and 100 %): https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DeploymentConfiguration.html
- ECS Express Mode resources (canary by default, scaling 1 to 20, subnets and NAT): https://docs.aws.amazon.com/en_en/AmazonECS/latest/developerguide/express-service-work.html
- ECS Express Mode scaling target: https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ExpressGatewayScalingTarget.html
- ECS canary deployments (old and new task sets run together): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/canary-deployment.html

### Not confirmed

- Production AWS account, region, VPC layout, NAT, ALB idle timeout and domain names: not seen.
- The conditional-update claim under Postgres with two tasks: reasoned from Postgres READ COMMITTED behaviour, tested only on SQLite.
- Whether Fargate throttles outbound port 25 the way EC2 does: not checked; the runbook avoids port 25.
- SES IAM policy scoping to an identity ARN, and SNS notification field names for message correlation.
- ECS Express Mode: whether a maximum task count of 1 is accepted and how the canary behaves with one task.
- `groups_router._expand_args` tenant checks were not read line by line.
