# AI Governix — Release 2 Requirements: Sales Module and Commercial Gap Closure

**Version:** 0.4 · **Date:** 11 November 2026 · **Owner:** Futran AI Governance Advisory
**Status:** Confidential — internal, not for external distribution

**Relation to the Developer Handoff Specification v0.6.1.** This is a separate document for a separate release. It does not change v0.6.1 or its 59-screen mockup canvas. Where Release 2 needs something from an existing module, it is listed as a *touch point* (§6) that the v0.6.1 owners adopt when they are ready. Section references written as "v0.6.1 §n" point to the existing spec.

**What changed in v0.4:** every master price list item now carries a **Deliverables** text: what the client gets, written so a sales development manager can explain it to a client. It shows as a column on SM-14, on each Estimator line (SM-15), in the proposal's "What we'll do" section (SM-10) and on the acceptance page (SM-12). The master price list workbook gains the Release 2 columns (deliverables, sellable status, delivery mode, platform feature, included quantities, engagement type, entitlement key). L-09 is renamed "end-client evidence pack and configuration check" (§2.2, §4.6, §4.9, SM-14).

**What changed in v0.3:** only the **CEO and President** (new role **Price List Owner**) can change the master price list. Futran Admin and the Chief Auditor now view it only; keeping the Chief Auditor out of price-setting also protects audit independence. Sales roles can **edit any line price, quantity or description on a client's estimate or proposal and save it**; those edits stay on that client's record and never change the master. The guardrail approvals (§4.7) still apply before a proposal is sent (§4.1, §4.7, §4.9, SM-14, SM-15).

**What changed in v0.2:** the master price list now lives in the app as an editable grid (SM-14) that Futran Admin and the Chief Auditor maintain directly: edit any field, add, duplicate or retire items, with a reason and full change history. A new **Estimator** (SM-15) prices any mix of items from the live master without a questionnaire. Catalog edits no longer need Pricing Approver sign-off; per-proposal discount guardrails stay (§4.1, §4.7, §4.9).

**Screen sets (new canvas, separate from the v0.6.1 mockups):** https://claude.ai/artifact/HYzuaGpJXSSnn4d1cdyV6h
- **Set A — Sales module:** SM-01 to SM-15
- **Set B — Commercial and service gaps:** G-01 to G-11

**Source documents:** AI Governix Developer Spec v0.6.1 (29 Oct 2026); *Futran_AI_Governix_Master_Price_List.xlsx* (31 Oct 2026, 93 line items); *AI Governix Suite — Sales Collateral* doc (pitches, scoping questionnaire, price line items).

---

## 1. Purpose

Release 2 closes the gap between what Futran sells and what AI Governix can deliver, track and bill. It has two parts:

1. **Module A — Sales.** A working sales desk inside AI Governix: log opportunities, run the scoping questionnaire live on a call or send it to the client, turn the answers into a priced proposal, get approvals, send it, record acceptance and hand the won deal to delivery.
2. **Module B — Commercial and service gaps.** Plans and entitlements, change orders, time tracking, client hierarchy, manual discovery import, new engagement types and workspaces (Copilot readiness, EU AI Act conformity, Agent Assure), evidence retention tiers and partner referrals.

**Release timing:** Release 2 starts after the Phase 1 MVP (v0.6.1 §22) and runs alongside Phase 2. It needs the Phase 1 data model, email integration (v0.6.1 §26) and the Sales Team role (v0.6.1 §27.5).

---

## 2. Gap analysis

### 2.1 Status key

| Status | Meaning |
|---|---|
| **Covered** | v0.6.1 Phase 1 supports delivering it |
| **Later** | v0.6.1 specifies it, but in Phase 2, 3 or 4 |
| **Partial** | Some support; a piece the price sheet needs is missing |
| **Missing** | Nothing in v0.6.1 |
| **Service** | Delivered by people outside the platform; needs only tracking |

Across the 93 price lines (grouped below by code family): **8 Covered, 18 Later, 41 Partial, 25 Missing, 1 Service.** Every line also lacks the commercial layer (catalog, quote, order, entitlement, billing export), which is gap X-1 below.

### 2.2 By price line

