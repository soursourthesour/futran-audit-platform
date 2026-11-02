"""Okta connector: SSO app assignments and OAuth (OIDC) apps that are AI products.

How access is granted: the client's Okta admin installs the Futran API service integration in the Admin Console and
grants it only the read scopes below; Okta issues a client ID and secret for that org, which the Client Admin enters on
the Integrations screen. The platform then uses the OAuth 2.0 client credentials flow against the org authorization
server: POST https://{okta domain}/oauth2/v1/token (grant_type=client_credentials, the scopes below).

Scopes (read only; "Use the okta.<resource>.read scopes to perform GET API operations"):
- okta.apps.read   "Allows the app to read information about Apps in your Okta organization"
                   GET /api/v1/apps, GET /api/v1/apps/{appId}/users
- okta.users.read  "Allows the app to read the existing users' profiles" — department and email of assigned users,
                   and the users' email domains that prove the Okta org is the client's own
Requests are paged with the Link header (rel="next").

Docs checked on 2 November 2026:
- API service integrations (client credentials, per-org client ID and secret, token endpoint):
  https://developer.okta.com/docs/guides/build-api-integration/main/
- OAuth 2.0 scopes for the Okta management API: https://developer.okta.com/docs/api/oauth2/
- Scope guidance: https://developer.okta.com/docs/guides/implement-oauth-for-okta/scopes/
- Application grants API: https://developer.okta.com/docs/api/openapi/okta-management/management/tag/ApplicationGrants
"""
from __future__ import annotations

import re

import httpx

from app.connectors import vendors
from app.connectors.adapters import ConnectorError
from app.connectors.adapters.http import MAX_PAGES, client, request
from app.connectors.signals import Signal

SCOPES = ["okta.apps.read", "okta.users.read"]
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.(okta|oktapreview|okta-emea|okta-gov|okta-mil)\.com$")


def clean_domain(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v).split("/", 1)[0]
    return v if DOMAIN_RE.match(v) else None


def _next(resp: httpx.Response) -> str | None:
    nxt = resp.links.get("next") if resp.headers.get("link") else None
    return nxt.get("url") if nxt else None


class OktaAdapter:
    type = "okta"

    def __init__(self, settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.transport = transport

    def scopes(self) -> list[str]:
        return list(SCOPES)

    def _token(self, c: httpx.Client, grant: dict) -> str:
        tok = request(c, "POST", f"https://{grant['tenant']}/oauth2/v1/token", "Signing in to Okta", auth=(grant["client_id"], grant["client_secret"]),
                      data={"grant_type": "client_credentials", "scope": " ".join(SCOPES)}, headers={"Accept": "application/json"}).json()
        return tok["access_token"]

    def _pages(self, c: httpx.Client, url: str, token: str, what: str):
        for _ in range(MAX_PAGES):
            resp = request(c, "GET", url, what, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            yield from resp.json()
            url = _next(resp)
            if not url:
                return

    def connect(self, *, domain: str, client_id: str, client_secret: str) -> dict:
        grant = {"tenant": domain, "client_id": client_id, "client_secret": client_secret}
        with client(self.transport) as c:
            token = self._token(c, grant)
            domains = set()
            for u in self._pages(c, f"https://{domain}/api/v1/users?limit=200", token, "Reading Okta users"):
                email = ((u.get("profile") or {}).get("email") or "").lower()
                if "@" in email:
                    domains.add(email.rsplit("@", 1)[1])
        grant["domains"] = sorted(domains)
        return grant

    def collect(self, grant: dict) -> list[Signal]:
        out: list[Signal] = []
        with client(self.transport) as c:
            token = self._token(c, grant)
            base = f"https://{grant['tenant']}"
            users = {u["id"]: u.get("profile") or {} for u in self._pages(c, f"{base}/api/v1/users?limit=200", token, "Reading Okta users")}
            for app in self._pages(c, f"{base}/api/v1/apps?limit=200&filter=status%20eq%20%22ACTIVE%22", token, "Reading Okta apps"):
                v = vendors.match_name(app.get("label") or app.get("name"))
                if v is None:
                    continue
                signal = "oauth_grant" if app.get("signOnMode") == "OPENID_CONNECT" else "sso_app"
                for au in self._pages(c, f"{base}/api/v1/apps/{app['id']}/users?limit=500", token, "Reading app assignments"):
                    p = users.get(au.get("id")) or {}
                    out.append(Signal(v.key, signal, p.get("department"), (p.get("email") or p.get("login") or "").lower() or None,
                                      " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x) or None))
        return out

    def revoke(self, grant: dict) -> None:
        # The client's Okta admin removes the API service integration to revoke it; the platform deletes what it stored.
        return None


def ensure_domain(value: str | None) -> str:
    d = clean_domain(value)
    if d is None:
        raise ConnectorError("Enter your Okta domain, for example yourcompany.okta.com.")
    return d
