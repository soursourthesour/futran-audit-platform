# Futran Audit Platform — Developer Handoff Specification

**Version:** 0.6.1 · **Date:** 29 October 2026 · **Owner:** Futran AI Governance Advisory
**Status:** Confidential — internal, not for external distribution

**What changed in v0.2:** the full content of *Futran AI Governance Audit Template v1.0* and *Addendum 5.1a (Data Sufficiency & Null-Compliance Risk)* is now specified for digitization (§18), per-AI-system data collection for in-house, vendor-supplied, open-source and hybrid systems is added, and a per-system risk scoring method is defined (§19), with four new screens (§20).

**What changed in v0.3:** 19 extended features from a competitive review of Fieldguide, Scytale, Compliance.ai and Archer Evolv are specified in §21 (AI copilot, integrations and AI discovery, continuous monitoring, regulatory alerts, obligation extraction, lineage, policy builder, impact assessment, Trust Center, questionnaire automation, bias and guardrail testing, training, heat map, agent monitoring, benchmarking, carry-forward, API, comments, platform certification), with 11 new screens (25–35) and a four-phase roadmap (§22). Development approach (build, buy, partner) is decided per feature.

**What changed in v0.4:** an AI system register with a 21-role governance catalogue, role statuses (assigned, external, no such person, pending committee, not applicable) and a go-live stage gate (§24, screens R1–R5); and a Futran-side regulatory master that holds every geography's AI laws, requirements, roles and committees, kept current by a Claude refresh that the Chief Auditor approves, and that generates each client's intro letter (§25, screens M1–M5). Colorado data updated to SB 26-189.

**What changed in v0.5:** emails now go out through Futran's and each client's own Microsoft 365 or Google mailbox, with reply and directory sync; recipients are AI Governix groups (AuditTeam, AIComplianceTeam, AI-NIST, AI-EUAct, DeptHeads, Employees) expanded at send time and sent as personal no-login links or in BCC (§26, screens E1–E5).

**What changed in v0.6.1:** every law and litigation refresh now ends with an alert to the Chief Auditor (in the app and by email), with reminders and escalation (§27.9, screen M6).

**What changed in v0.6:** per-user mailbox sync and "send to all employees"; a history log and requirements checklist for every AI system, captured at first entry; a paid tracing and incident add-on with an unlock flow; a litigation tracker; a new Futran Sales Team role with automatic opportunities; and automatic client alert emails on rule changes, deadlines and cases (§27, screens R6–R8, L1–L2, S1, A1).

**Companion design assets**
- Screen mockups (59 screens: incl. R6–R8, L1–L2, S1, A1 added in v0.6; 1–24 Phase 1, 25–35 Phases 2–3, R1–R5 register, M1–M5 and M1a–M1b regulatory master, E1–E5 email and groups): https://claude.ai/artifact/UTFNXhXiy1a5aMxNo1sBgW
- Design notes, diagrams and rationale: https://claude.ai/code/artifact/d02f9d94-3f9b-43d7-b3e3-79e316111ee2
- Reference data source: `Futran_US_AI_Law_Matrix_Federal_State.xlsx` (status as of 5 Oct 2026)

---

## 1. Purpose and scope

Replace Futran's paper and Excel audit forms with a multi-tenant web application that captures an AI governance audit end to end:

1. Futran creates a client and an engagement, and sends an initiation package.
2. The client sets up users, describes its AI governance structure, runs an employee attestation, and builds an AI inventory.
3. The client signs a management representation; Futran performs fieldwork, records findings, and issues a report.
4. The client responds; remediation is tracked to verified closure.

**Out of scope for Phase 1 (MVP):** billing, public website, native mobile apps (the employee attestation must work on a phone browser), automated bias-statistics computation (evidence upload only in Phase 1; calculator in Phase 2, §21 F11). All §21 features are Phase 2–4 (§22).

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
| 1 | Futran staff login `/staff/login` | — | Futran roles | Futran SSO (Microsoft), email/password, TOTP; link to client sign-in. Separate entry point from clients |
| 2 | Dashboard `/audits` | F | Futran | KPI tiles (in progress, completed, awaiting approval, awaiting client); engagements table (client, engagement, stage, chief auditor, target date, status); filters; activity feed; **New client** |
| 3–7 | New Client wizard `/clients/new` | F | Any Futran role (draft); Chief Auditor (step 5 approve) | 1 Company · 2 Locations & laws (law-matrix picker) · 3 Scope & team (type, period, dates, departments, exclusions, team, conflict confirmation) · 4 Client contacts (CAICO required; Client Admin same/different; optional Sponsor/DPO with "not appointed") · 5 Package review (7 items, preview/edit, client message, approval checklist, **Approve and send** / **Return to author**). Autosave drafts. |
| 8 | Client page `/clients/:id` | F | Futran | 9-stage tracker, client details, laws in scope, team, activity, resend invitation |
| 9 | Invitation email | Email | CAICO, Client Admin | Message, 7 items, accept button, 7-day expiry; no attachments |
| 9a | Accept invitation `/invite/:token` | C | Invited client users | Steps: confirm details → password (12+ chars, breached-password check) → MFA enrolment with QR and recovery codes → terms and audit-log acknowledgment → checklist. "Not you?" cancels the invitation |
| 9b | Client sign in `/login` | C | Client users | Client SSO (if enabled by Client Admin), email/password, TOTP; "Have an invitation?"; note that employees use the attestation link and need no account; link to Futran staff portal |
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

### 13.1 Role views (canvas pages)

Each role lands on its own home screen after sign-in, and the navigation shows only the modules that role can use (§5). The canvas has one page per role; shared screens sit on their main user's page.

| Role | Home screen | Primary screens | Also opens (on other pages) |
|---|---|---|---|
| Futran Admin | Admin console: users, templates, law-matrix import | 1 staff login, wizard steps 3–6, 26 regulatory updates, M1–M2 and M4 edits (approved by Chief Auditor) | Dashboard (all clients), audit log |
| Chief Auditor | 2 Dashboard | M1–M5 regulatory master (refresh, approve changes, intro letters), 8 client page, 7 approve and send, 17 findings approval, 23 risk score, 35 heat map, 19 final report, 34 benchmarking | Wizard, system assessment, documents, remediation close-out |
| Auditor | My work: assigned engagements, today's tasks | 21 systems, 22 assessment, 25 copilot, 24 documents, 16 fieldwork, 29 bias calculator, 20 remediation | Wizard steps 1–4 (draft only), dashboard filtered to assigned clients |
| QA Reviewer | QA queue: Chief-Auditor-authored findings and score overrides | — | Findings and scores, approve or return only |
| Chief AI Compliance Officer | 10 initiation checklist | R1–R5 AI system register and company roles (all departments), 9/9a/9b invitation and sign-in, 10a governance, 12 attestation, 15 inventory review, 18 responses, 27 policy builder, 31 monitoring, 33 training | Use cases, new AI projects, DPO review if no DPO, Trust Center approval |
| Client Admin | Client Admin home: users, SSO, connectors, role-change log | 11 users and departments, 30 integrations, R1 register (all, import), R5 user and committee lists | — (no audit content) |
| Executive Sponsor | Summary and signatures (sign-offs 4 and 6) | — | Inventory review, responses (read-only) |
| Data Protection Officer | Data review (sign-off 3), attestation privacy | — | Attestation tracker, inventory review, new AI projects |
| Department Compliance Lead | My department: approvals, attestation totals, findings | R1–R4 AI system register for own department, 28 new AI project | Use case form, responses for own department |
| Contributor | My tasks: returned items, evidence requests, drafts | 14 add a use case | — |
| Employee (no account) | Email link | 13 attestation, training module (phone) | 32 Trust Center (public) |

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

Steps 1–6 (plus §18–20) are Phase 1. Phases 2–4 follow the roadmap in §22.

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

## 21. Extended features (v0.3)

Nineteen features identified by comparing the design with Fieldguide, Scytale, Compliance.ai and Archer Evolv (October 2026). Each one is specified enough to design the data model now; **the development approach is decided per feature** (build, buy/license, partner or open-source) and features ship in the phases in §22. Phase 1 = everything in §1–20.

**Rules that apply to every AI-powered feature (F1, F5, F10, F14):**
1. **Human approves everything.** AI output is a *suggestion* with status `suggested`; nothing reaches a client, a finding, a score or a report until a named Futran user accepts it. No auto-approve setting.
2. **Cite the source.** Every suggestion links to the document, page and passage it came from, plus a confidence level (`high`/`medium`/`low`). No citation → shown as "unsupported" and cannot be accepted as evidence.
3. **Logged.** Prompt template version, model and provider, input object ids, output, and the accepting user go to the audit log (`AIInteraction` record).
4. **Client data protection.** Use an LLM provider under enterprise terms (no training on inputs, defined retention, data residency by region). Per-client opt-out switch at engagement level; when off, AI features are hidden for that engagement.
5. **Futran governs its own AI.** The platform's AI features are registered as AI systems in Futran's own tenant and audited with this same template. This is a sales point.