| Code | Item | v0.6.1 support | Gap | Release 2 fix |
|---|---|---|---|---|
| A-01 | Scoping call | None | No place to record a scoping call or its answers | SM-05 questionnaire, SM-04 opportunity |
| A-02a–c | Enterprise audit, tiered by AI systems | **Partial** — engagement and audit flow (§7–20) | No fee or tier on the engagement (open Q5); no link to an order | G-02 engagement commercials |
| A-03 | Extra AI system | **Partial** — adding a system needs Engagement Manager approval (§18.3) | No change order or price | G-02 change orders |
| A-04 | Extra jurisdiction | **Partial** — scope items | No change order | G-02 |
| A-05 | Shadow AI discovery sweep | **Later** — F2 connectors, Phase 3 | Nothing until Phase 3; sweep is sold today | G-05 manual discovery import |
| A-06a–c | Employee attestation | **Covered** — §9.5, screens 12–13 | Headcount band not recorded for pricing | Mapping rule + G-01 usage |
| A-07 | Governance / data-policy review | **Covered** — screen 10a | Count of documents beyond 5 not tracked | G-02 change orders |
| A-08a–b | Vendor AI due diligence | **Partial** — §9.2 inside an audit | No standalone vendor DD engagement | G-06 engagement type `vendor_due_diligence` |
| A-09 | Null-compliance review | **Covered** — §5.1a, §11 | — | — |
| A-10 | Bias testing outside LL144 | **Later** — F11 calculator, Phase 2 | — | Catalog marks "manual until Phase 2" |
| A-11 | Impact assessment (CO / EU / DPIA) | **Partial** — F8 is client project intake, Phase 2 | No Futran-delivered impact assessment template (EU AI Act Art. 27 FRIA) | G-06 template, G-08 workspace |
| A-12 | Remediation roadmap and re-test | **Covered** — screen 20 | Re-test as a billable event not tracked | G-03 time |
| A-13 | Board readout | **Missing** | No executive readout pack | G-06 template (readout pack export) |
| A-14 | Annual re-audit | **Later** — F16 carry-forward, Phase 2 | Renewal date and price not tracked | G-01 renewals |
| M-01a–f | Monitor / Monitor Plus subscription | **Partial** — `Subscription.plan` (F3) | No tier by system count, no entitlements, no enforcement, no billing (billing out of scope, §1) | G-01 plans and entitlements |
| M-02 | Extra seats | **Missing** | Seats not counted | G-01 usage |
| M-03a–c | Regulatory alert packs by state count | **Partial** — alerts by applicability (§25, §27.6) | No pack entitlement; alerts go to every matching client | G-01 entitlement `alert_packs` |
| M-04 | Litigation briefings | **Covered** — §27.4, §27.6 | Not gated by plan | G-01 |
| M-05 | Continuous control monitoring | **Later** — F3, Phase 3 | — | Catalog "roadmap"; quarterly manual re-check via G-05 |
| M-06a–e | Evidence vault and retention | **Partial** — 7-year retention per engagement (§15) | No storage metering, retention tiers per client or legal hold | G-10 |
| M-07a–b | Policy drafting and refresh | **Later** — F7, Phase 2 | Futran drafting hours not tracked | G-03 time |
| M-08a–c | Training workshops and e-learning | **Later** — F12, Phase 3 | Workshops not recorded | G-06 type `training_workshop`; catalog "roadmap" for e-learning |
| M-09 | Trust Center | **Later** — F9, Phase 3 | — | Catalog "roadmap" |
| M-10a–b | Questionnaire automation | **Later** — F10, Phase 3 | No per-questionnaire count | Catalog "roadmap"; G-01 metering when built |
| M-11a–c | Tracing and incident module | **Later** — R7/R8, Phase 3 | Plan pricing open (Q20) | Catalog prices; G-01 entitlement |
| M-12a–b | Incident response retainer | **Partial** — incident register in R7 | Standing retainer and activated hours not tracked | G-03 retainers |
| M-13 | Advisor hours bank | **Missing** | No hours bank | G-03 |
| M-14a–b | API access and custom integration | **Later** — F17, Phase 4 | Price sheet sells it before the platform has it | Catalog "roadmap" |
| M-15a–c | Compliance retainers | **Missing** | No retainer contract record | G-01 recurring order lines |
| AA-01–06 | Agent Assure | **Missing** — register stores only `agentassure_status` (§24.5) | No record of eval sets, 15-point checks, red-team results or assurance letters | G-09 Agent Assure records |
| AW-01–10 | AgentWarden | **Partial** — register field `guardrail_policy_ref`; R7 trace fed by GuardRail | No licence count, action volume, approver seats or deployment option | G-09 AgentWarden licence sync + G-01 metering |
| L-01 | LL144 Readiness Assessment | **Covered** — engagement type `ll144_bias_audit` | — | Package in catalog |
| L-02 | Independent bias audit | **Later** — evidence upload Phase 1, calculator Phase 2 | — | — |
| L-03 | Applicability determination (8-case map) | **Missing** | No LL144 applicability questionnaire | G-06 template `ll144_applicability` |
| L-04 | Synthetic / test-data audit | **Partial** — 5.1a.04 allows `test_data` | No synthetic dataset record | G-06 template field set |
| L-05 | Demographic data setup | **Partial** — null-compliance flag | Fix not tracked as a deliverable | G-02 deliverables |
| L-06 | Candidate notice workflow | **Partial** — LL144 notice template (§26.6) | 10-business-day notice timing not tracked | G-06 template checklist |
| L-07 | Annual renewal audit | **Missing** | No renewal date | G-01 renewals |
| L-08 | Other-state wrapper | **Partial** — scope items | No change order | G-02 |
| L-09 | Staffing chain: end-client evidence pack and configuration check | **Missing** — one `Organization` per client | No end-client hierarchy. LL144 needs an audit per tool, not per end-client; L-09 covers evidence packs, notices on that client's NYC jobs and a check for client-specific tool settings | G-04 client hierarchy |
| L-10 | Vendor-sponsored audit | **Missing** | HR-tech vendor as client, auditing its tool across customers | G-06 type `vendor_sponsored_audit` + G-04 |
| X-01 | Fractional AI Governance Officer | **Partial** — `external` role status (§24.2) | Independence check ignores a Futran person holding a client role | §4.7 rule I-3, G-03 time |
| X-02 | ISO/IEC 42001 readiness | **Partial** — ISO 42001 clauses optional (§10.4) | No readiness template | G-06 template |
| X-03 | EU AI Act conformity readiness | **Partial** — EU AI Act articles in mappings | No classification workspace, Annex IV tracker or FRIA; international law sheet open (Q3) | G-08 |
| X-04 | Copilot governance rollout | **Missing** — Copilot only as a register row | No readiness workspace; connectors Phase 3 | G-07 + G-05 import |
| X-05 | M&A AI due diligence | **Missing** | No engagement type | G-06 type `ma_due_diligence` |
| X-06 | Litigation support | **Service** | Hours not tracked | G-03 time |
| X-07 | Channel partner referral share | **Missing** | No partner or attribution record | G-11 partners |
| T-01–04 | Onboarding fee, residency, SLA, multi-year | **Missing** — data residency open (Q6) | No contract terms, region per tenant | G-01 plan settings; SM-09 terms |

### 2.3 Cross-cutting gaps

| # | Gap | Effect today | Fix |
|---|---|---|---|
| X-1 | No commercial layer: catalog, proposal, order, entitlement, billing export | Prices live in a spreadsheet; nothing links a sale to delivery | Module A + G-01 |
| X-2 | Sales is automatic-only (S1); no manual opportunity, prospect or activity log (open Q23) | Reps track deals outside the platform | SM-02 to SM-04 |
| X-3 | No scoping questionnaire in the platform | Answers on paper; no link to pricing | SM-05 to SM-08 |
| X-4 | No proposal builder | Proposals assembled by hand; no price or discount control | SM-09 to SM-12 |
| X-5 | Engagement types limited to three | New services can't run in the platform | G-06 |
| X-6 | No time or hours tracking | Retainers, hours banks and margins can't be measured | G-03 |
| X-7 | No entitlement or usage metering | Plans can't be enforced or billed | G-01 |
| X-8 | One-level client model | Staffing chains and groups can't be priced or audited per entity | G-04 |
| X-9 | **Price sheet sells roadmap items** (A-05 connectors, M-05, M-08c, M-09, M-10, M-11, M-14) | Sales can promise features the platform doesn't have | Catalog `sellable_status` (§4.9) |
| X-10 | Independence checks cover policy authorship only (F7) | Selling AgentWarden, a fractional officer or a remediation fix to an audit client isn't checked | §4.7 rules I-1 to I-4 |
| X-11 | No partner or referral record | Channel commissions can't be paid accurately | G-11 |
| X-12 | No data residency per tenant | Residency uplift (T-02) can't be honoured | G-01 plan settings |

---

## 3. Release 2 scope

| In scope | Out of scope |
|---|---|
| Module A: opportunities, activities, scoping questionnaire (recorded and sent), reconciliation, proposal builder, approvals, client acceptance, won handoff, catalog admin | Invoicing and payments inside the platform (Release 2 exports billing data; the accounting system invoices) |
| Module B: G-01 to G-11 | Building the Agent Assure test harness or AgentWarden runtime (separate products; Release 2 records their results and licences) |
| Import of the Master Price List workbook as catalog v1 | Discovery connectors (stay in Phase 3, F2; G-05 is the manual bridge) |
| Proposal documents as PDF and DOCX | CRM sync (HubSpot, Salesforce): open question R2-Q6 |

---

## 4. Module A — Sales

### 4.1 Roles

Release 2 renames the v0.6.1 **Sales Team** role to **Sales Officer** and adds three approval roles. A person can hold several roles; nobody approves their own proposal.

| Role | Can | Cannot |
|---|---|---|
| Sales Officer | Log and work opportunities; run and send scoping questionnaires; build, version and send proposals within guardrails; log activities; request approvals | See findings, evidence, risk scores or reports (as v0.6.1 §27.5); approve own discounts; send a proposal that needs approval |
| Sales Manager | Everything a Sales Officer can; reassign opportunities; approve discounts up to 15%; see team pipeline and reports | Approve proposed (unapproved) prices or discounts above 15% |
| Price List Owner (CEO and President) | **Edit the master price list (SM-14): change any field, add, duplicate, retire items, mark prices Approved, import from Excel** | — |
| Pricing Approver (CEO by default) | Approve discounts above 15%, prices below catalog Low and custom terms on a proposal | — |
| Chief Auditor | Independence approval for proposals to current or recent audit clients (§4.7); see pipeline; view the master price list | Edit the master price list |
| Futran Admin | View and export the master price list; maintain questionnaire bank, mapping rules, packages and proposal templates | Edit the master price list |

