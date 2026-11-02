"""Collect every domain's APIRouter. Each entry is a dotted module with a `router`."""
import importlib

from fastapi import APIRouter

ROUTER_MODULES: list[str] = ["auth.router", "invitations.router", "mail.router", "tenancy.router", "audit_log.router", "laws.router", "reference.router", "reference.templates_router", "engagements.router", "engagements.wizard_router", "files.router", "initiation.router", "signoffs.router", "engagements.client_router", "tenancy.people_router", "governance.router", "attestation.router", "inventory.router", "systems.router", "questionnaire.router", "docrequests.router", "scoring.router", "notifications.router", "signoffs.review_router", "findings.router", "reports.router", "remediation.router", "geo.router", "engagements.stage_router", "register.io_router", "register.router", "register.governance_router", "attestation.send_router", "mail.public_router", "mail.admin_router", "mail.groups_router", "regmaster.router"]


def api_routers() -> list[APIRouter]:
    return [importlib.import_module(f"app.{m}").router for m in ROUTER_MODULES]


# v0.6 WS-D: litigation, opportunities, refresh alerts (M6), client alerts (A1), refresh and review (M3)
ROUTER_MODULES += ["litigation.router", "sales.router", "staffalerts.router", "clientalerts.router", "refresh.router"]

# v0.6 WS-E: tracing add-on and unlock (R7, R8)
ROUTER_MODULES += ["tracing.router"]

# v0.6.1 WS-F: role home screens (§13.1)
ROUTER_MODULES += ["homes.router"]

# wave 3 WS-I: policy builder (F7), AI literacy training (F12) and Trust Center (F9)
ROUTER_MODULES += ["policies.router", "training.router", "trust.router"]

# wave 3 WS-K: bias calculator (screen 29), heat map and lineage (35), benchmarking (34), annual review carry-forward (F16)
ROUTER_MODULES += ["biascalc.router", "insights.router", "annual.router"]

# wave 3 WS-L: comments and mentions (F18)
ROUTER_MODULES += ["comments.router", "publicapi.admin_router", "tracing.agents_router", "platformtrust.router"]

# Wave 3 WS-H: regulatory change alerts (screen 26) and new AI project impact assessment (screen 28)
ROUTER_MODULES += ["impact.router", "regupdates.router"]

# wave 3 WS-G: AI copilot and the engagement AI switch (F1, screen 25)
ROUTER_MODULES += ["ai.router", "ai.explain_router", "ai.obligations_router", "ai.questionnaires_router"]