```
AIInteraction { id, engagement_id, feature (copilot_prefill/draft_finding/review_check/summary/obligation_extract/questionnaire), model, provider, prompt_version, input_refs[], output (json), citations[] {evidence_id, page, quote}, confidence, status (suggested/accepted/edited/rejected), decided_by, decided_at, reason }
```

### F1. AI audit copilot — Phase 2 (core), Phase 4 (orchestrator)
*Benchmark: Fieldguide Field Agents, Scytale Scy Agent, Archer Summarizer.* **Approach: build on an LLM API.**

| Capability | What it does | Phase |
|---|---|---|
| Document pre-fill | Reads uploaded policies, model cards, vendor terms and SOC 2 reports; proposes answers to template questions (§18.4) with page citations | 2 |
| Evidence check | For each checklist item, says whether linked evidence actually supports it and why | 2 |
| Draft findings | Writes finding text (condition, criteria, cause, effect, recommendation) in plain English from answers and rule triggers | 2 |
| Completeness reviewer | Before sign-off 5 and 7: lists unanswered required questions, ticks without evidence, contradictions between interview answers and documents, missing source persons | 2 |
| Summaries | Plain-language summary of a system, engagement or client for the Chief Auditor and report executive summary | 2 |
| Client Q&A helper | Explains what a question means to client contributors (from Appendix C glossary and intern notes), never suggests answers to the client | 2 |
| Orchestrator | Conversational "plan this engagement", "chase overdue documents", "prepare the draft report" that queues tasks for human approval | 4 |

Screen 25. Accepting a pre-fill sets `Response.source = ai_suggested_accepted` and still requires auditor verification.

### F2. Integrations and automated AI discovery — Phase 3
*Benchmark: Scytale (150+ integrations).* **Approach: build first 4 connectors; consider a unified-API provider for HRIS later.**

| Connector | Data pulled (read-only) | Use |
|---|---|---|
| Okta / Microsoft Entra ID | SSO app assignments, OAuth grants to AI apps | Discover sanctioned and OAuth-connected AI tools |
| Google Workspace | Third-party app OAuth tokens, Gemini usage | Shadow AI discovery |
| Microsoft 365 | Copilot licences and usage reports, app consents | Licensed vs. personal use |
| Expense CSV (any system) | Card transactions matched to an AI vendor list | Paid personal AI subscriptions |
| CASB / proxy log CSV (upload) | Domains visited (aggregated per department) | Traffic to AI domains |

Rules: client admin authorizes each connector (OAuth), read-only scopes only, data aggregated to tool × department (no per-person browsing data shown; per-user data visible to auditors only for Tier 2–3 named-user checks); each discovered tool becomes a `DiscoveredTool` that the client must confirm, map to an `AITool`, or dismiss with reason. Discovered tools not declared in attestation are flagged "undeclared". Connector runs logged; tokens encrypted; disconnect deletes stored tokens. Screen 30.

```
Connector { id, organization_id, type, status, scopes[], authorized_by, last_sync_at, error }
DiscoveredTool { id, connector_id, vendor, product, signal (sso_app/oauth_grant/licence/expense/traffic), department_id, user_count, first_seen, last_seen, matched_tool_id, status (new/confirmed/dismissed), dismiss_reason }
```

### F3. Continuous monitoring (subscription tier) — Phase 3
*Benchmark: Scytale continuous control monitoring.* **Approach: build; uses F2 data and scheduled checks.**
Between audits, a client on the **Monitor** plan gets: monthly re-sync of connectors; automatic checks (new undeclared AI tool, Tier 3 system with no bias test in 12 months, policy older than 12 months, commitment overdue, training below target, vendor SOC 2 report expired, LL144 audit older than 12 months); alerts to CAICO and assigned auditor; a monitoring dashboard (screen 31) with control status `healthy`/`attention`/`failed`/`not_started`. A failed check can open a remediation item or trigger reassessment (F8). Monitoring never changes a signed report; it feeds the next engagement.

```
MonitorCheck { id, code, description, frequency, rule (json), severity, applies_to (org/system/vendor) }
MonitorResult { id, organization_id, check_id, object_id, status, detail, run_at, alert_sent }
Subscription { organization_id, plan (audit_only/monitor/monitor_plus), start, end }
```

### F4. Regulatory change alerts — Phase 2 (curated), Phase 3 (licensed feed)
*Benchmark: Compliance.ai horizon scanning, Scytale regulatory radar.* **Approach: Phase 2 Futran-curated by FRD; Phase 3 evaluate a licensed regulatory content API.**
- `RegulatoryUpdate` records entered by Futran Research (FRD) or imported from a feed: law, jurisdiction, change type (`new_law`/`amendment`/`effective_date`/`enforcement_action`/`guidance`/`court_ruling`), summary, effective date, source URL, affected features (§10.2 enum), reviewed_by (expert-in-the-loop, required before publishing).
- Matching: an update alerts every client whose `ClientRequirement` or locations × AI features match. Clients see "What this means for you" with affected use cases and systems.
- Deadline calendar: upcoming effective dates per client (e.g. Colorado SB 26-189 on 1 Jan 2027).
- Each update can create a task for the client or an opportunity for Futran (advisory follow-up).
- Feeds the law matrix: approved updates create a new `matrix_version`.
- Weekly digest email; optional export to the FTLC content pipeline for LinkedIn posts.
Screen 26.

### F5. Obligation extraction and impact analysis — Phase 4
*Benchmark: Compliance.ai, Archer obligation extraction.* **Approach: build with F1 AI + mandatory expert review, or license.**
AI reads a law's text, proposes `Obligation` records (actor, action, condition, deadline, citation) with confidence; FRD reviews before publishing; each obligation maps to controls (§10.4) and template questions. Impact analysis shows, per client, which controls, policies, use cases and open findings a new obligation touches.

```
Obligation { id, regulation_id, text, actor (developer/deployer/employer/provider), citation, effective_date, control_ids[], question_ids[], status (suggested/approved), approved_by }
```

### F6. End-to-end lineage — Phase 3
*Benchmark: Compliance.ai full lineage, Archer lineage intelligence.* **Approach: build (graph view over existing links).**
Navigable chain **Regulation → Obligation → Control → Template question / checklist item → Response → Evidence → Finding → Remediation**, both directions. "Why is this a finding?" and "What proves this control?" answered in one click. Report appendix lists lineage for each finding. Screen 35 (with heat map).

### F7. Policy builder and template library — Phase 2
*Benchmark: Scytale custom policy builder, Archer guardrail seeding.* **Approach: build; content written by Futran (FATF/FRD).**
- Library of Futran templates: AI acceptable use policy, AI governance committee charter, bias & fairness committee terms of reference, RACI, AI incident response procedure, AI vendor due-diligence questionnaire, data classification for AI, employee AI data notice, human oversight procedure, model change management procedure.
- From a "Will create" commitment (§10.5) the client clicks **Start from Futran template** → guided questions (company name, tools allowed, data rules, roles) → generated draft → client edits → approval by CAICO → publish → staff acknowledgment campaign (reuses attestation) → commitment auto-closes with the approved policy as evidence.
- Licensing: templates available to subscribed clients; advisory hours to customize can be quoted from the screen ("How Futran can help").
- Independence rule: when Futran writes or customizes a client's policy, the **same Futran team cannot audit that policy** in a later engagement; the system blocks assignment and requires a different Lead Auditor.
Screen 27.

### F8. Pre-deployment AI impact assessment and reassessment triggers — Phase 2
*Benchmark: Archer privacy & ethical impact assessments.* **Approach: build; reuses question bank.**
- Clients on any subscription can submit a **new AI project** before go-live: intake form (purpose, tool, data, decision impact, population, jurisdictions) → auto tier (§11) and law match (§10.3) → required assessment depth → reviewers (DPO, Dept Lead, CAICO) → decision `approved`/`approved_with_conditions`/`rejected`, with conditions tracked.
- **Reassessment triggers:** system version change, new data category, new jurisdiction, new population, vendor change, failed monitor check, regulatory update affecting it, 12 months elapsed. A trigger reopens the affected sections of the system assessment.
- Futran may be asked for an independent opinion on Tier 3 projects (billable).
Screen 28.

```
ImpactAssessment { id, organization_id, project_name, intake (json), proposed_tier, matched_regulations[], status, decision, conditions[], decided_by, decided_at, ai_system_id (on go-live) }
ReassessmentTrigger { id, ai_system_id, type, detected_at, source (manual/monitor/regulatory_update/schedule), status }
```

