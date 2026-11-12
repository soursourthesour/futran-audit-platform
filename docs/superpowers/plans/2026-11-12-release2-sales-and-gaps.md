# Release 2 — sales module and commercial gaps: implementation plan

> For agentic workers: build each workstream test-first (superpowers:test-driven-development). This plan fixes ownership, shared names and the user's decisions so eight parallel workstreams fit together. The spec is the authority; this plan is its argument.

**Spec:** `docs/spec/Futran_Release2_Sales_and_Gaps_Spec_v0.4.md` (v0.4, 11 Nov 2026). **Screens:** `docs/reference/release2/*.dc.html` (SM-02 … SM-15, G-01 … G-11; open in a browser or read the markup; `Main.dc.html` is the index) and `SM14-Master-price-list-v0.4-bundle.html` (the v0.4 tweak of SM-14 with the deliverables column). Existing platform specs (v0.3, v0.6.1 mapping in the Build Schematic) still bind where Release 2 is silent.

## User's decisions (11 Nov 2026)

1. **Build all of Release 2 at once** (Module A SM-01 to SM-15 and Module B G-01 to G-11).
2. **Source files are not available.** The master price list workbook (93 items) and the Sales Collateral scoping questionnaire are not in hand. Seed the **sample items and questions shown in the screen designs** as demo/starter data, clearly editable; never invent prices or questions beyond the designs and the spec. The Price List Owner loads the real workbook through SM-14's Excel import (preview, then save with reason); the question bank is editable (SM-14 tab). Write the importer against the column list in spec §4.9 "Load and initial values".
3. **Open questions R2-Q1 to Q11 take these defaults**, each a setting or data the user can change later: Sales Manager discount limit 15%; click-to-accept only; billing export as a generic CSV; no price ranges on the client questionnaire; the Sales Manager owns the question bank; the platform is the sales system of record (no CRM sync); Agent Assure 15-point check items left blank for FATF to fill in (editable list); soft entitlement limits (hard only for `api_access` and `trust_center`); standard cost per hour entered by the Futran Admin; lost prospects deleted after 24 months unless reopened (daily job, logged); CEO/President second check off.
4. **No reversibility work needed** — no feature switch. Still: additive migrations only, nothing in existing data changed.
5. **Naming:** the product is the **Futran Audit Platform** everywhere users see it. The spec's "AI Governix" is never shown.

## Global constraints

- Tenant from the session only; every endpoint calls `authorize`; audit log append-only; Python >= 3.11; plain professional English, sentence case.
- No new Python dependencies (laptop never reinstalls). PDF via xhtml2pdf/reportlab, DOCX via python-docx, XLSX via openpyxl — all installed.
- Migrations additive only (new tables, nullable columns, new enum *values* stored as strings), exactly one Alembic head: rebase and re-point `down_revision` before pushing.
- The user tests on real data (client "test", demo clients). Upgrade must not change existing rows.
- Phone width 375 px for client-facing screens (SM-07, SM-12, G-04 client view, G-07 client view, G-09); Futran screens desktop-first but no sideways page scroll.
- Push after every commit: `git fetch origin build/v1:refs/remotes/origin/build/v1 && git rebase origin/build/v1 && git push origin HEAD:build/v1`. Resolve rebase conflicts by keeping both sides' intent — never drop another workstream's change. `nav.ts`, `policy/matrix.py`, `models_registry.py`, `routers_registry.py`, `notifications/jobs.py` and the demo seed are shared: add your own lines only.
- Uploaded files (CSV, XLSX) go through the existing guards (`app/core/xlsx_guard.py`, `csvsafe`); generated XLSX/CSV are formula-safe.
- Every new client-facing token link (SM-07 questionnaire, SM-12 acceptance) follows the existing token-link pattern (hashed, expiring, single purpose, rate limited, no login).

## Shared names (the contract between workstreams)

**Roles** (owned by R2): existing key `sales` keeps its key and is labelled **Sales Officer**; new keys `sales_manager`, `pricing_approver`, `price_list_owner`. A person can hold several. Users screen offers them (Futran Admin assigns). Nobody approves their own proposal.

