---
title: Futran Audit Platform — Per-System Questionnaire and Vendor Due Diligence
date: 2026-10-12
status: draft for approval
tags: [futran-audit-platform, ai-governance, vendor-risk, spec-addendum]
related: "[[Futran_Audit_Platform_Developer_Spec]] [[Futran_AI_Governance_Audit_Template]]"
---

# Per-System Questionnaire and Vendor Due Diligence

Addendum to the Futran Audit Platform developer spec (v0.1). It closes one gap: the spec captures AI tools and use cases, but it never asks the client to describe each AI system in use. The earlier Futran AI Governance Audit Template did this in sections 3, 6, 7, 8 and 9. This addendum brings those questions into the platform and adds a vendor branch.

## 1. What changes

| Spec today | With this addendum |
|---|---|
| `AITool`: vendor, product, plan, account type, SSO, training on inputs, retention | `AISystem`: one record per AI system in use, with a profile questionnaire |
| Vendor facts are four fields on the tool | `Vendor` record shared across systems, with a document checklist and a due diligence questionnaire |
| No per-system sign-off content | Department leads approve their systems (sign-off 2). The DPO reviews data handling (sign-off 3). The management representation names the system register |
| Auditor reviews use cases only | Auditor reviews each system and gives each vendor a risk rating |

Use cases stay as they are. A use case links to one or more systems, and a system can serve several use cases.

## 2. Who answers what

