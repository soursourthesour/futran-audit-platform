"""Google Workspace connector: third-party app OAuth grants and Gemini use, from the Admin SDK Reports API.

Consent: a Workspace super administrator signs in once (web-server OAuth, access_type=offline) and grants the read-only
scopes below to Futran's AI discovery OAuth client (separate from the email integration's). The hosted domain (`hd`) of
the signed-in admin must be one of the client's own email domains. Disconnecting revokes the refresh token at
https://oauth2.googleapis.com/revoke and deletes it.

Scopes (all read only):
- https://www.googleapis.com/auth/admin.reports.audit.readonly
    GET https://admin.googleapis.com/admin/reports/v1/activity/users/all/applications/token?eventName=authorize
      ("A user granted an application access to their data"; parameters app_name, client_id, scope)
    GET https://admin.googleapis.com/admin/reports/v1/activity/users/all/applications/gemini_in_workspace_apps
      (event feature_utilization: a Gemini-assisted action in a Workspace app)
- https://www.googleapis.com/auth/admin.directory.user.readonly
    GET https://admin.googleapis.com/admin/directory/v1/users?customer=my_customer (department of each person)
The Directory API's tokens.list (users/{userKey}/tokens) is not used: it needs admin.directory.user.security, which can
also delete tokens. The token audit log gives the same grants with a read-only scope.

Docs checked on 2 November 2026:
- OAuth Token audit activity events: https://developers.google.com/admin-sdk/reports/v1/appendix/activity/token
- Gemini in Workspace Apps activity events: https://developers.google.cn/admin-sdk/reports/v1/appendix/activity/gemini-in-workspace-apps
- Directory API tokens.list (scope not used, see above): https://developers.google.com/admin-sdk/directory/reference/rest/v1/tokens/list
- Web-server OAuth (access_type=offline, prompt=consent): https://developers.google.com/accounts/docs/OAuth
"""
from __future__ import annotations

import base64
import json
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from app.connectors import vendors
from app.connectors.adapters import ConnectorError, redirect_uri
from app.connectors.adapters.http import MAX_PAGES, client, expired, expires_at, request
from app.connectors.signals import Signal
from app.core.clock import utcnow

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
REPORTS = "https://admin.googleapis.com/admin/reports/v1/activity/users/all/applications"
DIRECTORY = "https://admin.googleapis.com/admin/directory/v1"
SCOPES = ["https://www.googleapis.com/auth/admin.reports.audit.readonly", "https://www.googleapis.com/auth/admin.directory.user.readonly"]
ID_SCOPES = ["openid", "email"]
LOOKBACK_DAYS = 30


def _claims(id_token: str | None) -> dict:
    """Claims of the ID token Google's token endpoint returned over TLS (read, not used as proof of anything else)."""
    try:
        part = (id_token or "").split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # malformed or missing
        return {}


