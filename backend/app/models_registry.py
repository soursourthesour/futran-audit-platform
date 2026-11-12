"""Import every domain's models so `Base.metadata` is complete (Alembic, tests)."""
import importlib

DOMAINS_WITH_MODELS: list[str] = ["tenancy", "audit_log", "auth", "mail", "invitations", "engagements", "reference", "laws", "questionnaire", "files", "initiation", "signoffs", "notifications", "governance", "attestation", "inventory", "systems", "findings", "docrequests", "scoring", "reports", "remediation", "register", "regmaster"]

for _mod in DOMAINS_WITH_MODELS:
    importlib.import_module(f"app.{_mod}.models")

# v0.6 WS-D domains: litigation, Sales Team opportunities, refresh pipeline, staff and client alerts
for _mod in ["litigation", "sales", "refresh", "staffalerts", "clientalerts"]:
    importlib.import_module(f"app.{_mod}.models")

# v0.6 WS-E: tracing add-on (subscriptions, incidents and their deadlines, action traces)
importlib.import_module("app.tracing.models")

# wave 3 WS-J: integrations and AI discovery (F2), continuous monitoring (F3)
for _mod in ["monitoring", "connectors"]:
    importlib.import_module(f"app.{_mod}.models")

# Wave 3 WS-G: AI interactions, obligations, extracted document text, questionnaires and the answer library (§21)
importlib.import_module("app.ai.models")
importlib.import_module("app.ai.connection")  # 11-03 F1: the platform's AI provider connection

# Wave 3 WS-H: regulatory change alerts (F4) and impact assessment with reassessment triggers (F8)
for _mod in ["regupdates", "impact"]:
    importlib.import_module(f"app.{_mod}.models")
# Its session listeners (systems added in this transaction are not changes) must be registered before the first request,
# not when a register edit first imports the module.
importlib.import_module("app.impact.detect")

# wave 3 WS-K: bias calculator (F11), benchmarking (F15), annual carry-forward (F16)
for _mod in ["biascalc", "insights", "annual"]:
    importlib.import_module(f"app.{_mod}.models")

# wave 3 WS-I: policy builder (F7), AI literacy training (F12) and Trust Center (F9)
for _mod in ["policies", "training", "trust"]:
    importlib.import_module(f"app.{_mod}.models")

# wave 3 WS-L: comments (F18), public API and webhooks (F17)
importlib.import_module("app.comments.models")
importlib.import_module("app.publicapi.models")
importlib.import_module("app.platformtrust.models")

# Release 2 R5: commercial core (orders, entitlements, usage, change orders, time and hours, handoff)
importlib.import_module("app.commercial.models")

# Release 2 R3: scoping questionnaire (SM-05 to SM-08) and mapping rules (spec §4.4, §4.5)
importlib.import_module("app.scoping.models")

# Release 2 R1: master price list, packages and estimates (SM-14, SM-15)
importlib.import_module("app.catalog.models")

# Release 2 R4: proposals, approvals and acceptance (SM-09 to SM-12)
importlib.import_module("app.proposals.models")
# Release 2 R6b: G-07 Copilot readiness and G-08 EU AI Act conformity workspaces
for _mod in ["copilot_readiness", "euaiact"]:
    importlib.import_module(f"app.{_mod}.models")

# Release 2 R6a: Agent Assure records and AgentWarden licence snapshots (G-09); service templates (G-06)
importlib.import_module("app.assurance.models")
importlib.import_module("app.servicetemplates.models")
# Release 2 R7: client hierarchy (G-04)
importlib.import_module("app.hierarchy.models")
# Release 2 R7: evidence vault and retention (G-10)
importlib.import_module("app.vault.models")
# Release 2 R7: partners and referrals (G-11)
importlib.import_module("app.partners.models")
