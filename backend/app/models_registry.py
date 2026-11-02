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
for _mod in ["monitoring"]:
    importlib.import_module(f"app.{_mod}.models")

# Wave 3 WS-G: AI interactions, obligations, extracted document text, questionnaires and the answer library (§21)
importlib.import_module("app.ai.models")

# Wave 3 WS-H: regulatory change alerts (F4) and impact assessment with reassessment triggers (F8)
for _mod in ["regupdates", "impact"]:
    importlib.import_module(f"app.{_mod}.models")

# wave 3 WS-K: bias calculator (F11), benchmarking (F15), annual carry-forward (F16)
for _mod in ["biascalc", "insights", "annual"]:
    importlib.import_module(f"app.{_mod}.models")

# wave 3 WS-I: policy builder (F7), AI literacy training (F12) and Trust Center (F9)
for _mod in ["policies"]:
    importlib.import_module(f"app.{_mod}.models")
