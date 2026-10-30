"""Microsoft Graph adapter (Microsoft 365).

Organisation mailbox (E1, E2): admin consent in Entra ID, then app-only tokens (client credentials) for that tenant.
Application permissions requested through `/.default`: Mail.Send, Mail.ReadWrite, User.Read.All, Group.Read.All,
GroupMember.Read.All. IT limits the app to the one sending mailbox with RBAC for Applications in Exchange Online
(see the README). User mailbox (§27.1): delegated authorization code flow with offline_access, Mail.Send,
Mail.ReadWrite and User.Read.

Docs: https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent ,
https://learn.microsoft.com/graph/auth-v2-user , https://learn.microsoft.com/en-us/graph/api/user-post-messages
"""
from datetime import datetime
from urllib.parse import quote, urlencode

import httpx

from app.core.config import Settings
from app.mail.providers import DirectoryEntry, DirectoryGroupEntry, IncomingMessage, OutgoingMessage, ProviderError, SentMessage, redirect_uri
from app.mail.providers.http import client, expired, expires_at, request

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
APP_SCOPE = "https://graph.microsoft.com/.default"
APP_PERMISSIONS = ["Mail.Send", "Mail.ReadWrite", "User.Read.All", "Group.Read.All", "GroupMember.Read.All"]
USER_SCOPES = ["offline_access", "openid", "email", "User.Read", "Mail.Send", "Mail.ReadWrite"]
USER_SELECT = "id,displayName,mail,userPrincipalName,department,jobTitle,officeLocation,accountEnabled,userType"