The depth of the profile follows the highest tier among the use cases a system supports. *(Futran's call, pending approval. See open question 1.)*

| Profile section | Every system | Systems with a Tier 2–3 use case | Vendor-provided systems |
|---|---|---|---|
| A. Identification | Required | Required | Required |
| B. Technology | Required | Required | Required |
| C. Decision impact | Rolled up from use cases | Required | Required |
| D. Testing and validation | — | Required | May point to vendor evidence |
| E. Human oversight | — | Required | Required (it is the client's process) |
| F. Security and monitoring | — | Required | May point to vendor evidence |
| G. Vendor documents | — | — | Required |
| H. Vendor due diligence | — | — | Required |

**Preparer:** the system owner, or a Contributor in that department. **Reviewer/approver:** the Department Compliance Lead. The DPO reviews sections B (data), G and H for data handling.

## 3. Per-system questions

Questions marked **[R]** are required. Questions marked **FINDING** pre-fill a draft finding for the auditor when the client gives that answer.

### A. Identification (all systems)
1. Official system name **[R]**: the name used in technical documentation.
2. System reference ID: auto-assigned (`SYS-###`), editable to match the client's own ID.
3. Version or release in production **[R]**
4. Status **[R]**: production · pilot · retired during audit period
5. Business owner, name and title **[R]**: the person accountable for the system.
6. Owning department **[R]**
7. Technical owner or lead engineer **[R]**. For vendor systems, this is the internal administrator.
8. Date first deployed **[R]**
9. Date of last major update
10. Date of last audit or review (enter "Never" if none)
11. System classification **[R]**: internal only · client-facing decision system · regulatory reporting · internal and external
12. How the system is sourced **[R]**: built in-house · vendor SaaS product · vendor model called via API · AI feature embedded in another vendor product · open-source model, self-hosted or customized · hybrid (describe)
    → Any answer other than "built in-house" opens sections G and H.
13. Vendor **[R if vendor-sourced]**: pick an existing vendor or add one.
14. Hosting and region **[R]**: AWS · Azure · GCP · on-premise · vendor-hosted · hybrid. Give the region(s).
15. Locations where the system is used: chosen from the client's sites, which links the system to the laws in scope.
16. Linked use cases: filled in automatically from the inventory.

### B. Technology (all systems)
1. AI type **[R]**: machine learning · deep learning · generative AI / LLM · rule-based · computer vision · NLP · agentic AI · other
2. Foundation model and version (if generative AI), e.g. GPT-4o, Claude, Gemini, Llama
3. Model architecture (if known)
4. Data the system receives **[R]**: PII · PHI · client data · confidential business data · public data only
5. Training data sources (in-house systems) **[R if in-house]**
6. Is client data used to train or improve the model? **[R]** yes · no · unknown (unknown → FINDING for Tier 2–3)
7. External APIs or services called at runtime
8. Where outputs are generated: same cloud · vendor API · edge device · other

### C. Decision impact (rolled up from use cases; confirmed per system for Tier 2–3)
1. Decision type **[R]**: fully automated · AI recommends, human decides · alert or flag only · analytics or reporting only
2. Population affected **[R]**, e.g. applicants, employees, policyholders, claimants
3. Estimated outputs used in decisions per month
4. Worst realistic consequence of a wrong output **[R]**
5. Used in a regulated context? **[R]** Yes (name the regulations) · No
6. Could outputs affect protected classes? yes · no · unknown
7. Client's own EU AI Act classification (if EU operations): prohibited · high-risk · limited · minimal
8. AEDT under NYC LL144? Shown only for employment use in NYC. The auditor confirms it in fieldwork.

### D. Testing and validation (Tier 2–3)
1. Model card or equivalent documentation exists? **[R]** yes (upload) · no (FINDING) · vendor provides (see G)
2. Bias testing performed? **[R]** yes · planned · no (FINDING when the system affects people) · relies on vendor testing
3. Date, method or tool, and protected attributes tested
4. Results summary and disparate impact ratio (upload as evidence; no calculation in v1)
5. Independent validation performed? **[R]** internal model risk team · external third party · no (FINDING if regulation requires it) · partial
6. Validator, date and report (upload)
7. Formal change approval before model updates? **[R]** yes · no (FINDING)
8. Bias monitored in production? yes (frequency) · no (FINDING)

### E. Human oversight (Tier 2–3)
1. Decision workflow, step by step **[R]**: what happens after the AI produces an output.
2. Can a human override the AI? **[R]** always · in defined cases · no (FINDING for consequential decisions)
3. Override process documented and trained? yes · no
4. Override rate over the last 6 months (a very low rate may mean rubber-stamping)
5. Reviewers trained to challenge AI outputs? yes · informal · no
6. Can decisions be explained to the person affected in plain language? **[R]** yes · no (FINDING)
7. Are affected people told AI is involved? yes · partial · no
8. Can affected people request human review? yes · no · not applicable

### F. Security and monitoring (Tier 2–3)
1. Who can access the model, prompts, training data and endpoints? **[R]**
2. Encryption at rest and in transit **[R]**: yes · no (FINDING) · vendor-managed (see H)
3. Prompt injection or adversarial testing (generative AI): yes · no · not applicable
4. Date of last penetration test covering this system (more than 12 months ago → FINDING)
5. Performance and drift monitoring in place? **[R]** automated · manual only · no (FINDING for production systems)
6. AI incidents in the last 12 months: count, plus a description of the most serious
7. AI incident procedure covers this system? **[R]** yes · no (FINDING)

## 4. Vendor branch

A `Vendor` record is created once and reused across every system from that vendor, so Microsoft is answered once even if the client uses Copilot and Azure OpenAI. The documents and due diligence are held per vendor, and each system confirms which product terms apply to it.

### G. Vendor documents checklist
Each item is answered **Uploaded** · **Requested from vendor** (date requested and expected date) · **Not available** (reason) · **Not applicable** (reason). "Requested" and "not available" items on systems linked to Tier 2–3 use cases become commitments, which are tracked like remediation.

| # | Document | When required |
|---|---|---|
| 1 | Master agreement or terms of service in force | Always |
| 2 | Data processing agreement (DPA) | Personal data sent to the system |
| 3 | Business associate agreement (BAA) | PHI sent to the system |
| 4 | SOC 2 Type II report or ISO/IEC 27001 certificate | Always |
| 5 | ISO/IEC 42001 certificate | If the vendor holds it |
| 6 | Model card, system card or technical documentation | Tier 2–3 |
| 7 | AI data-use terms (training on inputs, opt-out, retention) | Always |
| 8 | Subprocessor list, including the underlying model provider | Always |
| 9 | Data residency or processing-location statement | Always |
| 10 | Bias or fairness testing results | Systems affecting people |
| 11 | Independent bias audit summary (e.g. NYC LL144) | AEDT in scope |
| 12 | EU AI Act conformity information or instructions for use | High-risk system with EU operations |
| 13 | Security summary or penetration test letter | Tier 2–3 |
| 14 | Incident notification terms (if not in the agreement) | Tier 2–3 |

### H. Vendor due diligence questionnaire
The client answers these, usually through procurement or the system's business owner. Answers can cite the documents in G.

**Vendor profile**
1. Vendor legal name and HQ country **[R]**
2. Product(s) and plan(s) in use **[R]**
3. Internal contract owner **[R]**
4. Contract start date and next renewal date
5. How critical the vendor is to the business: high · medium · low

**Data handling**
6. Does the vendor train or improve its models on the client's inputs or outputs? **[R]** no (contractual) · no (setting only) · yes · unknown (FINDING)
7. Retention period for prompts, inputs and outputs **[R]**
8. Data deleted or returned at contract end? yes · no · unknown
9. Countries or regions where data is stored and processed **[R]**
10. Subprocessors disclosed, including the foundation model provider? yes · no (FINDING)
11. Is the client told before subprocessors change? yes · no

**Model transparency**
12. Does the vendor document model type, intended use and known limitations? yes · partial · no
13. Does the vendor notify the client before material model changes? yes · no (FINDING for Tier 3)
14. Does the vendor support explanations of individual outputs? yes · no · not applicable

**Fairness and testing**
15. Has the vendor tested for bias? Which attributes, and are the results shared? **[R for systems affecting people]**
16. Has the system had an independent audit (e.g. LL144 bias audit)? yes (upload) · no · not applicable

**Security**
17. Current SOC 2 Type II or ISO 27001? **[R]** yes · no (FINDING for Tier 2–3) · in progress
18. SSO and role-based access supported and enabled for the client? yes · no
19. Prompt injection or adversarial testing performed by the vendor? yes · no · unknown

**Contract and accountability**
20. Right-to-audit or right-to-assess clause? **[R]** yes · no
21. AI incident notification timeframe in the contract **[R]**: state the number of hours or days, or "none" (FINDING for Tier 2–3)
22. Indemnity or liability terms for AI outputs (e.g. IP or discrimination claims): yes · no · not reviewed
23. Will the vendor cooperate with regulators and provide information the client needs to meet its own obligations (e.g. EU AI Act deployer duties)? yes · no · not addressed

**Client's own vendor assessment**
24. Did the client run its own AI-specific vendor assessment before onboarding? **[R]** yes (upload) · generic IT assessment only · no (FINDING)
25. Client's risk rating for this vendor: high · medium · low, with the date reviewed and the next review date

The auditor then records **Futran's vendor risk rating** (high/medium/low with a rationale) in fieldwork, separately from the client's own rating.

## 5. Where it slots into the flow

| Stage | Addition |
|---|---|
| 1 Onboarding | Initiation package gains **item 8: AI system register and vendor due diligence** (client action: *answer*). The Chief Auditor sets the due date. The getting-started guide explains it. |
| 2 Setup | Client Admin can bulk-load systems and vendors from a CSV (template below) or enter them by hand. |
| 3 Discovery | New client screen **AI systems**. Employee-declared tools from the attestation appear as *unconfirmed* systems for the CAICO to confirm, merge or dismiss. New use cases must link to at least one system. Owners complete profiles. Vendor systems open sections G and H. **Exit gate adds:** every confirmed system has sections A–B complete, and every system linked to a Tier 2–3 use case has its full profile. Every vendor has its due diligence submitted, or each missing item is marked *requested* with a date. |
| 4 Client review | **Sign-off 2** covers the department's systems as well as its use cases. **Sign-off 3** (DPO) covers profile section B, data questions, and G/H data-handling answers. The **management representation** text is extended (below). The inventory snapshot locks systems, profiles and vendor answers. |
| 5 Fieldwork | New Futran screen **System review**: completeness, profile answers with evidence, the vendor's documents and DD, and auto-suggested findings from the FINDING answers. The auditor sets Futran's vendor risk rating and raises evidence requests for missing documents. |
| 6–8 | Findings map to systems and vendors. The final report gains a **System register** appendix and a **Third-party AI risk** section. |
| 9 Remediation | "Requested from vendor" commitments and vendor findings are tracked to closure. Each vendor shows a next review date. |

**Updated management representation text:**
> To the best of our knowledge, the AI inventory submitted for {client} is complete and accurate for the audit period. It includes every AI system in use in the departments in scope, whether built in-house or provided by a vendor, and we have disclosed all AI tools and use cases known to management.

**System register CSV:**
```csv
system_name,version,status,department,business_owner_email,technical_owner_email,source,vendor_name,hosting,region,ai_type
Résumé screening,2026.2,production,Human Resources,priya.shah@abc.com,it.admin@abc.com,vendor_saas,HireVue,vendor_hosted,us-east,machine_learning
```

## 6. Data model changes

| Entity | Key fields |
|---|---|
| `AISystem` (replaces `AITool`) | organization_id, engagement_id, ref_id, name, version, status, department_id, business_owner_user_id, technical_owner_user_id, source, vendor_id, hosting, regions[], location_ids[], ai_type, foundation_model, data_categories[], trains_on_client_data, confirmed (bool), created_from_attestation_id, profile_depth (`basic`/`full`, derived from the highest linked use-case tier), account_type, sso. The `account_type` and `sso` fields from AITool are kept for employee-declared tools |
| `SystemProfile` | system_id, section (`A`–`F`), answers (json), status (`not_started`/`in_progress`/`submitted`/`approved`/`returned`), preparer_id, approved_by |
| `Vendor` | organization_id, legal_name, hq_country, contract_owner_user_id, contract_start, renewal_date, criticality, client_risk_rating, client_reviewed_at, next_review_date, futran_risk_rating, futran_rating_rationale, rated_by |
| `VendorDocumentItem` | vendor_id, catalog_item (1–14), status (`uploaded`/`requested`/`not_available`/`not_applicable`), file_ids[], requested_on, expected_on, reason |
| `VendorDueDiligence` | vendor_id, engagement_id, answers (json), status, submitted_by, submitted_at |
| `UseCaseSystem` | use_case_id, system_id (replaces `tool_ids[]` on UseCase) |

The tiering rule in spec §11 now reads a system's `source`, `account_type` and `trains_on_client_data` as well as its data categories. Two cases make a use case at least Tier 2: a linked vendor system with **unknown** training-on-inputs, or any personal or free account.

## 7. Screens added

| # | Screen | Shell | Role |
|---|---|---|---|
| 14a | AI systems register `/systems` | C | CAICO, Dept Lead, Contributor |
| 14b | System profile `/systems/:id` (tabs A–F, plus Vendor tab) | C | System owner, Contributor, Dept Lead, DPO |
| 14c | Vendor `/vendors/:id` (documents checklist and due diligence) | C | Contract owner, CAICO, DPO |
| 16a | System review `/e/:id/systems/:id` | F | Auditor |

## 8. Build impact

About 5–7 additional hours: four screens, five entities, a questionnaire engine shared with the governance request, and report sections. The revised estimate is about **36–45 hours of build work over roughly 6–8 working days**.

## 9. Open questions

1. **Profile depth.** Is the full profile (sections D–F) required only for systems linked to Tier 2–3 use cases, or for every system? *Recommended: by tier, so Tier 1 tools such as an approved enterprise chatbot for drafting don't bury the client in questions.*
2. **Vendor participation.** Does the client fill in the due diligence on the vendor's behalf, or can the client send the vendor a secure, no-login link to answer section H and upload section G documents directly? The client would review the answers before submitting them. *Recommended: allow the link. Vendors answer faster and the client still owns the submission.*