**Two levels of pricing:**
1. **Master price list (SM-14):** the standard prices for everyone. Only the Price List Owners (CEO and President) can change it.
2. **Client estimate or proposal (SM-15, SM-09):** Sales Officers and Sales Managers can edit any line's price, quantity and description for that client and **save** it as often as they like. The edit is stored on that estimate or proposal only; the master never changes. Each edited line shows the master price beside it, an **Edited** badge and a **Reset to list price** button.

Saving is never blocked. Guardrail approvals (§4.7) are needed only to **send** a proposal whose edited prices fall outside the rules (e.g. below Low, or a discount above 15%).

### 4.2 Opportunity lifecycle

`Opportunity.stage`: `new → qualified → scoping → proposal → negotiation → won | lost` (plus `on_hold`).

| Stage | Entered when | Exit gate |
|---|---|---|
| new | Logged manually (SM-03) or created automatically (v0.6.1 §27.5 triggers) | Owner set and first activity logged |
| qualified | Rep confirms budget, decision maker and timeline (BANT fields) | Questionnaire started |
| scoping | Questionnaire in progress (recorded, sent or both) | Questionnaire locked (SM-08) |
| proposal | First proposal version drafted | A version sent to the client |
| negotiation | Client asked for changes or a new version is in progress | Accepted or lost |
| won | Client accepts a version (SM-12) or the rep records a signed PO | Handoff complete (SM-13) |
| lost | Rep closes with a reason (`price`, `timing`, `competitor`, `no_budget`, `no_decision`, `other`) | — |

Automatic opportunities keep their trigger (`unlock_request`, `law_change`, `new_law`, `effective_date`, `case`, `recommended_addon`) and add new Release 2 triggers: `renewal_due` (90 days before a contract end, G-01), `change_order` (G-02), `entitlement_limit` (usage at 90% of a limit, G-01), `discovery_finding` (Copilot or EU-scoped system found, G-05).

### 4.3 Opportunity logger

**Fields (SM-03, SM-04):** company (existing client, or new prospect), website, industry, size band, HQ state and country, contacts (name, title, email, phone, role: economic buyer, champion, technical, legal, procurement), source (`outbound_call`, `email_campaign`, `linkedin`, `inbound_web`, `referral_partner`, `event`, `existing_client`, `auto_trigger`), partner (G-11, when referred), segment (`staffing_hr`, `enterprise_bfsi_health_ins`, `agents_copilot`), trigger event (from the questionnaire's Section A list), products of interest (multi), estimated value, close date, owner, next step + due date, BANT (budget, authority, need, timeline), competitors.

**Rules:**
1. **Prospects are allowed** (answers v0.6.1 open Q23). A prospect is an `Organization` with `status = prospect`; it has no tenant data, no users and no login. Converting on win (SM-13) changes it to `draft` client.
2. **Duplicate check** on company name, website domain and contact email; the rep must merge or confirm "different company".
3. **Independence flag** is computed on save: the company is a current audit client, had an engagement completed in the last 24 months, or has an open remediation item. The flag shows on the record and drives §4.7.
4. **Activities** (`call`, `email`, `meeting`, `note`, `task`) with date, outcome, next step. Emails sent from the opportunity go through the rep's own mailbox (v0.6.1 §27.1) and replies thread back in.
5. Opportunities with no activity for 14 days show as stale on SM-01 and in the owner's weekly digest.

### 4.4 Scoping questionnaire

The question bank is the Sales Collateral scoping questionnaire, Sections A–H, stored as data (same engine pattern as v0.6.1 §18.1, separate bank). Each question has a stable code, e.g. `SQ-C.07` (total AI systems).

**Three ways to fill it:**

| Mode | Who | How |
|---|---|---|
| **Recorded on the call** (SM-05) | Sales Officer | Live form, sections A–H, ticks and counts, autosave every 5 s, keyboard-friendly. The suggested line-items panel updates as answers change. |
| **Sent to the client** (SM-06, SM-07) | Client contact | The rep picks sections and questions (pricing-sensitive ones hidden by default: budget, competitors), a contact and a due date. Sent as a personal no-login link from the rep's mailbox (v0.6.1 §26.4–26.5). Phone-friendly; saves as the client goes; client can forward to a colleague who gets their own link. Reminders on day 3 and 7. |
| **Hybrid** | Both | Rep records what they heard, then sends the rest to the client. Each answer keeps its source. |

**Answer fields:** value, `source` (`rep` / `client` / `rep_confirmed_client`), `confidence` (`confirmed` / `estimate` / `unknown`), note, answered_by, answered_at.

**Rules:**
1. "Unknown" is always a valid answer. An unknown AI system count adds A-05 (discovery sweep) as a suggested line and a note in the proposal assumptions.
2. Client answers never overwrite rep answers silently; a different value is shown as a conflict on SM-08.
3. Hidden internal fields (budget, competitors, red flags, independence) are never shown on the client link.
4. A questionnaire is **locked** on SM-08 before it feeds a proposal. Unlocking for edits creates a new version; proposals record the version they used.
5. The client link shows Futran branding, the not-legal-advice footer and a privacy note. Answers are stored in Futran's tenant against the prospect.

### 4.5 Mapping rules (questionnaire → line items)

Mapping rules are data (`MappingRule`), edited by Futran Admin and approved by the Pricing Approver. Each rule reads one or more answers and proposes a line item, quantity and reason. Rules seeded in v1:

| Answer(s) | Proposed line | Quantity |
|---|---|---|
| SQ-C.07 total AI systems ≤10 / 11–50 / 50+ | A-02a / b / c | 1 |
| SQ-C.07 above tier ceiling inside tier band | A-03 | systems above the tier's included count |
| SQ-C inventory = "partial" or "none", or SQ-C.07 unknown | A-05 | number of connectors ticked (min 1) |
| SQ-B.01 employees | A-06a / b / c | 1 |
| SQ-B.06 states count > included in audit (1) | A-04 | states − 1 |
| SQ-C.08 vendors | A-08a (1–9), A-08b (≥10) | vendors / 1 |
| SQ-D.02 AEDTs ≥ 1 and NYC = yes | L-01 + L-02 | 1 + (AEDTs − 1) |
| SQ-D data situation = little or none | L-04, L-05, A-09 | per AEDT / 1 / 1 |
| SQ-D business model = staffing | L-09 | end-clients |
| SQ-D other states ticked | L-08 | states ticked |
| SQ-E high-risk systems | A-11 | count |
| SQ-F plan interest | M-01a–f by SQ-C.07 tier | 1 |
| SQ-B jurisdictions ticked (state count) | M-03a / b / c | 1 |
| SQ-F retention years 7 / 10 | M-06c / M-06d | 1 |
| SQ-G agents live + planned (12 months) | AA-01, AA-02, AW-02a/b, AW-04 | agents (AW-02 by autonomy) |
| SQ-G any agent action ticked | AW-01 | 1 |
| SQ-H Copilot = yes, or SQ-C embedded AI lists Copilot | X-04 | 1 |
| SQ-B EU = yes and SQ-C high-risk count ≥ 1 | X-03 | high-risk systems with EU exposure |
| SQ-A trigger = M&A | X-05 | 1 |

Every proposed line shows the answer that produced it ("A-05 × 3 — because inventory is partial and Okta, M365 and Google were ticked"). The rep can accept, change quantity or remove; removing a rule-proposed line needs a reason.

### 4.6 Proposal builder

**Inputs:** locked questionnaire version, catalog version, package template (Starter, Governed, Agent-ready, Custom).

**Price precedence for each line:** edited price on this proposal → catalog list price → none (blocked). Reps can edit and save any line at any time; approval is needed only to send when an edited price is outside the guardrails. `Unit price used × qty × periods per year` = year-1 value (same rule as the Quote Builder sheet). Percentage items (A-14, M-06c/d, AW-07, AW-09, T-02, T-03) are computed against the lines they apply to and shown as their own lines.

**Proposal content (template sections, editable):** cover; your situation (pre-filled from Section A trigger and B–C footprint); what we'll do (one block per line, built from each item's **deliverables** in the master price list; the rep can tailor the wording for this client, and the edit is saved on the proposal only); deliverables and timeline; pricing table (one-time, recurring year 1, annual recurring after year 1, discount); assumptions (auto: unknowns, inclusions such as "5 policy documents reviewed", roadmap items excluded); terms (validity 30 days by default, payment terms, multi-year, SLA, data residency); independence statement (when flagged); acceptance block.

