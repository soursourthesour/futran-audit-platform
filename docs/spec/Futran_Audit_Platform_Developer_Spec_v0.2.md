# Futran Audit Platform — Developer Handoff Specification

**Version:** 0.2 · **Date:** 12 October 2026 · **Owner:** Futran AI Governance Advisory
**Status:** Confidential — internal, not for external distribution

**What changed in v0.2:** the full content of *Futran AI Governance Audit Template v1.0* and *Addendum 5.1a (Data Sufficiency & Null-Compliance Risk)* is now specified for digitization (§18), per-AI-system data collection for in-house, vendor-supplied, open-source and hybrid systems is added, and a per-system risk scoring method is defined (§19), with four new screens (§20).

**Companion design assets**
- Screen mockups (21 screens): https://claude.ai/artifact/UTFNXhXiy1a5aMxNo1sBgW
- Design notes, diagrams and rationale: https://claude.ai/code/artifact/d02f9d94-3f9b-43d7-b3e3-79e316111ee2
- Reference data source: `Futran_US_AI_Law_Matrix_Federal_State.xlsx` (status as of 5 Oct 2026)

---

## 1. Purpose and scope

Replace Futran's paper and Excel audit forms with a multi-tenant web application that captures an AI governance audit end to end:

1. Futran creates a client and an engagement, and sends an initiation package.
2. The client sets up users, describes its AI governance structure, runs an employee attestation, and builds an AI inventory.
3. The client signs a management representation; Futran performs fieldwork, records findings, and issues a report.
4. The client responds; remediation is tracked to verified closure.

**Out of scope for v1:** billing, public website, native mobile apps (the employee attestation must work on a phone browser), automated bias-statistics computation (evidence upload only in v1).

---

## 2. Glossary

| Term | Meaning |
|---|---|
| Engagement | One audit of one client for one period (e.g. "Initial AI governance assessment 2026"). |
| Use case | One business use of AI (e.g. "Résumé screening for NYC roles"). The central inventory record. |
| AI tool | A product used by the client (vendor, product, plan, account type). |
| Risk tier | 1 Baseline, 2 Elevated, 3 High-risk. Proposed by client, set finally by Futran auditor. |
| Sign-off | A recorded approval with preparer, reviewer and approver, locked after approval. |
| Management representation | Client statement that the AI inventory is complete and accurate (sign-off 4). |
| Commitment | A "Will constitute / Will create" answer with a target date; tracked like remediation. |
| AEDT | Automated employment decision tool (NYC Local Law 144). |
| Null-compliance risk | Procedurally compliant but substantively empty (e.g. bias audit with no demographic data). |

---

## 3. Tenancy, authentication and access

- **Multi-tenant.** Every record belongs to exactly one `Organization` (Futran or a client). All queries are filtered by tenant. Futran users see client data only for engagements they are assigned to (Admin and Chief Auditor see all).
- **Login:** email + password + TOTP MFA (mandatory for all accounts), or SAML/OIDC SSO per organization.
- **Invitations:** single-use secure link, expires after 7 days, user sets password and enrolls MFA on accept. Resend generates a new token and invalidates the old one.
- **No impersonation.** Futran users can never sign in as client users.
- **Employee attestation** uses a campaign-specific link with no account. Responses are tied to an email the employee enters (or SSO identity if the client enables it). The link must not expose any other data.
- **Session:** idle timeout 30 min (configurable), absolute timeout 12 h.

---

## 4. Roles

### 4.1 Futran roles
| Role | Purpose |
|---|---|
| Chief Auditor | Approves engagements and initiation packages, assigns team, approves findings, signs final report, closes remediation. |
| Admin | Manages Futran users, client organizations, templates and reference data. **No audit-judgment rights.** |
| Auditor | Drafts clients/engagements, performs fieldwork, sets final tiers, writes findings, verifies remediation. |
| QA Reviewer (optional, per engagement) | Approves findings authored by the Chief Auditor. |

### 4.2 Client roles
| Role | Required | Purpose |
|---|---|---|
| Executive Sponsor | Optional | Signs management representation; accepts remediation plan. Falls back to Chief AI Compliance Officer. |
| Chief AI Compliance Officer (CAICO) | Yes | Client lead; approves inventory, responses and public summaries; receives initiation package. |
| Client Admin | Yes (may be same person as CAICO) | Creates departments and users; assigns roles. No audit content rights. |
| Data Protection Officer (DPO) | Optional | Reviews data categories, Tier 2–3 use cases, attestation privacy. Falls back to CAICO. |
| Department Compliance Lead | Yes, one per department | Reviews/approves own department's tools and use cases. |
| Contributor | Optional | Prepares tool and use-case entries; uploads evidence (own department). |
| Employee | No account | Completes attestation via link. |

A user may hold multiple roles, but **never prepare and approve the same item** (enforced, see §6).

---

## 5. Permission matrix

Key: **C** create · **E** edit · **A** approve/sign · **V** view · **—** none · *dept* = own department · *assigned* = assigned engagements

| Action | Chief Auditor | Admin | Auditor | CAICO | Dept Compliance Lead | Contributor |
|---|---|---|---|---|---|---|
| Manage Futran users and platform settings | V | C/E | — | — | — | — |
| Create client organization and engagement | A | C/E | C (draft) · V *assigned* | V | — | — |
| Assign auditors to an engagement | C/E | V | V *assigned* | V | — | — |
| Manage client users and departments | V | C/E | — | C/E | V *dept* | — |
| Configure audit template and questionnaire | A | C/E | V | — | — | — |
| Register AI tools | V | — | E *assigned* | C/E/A | C/E *dept* | C *dept* |
| Submit use cases | V | — | E *assigned* | C/E/A | C/E/A *dept* | C/E *dept* |
| Propose risk tier | V | — | V | C/E | C/E *dept* | — |
| Set final risk tier | A (override) | — | C/E *assigned* | V | V *dept* | — |
| Record named users (Tier 2–3) | V | — | V *assigned* | C/E | C/E *dept* | C *dept* |
| Launch employee attestation campaign | V | — | V *assigned* | C/E | V *dept* | — |
| View individual attestations | V | — | V *assigned* | V | Aggregate only | — |
| Answer governance structure request | V | — | V *assigned* | C/E/A | — | — |
| Upload evidence | V | — | C *assigned* | C | C *dept* | C *dept* |
| Record findings | V | — | C/E *assigned* | — | — | — |
| Approve findings and sign final report | A | — | — | — | — | — |
| View final report | V | — | V *assigned* | V | V *dept sections* | — |
| Respond to findings / remediation plan | V | — | V *assigned* | C/E/A | C/E *dept* | V *dept* |
| Verify remediation | A (close) | — | C/E *assigned* | V | V *dept* | — |
| View audit log | V | V | V *assigned* | V *own org* | — | — |

Client Admin: manage departments/users/role assignments only. Executive Sponsor: view + sign sign-offs 4 and 6. DPO: CAICO view rights on data categories, attestations and governance; approver on sign-off 3.

---

## 6. Separation-of-duties rules (enforce in the API, not just the UI)

