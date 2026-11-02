"""Proof of a Microsoft tenant by the administrator's sign-in. Shared by the email integration (app.mail) and AI discovery
(app.connectors), which each use their own app registration.

Microsoft's admin-consent redirect (/adminconsent) names the tenant in its query string, and anyone holding a valid
state can edit it to another company's tenant that once consented to the same multi-tenant app. So after admin consent
the platform signs the administrator in (OpenID Connect authorization code flow at /organizations, scope openid, with a
nonce) and takes the tenant from the ID token's `tid`, which must equal the tenant that gave consent.

The ID token comes straight from Microsoft's token endpoint over TLS, in exchange for the code and the client secret, so
its signature is not checked (OpenID Connect Core 1.0, section 3.1.3.7); its audience, issuer, tenant, nonce and expiry
are. A guest account (an `idp` claim other than the issuer) is refused: the tenant must be the account's own.

Docs: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow ,
https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference
"""
from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlencode

LOGIN = "https://login.microsoftonline.com"
SCOPE = "openid"
TOKEN_URL = f"{LOGIN}/organizations/oauth2/v2.0/token"


class TenantProofError(Exception):
    """The sign-in does not prove the consented tenant. The message is for the person connecting."""


def authorize_url(*, client_id: str, redirect_uri: str, state: str, nonce: str, login_hint: str | None = None) -> str:
    q = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query", "scope": SCOPE, "state": state, "nonce": nonce}
    if login_hint:
        q["login_hint"] = login_hint
    return f"{LOGIN}/organizations/oauth2/v2.0/authorize?{urlencode(q)}"


def token_form(*, client_id: str, client_secret: str, redirect_uri: str, params: dict) -> dict:
    """The form to POST to TOKEN_URL for the sign-in's code. Raises TenantProofError when the sign-in did not happen."""
    if params.get("error"):
        raise TenantProofError(f"Microsoft did not sign you in: {params.get('error_description') or params['error']}"[:400])
    if not params.get("code"):
        raise TenantProofError("The sign-in response had no authorisation code.")
    return {"client_id": client_id, "client_secret": client_secret, "grant_type": "authorization_code", "code": params["code"], "redirect_uri": redirect_uri,
            "scope": SCOPE}


def _claims(id_token: str | None) -> dict:
    try:
        part = (id_token or "").split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # malformed or missing
        return {}


def proven_tenant(id_token: str | None, *, client_id: str, nonce: str, consented_tenant: str | None) -> str:
    """The tenant the ID token proves, which must be the one that gave consent."""
    c = _claims(id_token)
    tid = str(c.get("tid") or "")
    if (not tid or not client_id or c.get("aud") != client_id or c.get("iss") != f"{LOGIN}/{tid}/v2.0" or not nonce or c.get("nonce") != nonce
            or float(c.get("exp") or 0) <= time.time()):
        raise TenantProofError("Microsoft's sign-in response could not be verified. Start the connection again.")
    if c.get("idp") and c["idp"] != c["iss"]:
        raise TenantProofError("Sign in with an administrator account of your organisation's own Microsoft tenant, not a guest account.")
    if not consented_tenant or tid != consented_tenant:
        raise TenantProofError("You signed in to a different Microsoft tenant from the one that gave consent. Sign in with an administrator account "
                               "of your organisation's own tenant.")
    return tid