### F9. Trust Center — Phase 3
*Benchmark: Scytale Trust Center.* **Approach: build (public read-only pages).**
Client-controlled public page: AI governance commitments, policies chosen for publication, LL144 bias-audit summary (with date and auditor), "Audited by Futran" badge (engagement, period, rating band only if client opts in), contact for AI questions. Each item published only after CAICO approval and Futran confirmation that claims match the signed report (prevents "AI washing" — FTC Act §5). Access options: public, or gated by NDA click-through. View analytics for the client. Screen 32.

### F10. Security and AI questionnaire automation — Phase 3
*Benchmark: Scytale AI security questionnaires.* **Approach: build with F1 AI.**
Client uploads a customer's security/AI due-diligence questionnaire (XLSX, DOCX, PDF); AI drafts answers from the client's approved answer library, policies and latest Futran report, with citations; client reviews and exports in the original format. Answer library grows from approved answers. Futran-audited facts are marked as such.

### F11. Bias testing and GenAI guardrail testing — Phase 2 (bias calculator), Phase 4 (guardrail tests)
*Benchmark: Archer guardrail conformance, Fieldguide agentic testing.* **Approach: build on open-source statistics libraries (Futran's differentiator).**
- **Bias calculator (Phase 2):** auditor or client uploads applicant/decision data (CSV: id, selected/score, sex, race/ethnicity, optional age band) → validation → selection rates and impact ratios by sex, race/ethnicity and intersectional categories per NYC LL144 rules (scoring-rate method for scored tools) → 4/5ths flag → count of unknown category (feeds 5.1a null-compliance) → output tables for the LL144 public summary (§9.6 `PublicSummary`) and finding drafts. Data stays in the client's tenant; raw rows deleted after the engagement retention period unless the client opts to keep.
- Additional metrics: statistical parity difference, equal opportunity difference where outcome labels exist; small-sample warning when a category has < 2% of the data (LL144 exclusion rule) — configurable.
- **GenAI guardrail tests (Phase 4):** a test harness that sends a Futran-maintained set of prompts (prompt injection, jailbreak, data leakage, harmful output, PII echo) to a client's chatbot endpoint in a sandbox with written client permission; records pass/fail; feeds §8.1.05 and checklist 8.4. Only against systems the client owns or has authority to test.
Screen 29.

```
BiasTestRun { id, ai_system_id, dataset_file_id, method (selection_rate/scoring_rate), categories[], results (json), unknown_count, excluded_categories[], run_by, run_at, library_version }
```

### F12. AI literacy training delivery — Phase 3
*Benchmark: Scytale security awareness training.* **Approach: build simple course player or integrate an LMS (SCORM export).**
Futran-authored short modules (AI acceptable use, shadow AI and data leakage, human oversight for reviewers, bias basics for HR, GenAI prompt hygiene). Assign by department or role; track completion and quiz score; reminders; completion certificates; feeds `NamedUser.training_complete`, the AI literacy owner role (EU AI Act Art. 4) and monitor check. Screen 33.

### F13. Risk heat map — Phase 2
**Approach: build.** Likelihood × impact grid of AI systems (inherent vs. residual position, arrow showing control effect) and of findings by severity × domain. Filters by department, build type, framework. Exports to the report. Screen 35.

### F14. AI agent lifecycle monitoring and decision logging — Phase 4
*Benchmark: Archer AI agent oversight.* **Approach: partner or integrate via client logs.**
For agentic systems: register each agent (tools it can call, permissions, human approval points), ingest decision logs (client pushes via API or uploads), sample decisions for auditor review, track override rate (§7.1.04) over time, alert on permission changes. Adds question set "Agentic AI" to §18.4 (autonomy level, actions allowed, kill switch, rate limits, audit trail).

### F15. Cross-client benchmarking — Phase 3
*Benchmark: Fieldguide Insights & Analytics.* **Approach: build; requires enough engagements.**
Anonymized, aggregated maturity scores by domain, industry and size band ("your Bias & Fairness maturity is 1.0 vs. peer median 2.5"). Minimum 5 clients per comparison group before any figure is shown; no client identifiable; client consent clause in engagement letter. Internal Futran view adds pipeline insight (most common findings → service offerings). Screen 34.

### F16. Control reuse and annual carry-forward — Phase 2
**Approach: build.**
- **Annual review engagements** copy the prior engagement's systems, answers and evidence links as `carried_forward` (visible to the client to confirm or update). Unchanged answers need re-confirmation, not re-entry; changes are highlighted for the auditor.
- **Cross-framework reuse:** one piece of evidence linked to multiple controls (e.g. one bias test satisfies NYC LL144, NIST MEASURE 2.11 and EU AI Act Art. 10) via the control catalog.
- Year-over-year comparison of maturity and residual risk in the report.

### F17. Public API and webhooks — Phase 4
**Approach: build.** REST API (OAuth 2.0 client credentials, per-tenant keys, scopes) for: AI inventory read/write, use case intake, attestation status, findings and remediation status, regulatory updates. Webhooks for sign-off completed, remediation overdue, new regulatory update. Rate-limited, versioned, audit-logged. Lets clients sync with their GRC tools (ServiceNow, Archer) — relevant to Futran's ServiceNow partnership.

### F18. Comments, mentions and notification center — Phase 2
**Approach: build.** Threaded comments on any question, evidence item, finding or remediation item; @mentions; internal-only (Futran) vs. shared-with-client visibility flag (default internal for Futran users); in-app notification center with read/unread, plus the email notifications in §14. Comments on draft findings are always internal.

### F19. Platform certification and trust — start Phase 2, certify Phase 3
**Approach: process + vendor.** SOC 2 Type II readiness (controls, logging, vendor management, pen test) begins in Phase 2; Type II audit window in Phase 3; ISO/IEC 27001 and ISO/IEC 42001 as Phase 4 options; FedRAMP only if public-sector demand justifies it. Platform publishes its own Trust Center (F9) page.

### 21.1 New and changed entities (summary)
New: `AIInteraction`, `Connector`, `DiscoveredTool`, `MonitorCheck`, `MonitorResult`, `Subscription`, `RegulatoryUpdate`, `RegulatoryAlert`, `Obligation`, `PolicyTemplate`, `PolicyDocument`, `ImpactAssessment`, `ReassessmentTrigger`, `TrustCenterPage`, `TrustCenterItem`, `Questionnaire`, `AnswerLibraryItem`, `BiasTestRun`, `GuardrailTestRun`, `TrainingModule`, `TrainingAssignment`, `AgentRegistration`, `AgentDecisionSample`, `BenchmarkSnapshot`, `Comment`, `Notification`, `ApiClient`, `Webhook`.
Changed: `Response.source` (`client`/`auditor`/`ai_suggested_accepted`/`carried_forward`); `Engagement.ai_features_enabled` (bool), `Engagement.prior_engagement_id`; `EngagementTeam` independence check against `PolicyDocument.authored_by_futran_team`; `AISystem.agentic` (bool); `Organization.subscription_plan`.

### 21.2 New screens (v0.3)

| # | Screen | Shell | Feature | Phase |
|---|---|---|---|---|
| 25 | AI copilot on system assessment | F | F1 | 2 |
| 26 | Regulatory change alerts | F + C | F4 | 2 |
| 27 | Policy builder | C | F7 | 2 |
| 28 | New AI project impact assessment | C | F8 | 2 |
| 29 | Bias test calculator (LL144) | F | F11 | 2 |
| 30 | Integrations and AI discovery | C | F2 | 3 |
| 31 | Continuous monitoring dashboard | C + F | F3 | 3 |
| 32 | Trust Center (public) | Public | F9 | 3 |
| 33 | AI literacy training | C | F12 | 3 |
| 34 | Benchmarking and practice insights | F | F15 | 3 |
| 35 | Risk heat map and lineage | F | F13, F6 | 2 / 3 |

Features without their own screen in this version (F5, F10, F14, F16, F17, F18, F19) are specified above and appear inside existing screens or admin settings.

---

## 22. Phased roadmap

Durations are indicative for a small team (2–3 developers + Futran SMEs) and should be re-estimated by the development team.

| Phase | Theme | Contents | Indicative timing | Commercial outcome |
|---|---|---|---|---|
| **1 — MVP** | Run a full audit in the platform | §1–20 plus §26 email (Microsoft 365, Google, groups, personal and BCC sends, reply and directory sync), §24 register (R1–R5) and §25 law library, role catalogue, applicability and intro letter (M1, M2, M4, M5; seeded from the law matrix, edited by hand): roles, wizard, initiation, governance, attestation, inventory, sign-offs, template questionnaire, per-system scoring, findings, report, remediation | Months 0–5 | Replace paper template on first 2–3 clients |
| **2 — Smart audit** | Faster audits, more advisory pull-through | §25.3 Claude refresh and review queue (M3) feeding F4 alerts, F1 copilot (core), F7 policy builder, F8 impact assessment, F11 bias calculator, F13 heat map, F16 carry-forward, F18 comments; F19 SOC 2 readiness starts | Months 5–9 | Lower hours per engagement; template and policy services; LL144 audits fully in-platform |
| **3 — Always-on** | Recurring revenue | F2 integrations, F3 continuous monitoring, F4 licensed feed (if chosen), F6 lineage, F9 Trust Center, F10 questionnaires, F12 training, F15 benchmarking; SOC 2 Type II audit | Months 9–15 | Monitor subscription tier; client-facing trust and training |
| **4 — Advanced** | Depth for larger clients | F1 orchestrator, F5 obligation extraction, F11 GenAI guardrail tests, F14 agent monitoring, F17 API and webhooks; ISO 27001 / 42001 options | Months 15+ | Enterprise and BFSI deals; GRC tool integrations |

**Dependencies:** M3 refresh needs the M1/M2 data model and an approved source allowlist; F4 alerts need M3; R3 go-live gate needs M4 role maps; F3 needs F2; F9 needs signed reports (Phase 1) and F7 policies; F10 needs F1; F5 needs F1 and F4; F15 needs ≥ 5 comparable engagements; F17 should follow stable data model (after Phase 2).

**Build vs. buy decisions to make before each phase:** LLM provider and terms (F1, §25.3 refresh); regulatory content licence vs. in-house curation (F4); unified-API provider vs. direct connectors (F2); LMS vs. built-in player (F12); e-signature provider (open question 2).

---

## 23. Open questions

1. Should employees get an optional login role instead of the no-login attestation link?
2. E-signature: built-in click-to-sign with audit trail, or integrate DocuSign/Adobe Sign for sign-offs 1, 4 and 7?
3. International law sheet (EU AI Act, GDPR, India DPDP): who maintains it and when?
4. Should Futran's own internal AI usage audit run in the same platform as a "client" tenant?
5. Fee/engagement value fields on the engagement record, or kept outside the platform?
6. Which LLM provider and data-processing terms for the AI features, and which data residency regions (US, EU, India)?
7. Regulatory content: keep curation in FRD, or license a feed in Phase 3?
8. Pricing for the Monitor subscription tier, Trust Center and training seats.
9. Independence policy wording when Futran both writes a client's policies (F7) and audits that client — confirm with Legal.
10. Benchmarking consent: opt-in clause in every engagement letter, or opt-out?
11. Source allowlist for the Claude refresh: who owns it (FRD or Chief Auditor), and are law-firm alerts allowed as secondary sources?
12. Refresh cadence: every 2 weeks by default, or weekly during legislative sessions?
13. Who gives legal sign-off on `low` confidence and `new_law` changes: an internal reviewer, outside counsel, or the QA Reviewer?
14. Does the intro letter need counsel review before it is sent, given the not-legal-advice footer?
15. Can a client add its own roles to the catalogue (e.g. a sector regulator's role), or only Futran?
16. When two geographies conflict on a role or deadline, is "strictest wins" always right, or should the Chief Auditor choose per client?
17. Default sender for clients that cannot approve mailbox access in time: always Futran on their behalf, or hold the campaign?
18. BCC batch size and daily send caps per provider: set per client from their licence, or one safe default?
19. Should Department Heads be allowed to send to their own department without CAICO approval?
20. Tracing add-on pricing: per system, per agent action volume, or bundled with GuardRail?
21. Litigation sources: court dockets directly (PACER cost) or a licensed litigation feed?
22. Should clients see a read-only "cases that matter to you" page, or only emailed briefings?
23. Sales Team access to client names for prospects that are not yet clients: allowed, or opportunities for existing clients only?

---

## 24. AI system register and governance roles (v0.4)

The register is the client's single list of every AI app, agent, vendor tool, embedded AI feature and AI model. It extends the inventory in §9.5 and §19: a `UseCase` still records *how* AI is used, and an `AISystem` row in the register records *what* the AI is and who governs it. Screens R1–R5.

### 24.1 Role catalogue (21 roles)

The catalogue is reference data owned by Futran (§25). Each role has a level (`company` = filled once and inherited by every system; `system` = filled per AI system; `agent` = per system, agents only) and a default "needed by" stage. Which laws require each role is held in `LawRoleMap` (§25.2), so the required set for a system is computed, never hard-coded.

| # | Role | Level | Default needed by | Main sources |
|---|---|---|---|---|
| 1 | Accountable executive | company | development | NIST GOVERN 2.3; ISO 42001 §5.1 |
| 2 | AI Governance Committee | company | program set-up | NIST GOVERN 2.1, 3.1; ISO 42001 §5.3 (recommended) |
| 3 | AI Compliance Officer | company | development | EU AI Act Art. 26; NIST GOVERN 2 |
| 4 | Data Protection Officer | company | go-live | GDPR Art. 37; India DPDP §10 |
| 5 | Grievance officer (India) | company | go-live | DPDP §8(10); IT Rules 2021 |
| 6 | AI Incident Response Lead | company | go-live | EU AI Act Art. 26(5), 73; CERT-In (6 hours) |
| 7 | AI literacy and training owner | company | go-live | EU AI Act Art. 4 |
| 8 | Vendor AI risk owner | company | procurement | NIST GOVERN 6.1; EU AI Act Art. 25 |
| 9 | Records retention owner | company | go-live | EU AI Act Art. 26(6); CA ADS rules (4 yrs); Colorado SB 26-189 (3 yrs, developers) |
| 10 | AI System Owner | system | development | NIST GOVERN 2.1 |
| 11 | Technical owner | system | go-live | EU AI Act Art. 26(5)–(6) |
| 12 | Human oversight person | system | go-live | EU AI Act Art. 14, 26(2); Colorado human review |
| 13 | Stop / disengage authority | agent | go-live | EU AI Act Art. 14(4)(e); NIST MANAGE 2.4 |
| 14 | Agent permissions approver | agent | go-live | NIST GOVERN 2.1; enforced by GuardRail |
| 15 | Explainability contact | system | go-live | EU AI Act Art. 86; Colorado (30-day explanation); CCPA ADMT |
| 16 | Appeals and correction reviewer | system | go-live | Colorado; CCPA ADMT |
| 17 | Bias testing lead / independent auditor | system | go-live | NYC LL144; CA ADS rules; NIST MEASURE 2.11 |
| 18 | Impact assessment owner | system | go-live | EU AI Act Art. 27; CCPA risk assessment; DPDP (SDF) |
| 19 | Transparency and notice owner | system | go-live | NYC LL144; IL HB 3773; EU AI Act Art. 26(11), 50; Colorado |
| 20 | Data and consent steward | system | development | DPDP; CCPA; GDPR; EU AI Act Art. 10 |
| 21 | Worker representative contact | system | go-live | EU AI Act Art. 26(7) |

This replaces the 8-role list in §10.5 for the register. The §10.5 governance request screen (10a) keeps its 8 headline roles but reads them from this catalogue.

### 24.2 Role assignment statuses

Every role cell on a system (or the company) is one `RoleAssignment` with exactly one status:

| Status | Required fields | Effect |
|---|---|---|
| `assigned` | person (client user), optional backup, effective_from | Counts as filled |
| `external` | party name (vendor, auditor firm, service provider), contact | Counts as filled |
| `no_such_person` | — | Gap. Warning before go-live stage; blocks go-live if required at go-live; becomes a finding if the system is Live |
| `pending_committee` | target date | Counts as not filled. When the committee is recorded (R5), owners are notified to pick a member |
| `not_applicable` | reason | Only the AI Compliance Officer may set this on a role that a law marks *required*; Department Heads may set it on *recommended* roles |

For the human oversight person, two confirmations are also stored (EU AI Act Art. 26(2)): `training_completed` and `has_authority_to_override`. Evidence (appointment letter, RACI) can be attached to any assignment.

Company-wide roles are inherited by default. A system can override one (`override = true`, with reason); the override is visible to the AI Compliance Officer.

### 24.3 Stage gate

`AISystem.stage`: `proposed` → `in_development` (build or procurement) → `ready_for_go_live` → `live` → `retired`.

- Required roles for a system = union of `LawRoleMap` rows for the system's laws where `level = required`, plus recommended ones shown as such.
- A system cannot move to `live` while any role required at or before go-live has status `no_such_person` or `pending_committee`. The API enforces this, not only the UI.
- Moving to `live` needs approval by the AI Compliance Officer (Department Head submits).
- Bought agents still need every go-live role; development-side duties sit with the vendor and are recorded as `external` where relevant.
- Adding or removing a law recalculates required roles immediately. Removing a law needs AI Compliance Officer approval.

### 24.4 Register grid (R1) behaviour

- Columns (default set): select, AI system (+ owner), type, vendor / provider, model or algorithm, stage, risk tier, laws, last bias test (+ overdue flag at > 12 months), data consent, required roles filled (x / y with gap count), go-live gate, row menu. Column presets: Standard, Roles view, Bias and data view, All.
- Filters: search, type, stage, risk tier, law, governance role status, department (CAICO and Client Admin only).
- Add: "Add AI system" opens R4 as a step-by-step form; CSV import uses the same validation.
- Bulk edit (R2): select rows → bar with Edit selected, Assign a role, Change stage, Add or remove a law, Request bias test, Export. Only changed fields apply; "Keep current" leaves rows untouched. Conflicts (role already filled) ask: keep, replace, or add as second person. Reason for change is required and written to each row's history. "Live" cannot be set in bulk.
- Row menu (three dots): Open and edit, Edit governance roles, Record a bias test, Upload evidence, Submit for go-live approval, Duplicate, View change history, Retire.
- Company-wide tools (e.g. a Microsoft 365 Copilot licence) appear read-only to Department Heads, with a lock icon.

### 24.5 Per-system fields (R4)

| Section | Fields |
|---|---|
| What it is | name, type (`agent`/`vendor_app`/`embedded_feature`/`foundation_model_api`/`in_house_model`/`genai_chat_tool`), built or bought (`vendor`/`in_house`/`contractor`/`shadow`), department, stage, purpose, users (role level, or named for Tier 2–3), user count |
| Vendor and model | vendor (from vendor register), underlying AI provider (OpenAI, Anthropic, Microsoft Azure OpenAI, Google, Amazon Bedrock, Meta open model, in-house, unknown), model name and version, algorithm type, hosting, vendor trains on our data (yes/no/unknown), vendor documents received (contract with AI terms, DPA, model card, vendor bias audit, SOC 2 / ISO 27001, incident clause) |
| Agent actions (agents only) | allowed actions and tools (checklist + free text), autonomy (`suggest_only`/`acts_with_approval`/`autonomous`), GuardRail policy id, AgentAssure test status |
| Data and consent | data categories, data subjects, consent or lawful basis (`consent`/`notice_only`/`other_lawful_basis`/`not_obtained`/`na`), consent date or version, consent evidence, retention period, cross-border transfer |
| Laws and risk | laws (multi-select from the law library, with suggestions from client geographies and use), decision impact, calculated risk tier (§11, §19) |
| Bias testing | last test date, next due (default +12 months; before go-live for new systems), tested by (independent auditor / internal / vendor), method, result, unknown-demographic share (> 50% raises the null-compliance flag, Addendum 5.1a) |

### 24.6 New entities (client side)

| Entity | Key fields |
|---|---|
| AISystem | organization_id, department_id, name, type, sourcing, stage, purpose, owner_user_id, vendor_id, ai_provider, model_name, model_version, algorithm_type, hosting, vendor_trains_on_data, autonomy, guardrail_policy_ref, agentassure_status, risk_tier, company_wide (bool), created_by, updated_at |
| AISystemLaw | ai_system_id, regulation_id, source (`suggested`/`manual`), added_by, approved_by (for removals) |
| AISystemData | ai_system_id, data_categories[], data_subjects[], consent_basis, consent_ref, consent_evidence_id, retention_period, cross_border |
| AISystemAction | ai_system_id, action_code, description (agents) |
| BiasTest | ai_system_id, tested_on, next_due, tester_type, tester_name, method, result, unknown_share, report_evidence_id |
| RoleAssignment | organization_id, ai_system_id (null = company-wide), role_id, status, user_id, external_party, backup_user_id, target_date, reason, effective_from, training_completed, has_authority_to_override, override (bool), evidence_ids[], updated_by, updated_at |
| GovernanceCommittee | organization_id, status (`not_formed`/`formed`), target_date, formed_on, charter_evidence_id, meeting_cadence, approval_scope |
| CommitteeMember | committee_id, user_id or external_party, committee_role (`chair`/`secretary`/`legal`/`technical`/`business`/`external_advisor_non_voting`), covers_role_id |
| ChangeLog | entity, entity_id, field, old_value, new_value, reason, user_id, at (written for every register edit, single or bulk) |

### 24.7 Permissions (register)

| Action | Dept Head | AI Compliance Officer | Client Admin |
|---|---|---|---|
| See systems | own department | all | all |
| Add, edit, bulk edit systems | own department | all | all (import) |
| Fill per-system roles | yes | yes | no |
| Set company-wide roles | no | yes | no |
| Mark a required role Not applicable | no | yes | no |
| Approve go-live | no | yes | no |
| Change which laws apply | add only | add and remove | no |
| Manage users and committee member list | no | committee | users and committee list |
| Record the committee as formed | no | yes | no |

---

## 25. Regulatory master (Futran side, v0.4)

The regulatory master is Futran's database of every geography with AI rules: scope, statutory requirements, required roles and committees, penalties and sources. It drives client set-up, the intro letter, each AI system's required roles (§24) and regulatory alerts (F4). It is kept current by a Claude-powered refresh that the Chief Auditor runs and approves. Screens M1–M5.

### 25.1 Principles

1. **Claude proposes, a person approves.** Nothing Claude finds changes a live record, a client letter or a role requirement until the Chief Auditor approves it.
2. **Official sources first.** Refresh reads an allowlist of legislatures, regulators and official journals. Law-firm alerts are optional and marked as secondary.
3. **Every change is versioned.** Letters, audits and reports store the law version they used, so past work stays reproducible.
4. **Every fact cites a source.** Each requirement and each proposed change keeps the source URL and a quoted passage.

### 25.2 Database tables

Extends `Jurisdiction` and `Regulation` in §9.2 (the Regulation fields stay; versioned fields move to `LawVersion`).

| Table | Key fields |
|---|---|
| Jurisdiction | code, name, level (`global`/`region`/`country`/`federal`/`state`/`city`), parent_id |
| Regulation (law) | jurisdiction_id, short_name, citation, type (`statute`/`regulation`/`executive`/`guidance`/`framework`/`pending`), binding (bool), topics[], current_version_id |
| LawVersion | regulation_id, version_no, status (`in_force`/`enacted_not_in_force`/`phased`/`delayed`/`guidance`/`repealed`), signed_on, effective_on, compliance_on, scope_text, applies_to[] (`developer`/`deployer`/`employer`/`data_fiduciary`/`provider`), enforcer, penalty_text, cure_period, removed_text, litigation_text, approved_by, approved_at, source_ids[] |
| ScopeTest | law_version_id, order, question_text, answer_type, in_scope_rule (used by the applicability engine) |
| Requirement | law_version_id, code (e.g. CO-03), text, applies_to, needed_by_stage, evidence_text, role_id, citation, source_quote, source_id |
| RoleCatalog | id, name, description, level (`company`/`system`/`agent`), default_stage |
| LawRoleMap | law_version_id, role_id, level (`required`/`recommended`), needed_by_stage, requirement_ids[] |
| CommitteeRule | law_version_id (or framework), committee_type (`ai_governance_committee`/`risk_program`/`quality_management_system`/`sdf_setup`), level, composition_text, cadence, triggers_text |
| Source | jurisdiction_id, name, url, kind (`official`/`secondary`), active, last_read_at |
| RefreshRun | started_by, started_at, finished_at, scope (geographies), checks[] (`new_laws`/`amendments`/`rules_guidance`/`enforcement`), sources_read, model_id, prompt_version, status, cost |
| ProposedChange | refresh_run_id, change_type (`new_law`/`amendment`/`effective_date`/`new_rule`/`guidance`/`role_mapping`/`repeal`/`enforcement`), regulation_id (null for new law), field_path, old_value, new_value (JSON), summary, source_id, source_url, source_quote, confidence (`high`/`medium`/`low`), status (`pending`/`approved`/`edited_approved`/`held`/`rejected`/`legal_review`), reviewer_id, reviewed_at, review_note |
| ChangeImpact | proposed_change_id, organization_id, ai_system_ids[], roles_affected[], letter_update_needed (bool) |
| ClientGeography | organization_id, jurisdiction_id, basis (`office`/`employees`/`candidates`/`customers`/`data`), source (from wizard step 2) |
| ClientLawApplicability | organization_id, law_version_id, in_scope (bool), reason_text, scope_answers (JSON), decided_by, decided_at |
| IntroLetter | organization_id, version_no, status (`draft`/`approved`/`sent`), body (structured JSON + rendered PDF), law_versions_used[], approved_by, sent_at, supersedes_id |

### 25.3 Claude refresh pipeline (M3)

1. Chief Auditor clicks **Run refresh** (or the schedule fires; default every 2 weeks). Inputs: geographies (all, client geographies only, or chosen), checks, source set.
2. Backend calls the Claude API per jurisdiction with: the current approved `LawVersion` records (as JSON), the source allowlist, and a fixed prompt version. Claude uses web search/fetch limited to those sources.
3. Claude returns **structured output only** (JSON schema = `ProposedChange[]`): field path, old value, new value, summary, source URL, exact quote, confidence. Free-text answers are rejected by the schema validator.
4. Backend validates: source URL is on the allowlist (else confidence forced to `low`), quote is present, field path exists. Duplicate proposals across runs are merged.
5. `ChangeImpact` is computed for each proposal: which clients, AI systems, roles and letters it touches.
6. Review queue (M3): approve, edit then approve, hold until adopted, reject, or send to legal review. `low` confidence and all `new_law` items require a second reviewer or legal review before approval.
6a. When the run finishes (scheduled or manual, with or without changes), the Chief Auditor is alerted in the app and by email with counts by change type, clients affected and low-confidence items (§27.9).
7. On approval: a new `LawVersion` is written; `LawRoleMap` and `Requirement` rows are versioned; affected clients get a regulatory change alert (F4, screen 26) and, if chosen, a pending update to their intro letter.
8. Every run, prompt version, model id, response and decision is kept for audit.

Store model and prompt version on each run so results can be compared when either changes. Cap cost per run and log it.

### 25.4 Applicability engine (M5)

- Inputs: `ClientGeography` rows (from wizard step 2, screen 4) and answers to each law's `ScopeTest` questions (pre-filled from the client's AI systems and use cases where possible).
- Output: `ClientLawApplicability` rows, with a reason for every law in and out of scope ("Colorado AI Act: no Colorado operations or residents").
- Required roles for the client = union of `LawRoleMap` over in-scope laws. Required committees = union of `CommitteeRule`. Where two laws set different deadlines or levels for the same role, the stricter wins and both sources are shown.
- Re-runs automatically when a geography, an AI system's laws, or an approved law version changes.

### 25.5 Intro letter

Generated from the applicability result and sent to the client's Chief AI Compliance Officer with the initiation package (§12). Sections:
1. Where you operate and the laws that apply (geography, law, status, main duty).
2. Committee to form (composition, cadence, approvals, legal basis or "recommended").
3. Roles and responsibilities (all required roles, responsibility, required by, needed by; full list in Appendix A with a blank for the person's name).
4. Rules for each type of AI used: AI agents, AI/ML software making decisions about people, embedded AI features, generative AI tools and chatbots (rule lists come from `Requirement` rows filtered by system type).
5. How Futran keeps this current, and the law versions used.

Workflow: draft → Chief Auditor edits and approves → sent (PDF + platform). When an approved change affects a sent letter, M5 shows "Changes since letter vN" and drafts version N+1 listing only what changed. The client's AI system register (§24) is seeded from the same result, so the letter and the register always agree. Standard footer: general information, not legal advice.

### 25.6 Screens

| # | Screen | Shell | Role | Key elements |
|---|---|---|---|---|
| M1 | Law library `/reg` | F | Chief Auditor, Admin, Auditor (read) | KPI tiles, filters (region, status, applies to, topic), table by region: law, status, effective date, scope, requirement count, role count, committee/program, penalty, last change; Refresh button |
| M2 | Law record `/reg/:law` | F | Chief Auditor, Admin | Overview, scope tests, statutory requirements (code, text, applies to, needed by, evidence, role, citation), roles required, version history, pending-change banner |
| M3 | Refresh and review `/reg/refresh` | F | Chief Auditor | Run settings, last-run steps, review queue with old → new, source quote, confidence, impact, approve / edit / hold / reject / legal review, notify options |
| M4 | Role and committee catalogue `/reg/roles` | F | Chief Auditor, Admin | Role × law matrix (Req / Rec), level and stage per role, committee and program rules |
| M5 | Client applicability and intro letter `/clients/:id/applicability` | F | Chief Auditor | Client geographies, laws in and out of scope with reasons, changes since last letter, letter preview, approve and send |
| R1 | AI system register `/register` | C | Dept Head, CAICO, Client Admin | §24.4 |
| R2 | Bulk edit (dialog) | C | Dept Head, CAICO | §24.4 |
| R3 | System governance roles `/register/:id/roles` | C | Dept Head, CAICO | Roles grouped company-wide / per system, required by, needed by, status, person, gap banner, role editor panel |
| R4 | Add or edit system `/register/:id` | C | Dept Head, CAICO | §24.5 sections as tabs; step-by-step for new systems |
| R5 | Company roles and committee `/governance/roles` | C | CAICO, Client Admin | Company-wide roles, gaps by department, committee record and members |

### 25.7 Permissions (regulatory master)

- **Chief Auditor:** run refresh, approve or reject changes, approve and send intro letters.
- **Futran Admin:** edit records and the source allowlist; edits create a `ProposedChange` that the Chief Auditor approves.
- **Auditor:** read only; can suggest a change (creates a `ProposedChange` with source).
- **QA Reviewer:** second reviewer for `low` confidence and `new_law` changes.
- Clients never see the master directly; they see their applicability result, their letter and alerts.

### 25.8 Relation to earlier sections

- Replaces the manual "law matrix import" (§10.1) as the ongoing source. The `.xlsx` import stays for the first load (seed `LawVersion` v1 from `Futran_US_AI_Law_Matrix_Federal_State.xlsx`).
- F4 regulatory alerts now come from approved `ProposedChange` rows. `RegulatoryUpdate` (F4) maps to `ProposedChange` + `ChangeImpact`; the licensed-feed option in Phase 3 becomes an extra source type.
- Wizard step 2 (screen 4) writes `ClientGeography`; step 5 (screen 7) attaches the intro letter to the initiation package.
- Data note from the law matrix: Colorado SB 26-189 (signed 14 May 2026, compliance 1 Jan 2027) repeals and replaces SB 24-205 and removes the risk-management program and impact assessments. Seed data and role maps must use SB 26-189.

---

## 26. Email integration, groups and sync (v0.5)

Most actions in the platform start with an email: invitations, the initiation package, attestation requests, department-head approvals, evidence requests, reminders, regulatory alerts. In v0.5 these go out through the real mailboxes of Futran and of each client, and replies come back into the platform. Recipients are chosen as **groups that live only in AI Governix**; a group is expanded to people at the moment of sending. Screens E1–E5.

### 26.1 Mailbox connections (MVP: Microsoft 365 and Google Workspace)

| | Microsoft 365 | Google Workspace |
|---|---|---|
| API | Microsoft Graph | Gmail API + Admin SDK Directory API |
| Sign-in | OAuth 2.0, admin consent in Entra ID | OAuth 2.0, domain-wide delegation or admin-approved app |
| Send | Mail.Send (from the chosen mailbox only; use an application access policy to limit the app to that mailbox) | gmail.send for the chosen mailbox |
| Read replies | Mail.ReadWrite on the same mailbox, filtered to threads the platform started | gmail.modify on the same mailbox, same filter |
| Directory | User.Read.All, Group.Read.All, GroupMember.Read.All | admin.directory.user.readonly, admin.directory.group.readonly |

Other providers (SMTP and IMAP) come after MVP. Confirm exact scopes and sending limits against current Microsoft and Google documentation before build; limits are configuration, not code.

**Futran side (E1, Futran Admin):** one connection for AiAudit@futransolutions.com. Settings: send-as name, reply-to, sync interval, SPF / DKIM / DMARC check, test email.

**Client side (E2, Client Admin, part of onboarding):** four steps: (1) connect Microsoft 365 or Google; if the Client Admin is not a tenant admin, the platform emails the consent request to IT. (2) Choose who the emails come from: **the client's own mailbox** (recommended, e.g. ai-governance@client.com; employees see an internal sender and mail passes the client's filters), or **Futran on the client's behalf** (AiAudit@futransolutions.com with the client's name) if IT cannot approve yet. (3) Directory sync. (4) Test email. Wizard step 6 (client contacts) shows the client's email connection status, and the initiation checklist (screen 10) adds "Connect your email" as a task for the Client Admin.

