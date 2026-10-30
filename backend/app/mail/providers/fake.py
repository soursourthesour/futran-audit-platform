"""In-process fake of both providers, for tests and the demo. It keeps sent messages, lets a test add replies to a
thread, and serves a small directory for any domain. Nothing leaves the process."""
import itertools
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode

from app.core.clock import utcnow
from app.mail.providers import DirectoryEntry, DirectoryGroupEntry, IncomingMessage, OutgoingMessage, ProviderError, SentMessage

FIRST = ["Ana", "Ben", "Chloe", "Daniel", "Elena", "Farid", "Grace", "Hiro", "Isabel", "Jamal", "Kavya", "Liam", "Maya", "Noah", "Olivia", "Priya", "Quinn", "Rafael",
         "Sara", "Tomas", "Uma", "Victor", "Wen", "Ximena", "Yusuf", "Zara", "Aiden", "Bianca", "Carlos", "Dana", "Ethan", "Fatima", "Gabriel", "Hana", "Ivan", "Julia"]
LAST = ["Ruiz", "Okafor", "Martin", "Kim", "Rossi", "Haddad", "Nguyen", "Tanaka", "Silva", "Brooks", "Iyer", "Walsh", "Cohen", "Patel", "Reyes", "Shah", "Foster", "Lima",
        "Novak", "Berg", "Rao", "Costa", "Li", "Torres", "Aydin", "Ahmed", "Clarke", "Moretti", "Vega", "Ellis", "Wright", "Hassan", "Dubois", "Sato", "Petrov", "Klein"]
DEPARTMENTS = ["Human Resources", "Finance", "Operations", "Sales and Marketing", "Engineering and IT", "Legal"]
TITLES = {"Human Resources": "HR Business Partner", "Finance": "Financial Analyst", "Operations": "Operations Manager", "Sales and Marketing": "Account Executive",
          "Engineering and IT": "Software Engineer", "Legal": "Counsel"}


@dataclass
class FakeSent:
    thread_id: str
    message_id: str
    message: OutgoingMessage
    at: datetime


@dataclass
class FakeWorld:
    sent: list[FakeSent] = field(default_factory=list)
    replies: dict[str, list[IncomingMessage]] = field(default_factory=dict)
    directories: dict[str, tuple[list[DirectoryEntry], list[DirectoryGroupEntry]]] = field(default_factory=dict)
    fail_next: int = 0  # the next N sends fail (retry tests)
    _ids = itertools.count(1)

    def reset(self) -> None:
        self.sent.clear()
        self.replies.clear()
        self.directories.clear()
        self.fail_next = 0

    def add_reply(self, thread_id: str, *, from_address: str, subject: str, body: str, auto_reply: bool = False, at: datetime | None = None) -> IncomingMessage:
        m = IncomingMessage(message_id=f"fake-in-{next(self._ids)}", from_address=from_address.lower(), subject=subject, snippet=body[:500], received_at=at or utcnow(), auto_reply=auto_reply)
        self.replies.setdefault(thread_id, []).append(m)
        return m

    def set_directory(self, domain: str, people: list[DirectoryEntry], groups: list[DirectoryGroupEntry]) -> None:
        self.directories[domain.lower()] = (people, groups)

    def directory(self, domain: str) -> tuple[list[DirectoryEntry], list[DirectoryGroupEntry]]:
        domain = (domain or "example.com").lower()
        if domain not in self.directories:
            self.directories[domain] = _sample_directory(domain)
        return self.directories[domain]


