"""What a connector or upload reads, before it is stored: one `Signal` per person per AI product, aggregated to one
`Observation` per AI product × signal × department. Browsing data is aggregated with `keep_people=False`, so no person
leaves the parser."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    vendor_key: str
    signal: str  # sso_app | oauth_grant | licence | expense | traffic
    department: str | None
    person: str | None = None  # email, or a name when the source has no email
    person_name: str | None = None
    weight: int = 1  # requests (traffic) or transactions (expense)
    detail: str | None = None  # e.g. the OAuth scopes granted


@dataclass
class Observation:
    vendor_key: str
    signal: str
    department: str | None
    user_count: int
    count: int
    details: list[str] = field(default_factory=list)
    people: dict[str, str | None] | None = None  # person key -> display name; None for browsing data
    detail: str | None = None


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def aggregate(signals: list[Signal], *, keep_people: bool = True) -> list[Observation]:
    groups: dict[tuple[str, str, str], dict] = {}
    for s in signals:
        dept = " ".join((s.department or "").split()) or None
        key = (s.vendor_key, s.signal, (dept or "").casefold())
        g = groups.setdefault(key, {"dept": dept, "people": {}, "anon": 0, "count": 0, "details": set()})
        if s.person:
            p = s.person.strip().lower()
            g["people"].setdefault(p, s.person_name)
        else:
            g["anon"] += 1
        g["count"] += max(int(s.weight or 0), 0)
        if s.detail:
            g["details"].update(d.strip() for d in s.detail.split(",") if d.strip())
    out = []
    for (vendor_key, signal, _), g in groups.items():
        o = Observation(vendor_key, signal, g["dept"], len(g["people"]) + g["anon"], g["count"], sorted(g["details"]), dict(g["people"]) if keep_people else None)
        o.detail = describe(o)
        out.append(o)
    return out


def describe(o: Observation) -> str | None:
    """The short text shown beside the source: "6 paid subscriptions", "55 requests", or the scopes granted."""
    if o.signal == "expense":
        return _plural(o.user_count, "paid subscription", "paid subscriptions")
    if o.signal == "traffic":
        return _plural(o.count, "request", "requests")
    return ", ".join(o.details)[:300] if o.details else None