### 26.2 Sync

- **Outbound log:** every sent message is stored with template, groups, expanded recipient list, delivery mode, provider message id and status.
- **Replies:** the subject carries an engagement reference (e.g. `[GVX-1042]`) and the provider thread id is stored; the sync job reads only those threads and attaches replies to the engagement's activity. Out-of-office and bounce messages update recipient status.
- **Directory sync (client):** daily by default (configurable). Imports name, email, department, job title, manager and office for people in a chosen directory group (e.g. "All Staff"); optional guests and contractors. Leavers are removed from groups; their past answers are kept. Departments feed screen 11.
- **Futran users** sync from Futran's tenant in the same way.
- No other mailbox content is read. Tokens are stored encrypted; the connection can be revoked from either side.

### 26.3 Groups (internal to AI Governix)

Groups are never created in Microsoft 365 or Google. Each group has a source:

| Source | Example | Updates |
|---|---|---|
| Manual list | AIComplianceTeam, AI-NIST, AI-EUAct, Contractors | When someone edits it (or CSV import) |
| Rule | AuditTeam (all active Futran users), ChiefAuditors, DeptHeads (role = Department Head), Employees · HR (department = HR), AI Governance Committee (from R5) | Automatically when roles, departments or committee change |
| Directory group | Employees · All (from "All Staff"), Employees · NYC recruiters | At each directory sync |

