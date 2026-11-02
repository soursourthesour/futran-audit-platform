"""In-process fake of every discovery connector, for tests, the demo and the browser tests. Nothing leaves the process.

Consent: the fake consent page (/integrations/test-consent) posts back the domain the admin signs in with; like the real
providers, the tenant's verified domains come from the provider side (FAKE.tenants), not from the platform. Okta: any
client secret except "wrong" works, and the org's users are in the domain given in FAKE.okta_orgs or, by default, the
Okta subdomain's company (abccorp.okta.com -> abccorp.example).
Signals: FAKE.signals[(type, tenant)] when a test sets them, else a small sample for the tenant's first domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from app.connectors.adapters import ConnectorError
from app.connectors.signals import Signal

FIRST = ["Ana", "Ben", "Chloe", "Daniel", "Elena", "Farid", "Grace", "Hiro", "Isabel", "Jamal", "Kavya", "Liam", "Maya", "Noah", "Olivia", "Priya", "Quinn", "Rafael",
         "Sara", "Tomas", "Uma", "Victor", "Wen", "Ximena", "Yusuf", "Zara", "Aiden", "Bianca", "Carlos", "Dana"]
LAST = ["Ruiz", "Okafor", "Martin", "Kim", "Rossi", "Haddad", "Nguyen", "Tanaka", "Silva", "Brooks", "Iyer", "Walsh", "Cohen", "Patel", "Reyes", "Shah", "Foster", "Lima",
        "Novak", "Berg", "Rao", "Costa", "Li", "Torres", "Aydin", "Ahmed", "Clarke", "Moretti", "Vega", "Ellis"]


@dataclass
class FakeConnectorWorld:
    tenants: dict[str, list[str]] = field(default_factory=dict)  # tenant id -> verified domains
    okta_orgs: dict[str, list[str]] = field(default_factory=dict)  # okta domain -> the email domains of its users
    signals: dict[tuple[str, str], list[Signal]] = field(default_factory=dict)  # (type, tenant) -> what a sync reads
    fail_next: int = 0
    revoked: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        self.tenants.clear()
        self.okta_orgs.clear()
        self.signals.clear()
        self.revoked.clear()
        self.fail_next = 0


FAKE = FakeConnectorWorld()


def people(domain: str, start: int, n: int) -> list[tuple[str, str]]:
    out = []
    for i in range(start, start + n):
        f, l = FIRST[i % len(FIRST)], LAST[(i * 7) % len(LAST)]
        out.append((f"{f.lower()}.{l.lower()}@{domain}", f"{f} {l}"))
    return out


def sample(ctype: str, domain: str) -> list[Signal]:
    """A plausible default for a tenant nobody configured: a few AI products across departments."""
    def many(key, signal, dept, start, n, detail=None):
        return [Signal(key, signal, dept, e, nm, detail=detail) for e, nm in people(domain, start, n)]

    if ctype == "okta":
        return many("hirevue", "sso_app", "HR", 0, 14) + many("grammarly", "oauth_grant", "HR", 14, 4, "okta.users.read.self")
    if ctype == "google_workspace":
        return many("otter", "oauth_grant", "Sales & Marketing", 3, 11, "calendar, drive") + many("google_gemini", "licence", "Finance", 20, 6)
    if ctype == "entra_id":
        return many("openai_chatgpt", "oauth_grant", "Finance", 8, 3, "User.Read") + many("fireflies", "oauth_grant", "Sales & Marketing", 12, 2, "Calendars.Read")
    if ctype == "microsoft_365":
        return many("microsoft_copilot", "licence", "Finance", 0, 9) + many("microsoft_copilot", "licence", "Sales & Marketing", 9, 12)
    return []


class FakeAdapter:
    def __init__(self, ctype: str, settings=None):
        self.type = ctype
        self.s = settings

    def scopes(self) -> list[str]:
        if self.type == "okta":
            from app.connectors.adapters.okta import SCOPES
        elif self.type == "google_workspace":
            from app.connectors.adapters.google import SCOPES
        else:
            from app.connectors.adapters.microsoft import PERMISSIONS

            return list(PERMISSIONS[self.type])
        return list(SCOPES)

    # ---- OAuth (Entra ID, Microsoft 365, Google Workspace)
    def consent_url(self, *, state: str, login_hint: str | None = None, tenant: str | None = None) -> str:
        base = self.s.base_url if self.s is not None else ""
        q = {"type": self.type, "state": state}
        if login_hint:
            q["login_hint"] = login_hint
        return f"{base}/integrations/test-consent?{urlencode(q)}"

    def complete_consent(self, *, params: dict) -> dict:
        if params.get("error"):
            raise ConnectorError("Access was not granted.")
        domain = (params.get("domain") or "").strip().lower() or "example.com"
        tenant = str(params.get("tenant") or "")
        if tenant and tenant in FAKE.tenants:
            domains = list(FAKE.tenants[tenant])
        else:
            tenant, domains = f"fake-tenant-{domain}", [domain]
        return {"fake": True, "tenant": tenant, "domains": domains, "account": params.get("login_hint") or f"admin@{domain}", "access_token": "fake-access",
                "refresh_token": "fake-refresh"}

    # ---- Okta
    def connect(self, *, domain: str, client_id: str, client_secret: str) -> dict:
        if client_secret == "wrong":
            raise ConnectorError("Okta refused the client ID and secret (401). Check them in the Futran integration in your Okta Admin Console.", status=401)
        sub = domain.split(".", 1)[0]
        domains = FAKE.okta_orgs.get(domain) or [f"{sub}.example"]
        return {"fake": True, "tenant": domain, "domains": domains, "client_id": client_id, "client_secret": client_secret}

    # ---- every type
    def collect(self, grant: dict) -> list[Signal]:
        if FAKE.fail_next > 0:
            FAKE.fail_next -= 1
            raise ConnectorError("Simulated provider failure (503).", status=503)
        key = (self.type, grant.get("tenant") or "")
        if key in FAKE.signals:
            return list(FAKE.signals[key])
        return sample(self.type, (grant.get("domains") or ["example.com"])[0])

    def revoke(self, grant: dict) -> None:
        FAKE.revoked.append({"type": self.type, "tenant": grant.get("tenant")})
