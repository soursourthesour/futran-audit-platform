"""Collect every domain's APIRouter. Each entry is a dotted module with a `router`."""
import importlib

from fastapi import APIRouter

ROUTER_MODULES: list[str] = ["auth.router", "invitations.router", "mail.router", "tenancy.router", "audit_log.router", "laws.router", "reference.router", "reference.templates_router", "engagements.router", "engagements.wizard_router", "files.router", "initiation.router", "signoffs.router", "engagements.client_router", "tenancy.people_router", "governance.router", "attestation.router", "inventory.router", "systems.router", "questionnaire.router", "docrequests.router", "scoring.router", "notifications.router", "signoffs.review_router", "findings.router", "reports.router", "remediation.router", "geo.router", "engagements.stage_router"]


def api_routers() -> list[APIRouter]:
    return [importlib.import_module(f"app.{m}").router for m in ROUTER_MODULES]
