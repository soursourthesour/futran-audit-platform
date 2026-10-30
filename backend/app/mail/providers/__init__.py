"""Mail provider adapters: Microsoft Graph, and Gmail plus the Admin SDK Directory API (spec §26.1).

Plain OAuth 2.0 over httpx; no Microsoft or Google client library. Each adapter has an in-process fake (fake.py) that
tests and the demo use: whenever EMAIL_MODE=outbox, or MAIL_PROVIDER_MODE=fake, nothing goes to the network.

Documentation checked on 30 October 2026 (also listed in the README):
- Microsoft admin consent: https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent
- Microsoft delegated (authorization code) flow: https://learn.microsoft.com/graph/auth-v2-user
- Graph create draft (returns id and conversationId): https://learn.microsoft.com/en-us/graph/api/user-post-messages
- Graph sendMail (202, no body; Mail.Send): https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-beta
- Limiting the app to one mailbox (RBAC for Applications in Exchange Online):
  https://office365itpros.com/2026/02/17/mail-send-rbac-for-applications/amp/
- Exchange Online sending limits (30 messages a minute, 10,000 recipients a day, 500 recipients a message):
  https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-sending-limits-troubleshoot
- Gmail scopes (gmail.send sensitive; gmail.modify restricted): https://developers.google.com/workspace/gmail/api/auth/scopes
- Google web-server OAuth (access_type=offline, prompt=consent): https://developers.google.com/accounts/docs/OAuth
- Workspace admins trusting an app (API controls): https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data
- Gmail sending limits (2,000 a day per user; 2,000 recipients a message, 500 external):
  https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace
- Admin SDK Directory service: https://developers.google.com/apps-script/advanced/admin-sdk-directory
"""
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import Settings

PROVIDERS = ("microsoft365", "google")
PROVIDER_LABELS = {"microsoft365": "Microsoft 365", "google": "Google Workspace"}


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class OutgoingMessage:
    from_address: str
    from_name: str
    reply_to: str | None
    to: list[str]
    bcc: list[str]
    subject: str
    html: str
    text: str


@dataclass
class SentMessage:
    message_id: str | None
    thread_id: str | None


@dataclass
class IncomingMessage:
    message_id: str
    from_address: str
    subject: str
    snippet: str
    received_at: datetime
    auto_reply: bool = False


@dataclass
class DirectoryEntry:
    directory_id: str
    email: str
    name: str
    department: str | None = None
    job_title: str | None = None
    manager_id: str | None = None
    office: str | None = None
    is_guest: bool = False
    enabled: bool = True
    group_ids: list[str] = field(default_factory=list)


@dataclass
class DirectoryGroupEntry:
    directory_id: str
    name: str
    member_count: int = 0


def redirect_uri(settings: Settings, provider: str) -> str:
    own = settings.ms_redirect_uri if provider == "microsoft365" else settings.google_redirect_uri
    return own or f"{settings.base_url}/api/v1/mail/oauth/{provider}"


def use_fake(settings: Settings) -> bool:
    mode = (settings.mail_provider_mode or "auto").lower()
    return mode == "fake" or (mode == "auto" and settings.email_mode == "outbox")


def credentials_status(settings: Settings) -> dict:
    """What is configured, what is missing, and the redirect URI IT must register, per provider."""
    ms_missing = [k for k, v in (("MS_CLIENT_ID", settings.ms_client_id), ("MS_CLIENT_SECRET", settings.ms_client_secret)) if not v]
    g_missing = [k for k, v in (("GOOGLE_CLIENT_ID", settings.google_client_id), ("GOOGLE_CLIENT_SECRET", settings.google_client_secret)) if not v]
    fake = use_fake(settings)
    return {
        "test_mode": fake,
        "microsoft365": {"configured": not ms_missing, "missing": ms_missing, "redirect_uri": redirect_uri(settings, "microsoft365"), "available": fake or not ms_missing},
        "google": {"configured": not g_missing, "missing": g_missing, "redirect_uri": redirect_uri(settings, "google"), "available": fake or not g_missing},
    }


def get_adapter(settings: Settings, provider: str | None):
    """The adapter for `provider`: the fake in test mode, the real one when its client ID and secret are set, else None
    (and email falls back to the outbox or SMTP)."""
    if provider not in PROVIDERS:
        return None
    if use_fake(settings):
        from app.mail.providers.fake import FakeAdapter

        return FakeAdapter(provider, settings)
    st = credentials_status(settings)[provider]
    if not st["configured"]:
        return None
    if provider == "microsoft365":
        from app.mail.providers.microsoft import MicrosoftGraphAdapter

        return MicrosoftGraphAdapter(settings)
    from app.mail.providers.google import GoogleAdapter

    return GoogleAdapter(settings)