**Versions:** v1, v2… Each version is immutable once sent. The builder shows a diff between versions (lines, quantities, prices, terms).

**Send (SM-10):** PDF and DOCX export; email from the rep's mailbox with a personal acceptance link (SM-12) that expires with the proposal; reminders; view tracking (link opened, not pixels).

**Acceptance (SM-12):** the client views the proposal, then **Accept** (name, title, email, tick "I am authorised to accept for [company]", optional PO number and upload) or **Request changes** (free text). Accepting records an `Acceptance` with time and IP and moves the opportunity to `won`. Optional e-signature integration follows v0.6.1 open Q2.

### 4.7 Guardrails and approvals

**Pricing rules:**

| Rule | Approver |
|---|---|
| P-1 Any line at a catalog price whose status is **Proposed** (not yet marked Approved by a Price List Owner) | Pricing Approver |
| P-2 Discount on recurring ≤ 15% | Sales Manager |
| P-3 Discount > 15%, or any one-time discount | Pricing Approver |
| P-4 Override price below catalog Low | Pricing Approver |
| P-5 Override price above catalog High | Sales Manager (sanity check) |
| P-6 Custom terms (payment > 30 days, liability, SLA credits) | Pricing Approver |
| P-7 Line with `sellable_status = roadmap` | Blocked. Can appear only in an "Optional, when available" section with no price |
| P-8 Line with `sellable_status = manual_delivery` | Allowed; assumption line added automatically ("delivered by Futran consultants until the platform feature ships") |