1. Admin can never create, edit or approve findings or risk tiers.
2. No self-approval: the approver of any item must differ from its author/preparer. Chief-Auditor-authored findings route to the QA Reviewer.
3. Client proposes the tier; only an assigned Auditor sets the final tier; only the Chief Auditor overrides.
4. Signed items are immutable. Corrections create a new version with a mandatory reason; both versions remain visible.
5. Clients can respond to findings but never edit finding text.
6. Client "mark done" on remediation moves an item to *Awaiting verification*; only Futran can verify (Auditor) and close (Chief Auditor).
7. Engagement isolation: auditors see only assigned engagements; tenants are fully partitioned.
8. Attestation privacy: Department Compliance Leads see department totals only, never individual responses.
9. Assigning/removing a sign-off role (CAICO, Executive Sponsor, DPO) notifies Futran and is logged.
10. Every create, edit, approval, send, and view of sensitive records (attestations, evidence) writes an append-only audit-log entry.

---

## 7. Engagement workflow (state machine)

`Engagement.status`: `draft → pending_approval → initiated → in_progress → completed → archived` (plus `returned` from `pending_approval` back to `draft`).
`Engagement.stage` (1–9) advances only when the gate for the current stage is satisfied.

| Stage | Name | Who acts | Exit gate |
|---|---|---|---|
| 1 | Onboarding | Futran drafts → Chief Auditor approves & sends; CAICO signs | Sign-off 1 approved |
| 2 | Setup | Client Admin creates departments/users | Every in-scope department has a Department Compliance Lead |
| 3 | Discovery | Attestation campaign; contributors submit tools/use cases; governance request answered | Campaign closed **and** governance request submitted |
| 4 | Client review | Dept Lead → DPO → CAICO → Executive Sponsor | Sign-offs 2, 3, 4 approved → inventory snapshot locked (v1) |
| 5 | Fieldwork | Auditor sets final tiers, requests evidence, drafts findings | All findings submitted |
| 6 | Futran QA | Chief Auditor / QA Reviewer approve findings; draft report issued | Sign-off 5 approved |
| 7 | Response | Client responses + remediation plan; Auditor reviews adequacy | Sign-off 6 approved |
| 8 | Final report | Chief Auditor signs; CAICO approves public summary | Sign-offs 7 and 8 approved |
| 9 | Remediation | Owners fix; Auditor verifies; Chief Auditor closes | All items closed → `completed` |

---

## 8. Sign-offs

Each sign-off is a `SignOff` record: `{engagement_id, number, preparer_id, reviewer_id?, approver_id, status (pending|approved|returned), comment, approved_at, document_version_id}`. When a role is not appointed, the next role up takes its place (DPO → CAICO; Executive Sponsor → CAICO).

| # | Sign-off | Preparer | Reviewer | Approver |
|---|---|---|---|---|
| 1 | Engagement letter and scope | Futran Admin/Auditor | Chief Auditor | CAICO (client) and Chief Auditor (Futran) |
| 2 | Department inventory | Contributor | Dept Compliance Lead | Dept Compliance Lead |
| 3 | Data categories for Tier 2–3 use cases | Dept Compliance Lead | DPO | CAICO |
| 4 | Management representation | CAICO | DPO | Executive Sponsor (or CAICO) |
| 5 | Final risk tiers and findings | Auditor | QA Reviewer (if author is Chief Auditor) | Chief Auditor |
| 6 | Management responses and remediation plan | Dept Compliance Lead | CAICO | Executive Sponsor (or CAICO) |
| 7 | Final report | Auditor | Chief Auditor | Chief Auditor signs; client acknowledges receipt |
| 8 | Public summary (e.g. LL144) | Auditor | CAICO | CAICO |

Management representation text (template, editable by Admin):
> To the best of our knowledge, the AI inventory submitted for {client} is complete and accurate for the audit period, and we have disclosed all AI tools and use cases known to management in the departments in scope.

---

## 9. Data model

All tables have `id (uuid)`, `organization_id` (tenant), `created_at`, `created_by`, `updated_at`, `updated_by`. Soft delete only (`deleted_at`).

### 9.1 Access and tenancy
| Entity | Key fields |
|---|---|
| Organization | name, legal_name, trading_name, type (`futran`/`client`), industry, employee_band, hq_address (street, city, state, postal_code, country), website, client_ref (`FUT-####`), status (`draft`/`active`/`archived`), engagement_reason |
| Department | organization_id, name, head_user_id, headcount |
| User | organization_id, name, email, job_title, phone, mfa_enabled, sso_subject, status (`invited`/`active`/`disabled`) |
| RoleAssignment | user_id, role (enum §4), scope_type (`org`/`department`/`engagement`), scope_id, start_date, end_date |
| ClientContact | organization_id, name, title, email, phone, contact_role (`caico`/`client_admin`/`exec_sponsor`/`dpo`), user_id (after accept), not_appointed (bool) |
| Invitation | client_contact_id or user_id, token_hash, sent_at, expires_at, accepted_at, status |
| AuditLog | actor_id, action, object_type, object_id, before (json), after (json), ip, user_agent, at — **append-only** |

### 9.2 Locations, laws and scope
| Entity | Key fields |
|---|---|
| ClientLocation | organization_id, site_name, street, city, state_code, country, employees_at_site, in_scope, matrix_state (FK Jurisdiction) |
| Jurisdiction *(reference)* | code (e.g. `US`, `US-NY`, `US-NYC`, `US-IL`, `EU`, `IN`), name, level (`federal`/`state`/`city`/`country`/`region`) |
| Regulation *(reference)* | jurisdiction_id, short_name, citation, category/feature (enum §10.2), type (`statute`/`regulation`/`executive`/`voluntary`/`pending`), enforcer, trigger_text, obligations_text, developments_text, effective_date, status_text, applies_to (`deployer`/`developer`/`both`), source_row_ref, matrix_version |
| ClientRequirement | organization_id, regulation_id (nullable), source (`auto`/`manual`/`futran_default`), reason_text, in_scope, notes, free_text (for manual) |
| Engagement | client_id, name, type (`initial_assessment`/`ll144_bias_audit`/`annual_review`), period_start, period_end, letter_due, report_due, status, stage, created_by, approved_by, approved_at |
| ScopeItem | engagement_id, regulation_id or framework_id, location_ids[], department_ids[], exclusions_text |
| EngagementTeam | engagement_id, user_id, role (`chief_auditor`/`auditor`/`qa_reviewer`), conflict_confirmed_at |

### 9.3 Initiation
| Entity | Key fields |
|---|---|
| DocumentTemplate *(reference)* | name, version, type (`engagement_letter`/`roles_note`/`user_csv`/`department_csv`/`data_notice`/`getting_started`/`governance_request`), body_with_merge_fields |
| InitiationPackage | engagement_id, version, status (`draft`/`approved`/`sent`/`acknowledged`), client_message, approved_by, sent_at, acknowledged_at |
| PackageDocument | package_id, template_id, template_version, generated_file_id, merge_values (json), requires_action (`sign`/`nominate`/`upload`/`review`/`read`/`answer`), completed_at |

### 9.4 Governance structure (requested by Chief Auditor)
| Entity | Key fields |
|---|---|
| GovernanceRequest | engagement_id, requested_by, due_date, items_selected (json), status (`open`/`submitted`/`accepted`), submitted_by, submitted_at, accuracy_confirmed |
| GovernanceDocumentItem | request_id, catalog_item_id, status (`uploaded`/`will_create`/`not_applicable`/`unanswered`), file_ids[], target_date, interim_owner_user_id, na_reason |
| GovernanceRoleItem | request_id, catalog_role_id, status (`in_place`/`will_constitute`/`not_applicable`/`unanswered`), named_user_ids[] or free-text names, chair, member_count, meeting_frequency, terms_of_reference_file_id, target_date, interim_owner, planned_members, na_reason |
| Commitment | engagement_id, source (`governance_document`/`governance_role`), source_id, description, target_date, owner, status (same lifecycle as RemediationItem) |