class MicrosoftGraphAdapter:
    provider = "microsoft365"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.transport = transport

    # ---- consent
    def scopes(self, kind: str) -> list[str]:
        return APP_PERMISSIONS if kind == "admin" else USER_SCOPES

    def consent_url(self, *, kind: str, state: str, tenant: str | None = None, login_hint: str | None = None) -> str:
        if kind == "admin":
            q = {"client_id": self.s.ms_client_id, "scope": APP_SCOPE, "redirect_uri": redirect_uri(self.s, self.provider), "state": state}
            return f"{LOGIN}/{quote(tenant or 'organizations')}/v2.0/adminconsent?{urlencode(q)}"
        q = {"client_id": self.s.ms_client_id, "response_type": "code", "redirect_uri": redirect_uri(self.s, self.provider), "response_mode": "query",
             "scope": " ".join(USER_SCOPES), "state": state}
        if login_hint:
            q["login_hint"] = login_hint
        return f"{LOGIN}/organizations/oauth2/v2.0/authorize?{urlencode(q)}"

    def complete_consent(self, *, kind: str, params: dict) -> dict:
        from app.mail.tokens import Grant

        if params.get("error"):
            raise ProviderError(f"Microsoft did not grant access: {params.get('error_description') or params['error']}"[:400])
        with client(self.transport) as c:
            if kind == "admin":
                tenant = str(params.get("tenant") or "")
                if not tenant or params.get("admin_consent") not in ("True", "true", True):
                    raise ProviderError("The consent response did not confirm admin consent.")
                # The tenant in the response is not trusted on its own: getting an app token for it proves consent.
                g = Grant({"kind": "app", "tenant": tenant})
                self._app_token(c, g)
                org = request(c, "GET", f"{GRAPH}/organization", "Reading the organisation", headers=self._auth(g)).json().get("value", [{}])
                o = org[0] if org else {}
                g["display_name"] = o.get("displayName")
                g["domains"] = [d["name"] for d in o.get("verifiedDomains", []) if d.get("name")]
                return g
            code = params.get("code")
            if not code:
                raise ProviderError("The sign-in response had no authorisation code.")
            tok = request(c, "POST", f"{LOGIN}/organizations/oauth2/v2.0/token", "Signing in", data={
                "client_id": self.s.ms_client_id, "client_secret": self.s.ms_client_secret, "grant_type": "authorization_code", "code": code,
                "redirect_uri": redirect_uri(self.s, self.provider), "scope": " ".join(USER_SCOPES)}).json()
            g = Grant({"kind": "delegated", "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"), "expires_at": expires_at(tok.get("expires_in"))})
            me = request(c, "GET", f"{GRAPH}/me?$select=mail,userPrincipalName", "Reading the signed-in user", headers=self._auth(g)).json()
            g["mailbox"] = (me.get("mail") or me.get("userPrincipalName") or "").lower()
            return g

    # ---- tokens
    def _app_token(self, c: httpx.Client, g) -> None:
        tok = request(c, "POST", f"{LOGIN}/{quote(g['tenant'])}/oauth2/v2.0/token", "Getting an app token", data={
            "client_id": self.s.ms_client_id, "client_secret": self.s.ms_client_secret, "grant_type": "client_credentials", "scope": APP_SCOPE}).json()
        g.update_tokens(access_token=tok["access_token"], expires_at=expires_at(tok.get("expires_in")))

    def _ensure(self, c: httpx.Client, g) -> None:
        if not expired(g):
            return
        if g.get("kind") == "app":
            self._app_token(c, g)
            return
        if not g.get("refresh_token"):
            raise ProviderError("The mailbox sign-in has expired. Connect it again.")
        tok = request(c, "POST", f"{LOGIN}/organizations/oauth2/v2.0/token", "Refreshing the sign-in", data={
            "client_id": self.s.ms_client_id, "client_secret": self.s.ms_client_secret, "grant_type": "refresh_token", "refresh_token": g["refresh_token"],
            "scope": " ".join(USER_SCOPES)}).json()
        g.update_tokens(access_token=tok["access_token"], refresh_token=tok.get("refresh_token"), expires_at=expires_at(tok.get("expires_in")))

    @staticmethod
    def _auth(g) -> dict:
        return {"Authorization": f"Bearer {g['access_token']}"}

    def _base(self, g, mailbox: str) -> str:
        return f"{GRAPH}/me" if g.get("kind") == "delegated" else f"{GRAPH}/users/{quote(mailbox)}"

    # ---- mail
    def send(self, g, m: OutgoingMessage) -> SentMessage:
        def rcpt(addrs):
            return [{"emailAddress": {"address": a}} for a in addrs]

        draft = {"subject": m.subject, "body": {"contentType": "HTML", "content": m.html}, "toRecipients": rcpt(m.to), "bccRecipients": rcpt(m.bcc)}
        if m.reply_to:
            draft["replyTo"] = rcpt([m.reply_to])
        with client(self.transport) as c:
            self._ensure(c, g)
            base = self._base(g, m.from_address)
            # Create then send (not sendMail), so the message and conversation IDs are known for reply sync.
            created = request(c, "POST", f"{base}/messages", "Creating the message", headers=self._auth(g), json=draft).json()
            request(c, "POST", f"{base}/messages/{quote(created['id'])}/send", "Sending the message", headers=self._auth(g))
            return SentMessage(message_id=created.get("id"), thread_id=created.get("conversationId"))

    def thread_messages(self, g, mailbox: str, thread_id: str) -> list[IncomingMessage]:
        """Messages in one conversation the platform started. No other mail is read."""
        out = []
        with client(self.transport) as c:
            self._ensure(c, g)
            safe = thread_id.replace("'", "''")
            url = f"{self._base(g, mailbox)}/messages?$filter=conversationId eq '{safe}'&$select=id,from,subject,receivedDateTime,bodyPreview,internetMessageHeaders&$top=50"
            for item in self._pages(c, g, url, "Reading replies"):
                frm = ((item.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
                if frm == mailbox.lower():
                    continue
                headers = {h.get("name", "").lower(): h.get("value", "") for h in item.get("internetMessageHeaders") or []}
                out.append(IncomingMessage(message_id=item["id"], from_address=frm, subject=item.get("subject") or "", snippet=(item.get("bodyPreview") or "")[:500],
                                           received_at=_dt(item.get("receivedDateTime")), auto_reply=headers.get("auto-submitted", "no").lower() not in ("", "no")))
        return out

    # ---- directory
    def _pages(self, c: httpx.Client, g, url: str, what: str):
        while url:
            data = request(c, "GET", url, what, headers=self._auth(g)).json()
            yield from data.get("value", [])
            url = data.get("@odata.nextLink")

    def list_people(self, g, *, scope_group: str | None, include_guests: bool) -> list[DirectoryEntry]:
        with client(self.transport) as c:
            self._ensure(c, g)
            url = (f"{GRAPH}/groups/{quote(scope_group)}/transitiveMembers/microsoft.graph.user?$select={USER_SELECT}&$top=999" if scope_group
                   else f"{GRAPH}/users?$select={USER_SELECT}&$expand=manager($select=id)&$top=999")
            out = []
            for u in self._pages(c, g, url, "Reading people"):
                guest = (u.get("userType") or "Member") == "Guest"
                email = (u.get("mail") or "").lower()
                if not email or (guest and not include_guests):
                    continue
                out.append(DirectoryEntry(directory_id=u["id"], email=email, name=u.get("displayName") or email, department=u.get("department"), job_title=u.get("jobTitle"),
                                          manager_id=(u.get("manager") or {}).get("id"), office=u.get("officeLocation"), is_guest=guest, enabled=u.get("accountEnabled", True) is not False))
            return out

    def list_groups(self, g) -> list[DirectoryGroupEntry]:
        with client(self.transport) as c:
            self._ensure(c, g)
            return [DirectoryGroupEntry(directory_id=x["id"], name=x.get("displayName") or x["id"]) for x in self._pages(c, g, f"{GRAPH}/groups?$select=id,displayName&$top=999", "Reading groups")]

    def group_member_ids(self, g, group_id: str) -> list[str]:
        with client(self.transport) as c:
            self._ensure(c, g)
            return [x["id"] for x in self._pages(c, g, f"{GRAPH}/groups/{quote(group_id)}/transitiveMembers?$select=id&$top=999", "Reading group members")]

    def revoke(self, g) -> None:
        """Microsoft has no token revocation endpoint for this flow; the token is deleted here and IT removes the app's
        consent in Entra ID (Enterprise applications) to cut access on their side."""
        return None


def _dt(v: str | None) -> datetime:
    if not v:
        from app.core.clock import utcnow

        return utcnow()
    return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