Default groups created for every client: AIComplianceTeam, DeptHeads, Employees · All, AI Governance Committee. Default Futran groups: AuditTeam, ChiefAuditors, Auditors, QAReviewers, FutranAdmins, and one rule group per engagement team. Groups can be nested (a group may include another group); loops are rejected.

Grid behaviour matches §24.4: Add group, Import from directory, tick boxes with bulk bar (edit, send email to selected, sync now, export), three-dot row menu (open and edit, preview who receives it, send email, sync now, duplicate, export members, delete), and an edit panel (name, purpose, source, members, exclusions).

### 26.4 Sending to groups (E4)

1. Sender picks a template and one or more groups, plus exclusions (other groups, "already responded", people on leave).
2. **Expansion at send time:** groups (and nested groups) are resolved to people; duplicates removed; leavers, people on leave, unsubscribed-from-reminders and excluded people removed. The preview shows each step's count, and the final list can be viewed or downloaded. The expanded list is saved with the send, so the log shows exactly who was emailed even if the group later changes.
3. **Delivery mode:**
   - **Personal link (default for attestation, approvals and evidence requests):** one message per person, each with a unique, signed, expiring link (no login). Nobody sees other recipients. Enables per-person status and targeted reminders.
   - **BCC broadcast (for notices):** one message per batch with all recipients in BCC (batch size configurable, default 450) and a shared link. Because the link is shared, the form asks for the person's work email and sends a one-time code to it before they can submit.