### 9.5 Inventory and attestation
| Entity | Key fields |
|---|---|
| AITool | organization_id, vendor, product, plan, account_type (`enterprise`/`team`/`personal_paid`/`personal_free`/`unknown`), sso (bool), training_on_inputs (bool/unknown), retention_terms, approval_status |
| UseCase | organization_id, engagement_id, name, department_id, purpose, tool_ids[], data_categories[] (`pii`/`phi`/`client`/`confidential`/`none`), decision_impact (`none`/`informs`/`consequential`), proposed_tier, final_tier, final_tier_rationale, aedt_determination, owner_user_id, status (`draft`/`submitted`/`dept_approved`/`returned`), created_from_attestation_id |
| UsageRecord | use_case_id, role_name, headcount, frequency |
| NamedUser | usage_record_id, person_name or user_id, training_complete, policy_acknowledged, oversight_role — **required when tier ≥ 2** |
| InventorySnapshot | engagement_id, version, locked_at, sign_off_id, payload (json of all tools/use cases at lock) |
| AttestationCampaign | engagement_id, policy_version, launched_at, closes_at, department_ids[], link_token, status |
| Attestation | campaign_id, respondent_name, respondent_email, department_id, uses_ai (bool), tools_declared (json: tool + account_type), purposes (json), data_entered[], policy_acknowledged, submitted_at |

### 9.6 Audit execution
| Entity | Key fields |
|---|---|
| EvidenceRequest | engagement_id, use_case_id?, description, requested_by, due_date, status (`outstanding`/`received`/`answered`/`waived`) |
| Evidence | engagement_id, linked object (tool/use case/finding/request/governance item), file_id, type (`survey_export`/`sso_log`/`expense_report`/`casb_report`/`vendor_terms`/`policy`/`other`), uploaded_by, sha256 |
| Finding | engagement_id, ref (`F-001`…), ai_system_id?, use_case_ids[], template_section (e.g. `6.2`), source_question_ids[], title, description, severity (`critical`/`high`/`medium`/`low`/`observation`, §18.6), control_refs[] (regulation/framework control ids), recommended_remediation, proposed_owner, author_id, status (`draft`/`submitted`/`approved`/`returned`), approved_by, approved_at, null_compliance_flag |
| ManagementResponse | finding_id, response (`agree`/`partially_agree`/`disagree`), planned_action, owner_user_id, due_date, status |
| RemediationItem | finding_id or commitment_id, action, owner_user_id, due_date, status (`open`/`in_progress`/`awaiting_verification`/`closed`/`reopened`), marked_done_at, verified_by, verification_note, closed_by |
| Report | engagement_id, version, type (`draft`/`final`), file_id, signed_by, signed_at, correction_reason |
| PublicSummary | engagement_id, regulation_id (e.g. LL144), tool_name, audit_date, data_source, impact_ratios (json), unknown_category_count, approved_by_client_at |

### 9.7 Key relationships
- Organization 1→N Department, User, ClientLocation, ClientRequirement, ClientContact, AITool, Engagement.
- Jurisdiction 1→N Regulation; ClientLocation → Jurisdiction suggests ClientRequirements.
- Engagement 1→N ScopeItem, EngagementTeam, InitiationPackage, GovernanceRequest, AttestationCampaign, UseCase, Finding, SignOff, Report.
- UseCase N↔N AITool; UseCase 1→N UsageRecord 1→N NamedUser; UseCase 1→N Evidence, Finding.
- Finding 1→1 ManagementResponse 1→N RemediationItem. Commitment 1→N RemediationItem.

---

## 10. Reference data

### 10.1 Law matrix import (Admin → Reference data)
Source workbook: `Futran_US_AI_Law_Matrix_Federal_State.xlsx`. Sheets:
- **Federal Laws** — header on row 3. Columns: `Category`, `Law / Instrument`, `Type`, `Enforcer`, `When it reaches AI`, `Key obligations for organizations using AI`, `2025–26 developments`, `Most affected`. One row = one `Regulation` with `jurisdiction = US (federal)`. 27 rows as of 5 Oct 2026.
- **State Matrix** — header on row 3. Column A = state (26 states). Columns B–J = the nine AI features (§10.2). Each cell holds one or more laws separated by line breaks; `—` means none.
- **Read Me**, **Coverage Summary**, **Sources** — informational; store `Sources` as citations on the import version.

Import rules:
1. Each import creates a `matrix_version` (date from the Read Me status line).
2. Federal rows map 1:1. State cells are split on line breaks into candidate regulations; the Admin reviews a preview table (state, feature, extracted short name, full text) and confirms or edits short names before publishing. Text flagged "(verify)" in the source is kept and shown with a *Verify* badge.
3. Mark developer-only laws (e.g. frontier-model laws) `applies_to = developer`; the picker greys them out for deployer clients.
4. Re-import never deletes laws already referenced by a ClientRequirement; superseded rows are marked `superseded_by`.
5. NYC laws sit under `New York (incl. NYC)`; create city jurisdiction `US-NYC` for NYC Local Law 144 and the NYC biometric law.
6. The matrix is US-only. Add an international sheet later (EU AI Act, GDPR, India DPDP) using the same schema.

### 10.2 Feature categories (enum, from the State Matrix columns)
`consequential_decisions_admt` · `employment_hiring` · `privacy_profiling` · `health_insurance` · `chatbots_minors` · `synthetic_content` · `frontier_safety` · `biometrics_pricing` · `government_other`

### 10.3 Law suggestion logic (wizard step 2)
- For each in-scope location → its matrix state + Federal.
- Pre-check laws where the feature matches the client's known AI use (industry and engagement reason; e.g. hiring AI → `employment_hiring`).
- Always add the Futran defaults: NIST AI RMF 1.0; NY Civil Rights Law §52-c when any NY location is in scope (employee monitoring notice).
- Picker UI: filters for Geography (client states + Federal, Federal, each of the 26 states), AI feature, free-text search; grouped results with checkboxes; "Add N laws".

### 10.4 Framework control catalog
Store controls for mapping findings and governance roles:
- **OECD AI Principles:** 1.1 Inclusive growth, 1.2 Human rights & fairness, 1.3 Transparency & explainability, 1.4 Robustness, security & safety, 1.5 Accountability.
- **NIST AI RMF 1.0:** GOVERN, MAP, MEASURE, MANAGE functions with sub-categories (e.g. GOVERN 2, GOVERN 6, MEASURE 2.9, MEASURE 2.11, MANAGE 4).
- **EU AI Act:** articles used in mappings (Art. 4, 10, 13, 14, 26, 86).
- **ISO/IEC 42001** (clauses, optional).

### 10.5 Governance catalog (drives the governance request screen)
**Governance documents:** AI compliance department charter (constitution) · Committee terms of reference · RACI for AI systems · AI acceptable use policy · Leadership/board resolution (optional).

**Data security and data governance documents (reviewed for AI coverage only):** Information security policy · Data governance and classification policy · Privacy policy and DPIAs · Third-party and AI vendor risk procedure · Incident response plan and data retention schedule. Scope note shown to client: *Futran reviews how these cover AI; it does not audit the full security program; SOC 2 / ISO 27001 reports may be uploaded as evidence.*