**Independence rules (Chief Auditor approval when the opportunity's independence flag is set):**

| Rule | Check |
|---|---|
| I-1 | Futran does not sell the remediation of a finding it raised in an open engagement (v0.6.1 §27.5). Lines whose catalog `remediation_of` tags match an open finding's domain are blocked until the Chief Auditor approves with a note |
| I-2 | Policy drafting (M-07), AgentWarden (AW-*) or Agent Assure (AA-*) for systems Futran audits: Chief Auditor must confirm a separate delivery team; the handoff (SM-13) records the team and the audit assignment check (v0.6.1 F7) extends to these lines |
| I-3 | Fractional AI Governance Officer (X-01): the Futran person who will hold the client role is excluded from that client's audit team; enforced when they are added to `EngagementTeam` |
| I-4 | Proposals to audit clients carry a fixed independence statement in the document |

A proposal with any unmet approval cannot be sent. Approvals are recorded per proposal version (who, when, rule, note) and listed on SM-11.

### 4.8 Won → handoff (SM-13)

On acceptance the system creates, in one transaction, and lists for the Sales Officer and Chief Auditor to confirm:

1. **Client organization:** prospect → `draft` client (v0.6.1 §9.1), with contacts copied to `ClientContact`.
2. **Order** with order lines copied from the accepted proposal version (prices frozen).
3. **Engagement drafts** for each delivery line family: audit lines → `initial_assessment`; LL144 lines → `ll144_bias_audit`; new types from G-06. The New Client wizard (v0.6.1 screens 3–7) opens pre-filled: locations and laws from Section B, departments and AI system count from Section C, contacts from the opportunity.
4. **Subscription and entitlements** (G-01) for recurring lines.
5. **Hours banks and retainers** (G-03) for M-12, M-13, X-01, X-06.
6. **Partner commission record** (G-11) when the opportunity has a partner.
7. Notifications: Chief Auditor (approve engagement drafts and team), Futran Admin (client set-up), finance (billing export, G-01).

Handoff never sends anything to the client. The initiation package still goes through Chief Auditor approval as in v0.6.1 §7.

### 4.9 Master price list in the app (SM-14) and Estimator (SM-15)

The master price list is a live grid in AI Governix. It is the **only** price source: the Estimator, the Proposal builder, change orders (G-02), hours-bank overage (G-03) and billing export (G-01) all read from it. The Excel workbook is used once, to load v1, and afterwards only as an optional import or export.

**Who can do what**

| Action | Price List Owner (CEO, President) | Futran Admin, Chief Auditor | Sales Manager, Sales Officer |
|---|---|---|---|
| View the grid | yes | yes (read-only) | yes (read-only) |
| Edit any field inline or in the side panel | yes | no | no |
| Add an item (blank, or duplicate an existing one) | yes | no | no |
| Retire or restore an item | yes | no | no |
| Bulk edit selected rows (e.g. +5% list price, change sellable status) | yes | no | no |
| Mark price status Proposed → Approved | yes | no | no |
| Import from Excel | yes | no | no |
| Export to Excel | yes | yes | yes |
| See change history | yes | yes | yes |
| Suggest a change (sends a note to the Price List Owners) | — | yes | yes |

**Grid behaviour (SM-14)**

- Columns: code, product, line item, **deliverables (what the client gets)**, description (short proposal text), pricing unit, billing, basis ($ / %), periods per year, Low, List, High, price status, sellable status, delivery mode, platform feature, included quantities, engagement type, entitlement key, notes, last changed (who, when). Column presets: Pricing, Sellability, Delivery, All.
- Filters: product, billing, price status, sellable status, changed in last 30 days, search.
- **Inline edit:** click a cell, type, press Enter. Changed cells are highlighted until saved. **Save changes** asks for one reason for the batch.
- **Side panel** (row menu → Edit) for all fields, including the full deliverables text, description and included quantities.
- **Deliverables** are maintained by the Price List Owners like any other field (history, reason, effective date). They are written for clients: what is delivered, how, what the client provides and typical duration. Every item must have deliverables before it can be Approved. Search covers deliverables text.
- **Add item:** blank row or Duplicate; code must be unique, product must exist; new items start as `Proposed` and `available`.
- **Retire** instead of delete: a retired item can't be added to new estimates or proposals but stays on old ones. Items are never hard-deleted.
- **Bulk edit:** select rows → set field, or change prices by % or amount, with rounding (nearest $10 / $50 / $100).
- **Validation:** Low ≤ List ≤ High; % items between 0 and 100%; periods per year 1, 4 or 12 (0 for partner share); code format `XX-00` with optional letter; a warning when List moves more than 25% in one edit.
- **Effective date:** a change applies now (default) or from a future date, e.g. new prices from 1 January. Future changes show as pending on the row.
- **History:** every change records field, old value, new value, reason, user and time; row menu → View history; whole-catalog change log with filter and export.
- **Optional second check:** a setting (off by default) that requires the other Price List Owner (CEO or President) to confirm price changes above a chosen % before they go live.
- **Suggest a change:** anyone who can view the grid can suggest a price or new item from the row menu; it goes to the Price List Owners as a task with the reason.

**How changes reach estimates and proposals**

| Where the price is used | What happens when the master changes |
|---|---|
| Saved estimate or draft proposal (SM-15, SM-09) | Lines the rep **edited** keep the rep's price. Lines still **at list** show a banner: "3 list prices changed since you saved. Update these lines?" The rep updates or keeps them; kept old prices are treated as edited prices |
| Proposal sent or accepted | Never changes. It keeps the catalog version it was built on |
| Orders and subscriptions | Never change until renewal. The renewal opportunity (G-01) uses current prices |
| Mapping rules | Keep working; a rule pointing to a retired item is flagged on SM-14 for repair |

The catalog keeps an internal version number that increases with every saved batch, so any estimate or proposal can show exactly which prices it used.

**Estimator (SM-15)**

A quick price tool for Sales Officers and Managers, the in-app version of the Quote Builder sheet. No questionnaire needed.
- Pick a package (Starter, Governed, Agent-ready) or start empty; add items by code or search; set quantity.
- Each line has **What the client gets**, which expands the item's deliverables so the rep can read them on a call; a toggle shows them on every line. The rep can tailor the text for this client; it never changes the master.
- Unit price starts at the master List price, with the Low–High range beside it. **The rep can type a different price, quantity or description on any line and save.** Edited lines show an Edited badge, the list price beside the edited price, the difference, and **Reset to list price**. Roadmap items can't be added; manual-delivery items carry their assumption note.
- **Save** keeps the estimate on the client's opportunity with every edit; it can be reopened, changed and saved again (each save is a version with who and when). Saving is always allowed; the guardrail warnings (§4.7) show which approvals a proposal will need.
- Discount on recurring, contract term and data region, with the same guardrail warnings as the proposal builder.
- Totals: one-time, recurring year 1, discount, year-1 total, annual recurring after year 1.
- **Convert to proposal** opens SM-09 with the same lines and edited prices. Estimates are internal and are never sent to clients directly.

**Load and initial values**
- v1 loads from *Futran_AI_Governix_Master_Price_List_R2.xlsx* (Master Price List sheet): code, product, line item, pricing unit, billing, basis, periods/yr, low, list, high, price status, notes, plus the Release 2 columns M–S: deliverables, sellable status, delivery mode, platform feature / release, included quantities, engagement type, entitlement key.
- Initial values in the workbook: `sellable_status` = `roadmap` for M-05, M-08c, M-09, M-10a–b, M-14a; `manual_delivery` for A-05, A-10 (until Phase 2), M-11 (until Phase 3); otherwise `available`. When the v0.6.1 feature named in `platform_feature_ref` is released, Futran Admin flags it and a Price List Owner confirms the change.
- Later Excel imports show a preview of adds, changes and retirements before anything is saved; they follow the same history and reason rules.

### 4.10 Notifications

| Event | Recipients | Channel |
|---|---|---|
| Opportunity assigned to you | Owner | In-app + email |
| Client completed or partly completed the questionnaire | Owner | In-app + email |
| Approval needed | Approver for the rule | In-app + email |
| Approval granted or returned | Owner | In-app |
| Proposal opened / not opened after 3 days / expiring in 5 days | Owner | In-app |
| Proposal accepted / changes requested | Owner, Sales Manager, Chief Auditor (if flagged) | In-app + email |
| Stale opportunity (14 days) | Owner | Weekly digest |

### 4.11 Entities (Module A)

| Entity | Key fields |
|---|---|
| Opportunity *(extends v0.6.1 §27.7)* | organization_id, name, source, partner_id, segment, trigger (manual or auto values §4.2), trigger_ref, products_of_interest[], est_value, close_date, owner_id, stage, lost_reason, bant (json), competitors[], independence_flag, independence_reason, next_step, next_step_due, needs_ca_approval, created_by |
| OpportunityContact | opportunity_id, name, title, email, phone, contact_role |
| Activity | opportunity_id, type, at, summary, outcome, next_step, mail_thread_id, by |
| ScopingQuestion *(reference)* | bank_version, code, section, label, help, type, options[], client_visible, internal_only, order |
| ScopingQuestionnaire | opportunity_id, bank_version, version, mode (`recorded`/`sent`/`hybrid`), status (`draft`/`sent`/`client_in_progress`/`client_submitted`/`locked`), locked_by, locked_at |
| ScopingAnswer | questionnaire_id, question_code, value (json), source, confidence, note, answered_by (user or contact), answered_at |
| QuestionnaireSend | questionnaire_id, contact_id, question_codes[], mail_recipient_id, due_on, reminders_sent, status |
| MappingRule | catalog_version, code, inputs (json: question codes + conditions), line_code, qty_formula (json), reason_template, active, approved_by |
| CatalogVersion | version (increments per saved batch), saved_by, saved_at, reason, source (`grid`/`bulk`/`import`), change_count |
| CatalogChange | catalog_version_id, item_code, field, old_value, new_value, effective_from, reason, changed_by, changed_at, confirmed_by (when second check is on) |
| PriceSuggestion | item_code (or new), suggested_by, field, suggested_value, reason, status (`open`/`accepted`/`declined`), decided_by, decided_at |
| CatalogItem | catalog_version_id, code, product, name, description, pricing_unit, billing, basis (`$`/`%`), periods_per_year, low, list, high, price_status (`existing`/`proposed`/`approved`), deliverables (text, client-facing), sellable_status, delivery_mode, platform_feature_ref, included_quantities (json), remediation_of[], engagement_type, entitlement_key, notes, status (`active`/`retired`), pending_change_id, updated_by, updated_at |
| PackageTemplate | name, catalog_version_id, lines (json: code + default qty) |
| Estimate | opportunity_id (optional), name, version, package, lines (json: code, description, deliverables_override, qty, list_price, edited_price, edited_by, edited_at, unit_price_used, catalog_version), discount_recurring_pct, term, data_region, totals (json), created_by, saved_by, saved_at, converted_proposal_id |
| Proposal | opportunity_id, estimate_id (optional), version, questionnaire_version, catalog_version, package, status (`draft`/`awaiting_approval`/`approved`/`sent`/`viewed`/`changes_requested`/`accepted`/`expired`/`superseded`), valid_until, discount_recurring_pct, terms (json), sections (json), totals (json: one_time, recurring_y1, discount, y1_total, arr), sent_at, file_ids (pdf, docx) |
| ProposalLine | proposal_id, catalog_code, description, deliverables_text (copied from catalog, editable per proposal), qty, list_price, override_price (the edited price), edited_by, edited_at, unit_price_used, periods_per_year, line_value, source (`rule`/`package`/`manual`), rule_code, reason, removed_reason |
| ApprovalRequest | proposal_id, rule (`P-1`…`I-4`), line_ids[], requested_by, approver_role, approver_id, status (`pending`/`approved`/`returned`), note, decided_at |
| Acceptance | proposal_id, name, title, email, authorised_confirmed, po_number, po_file_id, ip, user_agent, accepted_at |
| Order | organization_id, proposal_id, opportunity_id, status (`open`/`active`/`completed`/`cancelled`), start_on, end_on, billing_contact |
| OrderLine | order_id, catalog_code, qty, unit_price, periods_per_year, start_on, end_on, engagement_id, subscription_id |

### 4.12 Screens — Set A (Sales module)

| # | Screen | Shell | Roles | Key elements |
|---|---|---|---|---|
| SM-01 | Sales home `/sales` | F | Sales Officer, Sales Manager | KPI tiles (open pipeline $, weighted, proposals out, won this quarter), pipeline by stage, my tasks and next steps, approvals waiting on me, stale deals, auto-opportunities new this week |
| SM-02 | Opportunities `/sales/opportunities` | F | Sales roles, Chief Auditor (read) | Grid: company, prospect/client badge, source, trigger, products, value, stage, owner, next step, independence flag; filters; bulk (assign, change stage, export); row menu; **Log opportunity** |
| SM-03 | Log opportunity (dialog) | F | Sales Officer | Company search with duplicate check, new prospect fields, contacts, source and partner, segment, trigger, products, value, close date, next step |
| SM-04 | Opportunity record `/sales/opportunities/:id` | F | Sales roles | Header with stage bar; tabs: overview (BANT, contacts, trigger), activity timeline with log call/email/meeting, questionnaire status, proposals and versions, independence panel |
| SM-05 | Scoping call — record answers `/sales/opportunities/:id/scoping` | F | Sales Officer | Section nav A–H with completion, question cards (ticks, counts, unknown, confidence), live **Suggested line items** panel with reasons and running estimate |
| SM-06 | Send questionnaire to client (dialog) | F | Sales Officer | Contact, sections and questions (internal ones locked off), due date, reminders, message preview, send from my mailbox |
| SM-07 | Client questionnaire `/q/:token` | Phone web | Client contact | Futran-branded, section progress, plain-language questions, unknown option, save and continue, forward to colleague, submit |
| SM-08 | Review answers `/sales/opportunities/:id/scoping/review` | F | Sales Officer | Side-by-side rep vs client answers, conflicts to resolve, unknowns and their effect, version, **Lock and build proposal** |
| SM-09 | Proposal builder `/sales/proposals/:id` | F | Sales Officer, Sales Manager | Package picker; line table (code, item, source/reason, qty, list, override, unit used, periods, value, status badges); totals; discount; terms; guardrail and independence warnings; approvals needed; version selector and diff |
| SM-10 | Proposal preview and send `/sales/proposals/:id/send` | F | Sales Officer | Document preview by section, export PDF/DOCX, email composer, acceptance link expiry, send log |
| SM-11 | Approvals `/sales/approvals` | F | Sales Manager, Pricing Approver, Chief Auditor | Queue by rule; selected request with lines, prices vs catalog, margin note, independence context; approve or return with note |
| SM-12 | Proposal acceptance `/p/:token` | Public web | Client contact | Proposal summary and full document, pricing, terms, **Accept** form, **Request changes** |
| SM-13 | Won — hand off to delivery `/sales/opportunities/:id/handoff` | F | Sales Officer, Chief Auditor | Checklist of records created (client, order, engagement drafts, subscription, hours banks, partner commission), each with status and link; delivery team and independence confirmation |
| SM-14 | Master price list `/staff/admin/catalog` | F | CEO and President (edit); Futran Admin, Chief Auditor, Sales roles (view, export, suggest) | Editable grid with a **Deliverables** column (summary + Read all), full deliverables editor in the side panel, inline edit, changed-cell highlights, Save with reason, add / duplicate / retire, bulk edit by % or amount, validation, effective date, side panel, row history, change log, Excel import (preview) and export; tabs for mapping rules, packages, question bank and proposal templates |
| SM-15 | Estimator `/sales/estimate` | F | Sales Officer, Sales Manager | Package picker, add items by code or search, **What the client gets** per line (expand or show all), editable qty, price and description per line (Edited badge, list price shown, Reset to list price), Low–High range, status badges, discount, term, region, guardrail warnings, totals, save to opportunity, convert to proposal |

---

## 5. Module B — Commercial and service gaps

### B1. Plans, entitlements, usage and billing export (G-01)

- A client's commercial position = active **Order lines** → **Subscription** (v0.6.1 F3 entity, extended) → **Entitlements**.
- Entitlement keys (from `CatalogItem.entitlement_key`): `ai_systems` (tier ceiling), `seats`, `alert_packs` (state count), `litigation_briefings`, `vault_gb`, `retention_years`, `legal_holds`, `tracing_systems`, `agents_protected`, `agent_actions_month`, `approver_seats`, `questionnaires_year`, `advisor_hours`, `trust_center`, `api_access`.
- **Usage** is measured daily from platform data: AI systems in the register (not retired), active client users with logins, alert jurisdictions, vault storage, tracing systems, AgentWarden agents and actions (B9 sync), questionnaires processed.
- **Enforcement is soft** in Release 2: at 90% of a limit the CAICO and the account owner are told and an `entitlement_limit` opportunity is created; at 100% the platform keeps working, shows "over plan" to Futran and adds the overage to the billing export. Hard limits only for `api_access` and `trust_center` (feature on/off).
- **Renewals:** each recurring order line has an end date; a `renewal_due` opportunity is created 90 days before.
- **Plan settings:** data region (`us` / `eu` / `in`, set at tenant creation, cannot move without a migration ticket), support level, onboarding fee waived (yes/no).
- **Billing export:** monthly CSV and API pull per client: order lines due this period, overages, hours used beyond banks, partner commissions due. Columns match the accounting system import (open question R2-Q3). No invoices are created in the platform.

| Entity | Key fields |
|---|---|
| Subscription *(extends v0.6.1 F3)* | organization_id, plan (`audit_only`/`monitor`/`monitor_plus`), tier, order_id, start_on, end_on, auto_renew, data_region, support_level |
| Entitlement | subscription_id, key, limit, source_order_line_id |
| UsageRecord | organization_id, key, measured_on, value |
| BillingExportRun | period, run_by, run_at, file_id, rows, status |

### B2. Engagement commercials and change orders (G-02)

- New **Commercial** tab on the engagement: order and order lines, fee, billing milestones (e.g. 50% at sign-off 1, 50% at final report), deliverables list from the catalog lines, change orders.
- **Change order** when scope grows: add AI system (A-03), add jurisdiction (A-04, L-08), extra documents (A-07), extra readout (A-13), extra vendors (A-08). The auditor or Engagement Manager raises it from the scope screen; priced from the catalog; Sales Officer and Pricing Approver rules apply; the client CAICO approves in the platform; only then does the scope change take effect. This hooks the existing rule "adding a system after initiation requires Engagement Manager approval" (v0.6.1 §18.3).
- Answers v0.6.1 open Q5: fee and value fields live in the platform, visible to Chief Auditor, Engagement Manager, Sales roles and Admin; **never to Auditors**, so fee does not influence fieldwork.

| Entity | Key fields |
|---|---|
| EngagementCommercial | engagement_id, order_id, fee_total, milestones (json) |
| ChangeOrder | engagement_id, ref (`CO-001`), reason, lines (json: code, qty, price), raised_by, status (`draft`/`awaiting_futran_approval`/`awaiting_client`/`approved`/`rejected`), client_approved_by, approved_at, scope_change_ref |

### B3. Time and hours (G-03)

- Futran staff log time against an engagement, a retainer or an hours bank: date, hours, activity (`fieldwork`, `report`, `remediation_retest`, `policy_drafting`, `advisory`, `incident_response`, `litigation_support`, `training`), billable (yes/no), note.
- **Hours banks** (M-13): purchased hours, used, remaining, expiry; alert at 80% used; overage priced from the catalog.
- **Retainers** (M-12, X-01): standing monthly fee plus activation. Activating the incident retainer (M-12b) opens an incident engagement and starts billable time at the catalog hourly rate.
- **Margin view** for Chief Auditor and Sales Manager: hours × standard cost vs fee per engagement, to validate proposed prices after the first 3–5 engagements (as the price list notes say).

| Entity | Key fields |
|---|---|
| TimeEntry | user_id, engagement_id or hours_bank_id or retainer_id, date, hours, activity, billable, note, approved_by |
| HoursBank | organization_id, order_line_id, hours_purchased, expires_on |
| Retainer | organization_id, order_line_id, type (`incident_response`/`fractional_officer`/`compliance`), monthly_fee, hourly_rate, status |
| StandardCost | role, cost_per_hour, effective_from |

### B4. Client hierarchy (G-04)

- `Organization.parent_id` and `relationship` (`subsidiary`, `end_client`, `customer_of_vendor`).
- **Staffing chains (L-09):** a staffing firm lists its end-clients; each LL144 audit, notice and public summary can be scoped to one end-client; pricing counts end-clients.
- **Vendor-sponsored audit (L-10):** an HR-tech vendor client lists the customers whose data is pooled (5.1a.04 `pooled_same_aedt`); customers get read-only access to the summary that names them, if the vendor allows.
- **Groups:** a parent sees roll-up dashboards of its subsidiaries' registers if each subsidiary's CAICO consents.
- Tenancy rules (v0.6.1 §3) are unchanged: each child is its own tenant; sharing is explicit and logged.

### B5. Manual discovery import (G-05)

The bridge until Phase 3 connectors (v0.6.1 F2). A Futran consultant or the Client Admin uploads standard admin exports; the platform turns them into `DiscoveredTool` rows (same entity and confirm/dismiss flow as F2, `signal = manual_import`), so Phase 3 connectors replace the import without changing the data.

| Export | Source | Parsed into |
|---|---|---|
| Copilot licence and usage report (CSV) | Microsoft 365 admin center | Copilot licences, active users by department |
| Enterprise applications and consents (CSV) | Microsoft Entra ID | AI apps with sign-in or consent |
| Third-party app access (CSV) | Google Admin console | AI apps with OAuth access |
| Gemini usage report (CSV) | Google Admin console | Gemini active users by app |
| Gemini Enterprise apps and agents (list) | Google Cloud console | Agents (feeds G-09) |
| Expense export (CSV) | Any expense system | Paid AI subscriptions |
| Proxy / CASB log summary (CSV) | Netskope, Zscaler, others | Traffic to AI domains |

- Column mapping step with saved presets per export type; an AI vendor dictionary (Futran-maintained) matches names to vendors.
- Findings that create opportunities (`discovery_finding`): Copilot licences found (X-04), agents found (AA/AW), undeclared paid AI tools, EU-scoped high-risk system (X-03).
- Each import is an evidence item (v0.6.1 §9.6) with SHA-256.

### B6. Service template library and new engagement types (G-06)

`Engagement.type` gains: `vendor_due_diligence`, `vendor_sponsored_audit`, `ll144_applicability`, `copilot_readiness`, `eu_ai_act_readiness`, `iso42001_readiness`, `ma_due_diligence`, `agent_assurance`, `training_workshop`, `advisory_retainer`.

Each type has a **service template**: question bank (reusing the v0.6.1 §18.1 engine), checklists, deliverables, default stages, report template and catalog codes. Futran Admin maintains them; the Chief Auditor approves a template version before use.

| Template | Content to seed (owner) |
|---|---|
| LL144 applicability | The 8-case staffing applicability map (*LL144_8Case_Staffing_Applicability_Map.xlsx*), candidate-notice 10-business-day checklist, public summary checklist (FATF) |
| Copilot readiness | Microsoft's Pilot / Deploy / Operate oversharing blueprint mapped to checks: oversharing report, sensitivity labels, DLP for Copilot, restricted content discovery, audit logging, usage policy, user training (Microsoft practice) |
| EU AI Act readiness | Applicability, role (provider / deployer), classification, deployer duties (Art. 4, 14, 26, 27, 50), provider duties (Art. 9–15, 17, 43, 72), Annex IV technical documentation list, Art. 73 incident reporting; dates: Annex III high-risk 2 Dec 2027, Annex I 2 Aug 2028 (Regulation (EU) 2026/1744) (FRD) |
| ISO/IEC 42001 readiness | Clauses 4–10 and Annex A controls as checklist items with evidence (FATF) |
| Vendor due diligence | v0.6.1 §9.2 questions as a standalone engagement, one section per vendor |
| M&A due diligence | Target AI inventory, regulatory exposure, open litigation, red-flag summary |
| Board readout pack | Export from a signed report: one-page summary, heat map, top 5 findings, roadmap, as PDF and PPTX |

### B7. Copilot readiness workspace (G-07)

- Opens on a `copilot_readiness` engagement. Inputs: G-05 imports (Copilot licences and usage) plus uploaded Purview oversharing / data risk assessment and SharePoint Advanced Management permission reports (CSV).
- **Site risk list:** site, owner, sensitivity label coverage, sharing scope (everyone / org / specific), sensitive item count, last activity, risk (High / Medium / Low), action (`restrict_discovery`, `fix_permissions`, `apply_label`, `archive`, `accept`), owner, status.
- **Rollout waves:** wave name, groups, date, readiness checks passed, go / hold.
- **Controls checklist** from the G-06 template with evidence.
- Output: readiness report and the Copilot entry in the client's AI register (v0.6.1 R1) with its laws and roles.

### B8. EU AI Act conformity workspace (G-08)

- Opens on an `eu_ai_act_readiness` engagement or from an AI system with EU geography.
- Per AI system: EU exposure basis, **role** (provider, deployer, importer, distributor), **classification** (prohibited, high-risk Annex III category, high-risk Annex I, transparency-only, minimal) with reasoning and legal-review flag, applicable articles (computed), deadline (computed from classification), obligations checklist with evidence, **Annex IV technical documentation tracker** (providers), **fundamental-rights impact assessment** (deployers where Art. 27 applies), Art. 50 notices, Art. 73 incident readiness.
- Classification is signed off by the partner law firm reviewer (role `Legal/Compliance Reviewer`, v0.6.1 §18.3) before the report is issued.
- Feeds the regulatory master (v0.6.1 §25) as the international law sheet (answers open Q3): EU AI Act requirements are seeded as `Requirement` rows.

### B9. Agent Assure records and AgentWarden licence sync (G-09)

Agent Assure and AgentWarden stay separate products. AI Governix records their results and licences against each agent in the register.

- **Agent Assure record per agent and release:** gold evaluation set (version, size, owner), **15-point pre-deploy check** (items seeded from the Agent Assure methodology; FATF to supply), red-team scenario results (scenario, outcome, severity), pass / conditional / fail, assurance letter (file, signed by, date), re-certification trigger on model or version change (reuses v0.6.1 F8 reassessment triggers).
- The register field `agentassure_status` (v0.6.1 §24.5) is now computed from the latest record.
- **AgentWarden licence sync:** daily pull (API, or CSV until the API exists) of protected agents, autonomy level, monthly action counts, approver seats, deployment (SaaS / VPC). Feeds G-01 usage for AW-02, AW-03, AW-05.
- Independence rule I-2 applies when Futran also audits the agent.

| Entity | Key fields |
|---|---|
| AssuranceRun | ai_system_id, release_ref, eval_set_version, eval_set_size, checks (json: item, result, note), redteam (json), outcome, letter_file_id, signed_by, signed_on, next_due_trigger |
| WardenLicenceSnapshot | organization_id, ai_system_id, autonomy, actions_month, approvers, deployment, synced_at |

### B10. Evidence vault and retention (G-10)

- Per-client **retention tier** (3 / 7 / 10 years; default 7 as v0.6.1 §15) and storage used vs entitlement.
- **Legal hold:** name, matter, scope (engagements, systems, date range), set by Chief Auditor on client request, blocks deletion until released; each hold is billable (M-06e).
- Retention countdown list: items due for deletion in the next 90 days, with hold status.
- Storage measured daily for G-01.

| Entity | Key fields |
|---|---|
| RetentionPolicy | organization_id, years, effective_from, set_by |
| LegalHold | organization_id, name, matter_ref, scope (json), set_by, set_at, released_at |

### B11. Partners and referrals (G-11)

- Partner records: name, type (`law_firm`, `ats_vendor`, `hr_tech`, `cloud_partner`, `audit_firm`, `other`), agreement file, commission rule (e.g. 15% of first-year contract value), contact, status.
- An opportunity may carry a partner; on win a `Commission` row is created from the accepted proposal's first-year value.
- Bar rules for law firms: commission rules are disabled for `law_firm` partners (referrals both ways, no fees), shown as a note.
- Outbound referrals: Futran records work referred to a partner (e.g. legal opinion), for relationship tracking.

| Entity | Key fields |
|---|---|
| Partner | name, type, agreement_file_id, commission_rule (json), contact, status |
| Commission | partner_id, opportunity_id, order_id, base_value, rate, amount, status (`due`/`paid`/`void`), due_on |
| Referral | partner_id, direction (`in`/`out`), organization_id, opportunity_id, note, at |

### 5.12 Screens — Set B (gaps)

| # | Screen | Shell | Roles | Key elements |
|---|---|---|---|---|
| G-01 | Plans, entitlements and usage `/staff/clients/:id/plan` | F | Futran Admin, Sales Manager, Chief Auditor | Plan and tier, data region, renewal date, entitlement bars (used vs limit), over-plan flags, order lines, billing export |
| G-02 | Engagement commercials `/e/:id/commercial` | F | Chief Auditor, Engagement Manager, Sales | Order lines, fee and milestones, deliverables, change orders list and editor, client approval status |
| G-03 | Time and hours `/staff/time` | F | All Futran staff; Chief Auditor and Sales Manager (margins) | Weekly timesheet, hours banks and retainers with balance, margin by engagement |
| G-04 | Client hierarchy `/staff/clients/:id/entities` | F (and C for parent CAICO) | Futran Admin, CAICO | Tree of parent, subsidiaries and end-clients, relationship, consent to roll-up, LL144 scope per end-client |
| G-05 | Discovery import `/e/:id/discovery/import` | F (and C for Client Admin) | Auditor, Client Admin | Export type, upload, column mapping, preview, matched vendors, discovered tools with confirm / dismiss, opportunities raised |
| G-06 | Service templates `/staff/admin/templates` | F | Futran Admin, Chief Auditor | Engagement types and template versions, sections, checklists, deliverables, linked catalog codes, approve |
| G-07 | Copilot readiness `/e/:id/copilot` | F (client view C) | Auditor, Microsoft practice, CAICO | Licence and usage summary, site risk list with actions, rollout waves, controls checklist |
| G-08 | EU AI Act conformity `/e/:id/eu-ai-act` | F | Auditor, Legal/Compliance Reviewer | Systems with role, classification and deadline; per-system obligations checklist; Annex IV tracker; FRIA status; legal sign-off |
| G-09 | Agent assurance `/register/:id/assurance` | C and F | CAICO, Auditor | Release history, 15-point check results, red-team results, assurance letter, AgentWarden licence status |
| G-10 | Evidence vault and retention `/staff/clients/:id/vault` | F | Chief Auditor, Futran Admin | Storage used vs plan, retention tier, legal holds, deletion countdown |
| G-11 | Partners `/staff/partners` | F | Sales Manager, Futran Admin | Partner list, agreement, commission rule, referred opportunities, commissions due and paid |

---

## 6. Touch points with v0.6.1 (adopt when ready; no edits made to v0.6.1)

| v0.6.1 item | Release 2 need |
|---|---|
| §4.1 roles, §27.5 Sales Team | Rename to Sales Officer; add Sales Manager, Pricing Approver and Price List Owner (CEO, President) |
| §9.1 `Organization.status` | Add `prospect`; add `parent_id`, `relationship` (B4) |
| §9.2 `Engagement.type` | Add the ten types in B6 |
| §27.7 `Opportunity` | Extend with §4.11 fields and new triggers |
| F2 `DiscoveredTool.signal` | Add `manual_import` (B5) |
| F3 `Subscription` | Extend per B1; add `Entitlement`, `UsageRecord` |
| F7 independence check | Extend to rules I-1 to I-3 |
| §18.3 add-system rule | Route through change orders (B2) |
| §24.5 `agentassure_status` | Computed from B9 |
| §25 regulatory master | EU AI Act seeded via B8 |
| Open questions answered | Q5 (fees in platform, hidden from Auditors), Q8 (prices in catalog), Q20 (tracing plans per catalog M-11a–c), Q23 (prospects allowed), Q3 (EU sheet via B8) |

---

## 7. Delivery order within Release 2

| Step | Contents | Depends on |
|---|---|---|
| R2.1 Price list, estimator and opportunities | SM-14 editable grid and import, SM-15 Estimator, SM-01 to SM-04, roles | Phase 1 auth and email |
| R2.2 Scoping | SM-05 to SM-08, mapping rules | R2.1 |
| R2.3 Proposals | SM-09 to SM-13, approvals, acceptance, handoff | R2.2, G-01 entities |
| R2.4 Commercial core | G-01, G-02, G-03 | R2.3 orders |
| R2.5 Service gaps | G-05, G-06, G-07, G-08, G-09 | Phase 1 register and engagements |
| R2.6 Remaining | G-04, G-10, G-11 | R2.4 |

R2.1–R2.3 give sales a working desk first; R2.5 can run in parallel with a second team.

---

## 8. Open questions (Release 2)

1. **R2-Q1** Sales Manager discount limit: 15% as in the price list, or lower?
2. **R2-Q2** E-signature on acceptance: click-to-accept only, or DocuSign/Adobe Sign (same decision as v0.6.1 Q2)?
3. **R2-Q3** Accounting system for the billing export (QuickBooks, Zoho Books, NetSuite, other)?
4. **R2-Q4** Should the client questionnaire link show indicative price ranges? (Default no.)
5. **R2-Q5** Who owns the scoping question bank: Sales Manager or FATF?
6. **R2-Q6** CRM: is AI Governix the system of record for sales, or should it sync with HubSpot or Salesforce?
7. **R2-Q7** Agent Assure 15-point check content and AgentWarden API: available for seeding, and when?
8. **R2-Q8** Hard vs soft entitlement limits after Release 2?
9. **R2-Q9** Standard cost per hour by role for margin views (Finance to supply)?
10. **R2-Q10** Prospects' data retention if lost: delete after 24 months unless reopened?
11. **R2-Q11** Turn on the second-person check (CEO and President confirm each other's large price changes, §4.9)? If yes, at what % change?