4. Sending is queued and paced to stay inside provider limits; failed sends retry, then show as bounced.
5. Reminders (e.g. day 3 and day 7) go only to people with no response, using the same mode.

### 26.5 No-login employee links

- Personal link token: random, at least 128 bits, stored hashed, bound to one person and one campaign, expires (default 14 days), single active link per person (a resend invalidates the old one).
- Opening the link shows screen 13 with the person's name and department pre-filled from the directory; they confirm or correct.
- Answers create draft use cases in the inventory (§9.5) and mark the person "responded" for that campaign.
- Shared (BCC) link: email + one-time code (6 digits, 10 minutes, rate-limited); the email must belong to an expanded recipient of that send.
- No tracking pixels; "opened" means the link was opened.

### 26.6 Templates

Template fields: name, purpose, default delivery mode, subject (with engagement reference), body with merge fields ([First name], [Department], [Link], [Due date], [Sender name]), language, owner (Futran or client). Futran ships defaults (initiation package, attestation request, department-head approval, LL144 candidate notice, training, regulatory change alert, evidence request); clients can copy and edit their own. Every template edit is versioned.

### 26.7 Email and admin log (E5)

- **Emails sent:** time, template, groups, delivery mode, recipients, delivered, bounced, opened link, completed, replies, sent by; row menu: open message, see recipients and status, remind non-responders, resend bounced, open reply thread, export.
- **Admin log:** connection changes, admin consent, sender changes, group edits, directory sync results, every send. Append-only, kept 7 years (match §15 retention). Futran sees both logs for its engagements; the client sees its own.