**Governance roles (each mapped to controls):**
| Role | OECD | NIST AI RMF | EU AI Act |
|---|---|---|---|
| AI governance committee | 1.5 | GOVERN 2 | Art. 26 |
| Bias and fairness review committee | 1.2 | MEASURE 2.11 | Art. 10 (+ NYC LL144) |
| Explainability owner | 1.3 | MEASURE 2.9 | Art. 13, 86 |
| Accountable owner per high-risk system | 1.5 | GOVERN 2 | Art. 26 |
| Human oversight lead | 1.2 | MANAGE | Art. 14, 26 |
| AI incident response owner | 1.4 | MANAGE 4 | Art. 26 |
| AI literacy and training owner | — | GOVERN 2 | Art. 4 |
| EU representative contact | — | — | EU AI Act (only if EU operations) |

Answer rules: **In place** → names (and documents) required. **Will constitute / Will create** → target date + interim owner required → auto-creates a `Commitment`. **Not applicable** → reason required. Submit is disabled until every selected item is answered and the accuracy box is ticked. A coverage panel computes status per OECD principle and NIST function (`covered` / `planned` / `partial` / `gap`).

---

## 11. Risk tiering rules (proposed tier, auto-calculated)

| Tier | Rule (first match wins) | Granularity required |
|---|---|---|
| 3 High-risk | `decision_impact = consequential` (hiring, promotion, credit, housing, insurance, health, education) | Named users, training & acknowledgment status, human-oversight role |
| 2 Elevated | data_categories includes PII/PHI/client/confidential **or** any tool `account_type` in (`personal_free`, `personal_paid`, `unknown`) | Named user list + account type |
| 1 Baseline | otherwise | Department, role, headcount, owner |

The auditor sets `final_tier` with a rationale; for employment use in NYC, also `aedt_determination`.

**Null-compliance check:** if a Tier 3 hiring use case has `aedt_determination = in_scope` and the client answers that no applicant demographic data is collected, show the warning panel and pre-fill a finding draft with `null_compliance_flag = true`.

---

## 12. Initiation package (7 items) and upload formats

| # | Item | Client action |
|---|---|---|
| 1 | Engagement letter and scope | Sign (sign-off 1) |
| 2 | Roles and responsibilities note | Nominate role holders |
| 3 | User list upload template (CSV) | Upload, or Client Admin adds users |
| 4 | Department list template (CSV, pre-filled from scope) | Confirm or upload |
| 5 | Employee data notice (includes NY §52-c wording where relevant) | Review and circulate |
| 6 | Getting started guide | Read |
| 7 | AI governance structure request (Chief Auditor chooses items) | Answer (§10.5) |

**User list CSV** (one row per person who needs a login; not all employees):
```csv
first_name,last_name,email,job_title,department,role,location
Priya,Shah,priya.shah@abc.com,Head of HR,Human Resources,Department Compliance Lead,New York NY
Tom,Reyes,tom.reyes@abc.com,Recruiter,Human Resources,Contributor,New York NY
```
- `role` ∈ {Chief AI Compliance Officer, Client Admin, Executive Sponsor, Data Protection Officer, Department Compliance Lead, Contributor}.
- `department` must exist in the department list.
- Validation returns row-level errors; "Import N ready rows" imports valid rows only.

**Department list CSV:**
```csv
department,head_name,head_email,headcount
Human Resources,Priya Shah,priya.shah@abc.com,14
```

---

## 13. Screens

Routes are suggestions. "F" = Futran app shell (navy header), "C" = client app shell (white header).

| # | Screen | Shell | Primary role(s) | Key elements |
|---|---|---|---|---|
| 1 | Login | — | All | SSO, email/password, TOTP, invitation link entry |
| 2 | Dashboard `/audits` | F | Futran | KPI tiles (in progress, completed, awaiting approval, awaiting client); engagements table (client, engagement, stage, chief auditor, target date, status); filters; activity feed; **New client** |
| 3–7 | New Client wizard `/clients/new` | F | Any Futran role (draft); Chief Auditor (step 5 approve) | 1 Company · 2 Locations & laws (law-matrix picker) · 3 Scope & team (type, period, dates, departments, exclusions, team, conflict confirmation) · 4 Client contacts (CAICO required; Client Admin same/different; optional Sponsor/DPO with "not appointed") · 5 Package review (7 items, preview/edit, client message, approval checklist, **Approve and send** / **Return to author**). Autosave drafts. |
| 8 | Client page `/clients/:id` | F | Futran | 9-stage tracker, client details, laws in scope, team, activity, resend invitation |
| 9 | Invitation email | Email | CAICO, Client Admin | Message, 7 items, accept button, 7-day expiry; no attachments |
| 10 | Initiation checklist `/start` | C | CAICO | 7 tasks with progress |
| 10a | AI governance structure `/governance` | C | CAICO (DPO view) | Governance documents; data security & governance policies; 8 roles with In place / Will constitute / N/A; coverage panel; commitments; submit |
| 11 | Departments and users `/users` | C | Client Admin | CSV upload with row errors; departments with lead status; users table with invitation status |
| 12 | Attestation tracker `/attestation` | C | CAICO | Response counts by department (totals), tools declared with account type, draft use cases created, reminder, copy link |
| 13 | Employee attestation `/a/:token` | Phone web | Employee | 4 steps: department → tools + account type → purposes + data entered → acknowledgment |
| 14 | Add/edit use case `/inventory/new` | C | Contributor, Dept Lead | Name, department, tools, purpose, data categories, decision impact, live proposed tier, usage, named users (Tier 2–3), evidence |
| 15 | Inventory review `/inventory` | C | CAICO, Sponsor | Sign-offs 2–4 tracker, use-case table with tiers, management representation, approve and send for signature |
| 16 | Fieldwork `/e/:id/use-cases/:id` | F | Auditor | Final tier + rationale, AEDT determination, evidence requests, draft finding, null-compliance panel, client inventory summary |
| 17 | Findings approval `/e/:id/findings` | F | Chief Auditor, QA Reviewer | Queue, selected finding, approve/return with comment, issue draft report (locked until all approved) |
| 18 | Management response `/report/draft` | C | CAICO, Dept Leads, Sponsor | Read-only finding, response, action, owner, due date; sign-off 6 panel |
| 19 | Final report `/e/:id/report` | F | Chief Auditor | Section checklist, preview, sign and issue; LL144 public summary awaiting client approval |
| 20 | Remediation `/e/:id/remediation` | F + C | Auditor, Chief Auditor, owners | Status tiles, items table (findings + commitments), verify / reopen panel |

Accessibility: WCAG 2.1 AA, real form controls with labels, 44 px touch targets, keyboard navigable, text contrast ≥ 4.5:1. All screens responsive to 375 px width.

---

## 14. Notifications

| Event | Recipients | Channel |
|---|---|---|
| Draft submitted for approval | Chief Auditor | In-app + email |
| Initiation package sent | CAICO, Client Admin | Email (invitation) |
| Invitation expiring in 48 h / expired | Invitee; Futran team | Email |
| Sign-off role changed | Chief Auditor, assigned auditors | In-app + email |
| Sign-off awaiting you | Next approver | In-app + email |
| Evidence request created / due in 3 days | Request owner | Email |
| Finding returned | Author | In-app |
| Remediation item marked done | Assigned auditor | In-app |
| Commitment / remediation overdue | Owner, CAICO, assigned auditor | Weekly digest |

