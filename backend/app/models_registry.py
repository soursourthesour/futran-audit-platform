"""Import every domain's models so `Base.metadata` is complete (Alembic, tests)."""
import importlib

DOMAINS_WITH_MODELS: list[str] = ["tenancy", "audit_log", "auth", "mail", "invitations", "engagements", "reference", "laws", "questionnaire", "files", "initiation", "signoffs", "notifications", "governance", "attestation", "inventory", "systems", "findings", "docrequests", "scoring", "reports", "remediation", "register", "regmaster"]

for _mod in DOMAINS_WITH_MODELS:
    importlib.import_module(f"app.{_mod}.models")

# v0.6 WS-D domains: litigation, Sales Team opportunities, refresh pipeline, staff and client alerts
for _mod in ["litigation", "sales", "refresh", "staffalerts", "clientalerts"]:
    importlib.import_module(f"app.{_mod}.models")
