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
ROUTER_MODULES += ["ai.connection_router"]  # 11-03 F1: Platform settings › AI provider
# wave 3 WS-J: integrations and AI discovery (screen 30), continuous monitoring (screen 31)
ROUTER_MODULES += ["connectors.router", "monitoring.router"]

# 11-03 fixes WS-N: counts on navigation entries (F6)
ROUTER_MODULES += ["nav.router"]

# 11-03 fixes WS-R: the Futran Admin's AI model list (C12)
ROUTER_MODULES += ["register.catalogue_router"]

# 11-10 U1: the client's one list of AI systems (register, inventory, use cases and the current audit)
ROUTER_MODULES += ["register.ailist"]

# Release 2 R5: SM-13 handoff, G-01 plan and entitlements, G-02 engagement commercials, G-03 time and hours
ROUTER_MODULES += ["commercial.router_handoff", "commercial.router_plan", "commercial.router_engagement", "commercial.router_time"]

# Release 2 R1: master price list (SM-14) and Estimator (SM-15)
ROUTER_MODULES += ["catalog.router", "catalog.estimate_router"]

# Release 2 R6a: service templates and engagement types (G-06), discovery import (G-05), agent assurance (G-09)
ROUTER_MODULES += ["servicetemplates.router", "connectors.import_router"]
# Release 2 R3: scoping questionnaire (SM-05 to SM-08, the public SM-07 link) and the question bank and mapping rules tabs
ROUTER_MODULES += ["scoping.router", "scoping.public_router"]
# Release 2 R6b: G-07 Copilot readiness (`/e/:id/copilot`, client `/copilot`) and G-08 EU AI Act conformity (`/e/:id/eu-ai-act`)
ROUTER_MODULES += ["euaiact.router", "euaiact.links_router"]