def _sample_directory(domain: str) -> tuple[list[DirectoryEntry], list[DirectoryGroupEntry]]:
    groups = [DirectoryGroupEntry("dg-all-staff", "All Staff"), DirectoryGroupEntry("dg-hr-team", "HR Team"), DirectoryGroupEntry("dg-nyc-recruiting", "NYC-Recruiting"),
              DirectoryGroupEntry("dg-contractors", "Contractors")]
    people = []
    for i, (first, last) in enumerate(zip(FIRST, LAST)):
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        guest = i >= 33  # the last three are contractors (guests)
        office = "New York" if i % 3 == 0 else ("Edison" if i % 3 == 1 else "Chicago")
        ids = ["dg-contractors"] if guest else ["dg-all-staff"]
        if dept == "Human Resources" and not guest:
            ids.append("dg-hr-team")
            if office == "New York":
                ids.append("dg-nyc-recruiting")
        people.append(DirectoryEntry(directory_id=f"fake-u{i + 1:03d}", email=f"{first.lower()}.{last.lower()}@{domain}", name=f"{first} {last}", department=dept,
                                     job_title=TITLES[dept], manager_id="fake-u001" if i else None, office=office, is_guest=guest, group_ids=ids))
    for g in groups:
        g.member_count = sum(1 for p in people if g.directory_id in p.group_ids)
    return people, groups


FAKE = FakeWorld()


class FakeAdapter:
    def __init__(self, provider: str, settings=None):
        self.provider = provider
        self.s = settings

    def scopes(self, kind: str) -> list[str]:
        from app.mail.providers.google import GoogleAdapter
        from app.mail.providers.microsoft import APP_PERMISSIONS, USER_SCOPES

        if self.provider == "microsoft365":
            return APP_PERMISSIONS if kind == "admin" else USER_SCOPES
        return GoogleAdapter.scopes(None, kind)  # type: ignore[arg-type]

    def consent_url(self, *, kind: str, state: str, tenant: str | None = None, login_hint: str | None = None) -> str:
        base = self.s.base_url if self.s is not None else ""
        q = {"provider": self.provider, "kind": kind, "state": state}
        if login_hint:
            q["login_hint"] = login_hint
        return f"{base}/mail/test-consent?{urlencode(q)}"

    def complete_consent(self, *, kind: str, params: dict) -> dict:
        from app.mail.tokens import Grant

        if params.get("error"):
            raise ProviderError("Access was not granted.")
        mailbox = (params.get("mailbox") or params.get("login_hint") or "").lower() or None
        domain = (params.get("domain") or (mailbox.split("@", 1)[1] if mailbox and "@" in mailbox else "example.com")).lower()
        return Grant({"fake": True, "kind": "app" if kind == "admin" and self.provider == "microsoft365" else "delegated", "tenant": f"fake-tenant-{domain}",
                      "domains": [domain], "mailbox": mailbox, "access_token": "fake-access", "refresh_token": "fake-refresh"})

    def send(self, g, m: OutgoingMessage) -> SentMessage:
        if FAKE.fail_next > 0:
            FAKE.fail_next -= 1
            raise ProviderError("Simulated provider failure.", retryable=True)
        n = next(FakeWorld._ids)
        s = FakeSent(thread_id=f"fake-thread-{n}", message_id=f"fake-msg-{n}", message=m, at=utcnow())
        FAKE.sent.append(s)
        return SentMessage(message_id=s.message_id, thread_id=s.thread_id)

    def thread_messages(self, g, mailbox: str, thread_id: str) -> list[IncomingMessage]:
        return list(FAKE.replies.get(thread_id, []))

    def _domain(self, g) -> str:
        return ((g.get("domains") or ["example.com"])[0]).lower()

    def list_people(self, g, *, scope_group: str | None, include_guests: bool) -> list[DirectoryEntry]:
        people, _ = FAKE.directory(self._domain(g))
        return [p for p in people if (include_guests or not p.is_guest) and (scope_group is None or scope_group in p.group_ids)]

    def list_groups(self, g) -> list[DirectoryGroupEntry]:
        return list(FAKE.directory(self._domain(g))[1])

    def group_member_ids(self, g, group_id: str) -> list[str]:
        return [p.directory_id for p in FAKE.directory(self._domain(g))[0] if group_id in p.group_ids]

    def revoke(self, g) -> None:
        return None
