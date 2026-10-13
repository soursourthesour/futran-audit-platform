# Futran Audit Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v1 of the multi-tenant Futran Audit Platform: the 9-stage AI governance audit from client onboarding to verified remediation, with per-AI-system assessment and risk scoring.

**Architecture:** A single FastAPI process exposes `/api/v1` and serves a pre-built React SPA. Domain packages under `backend/app/` each own their models, services and routers. A policy layer (`authorize`) enforces tenancy, the permission matrix and separation of duties on every endpoint. Reference content (laws, question bank, catalogs, templates, risk methodology) is seeded from YAML/XLSX into versioned tables.

**Tech Stack:** Python ≥3.11 (CI on 3.13), FastAPI, Pydantic v2, SQLAlchemy 2 (sync), Alembic, argon2-cffi, pyotp, openpyxl, pycountry, docxtpl/python-docx, xhtml2pdf, Jinja2, APScheduler, anthropic, pytest. React 18 + TypeScript + Vite, React Router 6, TanStack Query 5, React Hook Form + Zod. Playwright for end to end.

**Spec:** `docs/spec/Futran_Audit_Platform_Build_Schematic.md` (decisions, overrides) → `docs/spec/Futran_Audit_Platform_Developer_Spec_v0.2.md` (functional source of truth). Mockups: `docs/reference/mockups/*.dc.html` with text in `docs/reference/mockups_text.md`. Template text: `docs/reference/Futran_AI_Governance_Audit_Template.txt`.

## Global Constraints