class GoogleAdapter:
    type = "google_workspace"

    def __init__(self, settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.transport = transport

    def scopes(self) -> list[str]:
        return list(SCOPES)

    def consent_url(self, *, state: str, login_hint: str | None = None, tenant: str | None = None) -> str:
        q = {"client_id": self.s.discovery_google_client_id, "redirect_uri": redirect_uri(self.s, "google"), "response_type": "code",
             "scope": " ".join(ID_SCOPES + SCOPES), "access_type": "offline", "prompt": "consent", "state": state}
        if login_hint:
            q["login_hint"] = login_hint
        if tenant:
            q["hd"] = tenant
        return f"{AUTH}?{urlencode(q)}"

    def complete_consent(self, *, params: dict) -> dict:
        if params.get("error"):
            raise ConnectorError(f"Google did not grant access: {params['error']}")
        if not params.get("code"):
            raise ConnectorError("The sign-in response had no authorisation code.")
        with client(self.transport) as c:
            tok = request(c, "POST", TOKEN, "Signing in to Google", data={"client_id": self.s.discovery_google_client_id, "client_secret": self.s.discovery_google_client_secret,
                                                                          "code": params["code"], "grant_type": "authorization_code", "redirect_uri": redirect_uri(self.s, "google")}).json()
        granted = set((tok.get("scope") or "").split())
        missing = [s for s in SCOPES if s not in granted]
        if missing:
            raise ConnectorError("Google did not grant every read-only permission the connector needs. Sign in again and allow them all.")
        claims = _claims(tok.get("id_token"))
        hd = (claims.get("hd") or "").lower()
        if not hd:
            raise ConnectorError("Sign in with a Google Workspace administrator account, not a personal Google account.")
        return {"tenant": hd, "domains": [hd], "account": (claims.get("email") or "").lower() or None, "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token"), "expires_at": expires_at(tok.get("expires_in"))}

    def _ensure(self, c: httpx.Client, grant: dict) -> None:
        if not expired(grant):
            return
        if not grant.get("refresh_token"):
            raise ConnectorError("The Google sign-in has expired. Connect Google Workspace again.")
        tok = request(c, "POST", TOKEN, "Refreshing the Google sign-in", data={"client_id": self.s.discovery_google_client_id,
                                                                               "client_secret": self.s.discovery_google_client_secret,
                                                                               "grant_type": "refresh_token", "refresh_token": grant["refresh_token"]}).json()
        grant["access_token"], grant["expires_at"] = tok["access_token"], expires_at(tok.get("expires_in"))
        grant["_refreshed"] = True

    def _pages(self, c: httpx.Client, url: str, params: dict, grant: dict, what: str, key: str):
        params = dict(params)
        for _ in range(MAX_PAGES):
            data = request(c, "GET", url, what, params=params, headers={"Authorization": f"Bearer {grant['access_token']}"}).json()
            yield from data.get(key) or []
            if not data.get("nextPageToken"):
                return
            params["pageToken"] = data["nextPageToken"]

    def collect(self, grant: dict) -> list[Signal]:
        start = (utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        out: list[Signal] = []
        with client(self.transport) as c:
            self._ensure(c, grant)
            depts = {}
            for u in self._pages(c, f"{DIRECTORY}/users", {"customer": "my_customer", "maxResults": 500, "projection": "full"}, grant, "Reading users", "users"):
                orgs = u.get("organizations") or []
                depts[(u.get("primaryEmail") or "").lower()] = (next((o.get("department") for o in orgs if o.get("department")), None), (u.get("name") or {}).get("fullName"))
            for ev in self._pages(c, f"{REPORTS}/token", {"eventName": "authorize", "startTime": start, "maxResults": 1000}, grant, "Reading OAuth grants", "items"):
                email = ((ev.get("actor") or {}).get("email") or "").lower()
                for e in ev.get("events") or []:
                    p = {x.get("name"): x.get("value") or x.get("multiValue") for x in e.get("parameters") or []}
                    v = vendors.match_name(p.get("app_name"))
                    if v is None:
                        continue
                    scopes = p.get("scope") or []
                    short = ", ".join(sorted({s.rstrip("/").rsplit("/", 1)[-1].split(".")[0] for s in (scopes if isinstance(scopes, list) else [scopes]) if s}))
                    dept, name = depts.get(email, (None, None))
                    out.append(Signal(v.key, "oauth_grant", dept, email or None, name, detail=short or None))
            gemini = vendors.by_key("google_gemini")
            for ev in self._pages(c, f"{REPORTS}/gemini_in_workspace_apps", {"eventName": "feature_utilization", "startTime": start, "maxResults": 1000}, grant,
                                  "Reading Gemini use", "items"):
                email = ((ev.get("actor") or {}).get("email") or "").lower()
                dept, name = depts.get(email, (None, None))
                out.append(Signal(gemini.key, "licence", dept, email or None, name, detail="Gemini in Workspace apps"))
        return out

    def revoke(self, grant: dict) -> None:
        token = grant.get("refresh_token") or grant.get("access_token")
        if not token:
            return
        with client(self.transport) as c:
            request(c, "POST", REVOKE, "Revoking the Google sign-in", data={"token": token})