### 26.8 New entities

| Entity | Key fields |
|---|---|
| MailConnection | owner (`futran` / organization_id), provider (`microsoft365` / `google`), tenant_id or domain, mailbox_address, send_as_name, reply_to, scopes[], token_ref (encrypted vault), consent_by, consent_at, status, last_sync_at, spf_ok, dkim_ok, dmarc_ok |
| DirectorySync | connection_id, scope_group, include_guests, schedule, department_field, last_run_at, counts (people, joined, left, changed), status, report |
| DirectoryPerson | organization_id, directory_id, email, name, department, job_title, manager_id, office, status (`active` / `left` / `on_leave`), user_id (if the person also has a login) |
| MailGroup | owner (`futran` / organization_id), name, purpose, source (`manual` / `rule` / `directory`), rule (JSON), directory_group_id, is_default, created_by |
| MailGroupMember | group_id, person_id or nested_group_id, added_by, added_at (manual groups only; rule and directory groups are computed) |
| MailTemplate | owner, name, purpose, default_mode, subject, body, merge_fields[], version, language |
| MailSend | organization_id, engagement_id, template_id, template_version, sender_connection_id, groups[], exclusions[], mode (`personal` / `bcc`), batch_size, scheduled_at, sent_at, sent_by, reminder_plan |
| MailRecipient | send_id, person_id, email, link_token_hash, link_expires_at, provider_message_id, status (`queued` / `sent` / `delivered` / `bounced` / `opened` / `completed`), reminders_sent, last_event_at |
| MailThread | send_id or engagement_id, provider_thread_id, subject_ref, last_reply_at |
| MailReply | thread_id, from, received_at, snippet, attachment_ids[], linked_entity |
| AdminLogEntry | owner, at, actor, action, details (JSON); append-only |

### 26.9 Permissions

| Action | Futran Admin | Chief Auditor / Auditor | Client Admin | CAICO | Dept Head |
|---|---|---|---|---|---|
| Connect or disconnect Futran mailbox | yes | no | — | — | — |
| Connect client mailbox, directory sync | — | — | yes | view | — |
| Manage Futran groups | yes | view | — | — | — |
| Manage client groups | — | view | yes | yes | own department's groups |
| Send to client groups | — | engagement emails only | yes | yes | own department only |
| Edit templates | Futran templates | — | client copies | client copies | — |
| See email and admin log | Futran + engagements | engagements | own | own | own department's sends |

### 26.10 Screens

| # | Screen | Shell | Role |
|---|---|---|---|
| E1 | Futran email and groups `/staff/admin/email` | F | Futran Admin |
| E2 | Connect your email `/admin/email` | C | Client Admin (onboarding) |
| E3 | Email groups `/admin/groups` | C | Client Admin, CAICO |
| E4 | Send an email to groups `/send` (also opened from campaigns and approvals) | C (and F for engagement emails) | CAICO, Client Admin, Chief Auditor |
| E5 | Email and admin log `/admin/log` | C and F | Client Admin, CAICO, Futran |

**Phase:** Phase 1 (MVP) for Microsoft 365 and Google, personal-link and BCC modes, groups, reply sync and logs. SMTP/IMAP and calendar suggestions after MVP.

---

## 27. History log, tracing add-on, litigation, client alerts and Sales Team (v0.6)

Screens R6–R8 (client), L1–L2, S1 and A1 (Futran).

### 27.1 Per-user mailbox sync and "send to all employees"

- Every user with a login (Futran staff and client roles) connects their own Microsoft 365 or Google mailbox at first sign-in (delegated OAuth). Mail they send from the app goes from their own address. Only threads the app started (subject reference such as `[GVX-1042]`) are read back; the rest of the mailbox is never read. Consent screen at first sign-in; disconnect any time; removed automatically when directory sync marks the person as left.
- Client Admin sets per-user sync to required, optional or off for client users; Futran Admin does the same for Futran staff. The organisation mailbox (§26.1) remains the sender for system emails and for users who have not connected.
- Employees without a login are never synced; they only receive mail.
- Groups record their creator and owner (`futran_admin` or `client_admin`). Futran Admin may create a client's starting groups during onboarding; the Client Admin can then edit them.
- The attestation campaign (screen 12) gets **Send to all employees**: the system group "All employees" (directory-synced), with optional department or location filter and "leave out people who already responded". Personal links and reminders as in §26.4.

### 27.2 System history log and requirements checklist (R6, core)

When a system is first entered in the register, the form asks for its history to date:

- "Since this system went live, have there been any incidents, complaints or errors?" Yes → entries are added; No → the system owner signs a "no incidents known" statement (stored with name and time; the auditor can test it).
- Also asked: bias tests done, tests before release, approvals, notices and consents.

**History log** (grid with add, bulk, row menu). Entry types and their fields:

| Type | Fields |
|---|---|
| Incident | date found, what happened, severity, people affected, cause, containment and fix, date closed, reportable (yes/no, law, deadline, date reported), provider told (EU AI Act Art. 26(5)) |
| Bias test | date, tester (independent / internal / vendor), method, groups tested, result, unknown-demographic share |
| Deployment test | date, kind (user acceptance, AgentAssure, red team, security), sample size, result |
| Impact assessment | date, law, outcome, next due |
| Notice or consent | date, audience, channel, version |
| Model change | date, old and new version, re-assessment needed |
| Approval | date, approver, scope |
| Training, vendor audit, monitoring review | date, summary, evidence |

Every entry carries evidence files, the person who recorded it and links to one or more requirements.

**Requirements checklist:** all `Requirement` rows (§25.2) for the system's laws, each `met` / `partly_met` / `not_met` / `not_applicable`, with the log entries and evidence that prove it. A requirement needed before use or go-live that is `not_met` counts in the go-live gate (§24.3) alongside missing roles.

