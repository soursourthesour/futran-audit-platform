"""Gmail API and Admin SDK Directory API adapter (Google Workspace).

Organisation mailbox: the sending mailbox signs in once (web-server OAuth, access_type=offline) and grants gmail.send,
gmail.modify and, when that account may read the directory, the Directory API read-only scopes. gmail.modify is a
restricted scope: Google requires app verification (and a security assessment) for external apps, unless the
client's Workspace admin marks the app as trusted in API controls. User mailbox (§27.1): gmail.send and gmail.modify.

Docs: https://developers.google.com/accounts/docs/OAuth , https://developers.google.com/workspace/gmail/api/auth/scopes ,
https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data
"""
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import quote, urlencode

import httpx

from app.core.config import Settings
from app.mail.providers import DirectoryEntry, DirectoryGroupEntry, IncomingMessage, OutgoingMessage, ProviderError, SentMessage, redirect_uri
from app.mail.providers.http import client, expired, expires_at, request

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DIRECTORY = "https://admin.googleapis.com/admin/directory/v1"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.modify"]
DIRECTORY_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user.readonly", "https://www.googleapis.com/auth/admin.directory.group.readonly",
                    "https://www.googleapis.com/auth/admin.directory.group.member.readonly"]
ID_SCOPES = ["openid", "email"]


