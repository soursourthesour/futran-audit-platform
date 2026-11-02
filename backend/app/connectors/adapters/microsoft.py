"""Microsoft Entra ID and Microsoft 365 connectors (Microsoft Graph, app-only).

Consent: the client's Global Administrator (or Privileged Role Administrator) grants admin consent to Futran's AI
discovery app registration at https://login.microsoftonline.com/{tenant|organizations}/v2.0/adminconsent with
scope=https://graph.microsoft.com/.default. The platform then takes app-only tokens for that tenant (client credentials)
and stores only the tenant id, encrypted. The app registration is separate from the email integration's and holds these
application permissions, all read only:

Entra ID ("SSO apps, OAuth grants"):
- Application.Read.All  GET /servicePrincipals (least privileged application permission), and
                        GET /servicePrincipals/{id}/appRoleAssignedTo (who is assigned to the app)
- Directory.Read.All    GET /oauth2PermissionGrants (least privileged application permission), and GET /users
                        (department of each person)
Microsoft 365 ("Copilot licences, app consents"):
- LicenseAssignment.Read.All  GET /subscribedSkus (least privileged application permission)
- Reports.Read.All            GET /copilot/reports/getMicrosoft365CopilotUsageUserDetail(period='D30') (v1.0; only users
                              with a Microsoft 365 Copilot licence are returned; names may be concealed by the tenant's
                              report privacy setting, in which case people are counted without a department)
- User.Read.All               GET /users (department)

Because admin consent with /.default grants every permission on the registration, one consent covers both connectors;
each connector uses only its own permissions. Disconnecting deletes the stored tenant id and token; to remove the consent
itself the client deletes the Futran enterprise application in Entra ID (the screen says so).

Docs checked on 2 November 2026:
- Admin consent: https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent
- List servicePrincipals: https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list
- List oauth2PermissionGrants: https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-list
- appRoleAssignedTo: https://learn.microsoft.com/graph/api/serviceprincipal-list-approleassignments
- List subscribedSkus: https://learn.microsoft.com/en-us/graph/api/subscribedsku-list
- Copilot usage user detail: https://learn.microsoft.com/en-ca/microsoft-365/copilot/extensibility/api/admin-settings/reports/copilotreportroot-getmicrosoft365copilotusageuserdetail
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

import httpx

from app.connectors import vendors
from app.connectors.adapters import ConnectorError, redirect_uri
from app.connectors.adapters.http import MAX_PAGES, client, expires_at, request
from app.connectors.signals import Signal

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
APP_SCOPE = "https://graph.microsoft.com/.default"
PERMISSIONS = {
    "entra_id": ["Application.Read.All", "Directory.Read.All"],
    "microsoft_365": ["LicenseAssignment.Read.All", "Reports.Read.All", "User.Read.All"],
}
COPILOT_SKUS = ("copilot",)


class MicrosoftAdapter:
    def __init__(self, settings, ctype: str, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.type = ctype
        self.transport = transport

    def scopes(self) -> list[str]:
        return list(PERMISSIONS[self.type])

    def consent_url(self, *, state: str, login_hint: str | None = None, tenant: str | None = None) -> str:
        q = {"client_id": self.s.discovery_ms_client_id, "scope": APP_SCOPE, "redirect_uri": redirect_uri(self.s, "microsoft"), "state": state}
        return f"{LOGIN}/{quote(tenant or 'organizations')}/v2.0/adminconsent?{urlencode(q)}"

    def _app_token(self, c: httpx.Client, tenant: str) -> str:
        tok = request(c, "POST", f"{LOGIN}/{quote(tenant)}/oauth2/v2.0/token", "Signing in to Microsoft", data={
            "client_id": self.s.discovery_ms_client_id, "client_secret": self.s.discovery_ms_client_secret, "grant_type": "client_credentials", "scope": APP_SCOPE}).json()
        return tok["access_token"]

    def complete_consent(self, *, params: dict) -> dict:
        if params.get("error"):
            raise ConnectorError(f"Microsoft did not grant access: {params.get('error_description') or params['error']}"[:400])
        tenant = str(params.get("tenant") or "")
        if not tenant or params.get("admin_consent") not in ("True", "true", True):
            raise ConnectorError("The consent response did not confirm admin consent.")
        with client(self.transport) as c:
            # the tenant in the redirect is not trusted on its own: an app token for it proves the consent
            token = self._app_token(c, tenant)
            org = request(c, "GET", f"{GRAPH}/organization?$select=displayName,verifiedDomains", "Reading the organization",
                          headers={"Authorization": f"Bearer {token}"}).json().get("value") or [{}]
        o = org[0] if org else {}
        return {"tenant": tenant, "display_name": o.get("displayName"), "domains": [d["name"].lower() for d in o.get("verifiedDomains", []) if d.get("name")],
                "account": "the tenant's administrator", "expires_at": expires_at(0)}

    def _pages(self, c: httpx.Client, url: str, token: str, what: str):
        for _ in range(MAX_PAGES):
            data = request(c, "GET", url, what, headers={"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"}).json()
            yield from data.get("value") or []
            url = data.get("@odata.nextLink")
            if not url:
                return

    def _users(self, c: httpx.Client, token: str) -> dict[str, dict]:
        out = {}
        for u in self._pages(c, f"{GRAPH}/users?$select=id,displayName,mail,userPrincipalName,department&$top=999", token, "Reading users"):
            out[u["id"]] = u
            for k in ("userPrincipalName", "mail"):
                if u.get(k):
                    out[u[k].lower()] = u
        return out

    def collect(self, grant: dict) -> list[Signal]:
        with client(self.transport) as c:
            token = self._app_token(c, grant["tenant"])
            users = self._users(c, token)
            return self._entra(c, token, users) if self.type == "entra_id" else self._m365(c, token, users)

    @staticmethod
    def _person(u: dict | None) -> tuple[str | None, str | None, str | None]:
        if not u:
            return None, None, None
        return u.get("department"), (u.get("mail") or u.get("userPrincipalName") or "").lower() or None, u.get("displayName")

    def _entra(self, c: httpx.Client, token: str, users: dict) -> list[Signal]:
        out: list[Signal] = []
        sps = self._pages(c, f"{GRAPH}/servicePrincipals?$select=id,appId,displayName&$top=100", token, "Reading enterprise applications")
        for sp in sps:
            v = vendors.match_name(sp.get("displayName"))
            if v is None:
                continue
            for a in self._pages(c, f"{GRAPH}/servicePrincipals/{sp['id']}/appRoleAssignedTo?$top=100", token, "Reading app assignments"):
                if a.get("principalType") == "User":
                    dept, email, name = self._person(users.get(a.get("principalId")))
                    out.append(Signal(v.key, "sso_app", dept, email or a.get("principalId"), name or a.get("principalDisplayName")))
            flt = quote(f"clientId eq '{sp['id']}'")
            for g in self._pages(c, f"{GRAPH}/oauth2PermissionGrants?$filter={flt}", token, "Reading app consents"):
                scope = ", ".join((g.get("scope") or "").split())
                if g.get("consentType") == "AllPrincipals":
                    out.append(Signal(v.key, "oauth_grant", None, None, None, detail=scope or None))
                    continue
                dept, email, name = self._person(users.get(g.get("principalId")))
                out.append(Signal(v.key, "oauth_grant", dept, email or g.get("principalId"), name, detail=scope or None))
        return out

    def _m365(self, c: httpx.Client, token: str, users: dict) -> list[Signal]:
        out: list[Signal] = []
        skus = request(c, "GET", f"{GRAPH}/subscribedSkus?$select=skuPartNumber,consumedUnits", "Reading licences", headers={"Authorization": f"Bearer {token}"}).json()
        licensed = sum(int(s.get("consumedUnits") or 0) for s in skus.get("value") or [] if any(k in (s.get("skuPartNumber") or "").lower() for k in COPILOT_SKUS))
        if not licensed:
            return out
        v = vendors.by_key("microsoft_copilot")
        url = f"{GRAPH}/copilot/reports/getMicrosoft365CopilotUsageUserDetail(period='D30')"
        seen = 0
        for row in self._pages(c, url, token, "Reading the Copilot usage report"):
            upn = (row.get("userPrincipalName") or "").lower()
            dept, email, name = self._person(users.get(upn))
            out.append(Signal(v.key, "licence", dept, email or upn or None, name, detail="active in the last 30 days" if row.get("lastActivityDate") else "licensed, not used"))
            seen += 1
        out += [Signal(v.key, "licence", None, None, None, detail="licensed, not in the usage report") for _ in range(max(licensed - seen, 0))]
        return out

    def revoke(self, grant: dict) -> None:
        # App-only consent is removed by deleting the enterprise application in Entra ID; nothing to call here.
        return None