Email templates are `DocumentTemplate` records (editable by Admin, versioned).

---

## 15. Privacy and security requirements

- Encryption in transit (TLS 1.2+) and at rest; evidence files in object storage with per-tenant prefixes and signed short-lived URLs; SHA-256 stored per file.
- Attestation data is visible only to CAICO, DPO and assigned Futran auditors; department leads get aggregates. Minimum aggregate size 3 before showing a department count (avoid re-identification).
- Employee data notice must be acknowledged by CAICO before an attestation campaign can launch (NY §52-c support).
- Data retention per engagement (default 7 years after completion, configurable); deletion requests logged.
- Audit log is append-only (no update/delete API), exportable as CSV.
- Role checks server-side on every endpoint; tenant ID from session, never from client input.

---

## 16. Non-functional

- Web app, modern browsers (last 2 versions). Brand colors: navy `#1B3A6B`, blue `#2E75B6`, accent `#0098D4` (accent not used for text). Typeface in mockups: IBM Plex Sans.
- p95 page load < 2 s for lists up to 1,000 rows; pagination beyond that.
- File uploads up to 50 MB each; virus scan on upload.
- All generated documents exportable as PDF and DOCX.
- Environments: dev, staging, production; seed script loads reference data (law matrix, frameworks, governance catalog, templates).

---

## 17. Suggested build order

1. Auth, tenancy, users, roles, audit log.
2. Reference data: law-matrix import, frameworks, templates, governance catalog.
3. New Client wizard, initiation package generation, invitations (screens 1–10).
4. Governance request module (10a) and commitments.
5. Client setup, attestation, inventory, sign-offs 2–4 (screens 11–15).
6. Fieldwork, findings, QA, reports, responses, remediation (screens 16–20).

---

## 18. Digitizing Audit Template v1.0 and Addendum 5.1a