class GoogleAdapter:
    provider = "google"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.transport = transport

    def scopes(self, kind: str) -> list[str]:
        return GMAIL_SCOPES + (DIRECTORY_SCOPES if kind == "admin" else [])

    def consent_url(self, *, kind: str, state: str, tenant: str | None = None, login_hint: str | None = None) -> str:
        q = {"client_id": self.s.google_client_id, "redirect_uri": redirect_uri(self.s, self.provider), "response_type": "code",
             "scope": " ".join(ID_SCOPES + self.scopes(kind)), "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
        if login_hint:
            q["login_hint"] = login_hint
        if tenant:
            q["hd"] = tenant
        return f"{AUTH}?{urlencode(q)}"

    def complete_consent(self, *, kind: str, params: dict) -> dict:
        from app.mail.tokens import Grant

        if params.get("error"):
            raise ProviderError(f"Google did not grant access: {params['error']}")
        if not params.get("code"):
            raise ProviderError("The sign-in response had no authorisation code.")
        with client(self.transport) as c:
            tok = request(c, "POST", TOKEN, "Signing in", data={"client_id": self.s.google_client_id, "client_secret": self.s.google_client_secret, "code": params["code"],
                                                               "grant_type": "authorization_code", "redirect_uri": redirect_uri(self.s, self.provider)}).json()
            g = Grant({"kind": "delegated", "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"), "expires_at": expires_at(tok.get("expires_in")),
                       "scope": tok.get("scope", "")})
            prof = request(c, "GET", f"{GMAIL}/profile", "Reading the mailbox", headers=self._auth(g)).json()
            g["mailbox"] = (prof.get("emailAddress") or "").lower()
            g["domains"] = [g["mailbox"].split("@", 1)[1]] if "@" in g["mailbox"] else []
            return g

    def _ensure(self, c: httpx.Client, g) -> None:
        if not expired(g):
            return
        if not g.get("refresh_token"):
            raise ProviderError("The mailbox sign-in has expired. Connect it again.")
        tok = request(c, "POST", TOKEN, "Refreshing the sign-in", data={"client_id": self.s.google_client_id, "client_secret": self.s.google_client_secret,
                                                                        "grant_type": "refresh_token", "refresh_token": g["refresh_token"]}).json()
        g.update_tokens(access_token=tok["access_token"], expires_at=expires_at(tok.get("expires_in")))

    @staticmethod
    def _auth(g) -> dict:
        return {"Authorization": f"Bearer {g['access_token']}"}

    def send(self, g, m: OutgoingMessage) -> SentMessage:
        em = EmailMessage()
        em["From"] = formataddr((m.from_name, m.from_address))
        if m.to:
            em["To"] = ", ".join(m.to)
        if m.cc:
            em["Cc"] = ", ".join(m.cc)
        if m.bcc:
            em["Bcc"] = ", ".join(m.bcc)  # Gmail delivers to Bcc and removes the header
        if m.reply_to:
            em["Reply-To"] = m.reply_to
        em["Subject"] = m.subject
        em.set_content(m.text)
        em.add_alternative(m.html, subtype="html")
        raw = base64.urlsafe_b64encode(em.as_bytes()).decode().rstrip("=")
        with client(self.transport) as c:
            self._ensure(c, g)
            data = request(c, "POST", f"{GMAIL}/messages/send", "Sending the message", headers=self._auth(g), json={"raw": raw}).json()
            return SentMessage(message_id=data.get("id"), thread_id=data.get("threadId"))

    def thread_messages(self, g, mailbox: str, thread_id: str) -> list[IncomingMessage]:
        with client(self.transport) as c:
            self._ensure(c, g)
            url = f"{GMAIL}/threads/{quote(thread_id)}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Auto-Submitted"
            data = request(c, "GET", url, "Reading replies", headers=self._auth(g)).json()
            out = []
            for msg in data.get("messages", []):
                h = {x["name"].lower(): x["value"] for x in (msg.get("payload") or {}).get("headers", [])}
                frm = h.get("from", "")
                addr = (frm.split("<")[-1].rstrip(">") if "<" in frm else frm).strip().lower()
                if addr == mailbox.lower() or "SENT" in (msg.get("labelIds") or []):
                    continue
                at = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=timezone.utc).replace(tzinfo=None)
                out.append(IncomingMessage(message_id=msg["id"], from_address=addr, subject=h.get("subject", ""), snippet=(msg.get("snippet") or "")[:500], received_at=at,
                                           auto_reply=h.get("auto-submitted", "no").lower() not in ("", "no")))
            return out

    def _pages(self, c: httpx.Client, g, url: str, key: str, what: str):
        token = None
        while True:
            full = f"{url}{'&' if '?' in url else '?'}maxResults=200" + (f"&pageToken={quote(token)}" if token else "")
            data = request(c, "GET", full, what, headers=self._auth(g)).json()
            yield from data.get(key, [])
            token = data.get("nextPageToken")
            if not token:
                return

    def list_people(self, g, *, scope_group: str | None, include_guests: bool) -> list[DirectoryEntry]:
        with client(self.transport) as c:
            self._ensure(c, g)
            allowed = None
            if scope_group:
                allowed = {m.get("id") for m in self._pages(c, g, f"{DIRECTORY}/groups/{quote(scope_group)}/members?includeDerivedMembership=true", "members", "Reading group members")}
            out = []
            for u in self._pages(c, g, f"{DIRECTORY}/users?customer=my_customer&projection=full", "users", "Reading people"):
                if allowed is not None and u.get("id") not in allowed:
                    continue
                org = (u.get("organizations") or [{}])[0]
                loc = (u.get("locations") or [{}])[0]
                manager = next((r.get("value") for r in u.get("relations") or [] if r.get("type") == "manager"), None)
                out.append(DirectoryEntry(directory_id=u["id"], email=(u.get("primaryEmail") or "").lower(), name=(u.get("name") or {}).get("fullName") or u.get("primaryEmail"),
                                          department=org.get("department"), job_title=org.get("title"), manager_id=manager, office=loc.get("buildingId") or org.get("location"),
                                          enabled=not u.get("suspended", False)))
            return out

    def list_groups(self, g) -> list[DirectoryGroupEntry]:
        with client(self.transport) as c:
            self._ensure(c, g)
            return [DirectoryGroupEntry(directory_id=x["id"], name=x.get("name") or x.get("email"), member_count=int(x.get("directMembersCount") or 0))
                    for x in self._pages(c, g, f"{DIRECTORY}/groups?customer=my_customer", "groups", "Reading groups")]

    def group_member_ids(self, g, group_id: str) -> list[str]:
        with client(self.transport) as c:
            self._ensure(c, g)
            return [m["id"] for m in self._pages(c, g, f"{DIRECTORY}/groups/{quote(group_id)}/members?includeDerivedMembership=true", "members", "Reading group members") if m.get("id")]

    def revoke(self, g) -> None:
        token = g.get("refresh_token") or g.get("access_token")
        if not token:
            return
        with client(self.transport) as c:
            try:
                request(c, "POST", REVOKE, "Revoking access", data={"token": token}, headers={"Content-Type": "application/x-www-form-urlencoded"})
            except ProviderError:
                pass  # the token is deleted here either way