**Catalog** (R1, package `app/catalog`): `CatalogItem`, `CatalogVersion`, `CatalogChange`, `PriceSuggestion`, `PackageTemplate`, `Estimate` (fields per spec §4.11). Functions other workstreams use:
- `catalog.service.get_item(db, code, *, include_retired=False) -> CatalogItem | None`
- `catalog.service.current_version(db) -> int`
- `catalog.service.items_by_codes(db, codes) -> dict[str, CatalogItem]`
- `CatalogItem.sellable_status` in `available | manual_delivery | roadmap`; `price_status` in `existing | proposed | approved`; `basis` `$ | %`.

**Opportunities** (R2, existing package `app/sales`): extends `Opportunity` per spec §4.11; adds `OpportunityContact`, `Activity`; `Organization.status = "prospect"` (prospects hidden from client lists, no users, no tenant data). `sales.independence.flag_for(db, org_id) -> tuple[bool, str]`. New triggers recognised by the opportunities screen: `renewal_due`, `change_order`, `entitlement_limit` (R5), `discovery_finding` (R6a). Existing automatic triggers, the opportunity scan and Chief Auditor approval keep working; `/opportunities` redirects to `/sales/opportunities`.

**Scoping** (R3, package `app/scoping`): `ScopingQuestion`, `ScopingQuestionnaire`, `ScopingAnswer`, `QuestionnaireSend`, `MappingRule`.
- `scoping.service.suggest_lines(db, questionnaire_id) -> list[dict]` (keys `code`, `qty`, `reason`, `rule_code`).
- `scoping.service.lock(db, questionnaire_id, actor) -> ScopingQuestionnaire` (new version on unlock).

**Proposals** (R4, package `app/proposals`): `Proposal`, `ProposalLine`, `ApprovalRequest`, `Acceptance`. On acceptance it calls `commercial.handoff.create_from_acceptance(db, proposal, acceptance, actor)` (R5). Independence rules I-1 to I-4 and pricing rules P-1 to P-8 live here; I-3 also enforced when a person is added to `EngagementTeam` (R4 owns that check in `app/engagements/team.py`, alongside the existing policy-author check).

**Commercial** (R5, package `app/commercial`): `Order`, `OrderLine`, `Entitlement`, `UsageRecord`, `BillingExportRun`, `EngagementCommercial`, `ChangeOrder`, `TimeEntry`, `HoursBank`, `Retainer`, `StandardCost`; extends the existing monitoring `Subscription` (F3) with spec B1 fields. `commercial.handoff.create_from_acceptance(...) -> Handoff` builds the SM-13 records (client from prospect, order, engagement drafts, subscription/entitlements, hours banks/retainers, commission via R7, notifications). Fee and value fields are never visible to Auditors.