The paper template becomes data. Every field, checklist item, document and declaration in the template is seeded into a **question bank** so content can be versioned and edited by Admin without code changes. Template sections 3–9 repeat **once per AI system in scope** (the template's "3A, 3B, 3C" copies).

### 18.1 Questionnaire engine

| Entity | Key fields |
|---|---|
| TemplateVersion | name (`Futran AI System Audit`), version (`1.0`), addenda (`5.1a`), effective_date, status |
| Question | template_version_id, code (e.g. `3.3.02`), section, sub_section, scope (`engagement`/`system`), label, help_text (the template's INTERN NOTE), type (`text`/`long_text`/`single`/`multi`/`yes_no_unknown`/`date`/`number`/`percent`/`person`/`file`), options[], required, default_respondent (`client`/`auditor`), applicability_rule (JSON, e.g. `{"q":"3.2.04","in":["vendor","hybrid"]}`), finding_rule (JSON: answer pattern → suggested severity + finding text), evidence_required, scoring_map (risk factor or maturity domain + points) |
| ChecklistItem | template_version_id, section (`4.3`, `5.4`, `6.4`, `7.3`, `8.4`), code, text, scope, maturity_domain, applicability_rule |
| Response | engagement_id, ai_system_id?, question_id, value, status (`answered`/`na`/`not_yet_in_place`/`unanswered`), na_reason, source_person_name, source_person_title, evidence_ids[], answered_by, answered_at, verified_by, verified_at |
| ChecklistResult | engagement_id, ai_system_id?, checklist_item_id, confirmed (bool), evidence_ids[], auditor_note |

**Golden Rules from the template, enforced:**
1. A checklist item can be ticked only if at least one evidence file is linked ("Do not tick unless you have seen the evidence").
2. "We plan to" / "we will" answers are saved with status `not_yet_in_place` and treated as *No* for scoring and findings.
3. Interview answers require `source_person_name` and `source_person_title`.
4. `N/A` requires a reason; required fields cannot be left blank at submit.
5. Draft findings are never visible to the client until approved (§6 rule 5 and sign-off 5).
6. Any *No* to a required question with a `finding_rule` auto-creates a **draft finding** for the auditor to confirm or dismiss (with reason).

**Who answers:** the client pre-fills factual fields as a pre-audit questionnaire (`default_respondent = client`); the auditor validates each answer in interviews and marks it verified. Assessment questions (risk classification, consequence severity, maturity) are auditor-only.

### 18.2 Template-to-platform map

| Template section | Platform module / screen | Scope |
|---|---|---|
| Cover block (client, audit ref `FSL-AI-AUD-YYYY-NNN`, lead auditor, period, industry, frameworks, status, overall risk) | Engagement record; wizard steps 1–3; Client page | Engagement |
| How to use / Five-step process / Golden rules | In-app help drawer; engine rules (§18.1) | — |
| §1 Client & Engagement Profile (1.1–1.3) | Wizard steps 1–4 (extra fields §18.3) | Engagement |
| §2 Document Review Log + Appendix A | Document Request Register (screen 24) | Engagement |
| §3 AI System Inventory (3.1–3.3) | AI Systems register + System profile (screens 21–22) | Per system |
| §4 Governance & Accountability (4.1–4.3) | Governance structure (screen 10a) + checklist 4.3 | Engagement |
| §5 Data Governance & Privacy (5.1, 5.1a, 5.2, 5.3, 5.4) | System assessment tab "Data & privacy" | Per system |
| §6 Model Development, Testing & Validation (6.1–6.4) | Tab "Model & validation" (in-house) or "Vendor assurance" (vendor) | Per system |
| §7 Human Oversight & Explainability (7.1–7.3) | Tab "Oversight & explainability" | Per system |
| §8 Security, Monitoring & Incidents (8.1–8.4) | Tab "Security & monitoring" | Per system |
| §9 Vendor & Third-Party AI Risk (9.1–9.2) | Vendor register (from AI tools) + tab "Vendor" | Engagement + per system |
| §10 Findings & Risk Register | Findings (screens 16–17) with 5-level severity | Engagement |
| §11 Maturity Scorecard | Risk score (screen 23) per system + engagement scorecard | Both |
| §12 Recommendations & Roadmap | Final report section + Remediation (screen 20) | Engagement |
| §13 Sign-off & Declarations | Sign-offs 5, 7 and client acknowledgement (§18.8) | Engagement |
| Appendix B Regulatory Quick Reference | Help drawer, linked from each question's frameworks | — |
| Appendix C Glossary | Glossary tooltips on question labels | — |

### 18.3 Engagement-level fields added from §1

**1.1 Client organization:** legal entity name*, trading name, primary industry*, head office address*, primary jurisdictions of operation*, annual revenue (approx., for penalty exposure), number of employees, **number of AI systems in scope***, client project lead name/title/email/phone* (= CAICO by default), client technical lead name/title, client compliance lead name/title. (*required)

**1.2 Futran engagement team:** Engagement Manager*, Lead Auditor* (= Chief Auditor for the engagement), Assisting Auditor/Intern*, Legal/Compliance Reviewer, engagement start*, target draft report date*, target final report date*, audit methodology version (default "Futran AI Audit Procedure v1.0").
→ Add engagement-team roles **Engagement Manager** and **Legal/Compliance Reviewer**; "Quality Reviewer" = QA Reviewer.

**1.3 Scope & boundaries:** AI systems included* (list of AISystem records), AI systems excluded + reason, business processes in scope*, data environments in scope* (`production`/`uat`/`dev`), geographic scope*, regulatory frameworks in scope* (NIST AI RMF, EU AI Act, DPDP, HIPAA, GDPR, SOC 2, ISO 27001, RBI FREE-AI, other + the law matrix picker), exclusions & limitations. Adding a system after initiation requires Engagement Manager approval (template rule).

**Industry vertical options:** extend to BFSI, Healthcare, Insurance, Public Sector, Staffing & recruitment, Pharma & life sciences, Property management, Other.

### 18.4 Per-system question inventory (sections 3, 5–9)

Codes are stable keys for the question bank. `*` = required. "→ F" marks answers that auto-create a draft finding.

**§3.1 System identification:** 3.1.01 official system name* · 3.1.02 system reference ID* · 3.1.03 version audited* · 3.1.04 system owner name & title* · 3.1.05 owner department* · 3.1.06 technical owner / lead engineer* · 3.1.07 production go-live date* · 3.1.08 last major update · 3.1.09 last audit/review (or "Never") · 3.1.10 classification* (`internal_only`/`client_facing_decision`/`regulatory_reporting`/`internal_and_external`).

**§3.2 Technology profile:** 3.2.01 AI system type* (multi: ML, deep learning, GenAI/LLM, rule-based, computer vision, NLP, agentic, other) · 3.2.02 model architecture · 3.2.03 foundation model + version (if GenAI) · **3.2.04 model built by*** (`in_house`/`vendor`/`open_source_customized`/`hybrid` + description) · 3.2.05 vendor legal name (if vendor/hybrid) · 3.2.06 hosting* (AWS/Azure/GCP/on-prem/hybrid + regions) · 3.2.07 languages/frameworks · 3.2.08 training data sources* · 3.2.09 inference environment · 3.2.10 external APIs called at runtime.

**§3.3 Business use & decision impact:** 3.3.01 business purpose* · 3.3.02 decision type* (`fully_automated`/`human_assisted`/`alert_only`/`analytics_only`) · 3.3.03 population affected* · 3.3.04 decisions per month · 3.3.05 consequence of incorrect output* (text + auditor severity 1–5) · 3.3.06 regulated context* (yes + regulations / no) · 3.3.07 affects protected classes (yes/no/unknown) · 3.3.08 EU AI Act classification (`prohibited`/`high`/`limited`/`minimal`, if applicable) · 3.3.09 NIST AI RMF tier (1–4) · 3.3.10 risk classification justification*.

**§5.1 Data inventory & classification:** 5.1.01 data types used in training* · 5.1.02 PHI in training (yes/no/unknown → F if unknown) · 5.1.03 PII in training · 5.1.04 special-category data (yes/no/unknown) · 5.1.05 data classification policy exists (no → F) · 5.1.06 data inventory/catalog (yes/no/informal) · 5.1.07 retention period (documented, enforced) · 5.1.08 deletion / model unlearning capability (yes/no/partial).

**§5.1a Data sufficiency & null-compliance (Addendum; shown when an AEDT or other bias audit is in scope):** 5.1a.01 collects applicant demographic data* (`voluntary_self_id`/`other_source`/`no`) · 5.1a.02 if no, deliberate choice or unaddressed gap* (client answer quoted verbatim) · 5.1a.03 % of candidate pool with unknown race/ethnicity or sex* · 5.1a.04 bias audit data source* (`employer_historical`/`vendor_supplied`/`third_party_inferred`/`pooled_same_aedt`/`test_data` + representativeness note) · 5.1a.05 null-compliance risk rating* (`low` < 20% excluded / `medium` 20–50% with documented rationale / `high` > 50%, no rationale, or design-to-avoid → F High) · 5.1a.06 recommended remediation*.

**§5.2 Legal basis & consent:** 5.2.01 GDPR basis (if applicable) · 5.2.02 HIPAA basis (if applicable) · 5.2.03 DPDP basis (if applicable) · 5.2.04 consent mechanism · 5.2.05 consent records retained (period) · 5.2.06 privacy notice covers AI (no → F) · 5.2.07 data subject rights handled (yes/no/partial) · 5.2.08 cross-border transfers + mechanism. No documented legal basis for personal data → F Critical.

**§5.3 HIPAA (shown when health data or HIPAA is in scope):** 5.3.01 covered-entity type · 5.3.02 vendor is business associate (`baa_in_place`/`baa_not_in_place` → F Critical/`no`) · 5.3.03 BAA date + covers AI use · 5.3.04 minimum necessary (yes documented/no/unknown) · 5.3.05 de-identification method · 5.3.06 PHI access logs retained 6 years (no → F) · 5.3.07 Security Rule controls (multi: access control, encryption at rest, in transit, workforce training, emergency access) · 5.3.08 breach notification procedure (60-day) · 5.3.09 HIPAA risk analysis last date (> 12 months → F).

**§6.1 Model development (in-house, open-source, hybrid):** 6.1.01 methodology* (none → F) · 6.1.02 model card exists (no → F for high-risk) · 6.1.03 feature documentation · 6.1.04 train/validation/test split % · 6.1.05 hyperparameter tuning method · 6.1.06 explainability method (SHAP/LIME/feature importance/rule extraction/none → F if high-risk) · 6.1.07 reproducibility (yes/no/unknown) · 6.1.08 change management for model updates.

**§6.2 Bias, fairness & ethics (all systems affecting people):** 6.2.01 bias testing performed* (no → F High when people are affected) · 6.2.02 last test date · 6.2.03 tool/method · 6.2.04 protected attributes tested · 6.2.05 results summary · 6.2.06 disparate impact ratio (number; < 0.80 → F) · 6.2.07 remediation taken · 6.2.08 ongoing bias monitoring + frequency (no → F) · 6.2.09 ethics review before launch.

**§6.3 Independent validation:** 6.3.01 validation required* (`yes`/`no`/`unclear` → escalate) · 6.3.02 performed* (`internal_mrm`/`external`/`no` → F if required/`partial`) · 6.3.03 validator name & organization · 6.3.04 date · 6.3.05 report obtained · 6.3.06 key findings & status · 6.3.07 frequency (never/ad hoc → F) · 6.3.08 covers bias (no → F).

**Vendor-supplied systems — "Vendor assurance" replaces §6.1 and §6.3** (`3.2.04 = vendor`); §6.2 still applies but evidence comes from the vendor and the client's own monitoring:
V.01 vendor provides model card / technical documentation (yes/no/partial) · V.02 vendor bias test results provided + date · V.03 vendor independent audit or bias audit (e.g. LL144) + date · V.04 client's own testing on its population (yes/no) · V.05 vendor trains on client data (yes/no/opt-out available) · V.06 configuration the client controls (thresholds, features, knock-out questions) documented · V.07 vendor change/version notification to client · V.08 contract allocates responsibility for bias audits and notices · plus all §9.2 vendor due-diligence questions for this vendor.

**§7.1 Human-in-the-loop:** 7.1.01 decision workflow* · 7.1.02 human can override* (no → F for high-impact) · 7.1.03 override process documented · 7.1.04 override rate last 6 months (%; near 0 flags rubber-stamping) · 7.1.05 escalation path for edge cases · 7.1.06 reviewer training · 7.1.07 time pressure on review · 7.1.08 right to human review honored (GDPR Art. 22 / DPDP).

**§7.2 Explainability:** 7.2.01 decisions can be explained* (no → F) · 7.2.02 explanation format (not provided → F) · 7.2.03 adverse action notices (BFSI) · 7.2.04 explanations tested with users · 7.2.05 individuals told AI is used (yes/no/partial).

**§8.1 AI-specific security:** 8.1.01 data poisoning controls · 8.1.02 adversarial testing · 8.1.03 model access controls* · 8.1.04 API security (multi: auth, rate limiting, input validation, output filtering, call logging) · 8.1.05 prompt injection testing (GenAI) · 8.1.06 model theft controls · 8.1.07 encryption at rest* (no → F) · 8.1.08 encryption in transit TLS 1.2+* (no → F) · 8.1.09 last pen test covering AI (> 12 months → F) · 8.1.10 dependency patching frequency.

**§8.2 Production monitoring:** 8.2.01 monitoring in place* (no → F) · 8.2.02 metrics tracked · 8.2.03 model drift alert + threshold · 8.2.04 data drift detection · 8.2.05 frequency (ad hoc on high-risk or < weekly → F) · 8.2.06 log retention · 8.2.07 performance review cadence (never → F) · 8.2.08 retraining process with change control.

**§8.3 Incident management:** 8.3.01 written AI incident definition · 8.3.02 AI incident response procedure* (no → F) · 8.3.03 response team roles · 8.3.04 incident log (request 12 months) · 8.3.05 incidents last 12 months + most serious · 8.3.06 regulatory notification process (no → F) · 8.3.07 EU AI Act serious-incident reporting (if in scope) · 8.3.08 post-incident review.

**§9.1 Vendor inventory (engagement level, prefilled from AI tools):** vendor/tool, AI capability provided, personal data processed (yes/no), BAA/DPA signed (yes/no), last risk review date, risk level (H/M/L).
**§9.2 Vendor due diligence (per vendor):** 9.2.01 vendor AI risk process (yes/no/generic IT only) · 9.2.02 AI-specific due-diligence questions · 9.2.03 SOC 2 Type II / ISO 27001 required · 9.2.04 AI transparency from vendor · 9.2.05 right-to-audit clause · 9.2.06 data localization in contract · 9.2.07 subprocessors disclosed · 9.2.08 incident notification timeframe.

**Checklists (seed verbatim from the template):** 4.3 Governance (10 items) · 5.4 Data governance (12 items + 5 from Addendum 5.1a) · 6.4 Model development (10) · 7.3 Human oversight (10) · 8.4 Security & monitoring (11). Each item is mapped to one maturity domain (§19.3).

**§4.1–4.2 (engagement level)** are captured by the Governance structure module (§10.5) plus these template fields not yet covered there: board-level AI oversight (named person), AI policy owner, policy last updated, policy covers employees, policy covers client-facing AI, AI risk appetite statement (yes/no/informal), AI incident escalation path, AI product owner per system, model risk manager (BFSI), data steward/owner*, AI ethics lead, security owner for AI, privacy officer/DPO*, third-party AI oversight owner, RACI exists (yes/no/partial).

### 18.5 Document request register (§2 + Appendix A)

Seed one **DocumentCatalog** from Appendix A's six categories (Governance; System & technical; Data privacy & legal; Security; Incident & training; Vendor & contract) and the 20-row register in §2.1; items flagged `per_system` (model cards, validation reports, bias reports, DPIAs, monitoring reports) are requested once per AI system.

| Entity | Key fields |
|---|---|
| DocumentRequest | engagement_id, catalog_item_id, ai_system_id?, requested_at, due_at (default: 5 business days before fieldwork), status (`pending`/`received`/`not_available`), received_at, evidence_ids[], finding_id |
| DocumentChase | document_request_id, chased_at, chased_by, note |

Rules: escalate to the Lead Auditor 3 business days after a chase with no receipt; `not_available` auto-creates a draft finding ("Missing documents = findings"); the request email uses the template's wording with [DATE] filled and the Engagement Manager in CC.

### 18.6 Findings classification (§10.1)

| Severity | Definition | Default remediation due |
|---|---|---|
| Critical | Immediate regulatory violation or existential risk (e.g. PHI without BAA; prohibited EU AI Act use) | 30 days; notify Lead Auditor immediately |
| High | Significant control gap with material exposure (e.g. no bias testing on credit model) | 60–90 days; remediation plan required |
| Medium | Control weakness, no immediate regulatory risk | 6 months; tracked in risk register |
| Low | Best-practice gap | Next annual cycle; no formal plan required |
| Observation | Advisory, maturity enhancement | 12-month roadmap |

Finding refs `F-001…`; each finding records template section, regulatory/standard reference, recommended remediation and owner. Findings must be written in plain English for a CEO reader.

### 18.7 Maturity scorecard (§11) and roadmap (§12)

Scale: 1 None · 2 Initial/ad hoc · 3 Defined/documented · 4 Managed/measured · 5 Optimized. Eight domains: Governance & Accountability (§4) · Data Governance & Privacy/HIPAA (§5) · Model Development & Validation (§6) · Bias, Fairness & Ethics (§6.2) · Human Oversight & Explainability (§7) · Security & Monitoring (§8) · Incident Management (§8.3) · Vendor & Third-Party AI Risk (§9). Scored per system (§19) and rolled up per engagement.

**§12.1 executive summary fields:** counts by severity, overall risk rating, most significant finding, greatest strengths observed (required: "always include genuine positives"), immediate actions within 30 days.
**§12.2 roadmap:** `RoadmapItem {ref R-01…, action, owner, priority, target_date, how_futran_can_help, finding_ids[]}`. "How Futran can help" links to Futran's service catalog and feeds the sales pipeline.

### 18.8 Declarations (§13)

| Declaration | Signer | Text source |
|---|---|---|
| Lead Auditor declaration | Lead Auditor | Template §13.1 text (versioned) |
| Engagement Manager sign-off | Engagement Manager | — |
| Quality Reviewer sign-off | QA Reviewer | — |
| Client acknowledgement | Client authorized representative | Template §13.2 declaration; UI must state that signing confirms receipt and reading, **not** agreement |
| Client remediation commitment | Client authorized representative | Either "will develop a remediation plan within 30 days" or "disputes the following findings" (list of finding refs) |

Report versioning follows the template: Draft v0.1 → Lead review v0.2 → Client v1.0 → Final v1.1. Futran signatures (Lead Auditor, Engagement Manager, Quality Reviewer) must be complete before the report is released to the client.

---

## 19. Per-AI-system data collection and risk scoring

### 19.1 AI system vs. use case vs. tool

| Record | What it is | Source |
|---|---|---|
| AITool | A product in use (often shadow AI, e.g. ChatGPT on a personal account) | Attestation, inventory |
| UseCase | A business use of one or more tools; tiered 1–3 for triage | Client inventory |
| **AISystem** | A system formally audited under template §3–9 (developed or vendor-supplied) | Created by auditor from Tier 3 (and selected Tier 2) use cases, or listed in scope at initiation |

Selection rule: every Tier 3 use case must map to an AISystem in scope; Tier 2 use cases get a **light assessment** (§3, §5, §9 and §7.2 only); Tier 1 stays inventory-only.

**AISystem fields:** engagement_id, name, reference_id, version, owner, technical_owner, department_id, built_by (`in_house`/`vendor`/`open_source_customized`/`hybrid`), vendor_id, tool_ids[], use_case_ids[], assessment_depth (`full`/`light`), status (`not_started`/`client_prefill`/`in_review`/`scored`/`locked`), completion_pct, methodology_version.

**Question sets by build type:** in-house → §3, §5, §6.1–6.4, §7, §8, §9 (if it calls external APIs); vendor → §3, §5, Vendor assurance (V.01–V.08), §6.2, §7, §8 (client-side controls: access, monitoring, incidents), §9.2 for that vendor; open-source customized → in-house set + licence & provenance questions; hybrid → in-house set + vendor assurance for the vendor components.

### 19.2 Inherent risk (impact before controls), 0–100

`Inherent = Σ weight × (factor score ÷ 5) × 100`

| Factor | Source | Score 1–5 | Weight |
|---|---|---|---|
| Decision type | 3.3.02 | Fully automated 5 · Human-assisted 3 · Alert/flag 2 · Analytics only 1 | 20% |
| Consequence of incorrect output | 3.3.05 (auditor severity) | 1 negligible … 5 severe or irreversible harm | 20% |
| Protected classes affected | 3.3.07 | Yes 5 · Unknown 4 · No 1 | 15% |
| Data sensitivity | 5.1.02–5.1.04 | PHI / biometric / special category 5 · financial or PII 3 · non-personal 1 | 15% |
| Regulated context | 3.3.06 | Yes 5 · No 1 | 10% |
| Volume | 3.3.04 | < 100/mo 1 · 100–1k 2 · 1k–10k 3 · 10k–100k 4 · > 100k 5 | 10% |
| System type | 3.2.01 (highest selected) | Agentic 5 · GenAI/LLM 4 · ML / DL / CV / NLP 3 · Rule-based 1 | 5% |
| Exposure | 3.1.10 | Client-facing or both 5 · Regulatory reporting 4 · Internal only 2 | 5% |

EU AI Act classification overrides: `prohibited` → rating Critical regardless of score; `high` → inherent floor of 70.

### 19.3 Control maturity (8 domains, 1–5)

Proposed domain score from evidence: % of the domain's applicable checklist items confirmed with evidence (0–19% → 1, 20–39% → 2, 40–59% → 3, 60–79% → 4, 80–100% → 5), minus 1 for each open High or Critical finding in that domain (minimum 1). The Lead Auditor sets the final score; a rationale is required when it differs from the proposed score by more than 1.

| Domain | In-house weight | Vendor weight |
|---|---|---|
| Governance & Accountability | 15% | 15% |
| Data Governance & Privacy | 15% | 15% |
| Model Development & Validation (vendor: Vendor assurance) | 15% | 10% |
| Bias, Fairness & Ethics | 15% | 15% |
| Human Oversight & Explainability | 15% | 15% |
| Security & Monitoring | 10% | 10% |
| Incident Management | 5% | 5% |
| Vendor & Third-Party AI Risk | 10% | 15% |

Open-source and hybrid systems use in-house weights. `Maturity M = Σ weight × domain score` (1–5). Engagement-level domains (Governance §4, Vendor §9.1) are shared by all systems in the engagement.

### 19.4 Residual risk and rating

`Control effectiveness CE = (M − 1) ÷ 4` · `Residual = Inherent × (1 − 0.75 × CE)` (controls can reduce risk by at most 75%).

| Residual score | Rating |
|---|---|
| ≥ 75 | Critical |
| 50–74.9 | High |
| 25–49.9 | Medium |
| < 25 | Low |

**Knock-out rules (override the score upward):**
- **Force Critical:** PHI processed by a vendor without a BAA (5.3.02); no documented legal basis for personal data (§5.2); EU AI Act prohibited practice (3.3.08); fully automated decision with consequence ≥ 4 and no human override (3.3.02 + 3.3.05 + 7.1.02).
- **Force at least High:** no bias testing on a system affecting people (6.2.01 = No and 3.3.07 ≠ No); no encryption at rest or in transit (8.1.07/8.1.08); null-compliance risk High (5.1a.05); independent validation required but not performed (6.3.01/6.3.02).

The Lead Auditor may raise or lower the final rating with a written rationale (logged). Engagement overall risk rating = highest final system rating; engagement maturity = inherent-risk-weighted mean of system maturity scores.

**Worked example — ATS résumé screening (vendor-supplied):** decision type human-assisted 3 (12) · consequence 4 (16) · protected classes yes 5 (15) · PII 3 (9) · regulated yes 5 (10) · ~2,000 decisions/month 3 (6) · ML 3 (3) · client-facing 5 (5) → **Inherent 76**. Domain scores (vendor weights) Gov 3, Data 2, Vendor assurance 2, Bias 1, Oversight 3, Security 3, Incident 2, Vendor 2 → **M = 2.25**, CE = 0.31 → **Residual 58.2 (High)**. Knock-outs: no bias testing and null-compliance High both force at least High → **Final rating: High**.

### 19.5 Storage

| Entity | Key fields |
|---|---|
| RiskMethodology | version, factor_weights (json), domain_weights_by_build_type (json), bands (json), knockout_rules (json), effective_date |
| SystemRiskScore | ai_system_id, methodology_version, factor_scores (json), inherent, domain_scores_proposed (json), domain_scores_final (json), domain_rationales (json), maturity, residual, knockouts_triggered[], computed_rating, final_rating, override_rationale, scored_by, approved_by, locked_at |
| EngagementScorecard | engagement_id, domain_scores (json), overall_maturity, overall_rating, narrative |

Scores recalculate on every answer change until the system is locked (locking is part of sign-off 5). Every recalculation is stored with the methodology version so old reports remain reproducible.

---

## 20. Additional screens (v0.2)

| # | Screen | Shell | Primary role(s) | Key elements |
|---|---|---|---|---|
| 21 | AI systems register `/e/:id/systems` | F | Auditor, Chief Auditor | Systems in scope with built-by (in-house / vendor / open-source / hybrid), depth (full/light), completion %, inherent, maturity, residual rating, knock-outs; add system from Tier 3 use cases |
| 22 | System assessment `/e/:id/systems/:sid` | F (client pre-fill in C shell) | Auditor; client technical/system owner pre-fills | Left nav of template sections with completion; question cards with source person, evidence, verified tick, N/A reason, "not yet in place" status; auto-draft-finding banner; vendor variant replaces §6.1/6.3 with Vendor assurance |
| 23 | System risk score `/e/:id/systems/:sid/score` | F | Lead Auditor | Inherent factor breakdown, 8 domain bars (proposed vs final), residual calculation, knock-outs, final rating with override rationale, lock |
| 24 | Document request register `/e/:id/documents` | F (client view in C shell) | Auditor; CAICO uploads | Appendix A catalog by category, per-system items, requested/due/received, chase log, escalation flags, "Not available → finding" |

Build order update: add the questionnaire engine and question-bank seed (from Template v1.0 + Addendum 5.1a) to step 2, and screens 21–24 plus risk scoring to step 6.

---

## 21. Open questions

1. Should employees get an optional login role instead of the no-login attestation link?
2. E-signature: built-in click-to-sign with audit trail, or integrate DocuSign/Adobe Sign for sign-offs 1, 4 and 7?
3. International law sheet (EU AI Act, GDPR, India DPDP): who maintains it and when?
4. Should Futran's own internal AI usage audit run in the same platform as a "client" tenant?
5. Fee/engagement value fields on the engagement record, or kept outside the platform?