### 27.3 Tracing and incident module (R7, paid add-on; R8 unlock)

- Shown on every system as a locked tab. Recommended (badge) when the system is Tier 3, or an agent that takes actions, or has a past incident.
- Unlocked features: action trace for agents (time, session, action, tool, data touched, decision allowed/blocked/escalated, policy, approver; fed by GuardRail or the agent's logs); incident register with a form and **regulator deadline timers** (EU AI Act Art. 73 and 26(5), Colorado AG notice where in scope, CERT-In 6 hours); drift and bias alerts between audits; export for regulators and Futran.
- Unlock flow (R8): the client picks systems (recommended ones pre-ticked), plan (per system / all Tier 2–3 / enterprise), approver (Executive Sponsor), optional 30-day trial. On submit: an approval task for the sponsor and an `Opportunity` for Futran Sales and the Chief Auditor. After the order is confirmed the module unlocks on those systems.
- Buying the module never changes audit results; auditors keep reviewing the system independently.

### 27.4 Litigation tracker (L1, L2)

- Menu **Litigation** in the Futran app. Visible to Chief Auditor, Auditors and Sales Team. Clients do not see the tracker; they receive case briefings by email (§27.6).
- Grid columns: geography, law or area, case name (X v. Y), court, short description, stage, last update, clients with similar AI. Filters: geography, law or area, stage, relevant client. Add case, bulk (send client briefing, assign to Sales, follow, export), row menu (open, edit, talking points, clients with similar AI, send briefing, create opportunity, follow).
- Case record (L2): overview, stage timeline, what it is about, why it matters, talking points (Futran-facing and client-facing), clients with similar AI (matched from registers by system type, vendor and use), sources.
- Kept current by the same Claude refresh pipeline as laws (§25.3): official court and regulator sources, proposals reviewed by the Chief Auditor before publishing. Each litigation refresh alerts the Chief Auditor the same way (§27.9). Stage values: `filed`, `pleadings`, `discovery`, `stayed`, `trial`, `appeal`, `decided`, `settled`, `dismissed`.
- Each case links to the laws it interprets, so a case appears on the law record (M2) too.

### 27.5 Sales Team role and opportunities (S1)

New Futran role **Sales Team**.

| Can | Cannot |
|---|---|
| See litigation tracker and case records | See audit findings, evidence, risk scores or reports |
| See opportunities and the trigger behind each | Send an offer to a current audit client without Chief Auditor approval |
| See client name, system type and whether an add-on is recommended or requested | Edit any law, case, register or engagement record |
| Log calls, proposals and outcomes | |

Opportunities are created automatically by: an unlock request (R8), a recommended add-on not yet bought, an approved law change or new law for the client's geographies, an effective date within 90 days, a relevant case. Fields: client, trigger, service, why now, value, owner, stage (`new` / `contacted` / `proposal` / `won` / `lost`), next step, Chief Auditor approval (required for current audit clients). Independence rule: Futran does not sell the remediation of a finding it raised in the same engagement (open question 9 applies).

### 27.6 Automatic client alerts (A1)

Rules (grid): when this happens → who gets it → client group → email template → approval → on/off → last sent.

| Trigger | Default recipients | Approval |
|---|---|---|
| Law change approved (M3) | Clients where the law applies · AIComplianceTeam | Chief Auditor per send |
| New law in a client's geography | Clients in that geography · AIComplianceTeam | Chief Auditor per send |
| Effective date in 90 and 30 days | Clients the law applies to · AIComplianceTeam, DeptHeads | Automatic |
| Relevant case added or updated | Clients using similar AI · AIComplianceTeam | Chief Auditor per send |
| Tracing add-on recommended | Chief AI Compliance Officer | Sales owner |

Each client's email lists only its affected systems and the to-dos taken from the `Requirement` rows, with a deadline and a button into the platform; it is sent from the client mailbox where connected (§26.1), else from Futran on the client's behalf, and logged in E5. Sends wait in an approval queue where the rule needs approval.

### 27.7 New entities

| Entity | Key fields |
|---|---|
| UserMailConnection | user_id, provider, mailbox, scopes[], token_ref, consented_at, status, last_sync_at |
| HistoryEntry | ai_system_id, type, occurred_on, summary, result, severity, details (JSON by type), requirement_ids[], evidence_ids[], recorded_by, recorded_at |
| NoIncidentStatement | ai_system_id, period_from, signed_by, signed_at |
| RequirementStatus | ai_system_id, requirement_id, status, history_entry_ids[], evidence_ids[], checked_by, checked_at |
| Incident | ai_system_id, code, found_on, description, severity, people_affected, cause, containment, fix, closed_on, reportable, law, deadline_at, reported_at, provider_notified_at, owner_id |
| ActionTrace | ai_system_id, at, session_id, action, tool, data_touched, decision (`allowed`/`blocked`/`escalated`), policy_ref, approver, agent_identity |
| AddonSubscription | organization_id, addon (`tracing`), ai_system_ids[], plan, trial_ends_on, status (`requested`/`approved`/`active`/`cancelled`), approved_by |
| Case | jurisdiction_id, area, name, court, docket_ref, description, stage, last_update_on, regulation_ids[], talking_points_futran, talking_points_client, source_ids[], version |
| CaseClientMatch | case_id, organization_id, ai_system_ids[], match_reason |
| Opportunity | organization_id, trigger (`unlock_request`/`recommended_addon`/`law_change`/`new_law`/`effective_date`/`case`), trigger_ref, service, value, owner_id, stage, next_step, needs_ca_approval, ca_approved_by, ca_approved_at |
| AlertRule | trigger, audience_rule, client_group, template_id, approval (`chief_auditor`/`automatic`/`sales_owner`), active, last_sent_at |
| AlertSend | alert_rule_id, organization_id, change_ref, affected_system_ids[], todo_items[], status (`waiting_approval`/`sent`/`held`), mail_send_id |

### 27.8 Screens

| # | Screen | Shell | Roles |
|---|---|---|---|
| R6 | System history and requirements `/register/:id/history` | C | Dept Head, CAICO |
| R7 | Tracing and incidents `/register/:id/tracing` | C | CAICO, Dept Head, AI Incident Response Lead (add-on) |
| R8 | Unlock add-on (dialog) | C | CAICO, Client Admin; Executive Sponsor approves |
| L1 | Litigation tracker `/litigation` | F | Chief Auditor, Auditors, Sales Team |
| L2 | Case record `/litigation/:id` | F | Chief Auditor, Auditors, Sales Team |
| S1 | Opportunities `/opportunities` | F | Sales Team, Chief Auditor |
| A1 | Automatic client alerts `/alerts` | F | Chief Auditor, Futran Admin |

**Phasing:** Phase 1: R6 history and requirements checklist, per-user sync, send to all employees. Phase 2: L1–L2 litigation tracker (curated, then Claude refresh), A1 client alerts, S1 opportunities and the Sales Team role. Phase 3: R7 tracing add-on with GuardRail feed, R8 unlock and billing.

### 27.9 Chief Auditor refresh alerts (M6)

- **Trigger:** every `RefreshRun` for laws (§25.3) or litigation (§27.4) that finishes, scheduled or manual, including runs that find nothing new (configurable).
- **Recipients:** all Chief Auditors by default (or only the one who ran it); copy to QA Reviewer and/or Futran Admin.
- **Channels:** in-app alert under a bell in the Futran header (unread badge; unread alerts stay at the top until the changes are reviewed) and email from AiAudit@futransolutions.com.
- **Content:** sources read; counts by change type (new laws, amendments and dates, new rules or guidance, case updates); clients and AI systems affected; low-confidence items flagged for legal review; buttons to the M3 review queue and the L1 tracker. States that client alerts are on hold until approval.
- **Reminders and escalation:** reminder if any change is still pending after N days (default 3); escalation after M days (default 7) to the other Chief Auditor and the Futran Admin. Each alert, reminder and escalation is written to the email log (E5) and the admin log.
- **Settings (M6):** recipients, copy, when (every run / only with changes / only high-impact or low-confidence), channels, reminder and escalation days, test alert.
- The run screen (M3) and litigation tracker (L1) show "When finished, alert" and the last alert status.

| Entity | Key fields |
|---|---|
| StaffAlert | user_id, kind (`refresh_done`/`review_reminder`/`escalation`), refresh_run_id, summary (JSON counts), created_at, read_at, resolved_at, email_send_id |
| AlertSetting | scope (`law_refresh`/`litigation_refresh`), recipients_rule, cc_roles[], when_rule, channels[], remind_after_days, escalate_after_days, escalate_to_roles[] |

Screen **M6** · Refresh alerts and settings `/staff/alerts` · F · Chief Auditor (settings: Chief Auditor, Futran Admin).
