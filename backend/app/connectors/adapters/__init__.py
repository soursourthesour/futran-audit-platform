"""Connector adapters for AI discovery (spec §21 F2): Okta, Microsoft Entra ID, Microsoft 365 and Google Workspace.

Plain HTTPS over httpx, no vendor SDK. Every adapter asks for read-only access only and returns `Signal`s (one per person
per AI product); the service aggregates them to tool × department before anything is stored. Each adapter has an
in-process fake (fake.py) used by tests, the demo and the browser tests: whenever CONNECTOR_MODE=fake, or
CONNECTOR_MODE=auto with EMAIL_MODE=outbox, nothing goes to the network.

Microsoft (Entra ID and Microsoft 365) and Google use their own app registrations (DISCOVERY_MS_CLIENT_ID,
DISCOVERY_GOOGLE_CLIENT_ID), separate from the email integration's, so the admin consent for discovery grants read
permissions only and never Mail.Send. Okta has no consent redirect for a third-party API integration: the client's Okta
admin installs the Futran API service integration (read scopes only) and gives the Client Admin its client ID and
secret, which the platform stores encrypted. Documentation each adapter follows is cited in its module.
"""
from __future__ import annotations

from app.core.config import Settings

LABELS = {"okta": "Okta", "entra_id": "Microsoft Entra ID", "google_workspace": "Google Workspace", "microsoft_365": "Microsoft 365",
          "expense_csv": "Expense data", "casb_csv": "Network logs"}
PROVIDER_OF = {"entra_id": "microsoft", "microsoft_365": "microsoft", "google_workspace": "google"}


class ConnectorError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def use_fake(settings: Settings) -> bool:
    mode = (settings.connector_mode or "auto").lower()
    return mode == "fake" or (mode == "auto" and settings.email_mode == "outbox")


def redirect_uri(settings: Settings, provider: str) -> str:
    base = settings.discovery_redirect_base or f"{settings.base_url}/api/v1/connectors/oauth"
    return f"{base.rstrip('/')}/{provider}"


def credentials_status(settings: Settings) -> dict:
    """Which providers can be connected on this platform, and what Futran IT must still configure."""
    fake = use_fake(settings)
    ms_missing = [k for k, v in (("DISCOVERY_MS_CLIENT_ID", settings.discovery_ms_client_id), ("DISCOVERY_MS_CLIENT_SECRET", settings.discovery_ms_client_secret)) if not v]
    g_missing = [k for k, v in (("DISCOVERY_GOOGLE_CLIENT_ID", settings.discovery_google_client_id), ("DISCOVERY_GOOGLE_CLIENT_SECRET", settings.discovery_google_client_secret)) if not v]
    return {"test_mode": fake,
            "microsoft": {"available": fake or not ms_missing, "missing": ms_missing, "redirect_uri": redirect_uri(settings, "microsoft")},
            "google": {"available": fake or not g_missing, "missing": g_missing, "redirect_uri": redirect_uri(settings, "google")},
            "okta": {"available": True, "missing": []}}


def get_adapter(settings: Settings, ctype: str):
    """The adapter for a connector type: the fake in test mode, the live one when its credentials are set, else None."""
    if ctype not in LABELS or ctype in ("expense_csv", "casb_csv"):
        return None
    if use_fake(settings):
        from app.connectors.adapters.fake import FakeAdapter

        return FakeAdapter(ctype, settings)
    provider = PROVIDER_OF.get(ctype, "okta")
    if not credentials_status(settings)[provider]["available"]:
        return None
    if ctype == "okta":
        from app.connectors.adapters.okta import OktaAdapter

        return OktaAdapter(settings)
    if provider == "microsoft":
        from app.connectors.adapters.microsoft import MicrosoftAdapter

        return MicrosoftAdapter(settings, ctype)
    from app.connectors.adapters.google import GoogleAdapter

    return GoogleAdapter(settings)