- Python code must run on 3.11+; no 3.12+-only syntax.
- Every table: `id` (UUID string, 36), `organization_id`, `created_at`, `created_by`, `updated_at`, `updated_by`, `deleted_at`. Soft delete only.
- The tenant comes from the session only, never from the request body or query.
- Every create, edit, approval, send, and view of attestations and evidence writes an `AuditLog` row. There is no update or delete path for `AuditLog`.
- Brand: navy `#1B3A6B`, blue `#2E75B6`, accent `#0098D4` (never used for text). Font: IBM Plex Sans. WCAG 2.1 AA, 44 px touch targets, usable at 375 px.
- User-facing copy is plain, specific professional English. No filler, no exclamation marks, sentence case.
- Session idle timeout 30 min and absolute 12 h, configurable. Invitations expire after 7 days. Uploads are capped at 50 MB.
- Attestation department counts below 3 display as "fewer than 3".
- Every generated document is available as both DOCX and PDF.
- Test mode (`MFA_REQUIRED=false` or `EMAIL_MODE=outbox`) shows a red bar on every page.
- Commit after every task and push to `origin main`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_018MiJNkamAJBqow5NWMUqUB`.

## Review Focus

1. **Cross-tenant access through IDs in URLs.** A client user who requests another tenant's engagement, system or file by ID gets a 404, never data. Pinned in Task 5 (`test_cross_tenant_id_returns_404`) and re-checked per router via the shared `assert_tenant_scoped_routes` test in Task 33.
2. **Self-approval via multiple roles.** A user holding both preparer and approver roles cannot approve their own item, including a Chief Auditor approving their own finding. Pinned in Task 5 (`test_sod_no_self_approval_multi_role`) and Task 29 (`test_chief_auditor_finding_routes_to_qa`).
3. **Re-importing the law workbook after clients reference laws.** Referenced laws are never deleted; changed ones are superseded. Pinned in Task 10 (`test_reimport_keeps_referenced_and_supersedes`).
4. **CSV uploads with messy rows** (BOM, trailing spaces, duplicate emails, unknown department, wrong role spelling). Valid rows import and every bad row gets its own error. Pinned in Task 18 (`test_user_csv_messy_rows`).
5. **Editing after a lock.** Changing a signed or snapshot-locked item creates a new version with a mandatory reason and keeps the old one. Pinned in Task 27 (`test_signed_item_edit_creates_version`) and Task 25 (`test_locked_score_not_recalculated`).

---

## File Structure

```
backend/
  pyproject.toml                      deps, pytest config
  alembic.ini, migrations/            Alembic env + versions
  app/
    main.py                           create_app(settings) -> FastAPI; SPA static mount
    cli.py                            `python -m app.cli` seed-reference | reset-demo | create-admin
    core/{config.py,db.py,models.py,ids.py,errors.py,clock.py}
    audit_log/{models.py,service.py,router.py}
    auth/{models.py,passwords.py,sessions.py,totp.py,service.py,router.py,deps.py,csrf.py}
    invitations/{models.py,service.py,router.py}
    mail/{models.py,service.py,router.py}            OutboxMessage; send(); outbox viewer
    tenancy/{models.py,service.py,router.py}         Organization, Department, User, RoleAssignment
    policy/{roles.py,actions.py,matrix.py,authorize.py,sod.py}
    files/{models.py,storage.py,scan.py,service.py,router.py}
    reference/{jurisdictions.py,iso_seed.py,frameworks.py,catalogs.py,templates.py,router.py,models.py}
    laws/{models.py,importer.py,publish.py,refresh.py,router.py}
    questionnaire/{models.py,seed.py,rules.py,service.py,router.py}
    engagements/{models.py,service.py,gates.py,suggest.py,router.py}
    documents/{render.py,docx.py,pdf.py,templates/*.html.j2}
    initiation/{models.py,service.py,router.py}
    signoffs/{models.py,service.py,router.py}
    governance/{models.py,service.py,coverage.py,router.py}
    inventory/{models.py,tiering.py,service.py,router.py}
    attestation/{models.py,service.py,router.py}
    systems/{models.py,service.py,router.py}
    docrequests/{models.py,service.py,router.py}
    scoring/{engine.py,service.py,router.py}
    findings/{models.py,service.py,router.py}
    reports/{models.py,builder.py,service.py,router.py}
    remediation/{models.py,service.py,router.py}
    notifications/{models.py,service.py,jobs.py,router.py}
    demo/{seed_demo.py}
    static/                           built SPA (gitignored except .gitkeep)
  seeds/{law_matrix.xlsx,question_bank.yaml,checklists.yaml,document_catalog.yaml,
         governance_catalog.yaml,frameworks.yaml,risk_methodology_v1.yaml,eu_members.yaml,
         feature_map.yaml,templates/*.md.j2}
  tests/{conftest.py,factories.py,<domain>/test_*.py}
frontend/
  package.json, vite.config.ts (outDir ../backend/app/static), tsconfig.json
  src/{main.tsx,App.tsx,routes.tsx,api/{client.ts,<domain>.ts},
       shells/{FutranShell.tsx,ClientShell.tsx,PhoneShell.tsx,TestModeBar.tsx},
       components/{ui/*,StageTracker.tsx,LawPicker.tsx,QuestionCard.tsx,FileDrop.tsx,SignPanel.tsx,DataTable.tsx},
       screens/{futran/*,client/*,phone/*,admin/*,auth/*},
       styles/{tokens.css,base.css}}
e2e/{package.json,playwright.config.ts,journey.spec.ts,mobile.spec.ts}
setup.bat run.bat Dockerfile README.md .env.example CLAUDE.md
```

**Shared test fixtures (`backend/tests/conftest.py`)** used by every backend task:
- `db`: a fresh SQLite in-memory session per test, with `Base.metadata.create_all`.
- `client`: a FastAPI `TestClient` bound to `db`.
- `make_org(type="client"|"futran", **kw)`, `make_user(org, roles=[...], **kw)`, `login_as(client, user) -> client` (sets cookie and CSRF header; bypasses TOTP using `MFA_REQUIRED=false` in test settings unless the test opts in).
- `make_engagement(client_org, stage=1, team={...})`.

Factories live in `tests/factories.py`, and each later task adds factories there for its own models.

---

## Phase 1 — Foundation

### Task 1: Scaffold backend, settings, database, health endpoint

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/core/{config.py,db.py,models.py,ids.py,errors.py,clock.py}`, `backend/tests/conftest.py`, `backend/tests/core/test_health.py`, `.gitignore`, `.env.example`, `CLAUDE.md`, `backend/alembic.ini`, `backend/migrations/env.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings) fields: `database_url="sqlite:///./data/app.db"`, `file_store="local:./data/files"`, `mfa_required=True`, `email_mode="outbox"`, `smtp_*`, `anthropic_api_key=None`, `claude_model="claude-sonnet-4-5"`, `data_region_label="us-east"`, `session_idle_min=30`, `session_max_hours=12`, `retention_years_default=7`, `virus_scan="off"`, `base_url="http://localhost:8000"`, `secret_key`. Property `test_mode -> bool` (= `not mfa_required or email_mode == "outbox"`).
  - `get_settings() -> Settings` (lru_cache).
  - `Base` (DeclarativeBase).
  - `TimestampedTenantMixin` with the columns from Global Constraints.
  - `new_id() -> str` (uuid4 string).
  - `utcnow() -> datetime` in `core/clock.py`, monkeypatchable in tests.
  - `get_db()` FastAPI dependency.
  - `create_app(settings: Settings | None = None) -> FastAPI`.
  - Error types `NotFound` (404), `Forbidden` (403), `Conflict` (409), `Invalid` (422 with `errors: list[dict]`).

- [ ] **Step 1:** Write `test_health_reports_status_and_test_mode`: `GET /api/v1/health` → 200, `{"status": "ok", "test_mode": True, "data_region": "us-east", "version": "0.1.0"}` when settings have `mfa_required=False`.
- [ ] **Step 2:** Run `cd backend && uv run pytest tests/core/test_health.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement the files above. `create_app` registers error handlers that map the four error types to JSON `{"detail": ..., "errors": [...]}`. Alembic `env.py` targets `Base.metadata` and the `DATABASE_URL` from settings, with `render_as_batch=True` for SQLite.
- [ ] **Step 4:** Run tests → PASS. Run `uv run alembic revision --autogenerate -m baseline` (empty) and `uv run alembic upgrade head` against a temp SQLite → succeeds.
- [ ] **Step 5:** Commit `chore: scaffold backend, settings, db and health endpoint`, then push.

### Task 2: Tenancy models and the append-only audit log

**Files:**
- Create: `backend/app/tenancy/models.py`, `backend/app/audit_log/{models.py,service.py}`, `backend/tests/tenancy/test_models.py`, `backend/tests/audit_log/test_service.py`, migration

**Interfaces:**
- Produces models:
  - `Organization` (name, legal_name, trading_name, type `futran|client`, industry, employee_band, hq_street/city/state/postal_code/country, website, client_ref `FUT-####`, status `draft|active|archived`, engagement_reason, `data_region`, `is_internal: bool`). The root Futran org has `organization_id = id`.
  - `Department` (name, head_user_id, headcount, `parent_id` nullable).
  - `User` (name, email unique per org lower-cased, job_title, phone, password_hash nullable, mfa_enabled, sso_subject, status `invited|active|disabled`).
  - `RoleAssignment` (user_id, role, scope_type `org|department|engagement|system`, scope_id, start_date, end_date).
- Produces audit log:
  - `AuditLog` (actor_id, action, object_type, object_id, before json, after json, ip, user_agent, at).
  - `audit.record(db, actor_id, action: str, obj, before: dict|None, after: dict|None, request=None) -> AuditLog`.
  - `audit.query(db, organization_id, **filters) -> list[AuditLog]`.
- Helpers:
  - `next_client_ref(db) -> str` returns `FUT-0001`, then `FUT-0002`, and so on.
  - `snapshot(obj) -> dict` returns a JSON-able dict of column values.

- [ ] **Step 1:** Write tests:
  - `test_client_ref_sequence` asserts the first two refs are `FUT-0001` and `FUT-0002`.
  - `test_user_email_unique_case_insensitive` asserts that creating `A@x.com` and then `a@x.com` in the same org raises `Conflict`.
  - `test_audit_record_stores_before_after`.
  - `test_audit_log_is_append_only` asserts that updating or deleting an `AuditLog` row through the session raises `PermissionError`. Implement this with SQLAlchemy `before_update`/`before_delete` mapper events that raise.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Autogenerate the migration.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: tenancy models and append-only audit log`.

### Task 3: Authentication — passwords, sessions, TOTP, CSRF

**Files:**
- Create: `backend/app/auth/*`, `backend/tests/auth/test_login.py`, `test_sessions.py`, `test_totp.py`, migration

**Interfaces:**
- Produces models:
  - `AuthSession` (user_id, token_hash, created_at, last_seen_at, expires_at, ip, user_agent, mfa_passed bool, csrf_token).
  - `MfaSecret` (user_id, secret_encrypted, confirmed_at).
- Produces functions:
  - `hash_password(pw) -> str`; `verify_password(hash, pw) -> bool` (argon2). Password policy: at least 12 characters, not equal to the email.
  - `create_session(db, user, request) -> tuple[AuthSession, raw_token]`.
  - `load_session(db, raw_token) -> AuthSession | None`. Applies idle and absolute expiry, and touches `last_seen_at`.
  - `totp_provisioning_uri(user, secret)`; `verify_totp(secret, code) -> bool` (valid_window=1).
- Produces routes:
  - `POST /api/v1/auth/login {email, password}` → `{mfa_required: bool, mfa_enrolled: bool}`.
  - `POST /api/v1/auth/mfa/enroll` → `{otpauth_uri, secret}`.
  - `POST /api/v1/auth/mfa/verify {code}`.
  - `POST /api/v1/auth/logout`.
  - `GET /api/v1/auth/me` → `{user, organization, roles: [{role, scope_type, scope_id}], test_mode}`.
- Produces dependencies:
  - `current_actor(request, db) -> Actor`, where `Actor` is a dataclass: user, organization, roles, session.
  - It raises 401 when there is no session, and 403 `mfa_required` when MFA is required and not passed.
  - CSRF: an `X-CSRF-Token` header must equal `session.csrf_token` on POST, PUT, PATCH and DELETE.
- Cookie `fap_session`: HttpOnly, SameSite=Lax, Secure when `base_url` starts with https.

- [ ] **Step 1:** Write tests:
  - `test_login_wrong_password_401_and_audited`
  - `test_login_disabled_user_401`
  - `test_mfa_required_blocks_me_until_verified`, run with `mfa_required=True`
  - `test_totp_enroll_then_verify_marks_session`
  - `test_idle_timeout_expires_session`: monkeypatch `utcnow` 31 minutes ahead → 401
  - `test_absolute_timeout_expires_session`: keep the session active every 20 minutes for 12 h 1 min → 401
  - `test_csrf_required_on_post`
  - `test_password_policy_rejects_short`
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Encrypt the TOTP secret at rest with Fernet, keyed from `secret_key`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: password, session and TOTP authentication`.

### Task 4: Invitations and mail outbox

**Files:**
- Create: `backend/app/invitations/*`, `backend/app/mail/*`, `backend/tests/invitations/test_invitations.py`, `backend/tests/mail/test_outbox.py`, migration

**Interfaces:**
- Produces models:
  - `Invitation` (user_id, token_hash, sent_at, expires_at, accepted_at, status `pending|accepted|expired|revoked`).
  - `OutboxMessage` (to, cc, subject, body_html, body_text, template_key, related_type, related_id, status `queued|sent|failed`, sent_at, error).
- Produces functions:
  - `mail.send(db, template_key: str, to: list[str], context: dict, cc=None, related=None) -> OutboxMessage`. Renders the Jinja templates `backend/app/mail/templates/{key}.subject.j2`, `.html.j2` and `.txt.j2`. In `outbox` mode it stores with status `sent`; in `smtp` mode it sends with `smtplib` and records the result.
  - `invite_user(db, actor, user) -> Invitation`. Creates a fresh token, revokes earlier pending invitations, sends `invitation`, and returns the invitation. The raw token is only ever sent in the email.
  - `accept_invitation(db, raw_token, password) -> User`. Sets the password, sets status active, and creates the session.
- Produces routes:
  - `POST /api/v1/invitations/{user_id}/resend`
  - `GET /api/v1/invitations/accept/{token}` → `{email, organization_name, expired: bool}`
  - `POST /api/v1/invitations/accept/{token} {password}`
  - `GET /api/v1/admin/outbox` (Futran Admin and Chief Auditor only)

- [ ] **Step 1:** Write tests:
  - `test_invite_expires_after_7_days`
  - `test_resend_invalidates_previous_token`
  - `test_accept_sets_password_and_activates`
  - `test_accept_used_token_rejected`
  - `test_outbox_mode_stores_message_with_rendered_subject`
  - `test_invitation_email_has_no_attachments_and_contains_accept_link`
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: invitations and mail outbox`.

### Task 5: Policy layer — roles, permission matrix, scopes, separation of duties

**Files:**
- Create: `backend/app/policy/{roles.py,actions.py,matrix.py,authorize.py,sod.py}`, `backend/tests/policy/test_matrix.py`, `test_sod.py`, `test_tenancy_isolation.py`

**Interfaces:**
- `Role` (StrEnum):
  - Futran: `chief_auditor, admin, auditor, qa_reviewer, engagement_manager, legal_reviewer`
  - Client: `exec_sponsor, caico, client_admin, dpo, dept_compliance_lead, contributor`
- `Action` (StrEnum): one per row of spec §5, plus v0.2 actions.
  - From §5: `manage_futran_users, create_client_engagement, approve_engagement, assign_auditors, manage_client_users, configure_templates, approve_templates, register_ai_tool, submit_use_case, approve_use_case, propose_tier, set_final_tier, override_final_tier, record_named_users, launch_attestation, view_individual_attestations, view_attestation_aggregates, answer_governance, approve_governance, upload_evidence, record_findings, approve_findings, sign_final_report, view_final_report, respond_findings, approve_responses, verify_remediation, close_remediation, view_audit_log`
  - v0.2: `prefill_system, verify_system_answers, score_system, view_scores, manage_document_requests, upload_requested_document, sign_declaration, manage_reference_data, run_law_refresh`
- `MATRIX: dict[Role, dict[Action, Scope]]`, where `Scope` is one of `ALL, ASSIGNED, ORG, DEPT, SYSTEM, NONE`. It is transcribed from spec §5 plus §8a of the schematic:
  - Contributor with `scope_type=system` gets `prefill_system` and `upload_evidence` for that system.
  - Clients get `view_scores` only from Stage 7 (enforced in the scores service).
- `authorize(actor: Actor, action: Action, *, engagement_id=None, department_id=None, system_id=None, org_id=None) -> None` raises `Forbidden`. Futran ASSIGNED is satisfied by an `EngagementTeam` row, or by the `chief_auditor` and `admin` roles, which see all engagements.
- `scoped_query(actor, model)`: a tenant filter. Client actors get `model.organization_id == actor.organization.id`. Futran actors get client orgs that have an engagement they are assigned to; admin and chief_auditor get all.
- SoD helpers in `sod.py`:
  - `assert_not_self_approval(approver_id, *preparer_ids)`
  - `assert_not_admin_judgment(actor)`, used for findings and tiers
  - `assert_client_cannot_edit_finding(actor)`

- [ ] **Step 1:** Write tests:
  - `test_matrix_rows_match_spec`: a parametrized table of about 60 (role, action, expected scope) rows copied from spec §5.
  - `test_admin_never_judgment` covers `record_findings`, `approve_findings`, `set_final_tier` and `override_final_tier`, all denied.
  - `test_sod_no_self_approval_multi_role`: one user holding `dept_compliance_lead` and `contributor` cannot approve their own use case.
  - `test_auditor_unassigned_engagement_forbidden`.
  - `test_dept_lead_aggregate_only_attestations`.
  - `test_cross_tenant_id_returns_404`: a client user from org B requests org A's department by ID → 404. Use a temporary router registered only in the test, through `scoped_query`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: policy layer with permission matrix and separation of duties`.

### Task 6: Frontend foundation — shells, design tokens, auth screens, SPA serving

**Files:**
- Create: `frontend/*` (Vite React TS), `frontend/src/styles/tokens.css`, the shells, `screens/auth/{Login.tsx,MfaEnroll.tsx,MfaVerify.tsx,AcceptInvite.tsx}`, `api/client.ts`, `components/ui/{Button,Field,Input,Select,Checkbox,Table,Badge,Card,Tabs,Dialog,Toast,ProgressBar,EmptyState}.tsx`, `e2e/` scaffold, `e2e/auth.spec.ts`
- Modify: `backend/app/main.py`, which serves `app/static` with an SPA fallback for non-`/api` paths

**Interfaces:**
- `api/client.ts`:
  - `api.get/post/put/patch/delete<T>(path, body?)`. The base is `/api/v1`. It reads the CSRF token from `/auth/me`, keeps it in memory, and throws `ApiError {status, detail, errors}`.
  - `useMe()` (TanStack Query) and `RequireAuth` / `RequireRole` route guards.
- Shells (per the mockups):
  - `FutranShell` has a navy header with the nav "Dashboard · Clients · Templates · Reference data · Users" and shows the user's name and role.
  - `ClientShell` has a white header.
  - `PhoneShell` is a single column, at most 480 px wide.
  - `TestModeBar` is red and reads: "Test mode — sign-in codes are switched off and emails go to the outbox. Do not enter client data." (Use the correct half when only one of the two applies.)
- Vite `build.outDir = ../backend/app/static`. Dev proxy `/api` → `http://localhost:8000`.

- [ ] **Step 1:** Write the Playwright test `auth.spec.ts`: a seeded admin signs in with a password and lands on `/audits`; a wrong password shows "Email or password is incorrect."; the test-mode bar is visible.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:**
  - Implement the screens to match `Main.dc.html` (login layout).
  - Tokens: `--navy #1B3A6B; --blue #2E75B6; --accent #0098D4; --ink #1d2433; --muted #5b6474; --line #d9dee7; --bg #f5f7fa; --danger #b42318; --success #067647; --warn #b54708`.
  - Load IBM Plex Sans from Google Fonts with a system-font fallback. Self-host it under `public/fonts` so the app works offline.
  - Components use real labelled controls with a minimum height of 44 px.
- [ ] **Step 4:** Run `cd frontend && npm run build`, then `cd e2e && npx playwright test auth.spec.ts` against `uvicorn app.main:app` → PASS.
- [ ] **Step 5:** Commit `feat: frontend shells, design tokens and sign-in screens`.

### Task 7: Admin — users, settings, audit log and outbox viewers; CLI and launchers

**Files:**
- Create: `backend/app/tenancy/router.py` (Futran users CRUD), `backend/app/audit_log/router.py` (list + CSV), `backend/app/mail/router.py`, `backend/app/cli.py`, `frontend/src/screens/admin/{Users.tsx,AuditLog.tsx,Outbox.tsx,Settings.tsx}`, `setup.bat`, `run.bat`, `backend/tests/admin/test_admin_routes.py`

**Interfaces:**
- Routes:
  - `GET/POST/PATCH /api/v1/admin/users`, restricted to the Futran admin.
  - `GET /api/v1/audit-log?object_type&object_id&actor_id&from&to&format=csv`. The CSV columns are `at,actor,action,object_type,object_id,ip`.
- CLI:
  - `python -m app.cli create-admin --email --name` prints a one-time invitation link.
  - `python -m app.cli seed-reference` is idempotent and runs every loader registered in `app/reference/__init__.py:LOADERS`.
  - `python -m app.cli reset-demo` drops and recreates `data/app.db`, then runs `seed-reference` and `demo.seed_demo.run`.
- `setup.bat`:
  - Checks for Python 3.11+.
  - Creates `.venv` and runs `pip install -e backend`.
  - Copies `.env.example` to `.env` if it is missing.
  - Runs `alembic upgrade head`, then `seed-reference`.
- `run.bat`:
  - Activates `.venv` and runs `alembic upgrade head`.
  - Starts `uvicorn app.main:app --port 8000` and opens the browser.
  - The `--reset-demo` flag runs `reset-demo` first.
  - Same pattern as `ll144_run.bat`.

- [ ] **Step 1:** Write tests:
  - `test_admin_creates_futran_user_and_invites`
  - `test_auditor_cannot_manage_users_403`
  - `test_audit_log_csv_export_columns`
  - `test_audit_log_client_sees_own_org_only`
- [ ] **Step 2–4:** FAIL → implement (backend and screens) → PASS.
- [ ] **Step 5:** Commit `feat: admin users, audit log, outbox and launchers`. **Phase 1 check-in:** screenshots of login, the users screen and the audit log are sent to Sour.

## Phase 2 — Reference data

### Task 8: Jurisdiction tree, ISO seed, location resolution

**Files:**
- Create: `backend/app/reference/{models.py,jurisdictions.py,iso_seed.py}`, `backend/seeds/eu_members.yaml`, `backend/tests/reference/test_jurisdictions.py`, migration

**Interfaces:**
- `Jurisdiction` is a reference table without a tenant (`organization_id` is the Futran org).
  - Fields: code (unique), name, level `supranational|country|state|city`, parent_id, iso_code, `has_laws: bool`, `feature_notes: json` (from the Global Matrix), active.
  - Codes: `US`, `US-NY`, `US-NYC`, `EU`, `DE`, `IN`, `IN-KA`, `AE`, `SA`, and so on. ISO 3166-1 alpha-2 for countries; ISO 3166-2 for subdivisions; `<state>-<CITYCODE>` for cities.
- `JurisdictionMembership` (member_id, group_id): links countries to the EU.
- `seed_iso(db)` loads all countries and subdivisions from `pycountry`. Subdivisions are created with `has_laws=False`. It is idempotent.
- `resolve_jurisdictions(db, country: str, subdivision: str|None, city: str|None) -> list[Jurisdiction]`.
  - Order: city, state, country, then supranational groups.
  - The city is included only if a city jurisdiction exists under that state with a matching name. "New York", "New York City" and "NYC" all match `US-NYC`.

- [ ] **Step 1:** Write tests:
  - `test_resolve_manhattan` asserts the codes `["US-NYC","US-NY","US"]`.
  - `test_resolve_berlin` asserts `["DE-BE","DE","EU"]`.
  - `test_resolve_bangalore` asserts `["IN-KA","IN"]`.
  - `test_resolve_unknown_city_skips_city`.
  - `test_seed_iso_idempotent` asserts the count is unchanged on a second run.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: jurisdiction tree and location resolution`.

### Task 9: Law matrix importer — parse, preview, publish, versions

**Files:**
- Create: `backend/app/laws/{models.py,importer.py,publish.py}`, `backend/seeds/feature_map.yaml`, `backend/tests/laws/test_importer.py`, `test_publish.py`, migration

**Interfaces:**
- Models:
  - `MatrixVersion` (label, status_date, source_filename, sources json, status `draft|published|superseded`, published_by, published_at).
  - `Regulation` (jurisdiction_id, matrix_version_id, short_name, citation, feature, type `statute|regulation|executive|voluntary|pending|policy|guidance`, enforcer, trigger_text, obligations_text, developments_text, most_affected, effective_date_text, status_text, applies_to `deployer|developer|both`, verify_flag, source_sheet, source_row_ref, superseded_by_id, origin `import|manual|claude`).
  - `FeatureMap` (category_text → feature).
- `Feature` (StrEnum): the 9 values in spec §10.2.
- `parse_workbook(path) -> ImportPreview` is pure, with no database. `ImportPreview` has:
  - `status_date: date`
  - `rows: list[PreviewRow]`, where `PreviewRow` has jurisdiction_code, jurisdiction_name, level, feature, short_name, full_text, type, enforcer, trigger, obligations, developments, most_affected, verify_flag, applies_to, source_sheet, source_row_ref
  - `jurisdiction_notes: dict[code, dict[feature, text]]`
  - `sources: list[{topic, source}]`
  - `warnings: list[str]`
- Sheet rules (header on row 4; data rows have a non-empty column A):
  - **Federal Laws** → `US`.
  - **State Matrix**: column A is the state name, mapped to an ISO subdivision. `New York (incl. NYC)` → `US-NY`. Columns B–J are features in enum order. Each cell is split on `\n`, ignoring `—` and blanks. `short_name` is the text before the first ` (` or `:` (at most 120 characters). Any part that names "Local Law 144" or "NYC" is moved to `US-NYC`.
  - **Global Matrix**: rows go to `jurisdiction_notes`; they are not regulations.
  - **EU, UK, Canada, Mexico, Brazil, India, Australia, Singapore**: 8 columns, the same as Federal Laws. The jurisdiction is `EU`, `GB`, `CA`, `MX`, `BR`, `IN`, `AU` or `SG`.
  - **Gulf**: the category `"<Country> · <Category>"` splits into the jurisdiction (UAE→`AE`, Saudi Arabia→`SA`, Qatar→`QA`, Bahrain→`BH`, Oman→`OM`) and the category.
  - Category → feature through `feature_map.yaml`. Anything unmapped → `government_other`, with a warning.
  - `verify_flag` is true when any cell contains `(verify)`.
  - `applies_to = developer` when the feature is `frontier_safety`, or the text matches `/frontier|developers only|developer[s]? of/i`.
  - `status_date` is parsed from the Read Me line "Status as of 5 October 2026".
- `publish(db, preview, actor, edits: dict[row_key, short_name]) -> MatrixVersion` upserts jurisdictions (`has_laws=True`) and creates regulations. When an earlier published version exists:
  - Unchanged rows (same jurisdiction, feature and short_name) keep their identity.
  - Changed rows get `superseded_by`.
  - Rows referenced by a `ClientRequirement` are never deleted.

- [ ] **Step 1:** Write tests against `seeds/law_matrix.xlsx`:
  - `test_status_date` asserts `date(2026,10,5)`.
  - `test_federal_count`: 26 rows, all `US`.
  - `test_state_matrix_states` asserts 26 distinct state codes, including `US-NY` and `US-CA`.
  - `test_ll144_routed_to_nyc`.
  - `test_global_notes_12_jurisdictions` asserts the codes {EU, GB, CA, MX, BR, IN, AE, SA, QA, BH, AU, SG}.
  - `test_country_sheet_counts` asserts EU 9, UK 8, Canada 8, Mexico 6, Brazil 7, India 8, Gulf 12, Australia 9, Singapore 8.
  - `test_gulf_oman_created`.
  - `test_frontier_marked_developer`.
  - `test_verify_flag_detected`.
  - `test_sources_34`.
  - `test_reimport_keeps_referenced_and_supersedes`: publish, reference one law, edit its obligations text in a copied workbook, publish again; the old row has `superseded_by` set and still exists.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: global law matrix importer with versioned publish`.

### Task 10: Admin jurisdictions and laws screens; law picker API

**Files:**
- Create: `backend/app/laws/router.py`, `frontend/src/screens/admin/{Jurisdictions.tsx,LawImport.tsx}`, `frontend/src/components/LawPicker.tsx`, `backend/tests/laws/test_router.py`

**Interfaces:**
- Routes:
  - `POST /api/v1/admin/laws/import` (multipart xlsx) → preview JSON with a `preview_id` (cached on disk).
  - `POST /api/v1/admin/laws/import/{preview_id}/publish {edits}`.
  - `GET /api/v1/jurisdictions?tree=1`, plus POST and PATCH.
  - `GET /api/v1/laws?geo=<codes|client:{org_id}|all>&feature=&q=&include_developer=0` → grouped `{jurisdiction: [...regs]}`.
  - `POST/PATCH /api/v1/laws`: manual add and edit. Each write creates a new MatrixVersion labelled `manual edit <date>`.
- `LawPicker` props: `{geography options, selected ids, onAdd(ids)}`. It has filters for Geography, AI feature and search. Results are grouped with checkboxes and an "Add N laws" button. Developer-only laws are greyed out with the note "Frontier developers only; not relevant to a deployer". There is a *Verify* badge. This matches `NewClient2.dc.html`.

- [ ] **Step 1:** Write tests:
  - `test_import_preview_then_publish_via_api`
  - `test_laws_filter_by_geo_and_feature`
  - `test_manual_edit_creates_version`
  - `test_non_admin_cannot_import_403`
- [ ] **Step 2–4:** FAIL → implement → PASS (the screens are verified in the Phase 2 Playwright smoke test in Task 13).
- [ ] **Step 5:** Commit `feat: jurisdiction and law administration with law picker`.

### Task 11: Claude law refresh with human approval

**Files:**
- Create: `backend/app/laws/refresh.py`, `frontend/src/screens/admin/LawUpdates.tsx`, `backend/tests/laws/test_refresh.py`, migration

**Interfaces:**
- `RegulationProposal` (jurisdiction_id, regulation_id nullable, change_type `add|update|retire`, proposed json, rationale, sources json `[{title,url}]`, status `pending|accepted|rejected`, reviewed_by, reviewed_at, run_id).
- `LawRefreshRun` (jurisdiction_ids, requested_by, model, status, error, token_usage).
- `ClaudeClient` protocol: `research(prompt: str) -> str`. `AnthropicClaudeClient` uses `anthropic.Anthropic().messages.create(model=settings.claude_model, max_tokens=8000, tools=[{"type":"web_search_20250305","name":"web_search","max_uses":8}], messages=[...])`.
- `run_refresh(db, actor, jurisdiction_ids, client: ClaudeClient) -> LawRefreshRun`.
  - For each jurisdiction, it sends the current regulations as JSON and asks for a strict JSON array of changes. Each change has a schema of change_type, regulation_id, fields, rationale and sources.
  - It validates the response with Pydantic and stores the proposals.
  - Invalid JSON → the run is `failed`, with the error saved.
- `accept_proposals(db, actor, ids) -> MatrixVersion` applies the accepted changes as a new version (`origin=claude`).
- Routes:
  - `POST /api/v1/admin/laws/refresh {jurisdiction_ids}` returns 409 with the message "Add an Anthropic API key in settings to use law updates." when there is no key.
  - `GET /api/v1/admin/laws/refresh/{run_id}`
  - `POST /api/v1/admin/laws/proposals/decide {accept:[], reject:[]}`

- [ ] **Step 1:** Write tests with a `StubClaude`:
  - `test_refresh_creates_proposals_from_stub`
  - `test_invalid_json_marks_run_failed`
  - `test_accept_creates_new_version_with_claude_origin`
  - `test_refresh_without_key_409`
  - `test_proposal_sources_required` (a proposal without sources is rejected at validation)
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: Claude-assisted law refresh with admin approval`.

### Task 12: Catalogs, frameworks, document templates, risk methodology seeds

**Files:**
- Create:
  - `backend/seeds/{frameworks.yaml,governance_catalog.yaml,document_catalog.yaml,risk_methodology_v1.yaml}`
  - `backend/seeds/templates/{engagement_letter,roles_note,user_csv,department_csv,data_notice,getting_started,governance_request,document_request_email,report}.md.j2`
  - `backend/app/reference/{frameworks.py,catalogs.py,templates.py}`
  - `frontend/src/screens/admin/Templates.tsx`
  - `backend/tests/reference/test_seeds.py`
  - migration

**Interfaces:**
- Models:
  - `Framework` (code: `OECD|NIST_AI_RMF|EU_AI_ACT|ISO_42001`, name) and `FrameworkControl` (framework_id, code, title).
  - `GovernanceCatalogItem` (kind `document|security_document|role`, code, title, description, control_refs[], conditional `eu_operations|null`).
  - `DocumentCatalogItem` (category 1–6, code, title, per_system bool, template_section).
  - `DocumentTemplate` (key, name, version, type, body (Markdown + Jinja merge fields), active).
  - `RiskMethodology` (version, factor_weights, domain_weights_by_build_type, bands, knockout_rules, effective_date).
- Seed contents are copied verbatim from spec §10.4, §10.5, §18.5 (Appendix A, from the template text) and §19.2–19.4.
- The management representation text from spec §8 is the template `management_representation`.
- `render_template(db, key, context) -> str` returns Markdown.
- Templates screen: list, edit body, save as a new version. The Admin role only.

- [ ] **Step 1:** Write tests:
  - `test_governance_roles_8_with_controls` checks that "Bias and fairness review committee" maps to OECD 1.2, MEASURE 2.11 and EU Art. 10.
  - `test_governance_documents_5_plus_5_security`.
  - `test_document_catalog_6_categories_and_per_system_flags`, where model card, validation report, bias report, DPIA and monitoring report are per_system.
  - `test_risk_weights_sum_to_1`, for the factors and for each build type's domains.
  - `test_template_version_bump_on_edit`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: reference catalogs, frameworks, templates and risk methodology`.

### Task 13: Question bank — models, seed from Template v1.0 + Addendum 5.1a, rule evaluators

**Files:**
- Create: `backend/app/questionnaire/{models.py,seed.py,rules.py}`, `backend/seeds/{question_bank.yaml,checklists.yaml}`, `backend/tests/questionnaire/test_seed.py`, `test_rules.py`, `e2e/admin-reference.spec.ts`, migration

**Interfaces:**
- Models per spec §18.1:
  - `TemplateVersion`
  - `Question` (code, section, sub_section, scope `engagement|system`, label, help_text, type, options json `[{value,label}]`, required, default_respondent `client|auditor`, applicability_rule json, finding_rule json, evidence_required, scoring_map json, build_types `[in_house,vendor,open_source_customized,hybrid]`, light bool, order)
  - `ChecklistItem` (section, code, text, scope, maturity_domain, applicability_rule, pending_review bool)
- `question_bank.yaml` authors every question code in spec §18.4: §3.1–3.3, 5.1, 5.1a, 5.2, 5.3, 6.1–6.3, V.01–V.08, 7.1–7.2, 8.1–8.3, 9.1 (as a vendor-inventory grid), 9.2, and the engagement-level §4.1–4.2 fields.
  - Labels and help text (INTERN NOTEs) come verbatim from `docs/reference/Futran_AI_Governance_Audit_Template.txt`.
  - `light: true` marks §3, §5, §7.2 and §9 (the Tier 2 set).
  - `build_types` follows the question sets in spec §19.1.
  - `→ F` markers become `finding_rule {"when": {"in": [...]}, "severity": "...", "title": "..."}`.
- `checklists.yaml` contains:
  - 4.3 (10 items), 5.4 (12 items + 5 Addendum 5.1a items drafted with `pending_review: true`), 6.4 (10), 7.3 (10) and 8.4 (11), each with a `maturity_domain`.
  - Template text verbatim. The 8.4 list in the template text has one blank row, so the 11th item is the template's "Model retraining triggered by performance degradation goes through change control before re-deployment".
- `rules.py`:
  - `is_applicable(rule: dict|None, answers: dict[str, Any], system: SystemContext) -> bool`. Supported operators: `{"q": code, "in": [...]}`, `{"q": code, "eq": v}`, `{"system": "built_by", "in": [...]}`, `{"engagement": "has_regulation_feature", "eq": "health_insurance"}`, `{"all": [...]}`, `{"any": [...]}` and `{"not": rule}`.
  - `evaluate_finding(rule, value, status) -> FindingDraft|None`. The status `not_yet_in_place` is treated as "no" (golden rule 2).
- Loader `load_question_bank(db) -> TemplateVersion`, named `Futran AI System Audit`, version `1.0`, addenda `["5.1a"]`.

- [ ] **Step 1:** Write tests:
  - `test_template_version_1_0_with_5_1a`
  - `test_all_spec_codes_present` checks a hard-coded list of every code in spec §18.4, for example `3.1.01..3.1.10`, `3.2.01..3.2.10`, `5.1a.01..5.1a.06` and `V.01..V.08`.
  - `test_checklist_counts` asserts `{4.3:10, 5.4:17, 6.4:10, 7.3:10, 8.4:11}`.
  - `test_hipaa_applicability_hidden_without_health`.
  - `test_vendor_assurance_replaces_6_1_and_6_3`: a vendor system shows V.* and hides 6.1.* and 6.3.*.
  - `test_not_yet_in_place_triggers_finding`.
  - `test_null_compliance_high_rule` (5.1a.05 `high` → finding severity `high`).
  - `test_light_set_is_3_5_7_2_9`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Then Playwright `admin-reference.spec.ts`: the admin imports the workbook, publishes, sees 26 states, edits a law and sees a new version.
- [ ] **Step 5:** Commit `feat: question bank and checklists from Template v1.0 with rule evaluators`.

## Phase 3 — Onboarding (screens 2–10)

### Task 14: Engagement domain, client contacts, law suggestion, stage gates

**Files:**
- Create: `backend/app/engagements/{models.py,service.py,gates.py,suggest.py,router.py}`, `backend/tests/engagements/test_suggest.py`, `test_gates.py`, `test_state.py`, migration

**Interfaces:**
- Models:
  - `Engagement` (client_id, name, type `initial_assessment|ll144_bias_audit|annual_review`, audit_ref `FSL-AI-AUD-YYYY-NNN`, period_start, period_end, letter_due, report_due, draft_report_target, final_report_target, fieldwork_start, methodology_version default `Futran AI Audit Procedure v1.0`, frameworks json, business_processes, data_environments, geographic_scope, exclusions, status, stage 1–9, created_by, approved_by, approved_at, overall_rating, returned_comment)
  - `ClientLocation` (site_name, street, city, subdivision_code, country_code, employees_at_site, in_scope, jurisdiction_ids json)
  - `ClientRequirement` (regulation_id nullable, source `auto|manual|futran_default`, reason_text, in_scope, notes, free_text)
  - `ScopeItem`
  - `EngagementTeam` (user_id, role `engagement_manager|chief_auditor|auditor|qa_reviewer|legal_reviewer`, conflict_confirmed_at)
  - `ClientContact` (contact_role `caico|client_admin|exec_sponsor|dpo|project_lead|technical_lead|compliance_lead`, not_appointed, user_id)
  - Organization §18.3 extra fields: `primary_jurisdictions`, `annual_revenue_band`, `employee_count`, `ai_systems_in_scope_count`
- `suggest_requirements(db, org, engagement) -> list[Suggestion{regulation, reason}]`, per spec §10.3 with the D4 tree:
  - It covers every resolved jurisdiction of in-scope locations.
  - It pre-checks laws whose feature matches the industry and engagement reason, via a keyword map: hiring/recruit/staffing → employment_hiring; insur/health → health_insurance; credit/lend/bank → consequential_decisions_admt; chatbot → chatbots_minors.
  - It always adds the Futran defaults: NIST AI RMF 1.0, and NY Civil Rights Law §52-c when any location resolves to `US-NY`.
  - Developer-only laws are excluded.
- `transition(db, actor, engagement, to_status, comment=None)` follows the allowed moves `draft→pending_approval→initiated→in_progress→completed→archived` and `pending_approval→draft` (returned with a comment).
- `GATES: dict[int, Callable[[Session, Engagement], GateResult]]`, where `GateResult(ready: bool, unmet: list[str])`. Task 14 implements the gates for stages 1 and 2; later tasks register theirs.
- `advance_stage(db, actor, engagement) -> Engagement` raises `Conflict(unmet)`.

- [ ] **Step 1:** Write tests:
  - `test_suggest_ny_chicago_hiring` checks that NYC LL144, IL HB 3773, Title VII, ADEA, NY §52-c and NIST AI RMF are all present (6), matching `NewClient2.dc.html`.
  - `test_suggest_berlin_includes_eu_ai_act_and_gdpr`.
  - `test_developer_only_excluded`.
  - `test_return_to_author_requires_comment`.
  - `test_cannot_skip_status`.
  - `test_stage2_gate_requires_lead_per_department`.
  - `test_audit_ref_format` matches `FSL-AI-AUD-2026-001`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: engagement domain, law suggestion and stage gates`.

### Task 15: New client wizard (screens 3–7, steps 1–4) with autosave

**Files:**
- Create:
  - `frontend/src/screens/futran/newclient/{Wizard.tsx,StepCompany.tsx,StepLocations.tsx,StepScope.tsx,StepContacts.tsx}`
  - `backend/app/engagements/router.py` (wizard endpoints)
  - `backend/tests/engagements/test_wizard_api.py`

**Interfaces:**
- Routes:
  - `POST /api/v1/clients` creates a draft org and engagement and returns `{client_id, engagement_id}`.
  - `PUT /api/v1/clients/{id}/wizard/{step} {payload}` autosaves a partial payload and returns `{saved_at, errors}`. It validates only required fields at submit.
  - `GET /api/v1/clients/{id}/wizard`.
  - `POST /api/v1/clients/{id}/submit` moves the engagement to `pending_approval` and notifies the Chief Auditor.
- Step fields come from the mockups NewClient1–4 plus §18.3:
  - **Step 2:** a locations table with country, state and city selects (driven by `/jurisdictions`), and requirements with `LawPicker`.
  - **Step 3:** the conflict confirmation checkbox is required for every team member, and the Engagement Manager and Lead Auditor are required.
  - **Step 4:**
    - CAICO is required.
    - Client Admin is either "same as CAICO" or a different person.
    - Sponsor and DPO can be marked "not appointed".
    - The Project lead defaults to the CAICO.

- [ ] **Step 1:** Write tests:
  - `test_autosave_partial_step`.
  - `test_submit_missing_caico_422_lists_field`.
  - `test_auditor_creates_draft_only`: an auditor can't approve.
  - `test_ai_systems_included_creates_aisystem_rows`. Skip until Task 22 adds the model; the API stores names in `engagement.planned_systems` json for now.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: new client wizard steps 1–4 with autosave`.

### Task 16: Document generation — Markdown templates to DOCX and PDF

**Files:**
- Create: `backend/app/documents/{render.py,docx.py,pdf.py,styles.css}`, `backend/app/files/{models.py,storage.py,scan.py,service.py,router.py}`, `backend/tests/documents/test_render.py`, `backend/tests/files/test_files.py`, migration

**Interfaces:**
- `render_markdown(md: str) -> str` produces HTML using `markdown-it-py` with tables enabled.
- `to_docx(md: str, title: str, meta: dict) -> bytes` walks the markdown-it token stream and writes it with python-docx.
  - Supported elements: headings 1–3, paragraphs, bold and italic, bullet and numbered lists, tables, and a page-break marker `<!-- pagebreak -->`.
  - The header shows "Futran Solutions · Confidential". The footer shows the audit ref and the page number.
- `to_pdf(md: str, title: str, meta: dict) -> bytes` uses xhtml2pdf with `styles.css`, in IBM Plex Sans when the font is bundled and Helvetica otherwise.
- `FileObject` (storage_key, filename, content_type, size, sha256, scan_status `clean|not_scanned|infected`, uploaded_by, linked_type, linked_id).
- `storage.put(org_id, data, filename) -> key` and `storage.get(key) -> bytes`. Keys are `{org_id}/{yyyy}/{uuid}-{safe_name}`, and there are `LocalStorage` and `AzureBlobStorage` stubs.
- `files.upload(db, actor, upload, linked) -> FileObject` enforces 50 MB, writes sha256, and runs `scan()`.
- `GET /api/v1/files/{id}` streams the file after `authorize` and writes an audit-log entry whenever the file is evidence.

- [ ] **Step 1:** Write tests:
  - `test_docx_has_heading_table_and_footer_ref`: open the result with python-docx and check it.
  - `test_pdf_starts_with_%PDF_and_has_pages`.
  - `test_upload_rejects_over_50mb`.
  - `test_upload_records_sha256`.
  - `test_file_download_cross_tenant_404`.
  - `test_evidence_view_audited`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: DOCX and PDF generation and file storage`.

### Task 17: Initiation package, approval and send, sign-off 1, client page, dashboard, initiation checklist

**Files:**
- Create:
  - `backend/app/initiation/*` and `backend/app/signoffs/{models.py,service.py,router.py}`; the sign-off core lives here and is extended in Task 27
  - `frontend/src/screens/futran/{Dashboard.tsx,ClientPage.tsx,newclient/StepPackage.tsx}`
  - `frontend/src/screens/client/InitiationChecklist.tsx`
  - `frontend/src/components/{StageTracker.tsx,SignPanel.tsx}`
  - `backend/tests/initiation/test_package.py` and `backend/tests/signoffs/test_signoff1.py`

**Interfaces:**
- Models:
  - `InitiationPackage` and `PackageDocument`, per spec §9.3.
  - `SignOff` (engagement_id, number 1–8, scope_ref (e.g. department_id for sign-off 2), preparer_id, reviewer_id, approver_ids json, required_approver_roles json, status `pending|in_review|approved|returned`, comment, approved_at, document_version_id, version, supersedes_id, correction_reason).
  - `Signature` (sign_off_id, user_id, typed_name, signed_at, ip, document_sha256).
- `generate_package(db, engagement) -> InitiationPackage` creates the 7 PackageDocuments, each rendered to DOCX and PDF, with `requires_action` set per spec §12.
- `approve_and_send(db, actor, package, client_message)` is for the Chief Auditor only, and the preparer cannot be the approver. It:
  - checks the approval checklist
  - invites the CAICO and Client Admin (one invitation when they are the same person)
  - moves the status to `initiated` and the stage to 1
  - creates SignOff 1, which the CAICO and the Chief Auditor must both approve
- `return_to_author(db, actor, engagement, comment)`.
- `sign(db, actor, sign_off, typed_name) -> Signature`. The typed name must match the user's name, ignoring case and whitespace.
- Stage 1 gate: SignOff 1 is approved.
- Screens:
  - **Dashboard:**
    - KPI tiles: in progress, completed, awaiting approval, awaiting client.
    - Filters: All, In progress, Completed, Drafts.
    - Search, a table and an activity feed from `AuditLog`.
  - **Client page:**
    - A 9-stage tracker with "What's left", taken from the gate's unmet list.
    - Details, laws in scope and team.
    - Activity, and resending an invitation.
  - **Client initiation checklist:** 7 tasks with progress. Package item 1 opens the SignPanel.

- [ ] **Step 1:** Write tests:
  - `test_package_has_7_documents_with_actions`.
  - `test_package_docs_render_docx_and_pdf`.
  - `test_approve_and_send_invites_caico_and_client_admin`.
  - `test_same_person_caico_admin_single_invite`.
  - `test_preparer_cannot_approve_package`.
  - `test_signoff1_requires_both_parties`.
  - `test_typed_name_must_match`.
  - `test_dashboard_auditor_sees_assigned_only`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: initiation package, approval, sign-off 1 and dashboards`. **Phase 3 check-in** with screenshots of the dashboard, wizard step 2, package review and the client checklist.

## Phase 4 — Setup and discovery (screens 10a–14)

### Task 18: Departments and users with CSV import; sign-off role changes

**Files:**
- Create: `backend/app/tenancy/csv_import.py`, `frontend/src/screens/client/UsersDepartments.tsx`, `backend/tests/tenancy/test_csv.py`

**Interfaces:**
- `parse_department_csv(text) -> CsvResult` and `parse_user_csv(text, departments) -> CsvResult`.
  - `CsvResult(rows_ok: list[dict], errors: list[{row:int, field:str, message:str}])`.
  - Headers are exactly as in spec §12. The parser accepts a UTF-8 BOM and trims values.
  - Roles match case-insensitively on the full names listed in spec §12.
- `import_users(db, actor, rows) -> list[User]` creates users and RoleAssignments, then sends invitations.
- When an assignment to a sign-off role (caico, exec_sponsor or dpo) is assigned or removed:
  - `Notification` goes to the Chief Auditor and the assigned auditors.
  - An audit-log entry is written.
- Stage 2 gate (registered here): every in-scope department has an active `dept_compliance_lead`.

- [ ] **Step 1:** Write tests:
  - `test_user_csv_messy_rows`. The input has a BOM, trailing spaces, a duplicate email, an unknown department and the role "dept lead". Expect 2 ok rows and 3 errors with exact messages:
    - "Department 'Legal' is not in the department list."
    - "Role 'dept lead' is not recognised."
    - "Email appears more than once in this file."
  - `test_department_csv_prefilled_from_scope`.
  - `test_sign_off_role_change_notifies_futran`.
  - `test_client_admin_cannot_edit_audit_content`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: client departments and users with CSV import`.

### Task 19: AI governance structure request, commitments and coverage panel

**Files:**
- Create: `backend/app/governance/*`, `frontend/src/screens/client/Governance.tsx`, `frontend/src/screens/futran/GovernanceRequestSetup.tsx`, `backend/tests/governance/test_governance.py`, migration

**Interfaces:**
- Models per spec §9.4: `GovernanceRequest`, `GovernanceDocumentItem`, `GovernanceRoleItem` and `Commitment` (status `open|in_progress|awaiting_verification|closed|reopened`).
- `create_request(db, actor, engagement, selected_codes, due_date)` (Chief Auditor).
- `answer_item(db, actor, item, payload)` validates each answer:
  - **In place** needs the names, and the documents where the item is a document.
  - **Will constitute / will create** needs a target date and an interim owner, and creates or updates a `Commitment`.
  - **Not applicable** needs a reason.
- `submit(db, actor, request, accuracy_confirmed: bool)`. Every selected item must be answered.
- `coverage(request) -> dict[str, Literal["covered","planned","partial","gap"]]` keyed by OECD principle and NIST function:
  - **covered**: all mapped items are in place.
  - **planned**: at least one item will be created and none are missing.
  - **partial**: a mix of in-place and gap.
  - **gap**: none are in place and none are planned.
- Engagement-level §4.1–4.2 fields are stored as `Response` rows (scope engagement) once Task 23 lands. For now they are a JSON field, `GovernanceRequest.extra_fields`.

- [ ] **Step 1:** Write tests:
  - `test_in_place_requires_names`.
  - `test_will_constitute_creates_commitment`.
  - `test_na_requires_reason`.
  - `test_submit_blocked_until_all_answered_and_accuracy`.
  - `test_coverage_partial_and_gap`.
  - `test_eu_rep_only_when_eu_operations`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `Governance.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: AI governance structure request with commitments and coverage`.

### Task 20: Employee attestation campaign and phone form

**Files:**
- Create: `backend/app/attestation/*`, `frontend/src/screens/client/AttestationTracker.tsx`, `frontend/src/screens/phone/Attestation.tsx`, `backend/tests/attestation/test_attestation.py`, migration

**Interfaces:**
- `AttestationCampaign` and `Attestation`, per spec §9.5.
- `launch(db, actor, engagement, department_ids, closes_at, policy_version)` requires the employee data notice to be acknowledged by the CAICO first. That is `PackageDocument` item 5 with `completed_at` set.
- `submit_attestation(db, token, payload)` is a public, no-login endpoint (`POST /api/v1/public/attest/{token}`). It is rate-limited to 30 requests per minute per IP. The token exposes only the campaign's department list and policy text.
- `tracker(db, actor, campaign)` returns counts by department, with any count below 3 shown as `"fewer than 3"`, and tools declared with their account type. Individual responses are returned only for the CAICO, DPO and assigned auditors.
- Each declared tool is upserted as an `AITool`, matched case-insensitively on vendor and product (the model is in Task 21; the upsert is wired when Task 21 lands).
- Stage 3 gate (registered here and extended in Task 21): the campaign is closed and the governance request is submitted.

- [ ] **Step 1:** Write tests:
  - `test_launch_blocked_without_data_notice_ack`.
  - `test_public_link_exposes_no_other_data`.
  - `test_dept_counts_under_3_masked`.
  - `test_dept_lead_gets_aggregate_only`.
  - `test_submission_audited`.
  - `test_closed_campaign_rejects_submissions`.
- [ ] **Step 2–4:** FAIL → implement (4 phone steps per `Attestation.dc.html` and `Campaign.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: employee attestation campaign and phone form`.

### Task 21: Inventory — tools, use cases, tiering, named users and confirmation links

**Files:**
- Create: `backend/app/inventory/*`, `frontend/src/screens/client/UseCaseForm.tsx`, `frontend/src/screens/phone/NamedUserConfirm.tsx`, `backend/tests/inventory/test_tiering.py`, `test_named_users.py`, migration

**Interfaces:**
- Models per spec §9.5:
  - `AITool`, `UseCase`, `UsageRecord`.
  - `NamedUser`, which adds `email`.
  - `NamedUserLink` (named_user_id, token_hash, sent_at, completed_at, training_complete, policy_acknowledged, oversight_role_confirmed, unable_reason).
- `propose_tier(decision_impact, data_categories, tools: list[AITool]) -> int`, per spec §11. The first match wins:
  - 3 if `consequential`.
  - 2 if the data includes any of pii, phi, client or confidential, or if any tool has an account_type of personal_free, personal_paid or unknown, or `training_on_inputs` unknown.
  - Otherwise 1.
- `submit_use_case(db, actor, uc)`:
  - Recomputes `proposed_tier`.
  - Requires named users when the tier is 2 or above (`Invalid` lists them).
  - For each named user without an account, it creates a `NamedUserLink` and sends `named_user_confirm`.
- `POST /api/v1/public/confirm/{token}` takes `{training_complete, policy_acknowledged, oversight_role_confirmed}`.
- `set_final_tier(db, actor, uc, tier, rationale, aedt_determination=None)` is for an assigned auditor only. A Chief Auditor override needs a rationale. Raising the tier re-sends the links.
- Stage 3 gate addition: all use cases are submitted.

- [ ] **Step 1:** Write tests:
  - `test_tier3_consequential`.
  - `test_tier2_pii`.
  - `test_tier2_personal_account_tool`.
  - `test_tier1_otherwise`.
  - `test_tier2_requires_named_users`.
  - `test_links_sent_on_submit_tier2`.
  - `test_confirm_link_public_minimal`.
  - `test_client_cannot_set_final_tier`.
  - `test_admin_cannot_set_final_tier`.
  - `test_raise_tier_resends_links`.
- [ ] **Step 2–4:** FAIL → implement (use case form per `InventoryUseCase.dc.html`, with a live proposed tier) → PASS.
- [ ] **Step 5:** Commit `feat: AI inventory with tiering and named-user confirmations`.

## Phase 5 — Systems and evidence (screens 21–24)

### Task 22: AI systems and vendors register

**Files:**
- Create: `backend/app/systems/*`, `frontend/src/screens/futran/SystemsRegister.tsx`, `backend/tests/systems/test_systems.py`, migration

**Interfaces:**
- Models:
  - `AISystem` per spec §19.1 (engagement_id, name, reference_id `SYS-###` per engagement, version, owner_user_id, technical_owner_user_id, department_id, built_by, vendor_id, tool_ids, use_case_ids, assessment_depth `full|light`, status `not_started|client_prefill|in_review|scored|locked`, completion_pct, methodology_version).
  - `Vendor` (organization_id, legal_name, capability, personal_data_processed, baa_dpa_signed, last_risk_review, risk_level `H|M|L`). This is the §9.1 inventory.
- `create_from_use_case(db, actor, uc_ids, built_by, ...) -> AISystem`. Depth is `full` if any linked use case is final or proposed Tier 3, and `light` otherwise.
- After Stage 1, adding a system needs an Engagement Manager approval (`SystemAdditionRequest`, approved by an `engagement_manager` other than the requester).
- `unmapped_tier3(db, engagement) -> list[UseCase]` drives the register banner "N Tier 3 use cases are not mapped to a system".
- Planned systems from the wizard are converted to `AISystem` rows at approve-and-send. This back-fills Task 15's json.

- [ ] **Step 1:** Write tests:
  - `test_reference_ids_sequential_per_engagement`.
  - `test_depth_full_for_tier3_light_for_tier2`.
  - `test_unmapped_tier3_listed`.
  - `test_add_after_initiation_requires_em_approval`.
  - `test_wizard_planned_systems_converted`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `Systems.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: AI systems and vendor register`.

### Task 23: System assessment — responses, golden rules, client pre-fill and auditor verification

**Files:**
- Create: `backend/app/questionnaire/{service.py,router.py}`, `frontend/src/screens/futran/SystemAssessment.tsx`, `frontend/src/screens/client/SystemPrefill.tsx`, `frontend/src/components/QuestionCard.tsx`, `backend/tests/questionnaire/test_service.py`, migration

**Interfaces:**
- Models:
  - `Response` per spec §18.1, plus `history` via a `ResponseVersion` table.
  - `ChecklistResult`.
  - `DraftFindingLink` (response_id, finding_id, dismissed_reason).
- `questions_for(db, engagement, system|None, actor) -> list[QuestionView]`.
  - It applies `is_applicable` and the depth (light → only `light` questions), and `build_types`.
  - **Client actors** see only `default_respondent=client` questions and their own values.
  - **Futran actors** see everything, plus `verified` and the help text.
- `save_response(db, actor, question, value, status, na_reason, source_person_name, source_person_title, evidence_ids) -> Response` enforces the golden rules:
  - **N/A** needs a reason.
  - **Interview source.** When an auditor records an answer and marks it `verified`, the source person name and title are required.
  - **Not yet in place.** The status `not_yet_in_place` is stored as-is.
  - **Draft findings.** When `evaluate_finding` returns a draft, it creates or updates a draft Finding (Task 29 model; Task 23 creates `Finding` with the minimal fields and Task 29 extends it).
  - **Locks.** Writes are rejected when the system is locked, or when it is a client write after the Stage 4 snapshot (`Conflict` "Answers are locked after management representation; ask the auditor to reopen.").
- `verify(db, actor, response)` is for auditors only.
- `tick_checklist(db, actor, item, confirmed, evidence_ids)`: confirmed=true needs at least one evidence ID ("Link at least one evidence file before ticking this item.").
- `completion(db, system) -> (answered, applicable)` counts per section and overall, and updates `AISystem.completion_pct`.
- Screens:
  - The left nav lists template sections with their counts.
  - Question cards carry the source person, evidence, verified tick, N/A reason and "not yet in place" status.
  - There is an auto-draft-finding banner.
  - The intern note is visible to Futran only.
  - Both match `SystemAssess.dc.html`.

- [ ] **Step 1:** Write tests:
  - `test_client_sees_only_client_questions`.
  - `test_client_never_sees_verified_or_auditor_answers`.
  - `test_na_requires_reason`.
  - `test_verified_interview_requires_source_person`.
  - `test_checklist_tick_requires_evidence`.
  - `test_not_yet_in_place_creates_draft_finding`.
  - `test_light_system_shows_only_light_questions`.
  - `test_client_write_after_snapshot_conflict`.
  - `test_completion_counts`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: per-system assessment with golden rules and client pre-fill`.

### Task 24: Document request register with chase and escalation

**Files:**
- Create: `backend/app/docrequests/*`, `frontend/src/screens/futran/DocumentRegister.tsx`, `frontend/src/screens/client/DocumentUploads.tsx`, `backend/tests/docrequests/test_docrequests.py`, migration

**Interfaces:**
- `DocumentRequest` and `DocumentChase`, per spec §18.5.
- `issue_register(db, actor, engagement) -> list[DocumentRequest]`.
  - Creates one request per catalog item, and one per AI system for each `per_system` item.
  - The due date is `fieldwork_start` minus 5 business days.
  - Sends `document_request_email`, with the Engagement Manager in CC.
- `receive(db, actor, req, file_ids)`, `mark_not_available(db, actor, req, note)` (creates a draft finding) and `chase(db, actor, req, note)`.
- `escalations_due(db, today) -> list[DocumentRequest]` returns requests chased 3 or more business days ago with nothing received. The scheduler (Task 32) calls this and notifies the Lead Auditor.
- `business_days_between(a, b)` counts Monday to Friday only (no holiday calendar in v1).

- [ ] **Step 1:** Write tests:
  - `test_register_counts_with_per_system_items`. With 4 systems the count is the base count plus 4 × the per_system count; assert the numbers computed from the seed.
  - `test_due_5_business_days_before_fieldwork`.
  - `test_not_available_creates_draft_finding`.
  - `test_escalation_after_3_business_days`.
  - `test_client_sees_own_requests_no_findings`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `Documents.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: document request register with chase and escalation`.

### Task 25: Risk scoring engine, score screen and lock

**Files:**
- Create: `backend/app/scoring/{engine.py,service.py,router.py}`, `frontend/src/screens/futran/SystemScore.tsx`, `backend/tests/scoring/test_engine.py`, `test_service.py`, migration

**Interfaces:**
- `engine.py` is pure. Inputs are dataclasses: `FactorInputs`, `DomainInputs` and `Methodology` (loaded from `RiskMethodology`).
  - `inherent(f: FactorInputs, m) -> tuple[float, list[FactorRow]]`.
    - Each row is `Σ weight × (score ÷ 5) × 100`, rounded to 1 dp.
    - EU AI Act `high` → `max(score, 70)`.
  - `proposed_domain_score(pct_confirmed: float, open_high_or_critical: int) -> int`. Bands are 0–19 → 1, 20–39 → 2, 40–59 → 3, 60–79 → 4 and 80–100 → 5, minus 1 per open High or Critical finding, with a minimum of 1.
  - `maturity(domain_scores: dict[str,int], build_type, depth, m) -> float`. For depth `light`:
    - Weights are rescaled over the assessed domains `{governance, data, oversight, vendor}` (D17).
    - In-house weights apply to `open_source_customized` and `hybrid`.
  - `residual(inherent, M) -> float`: `CE = (M−1)/4`, then `inherent × (1 − 0.75 × CE)`, rounded to 1 dp.
  - `band(residual) -> Rating`: ≥75 Critical; 50–74.9 High; 25–49.9 Medium; <25 Low.
  - `knockouts(answers) -> list[Knockout{code, force: Rating}]` follows spec §19.4 exactly.
  - `final_rating(computed, knockouts, eu_prohibited) -> Rating`: the maximum of the band and the forced ratings, with Critical when prohibited.
- `service.recalculate(db, system)` is called after every `save_response`, `tick_checklist` and finding status change, unless the system is locked. It stores a `SystemRiskScore` row with the methodology version.
- `set_final_domain_score(db, actor, system, domain, score, rationale)` requires a rationale when the score differs from the proposed one by more than 1.
- `override_rating(db, actor, system, rating, rationale)` is for the Lead Auditor (the engagement's chief_auditor).
- `lock_scores(db, engagement)` is called by sign-off 5.
- `engagement_rollup(db, engagement) -> EngagementScorecard`:
  - Overall rating is the highest final system rating.
  - Maturity is the inherent-weighted mean.
- `GET /api/v1/systems/{id}/score` returns 403 to client actors before Stage 7 (D18).

- [ ] **Step 1:** Write tests:
  - `test_worked_example_ats`. Factor scores 3, 4, 5, 3, 5, 3, 3, 5 → inherent 76.0. Vendor domain scores Gov 3, Data 2, VendorAssurance 2, Bias 1, Oversight 3, Security 3, Incident 2, Vendor 2 → M 2.25. CE 0.3125 → residual 58.2 → computed High. Knock-outs `no_bias_testing` and `null_compliance_high` → final High. (The spec rounds CE to 0.31 but its 58.2 comes from the exact value.)
  - `test_eu_high_floor_70`.
  - `test_prohibited_forces_critical`.
  - `test_phi_vendor_no_baa_critical`.
  - `test_light_rescaled_weights_sum_to_1`.
  - `test_proposed_domain_minus_open_findings_min_1`.
  - `test_rationale_required_when_diff_gt_1`.
  - `test_locked_score_not_recalculated`.
  - `test_client_cannot_view_score_before_stage7`.
  - `test_rollup_highest_rating`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `SystemScore.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: per-system risk scoring with knock-outs and lock`. **Phase 5 check-in** with screenshots of the systems register, assessment, score and document register.

## Phase 6 — Review to close (screens 15–20)

### Task 26: Notifications and scheduled jobs

**Files:**
- Create: `backend/app/notifications/*`, `frontend/src/components/NotificationBell.tsx`, `backend/tests/notifications/test_jobs.py`, migration

**Interfaces:**
- `Notification` (user_id, kind, title, body, link, read_at).
- `notify(db, users, kind, title, body, link, email_template=None, context=None)` writes the in-app notification and, when a template is given, sends the email through `mail.send`.
- Every event in spec §14 is listed in `EVENTS: dict[str, EventSpec]`, giving the recipients resolver, the channel and the template.
- `jobs.py` (APScheduler, started in `create_app` unless `settings.disable_scheduler`) runs once a day. It:
  - warns about invitations expiring within 48 h and marks expired ones
  - flags evidence requests due in 3 days
  - runs document escalations (Task 24)
  - sends a weekly overdue digest every Monday covering commitments and remediation
- Each job is a plain function `run_<job>(db, today)` so it can be tested directly.

- [ ] **Step 1:** Write tests:
  - `test_invitation_48h_warning_once`.
  - `test_expired_invitation_marked_and_futran_notified`.
  - `test_weekly_digest_groups_by_owner`.
  - `test_events_table_covers_spec_14` (9 events).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: notifications and scheduled jobs`.

### Task 27: Sign-offs 2–4, management representation and inventory snapshot

**Files:**
- Modify: `backend/app/signoffs/service.py`
- Create: `backend/app/inventory/snapshot.py`, `frontend/src/screens/client/InventoryReview.tsx`, `backend/tests/signoffs/test_signoffs.py`, `backend/tests/inventory/test_snapshot.py`

**Interfaces:**
- `SIGNOFF_SPECS: dict[int, SignOffSpec]` holds the preparer, reviewer and approver role(s) per spec §8, with fallbacks: DPO → CAICO and Exec Sponsor → CAICO, used when `ClientContact.not_appointed` is set.
- `open_signoff(db, engagement, number, scope_ref=None)`, `review(db, actor, so, decision, comment)` and `approve(db, actor, so, typed_name)`.
  - They enforce SoD.
  - Sign-off 2 runs per department. Its preconditions are that every use case in the department is `dept_approved`, and every named-user link is completed or marked unable (§8a).
  - Approving sign-off 4 locks the snapshot.
- `correct(db, actor, so, reason) -> SignOff` creates a new version that supersedes the old one, keeps both, and requires a reason.
- `lock_snapshot(db, engagement, sign_off) -> InventorySnapshot` stores the JSON payload of tools, use cases, systems and client pre-fill responses.
- `add_snapshot_addendum(db, snapshot, kind, payload)` records a dated addendum (late confirmations).
- Stage 4 gate: sign-offs 2 (every department), 3 and 4 are approved.

- [ ] **Step 1:** Write tests:
  - `test_signoff2_per_department_preconditions`.
  - `test_dpo_not_appointed_falls_back_to_caico`.
  - `test_signoff4_locks_snapshot`.
  - `test_signed_item_edit_creates_version`.
  - `test_late_confirmation_becomes_addendum`.
  - `test_preparer_cannot_approve_signoff3`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `InventoryReview.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: client review sign-offs and inventory snapshot`.

### Task 28: Fieldwork use-case screen, AEDT determination, null-compliance panel, evidence requests

**Files:**
- Create: `backend/app/inventory/fieldwork.py`, `backend/app/docrequests/evidence_requests.py`, `frontend/src/screens/futran/FieldworkUseCase.tsx`, `backend/tests/inventory/test_fieldwork.py`

**Interfaces:**
- `EvidenceRequest`, per spec §9.6.
- `null_compliance_check(db, uc) -> NullComplianceResult|None`. It fires when the use case is Tier 3 hiring, has `aedt_determination = in_scope`, and the system's 5.1a.01 answer is `no`. It pre-fills a draft finding with `null_compliance_flag = true`.
- Stage 5 gate, per schematic §8a:
  - every Tier 3 use case maps to a system that is complete (no unanswered required applicable questions) and scored
  - every finding is `submitted` or `approved`
- Screen per `Fieldwork.dc.html`.

- [ ] **Step 1:** Write tests:
  - `test_null_compliance_panel_and_draft_finding`.
  - `test_stage5_gate_unmet_lists_unmapped_and_incomplete`.
  - `test_evidence_request_due_soon_notifies`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: fieldwork use-case review with null-compliance check`.

### Task 29: Findings, QA approval and sign-off 5

**Files:**
- Modify: `backend/app/findings/*`
- Create: `frontend/src/screens/futran/FindingsQA.tsx`, `backend/tests/findings/test_findings.py`

**Interfaces:**
- `Finding`, per spec §9.6 (the v0.2 fields), with refs `F-001` and up per engagement, and `default_due_days` by severity: critical 30, high 90, medium 182, low 365, observation 365.
- `submit(db, actor, f)`; `approve(db, actor, f, comment)`; `return_(db, actor, f, comment)`.
  - The approver is the Chief Auditor, or the QA Reviewer when the author is the Chief Auditor.
  - The approver is never the author.
  - A Critical finding notifies the Lead Auditor immediately.
- `dismiss_draft(db, actor, f, reason)`, for auto-drafted findings.
- Sign-off 5 approval:
  - requires every finding to be approved
  - locks the final tiers and system scores
  - unlocks "Issue draft report"
- Stage 6 gate: sign-off 5 is approved, and report v1.0 is released (Task 30).

- [ ] **Step 1:** Write tests:
  - `test_chief_auditor_finding_routes_to_qa`.
  - `test_author_cannot_approve`.
  - `test_client_never_sees_draft_findings`.
  - `test_signoff5_requires_all_approved_and_locks_scores`.
  - `test_finding_ref_sequence`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: findings review and QA approval`.

### Task 30: Reports, declarations, public summary (sign-offs 7–8)

**Files:**
- Create: `backend/app/reports/*`, `backend/seeds/templates/report.md.j2` (full), `frontend/src/screens/futran/FinalReport.tsx`, `backend/tests/reports/test_reports.py`, migration

**Interfaces:**
- Models:
  - `Report` (version label `v0.1|v0.2|v1.0|v1.1`, type, file ids docx/pdf, signed_by, signed_at, correction_reason, released_to_client_at).
  - `Declaration` (kind `lead_auditor|engagement_manager|quality_reviewer|client_acknowledgement|client_remediation_commitment`, user_id, text_version, signed_at, disputed_finding_refs).
  - `RoadmapItem` (R-01 and up).
  - `PublicSummary`.
- `build_report(db, engagement, version) -> ReportContent`. The sections are:
  - cover block per §18.2
  - executive summary per §12.1 (counts by severity, overall rating, the most significant finding, strengths (required), and 30-day actions)
  - findings by severity
  - a per-system profile and score
  - the maturity scorecard
  - the roadmap with "How Futran can help"
  - laws in scope
  - declarations
  - Appendices B and C, from the template text
- `release_client_draft(db, actor, engagement)` produces v1.0. Its preconditions are sign-off 5 plus the Lead Auditor and Engagement Manager declarations. The QA declaration is required only when a `qa_reviewer` is on the team; otherwise the report records "No QA Reviewer assigned".
- `issue_final(db, actor, engagement)` produces v1.1 and requires sign-off 7. It then requests the client acknowledgement. The UI text reads: "Signing confirms you have received and read this report. It does not mean you agree with every finding."
- `PublicSummary` and sign-off 8 are required only when `engagement.requires_public_summary` is true, i.e. when a requirement's regulation is NYC LL144 or is flagged `public_summary`. Impact ratios are entered by hand and the evidence is linked.
- Stage 8 gate: sign-off 7, the client acknowledgement, and sign-off 8 if it is required.

- [ ] **Step 1:** Write tests:
  - `test_report_v1_0_requires_declarations_and_so5`.
  - `test_qa_declaration_optional_without_qa_reviewer`.
  - `test_executive_summary_requires_strengths`.
  - `test_report_docx_contains_findings_table_and_scorecard`.
  - `test_client_ack_text_states_not_agreement`.
  - `test_public_summary_only_when_ll144`.
- [ ] **Step 2–4:** FAIL → implement (screen matches `FinalReport.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: reports, declarations and public summary`.

### Task 31: Management response, remediation and close-out

**Files:**
- Create: `backend/app/remediation/*`, `frontend/src/screens/client/ManagementResponse.tsx`, `frontend/src/screens/shared/Remediation.tsx`, `backend/tests/remediation/test_remediation.py`, migration

**Interfaces:**
- `ManagementResponse` and `RemediationItem`, per spec §9.6. Remediation items are created from the responses and from open `Commitment`s.
- `respond(db, actor, finding, response, planned_action, owner_id, due_date)` is for client users. Clients cannot edit finding text (Task 5 SoD).
- Sign-off 6 is prepared by the Dept Lead, reviewed by the CAICO and approved by the Sponsor or CAICO. Before it, the auditor runs `adequacy_review(db, actor, response, adequate, note)`. Stage 7 gate: sign-off 6.
- `mark_done(db, actor, item)` moves the item to `awaiting_verification` and notifies the auditor. `verify(db, actor, item, note)` is auditor only. `close(db, actor, item)` is Chief Auditor only. `reopen(db, actor, item, note)`.
- Stage 9 gate: every item is closed. The engagement then moves to `completed`.

- [ ] **Step 1:** Write tests:
  - `test_client_mark_done_goes_to_awaiting_verification`.
  - `test_only_auditor_verifies_only_chief_closes`.
  - `test_commitments_appear_in_remediation`.
  - `test_all_closed_completes_engagement`.
  - `test_client_cannot_edit_finding_text`.
- [ ] **Step 2–4:** FAIL → implement (screens match `Response.dc.html` and `Remediation.dc.html`) → PASS.
- [ ] **Step 5:** Commit `feat: management response and remediation to close-out`.

## Phase 7 — Demo, end-to-end, hand-over

### Task 32: Demo tenants

**Files:**
- Create: `backend/app/demo/seed_demo.py`, `backend/tests/demo/test_seed_demo.py`

**Interfaces:**
- `run(db)` creates four tenants:
  - **Futran:** the users `chief@futran.demo`, `admin@futran.demo`, `auditor1@futran.demo`, `auditor2@futran.demo`, `qa@futran.demo` and `em@futran.demo`, all with the password `Demo-Password-2026` and MFA off. The demo is only allowed when `test_mode` is on.
  - **ABC Corp:** New York HQ, Chicago and remote, with departments HR, Finance and Sales & Marketing, and users for every client role. The engagement runs from draft through every stage to `completed` by calling the real services, not raw inserts. It has the four systems (SYS-001 to SYS-004) with answers that reproduce the worked example.
  - **Meridian GmbH:** Berlin and Bangalore, left at Stage 3.
  - **Futran Solutions — internal:** `is_internal`, at Stage 2.
- A second ABC engagement, the "Annual review 2027" draft, is left in `pending_approval` so the approval screen has data.

- [ ] **Step 1:** Write tests:
  - `test_demo_abc_completed_and_sys001_high`.
  - `test_demo_meridian_suggests_eu_ai_act_gdpr_dpdp`.
  - `test_demo_refused_outside_test_mode`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat: demo tenants`.

### Task 33: End-to-end journey, mobile checks, accessibility checks, screenshots

**Files:**
- Create: `e2e/journey.spec.ts`, `e2e/mobile.spec.ts`, `e2e/a11y.spec.ts`, `backend/tests/test_route_tenancy.py`

**Interfaces:**
- `journey.spec.ts`, against a fresh database with reference data only:
  - Admin invites the Chief Auditor. The Auditor drafts a new client through the wizard, and the Chief Auditor approves and sends it.
  - The CAICO accepts the invite, signs sign-off 1 and completes the checklist. The Client Admin uploads the CSVs. The CAICO answers the governance request.
  - A campaign runs and an employee attests by phone. The Contributor adds use cases.
  - Sign-offs 2–4 are completed. The Auditor maps a system, completes the assessment and scores it. Findings are raised, then QA, then the v1.0 report.
  - The CAICO responds, followed by sign-off 6. The Chief Auditor issues the final report, and the client acknowledges it.
  - Remediation is marked done, verified and closed, and the engagement is `completed`.
- Screenshots of every screen go to `e2e/screenshots/`.
- `mobile.spec.ts`: the attestation and named-user confirmation work at 375×812, with no horizontal scroll and every control at least 44 px.
- `a11y.spec.ts`: `@axe-core/playwright` on 10 key screens, with no serious or critical violations.
- `test_route_tenancy.py`: `assert_tenant_scoped_routes` iterates `app.routes` that have an `{id}`-style parameter, calls each one as a client user from another tenant with an existing object ID, and expects 404 or 403. This is generated from a registry of route-to-factory mappings.

- [ ] **Step 1:** Write the specs.
- [ ] **Step 2:** Run them and fix failures through the owning task's code, using systematic debugging.
- [ ] **Step 3:** Everything passes, and the screenshots are reviewed by eye against the mockups.
- [ ] **Step 4:** Commit `test: end-to-end journey, mobile, accessibility and tenancy route checks`.

### Task 34: Packaging and hand-over

**Files:**
- Create: `Dockerfile` (multi-stage: node build, then python slim), `README.md`, final `setup.bat` and `run.bat`, `docs/HANDOVER.md`

**Interfaces:**
- The README covers:
  - what the platform is
  - setup on Windows (Python 3.11+, `setup.bat`, then `run.bat`, with `--reset-demo`)
  - the demo sign-ins
  - configuration (`.env` table from schematic §13)
  - switching on MFA and SMTP
  - adding the Anthropic key
  - deploying to Render (Docker web service plus Postgres; set `DATABASE_URL`)
  - the post-build backlog link
- The zip `Futran_Audit_Platform.zip` excludes `.venv`, `node_modules`, `data`, `__pycache__`, `.pytest_cache` and `e2e/test-results`.

- [ ] **Step 1:** On clean Linux, `docker build` succeeds. The container starts, `/api/v1/health` responds, and the login page loads.
- [ ] **Step 2:** Follow the README steps from a fresh clone: `python -m venv` → `pip install -e backend` → `alembic upgrade head` → `seed-reference` → `reset-demo` → start → sign in as `chief@futran.demo` works.
- [ ] **Step 3:** Commit and push. Copy the app and zip to `IT work\strategy development\Futran Audit Platform\`. Update the project doc `claude/Futran_Audit_Platform.md` with status, how to run and open items.