**Delivery services** (R6a: `app/servicetemplates`, `app/assurance`, discovery import in `app/connectors`; R6b: `app/copilot_readiness`, `app/euaiact`). `Engagement.type` gains the ten values in spec B6 (defined once in R6a's `servicetemplates.types.ENGAGEMENT_TYPES`; the New Client wizard and engagement screens accept them). `DiscoveredTool.signal` gains `manual_import`.

**Org, vault, partners** (R7: `app/hierarchy`, `app/vault`, `app/partners`): `Organization.parent_id`, `relationship`; `RetentionPolicy`, `LegalHold`; `Partner`, `Commission`, `Referral`. `partners.service.commission_for_win(db, opportunity, order, first_year_value) -> Commission | None` (law-firm partners never get a commission).

## Workstreams

| WS | Worktree | Screens | Notes |
|---|---|---|---|
| R1 price list and estimator | `/home/claude/wt-r1` | SM-14 (grid, side panel, history, change log, versions, effective dates, bulk edit, validation, add/duplicate/retire, Excel import with preview and export, suggest a change, second-check setting; tabs for mapping rules, packages, question bank, proposal templates — R1 builds the tab shell and packages; R3 fills the mapping-rules and question-bank tabs; R4 fills proposal templates), SM-15 Estimator | Seed the design's sample items and the four packages. Price List Owner edits; Futran Admin, Chief Auditor, sales roles view/export/suggest. |
| R2 sales desk | `/home/claude/wt-r2` | SM-01 Sales home, SM-02 Opportunities, SM-03 Log opportunity, SM-04 Opportunity record | Roles; prospects with duplicate check; BANT; contacts; activities (emails through the rep's own mailbox, replies thread back); stale after 14 days and weekly digest; independence flag; nav "Sales" group (Sales home, Opportunities, Estimator, Approvals, Price list, Partners — add the lines for all of them; routes not yet built show the platform's not-found page until their workstream lands). |
| R3 scoping | `/home/claude/wt-r3` | SM-05 record on the call, SM-06 send, SM-07 client questionnaire (phone, token link, forward to colleague, reminders day 3 and 7), SM-08 review and lock | Question bank as data (starter questions from the designs plus every code the spec's mapping rules use), internal-only questions never on the client link, answer source/confidence/conflicts, mapping rules engine with the spec §4.5 rules seeded (rules pointing to codes not in the catalog are flagged, not dropped); suggested line items panel with reasons and running estimate. |
| R4 proposals | `/home/claude/wt-r4` | SM-09 builder, SM-10 preview and send, SM-11 approvals, SM-12 public acceptance | Versions (immutable once sent) with diff; price precedence; %-items; sections from deliverables; PDF and DOCX; send from the rep's mailbox with acceptance link; view tracking (link opened); P-1 to P-8, I-1 to I-4; acceptance with authority tick, PO number and upload; calls R5 handoff. |
| R5 commercial core and handoff | `/home/claude/wt-r5` | SM-13 handoff, G-01 plans/entitlements/usage, G-02 engagement commercials and change orders, G-03 time and hours | Daily usage measurement; soft limits (90% → notify + `entitlement_limit` opportunity); renewals (`renewal_due` 90 days before); monthly billing export CSV; change orders hooked to the existing add-system rule; client CAICO approves change orders; time entries, hours banks (80% alert), retainers, margin view, standard cost. |
| R6a service templates, discovery import, agent assurance | `/home/claude/wt-r6a` | G-05 manual discovery import, G-06 service templates and engagement types, G-09 agent assurance and AgentWarden licence sync | G-05 extends the existing connectors CSV path with the spec's export types, column mapping presets and `discovery_finding` opportunities; each import is evidence with SHA-256. G-06 at `/staff/admin/service-templates` (the existing `/admin/templates` document templates screen stays). G-09 15-point check list editable, items blank by default; AgentWarden sync by CSV until an API exists; `agentassure_status` computed. |
| R6b Copilot readiness and EU AI Act | `/home/claude/wt-r6b` | G-07 Copilot readiness workspace, G-08 EU AI Act conformity workspace | G-07 imports (Copilot licence/usage, Purview oversharing, SharePoint permission CSVs), site risk list, rollout waves, controls checklist, readiness report, register entry. G-08 per-system role, classification with legal sign-off by the Legal/Compliance Reviewer, computed articles and deadlines (Annex III high-risk 2 Dec 2027, Annex I 2 Aug 2028 per spec B6), obligations checklist, Annex IV tracker, FRIA; EU AI Act requirements seeded into the law library only where the existing library lacks them (check first; never duplicate). Verify dates against the spec, not memory. |
| R7 hierarchy, vault, partners | `/home/claude/wt-r7` | G-04 client hierarchy, G-10 evidence vault and retention, G-11 partners | G-04: parent/subsidiary/end-client tree, roll-up only with each subsidiary CAICO's consent, LL144 scope per end-client; tenancy unchanged (each child its own tenant). G-10: retention tiers 3/7/10 (default 7), legal holds that block deletion (check the existing retention/deletion jobs honour them), 90-day countdown, storage metering for G-01. G-11: partners, commissions (law firms never), referrals in/out. |

## Review focus

1. Pricing integrity: the master never changes from an estimate or proposal; a sent proposal never changes; approvals cannot be bypassed (no self-approval, every rule checked server-side at send).
2. Public token pages (SM-07, SM-12): no data beyond what is meant for that contact; internal questions and prices never leak; tokens expire.
3. Independence: I-1 to I-4 enforced server-side; fee data never visible to Auditors.
4. Prospects never appear as clients, never get users or tenant data, and convert cleanly on win.
5. Existing features (opportunities, opportunity scan, monitoring subscription, connectors, engagements, templates) keep working on the user's existing data.
