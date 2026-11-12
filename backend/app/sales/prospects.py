"""Prospects (spec §4.3 rules 1-2, §4.8 item 1).

A prospect is an `Organization` with `status = "prospect"`. It is also stored with `type = "prospect"`, so every client
list and every client endpoint (which accept only `type == "client"`) leaves it out: it has no tenant data, no users and
no login. On a win the handoff (R5, `commercial.handoff`) converts it with `convert_to_client`, which makes it a normal
`draft` client with a client reference, as if added through the New Client wizard.

The duplicate check compares the company name (ignoring case, punctuation and legal suffixes), the website domain and
contact emails against clients and prospects."""
import re
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.tenancy.models import Organization

PROSPECT = "prospect"
SUFFIXES = {"llc", "inc", "incorporated", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "llp", "lp", "pllc", "group", "holdings", "the", "services",
            "solutions", "pvt", "private", "gmbh", "sa", "ag", "bv"}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "proton.me", "protonmail.com", "live.com", "msn.com"}


def is_prospect(org: Organization | None) -> bool:
    return org is not None and (org.status == PROSPECT or org.type == PROSPECT)


def kind_of(org: Organization | None) -> str:
    return "prospect" if is_prospect(org) else "client"


def name_key(name: str | None) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").casefold().replace("&", " and "))
    core = [w for w in words if w not in SUFFIXES]
    return " ".join(core or words)


def domain_of(value: str | None) -> str | None:
    """acmestaffing.com from a website, a bare domain or an email address."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if "@" in v and "/" not in v:
        v = v.rsplit("@", 1)[1]
    if "://" not in v:
        v = "http://" + v
    host = (urlparse(v).hostname or "").removeprefix("www.")
    return host or None


def _orgs(db: Session) -> list[Organization]:
    return list(db.scalars(select(Organization).where(Organization.type.in_(("client", PROSPECT)), Organization.deleted_at.is_(None), Organization.is_internal.is_(False))))


def find_duplicates(db: Session, *, name: str | None = None, website: str | None = None, emails: list[str] | None = None, exclude_id: str | None = None) -> list[dict]:
    """Clients and prospects that may be the same company, each with the reason."""
    from app.engagements.models import ClientContact
    from app.sales.models import Opportunity, OpportunityContact

    key = name_key(name) if name else ""
    dom = domain_of(website)
    mails = {e.strip().lower() for e in emails or [] if e and "@" in e}
    mail_domains = {domain_of(e) for e in mails} - FREE_MAIL - {None}
    by_id: dict[str, dict] = {}

    def hit(org: Organization, reason: str) -> None:
        if org.id == exclude_id:
            return
        row = by_id.setdefault(org.id, {"organization_id": org.id, "name": org.name, "kind": kind_of(org), "website": org.website, "reasons": []})
        if reason not in row["reasons"]:
            row["reasons"].append(reason)

    for org in _orgs(db):
        odom = domain_of(org.website)
        if key and name_key(org.name) == key:
            hit(org, "same name")
        elif key and len(key) >= 4 and (name_key(org.name).startswith(key + " ") or key.startswith(name_key(org.name) + " ")) and len(name_key(org.name)) >= 4:
            hit(org, "similar name")
        if odom and dom and odom == dom:
            hit(org, f"same domain {dom}")
        if odom and odom in mail_domains:
            hit(org, f"contact email at {odom}")
    if mails:
        rows = db.execute(select(Opportunity.organization_id, OpportunityContact.email).join(Opportunity, Opportunity.id == OpportunityContact.opportunity_id).where(
            func.lower(OpportunityContact.email).in_(mails), OpportunityContact.deleted_at.is_(None))).all()
        rows += db.execute(select(ClientContact.organization_id, ClientContact.email).where(func.lower(ClientContact.email).in_(mails), ClientContact.deleted_at.is_(None))).all()
        for org_id, email in rows:
            org = db.get(Organization, org_id)
            if org is not None and org.deleted_at is None and org.type in ("client", PROSPECT):
                hit(org, f"contact {email.lower()} already on file")
    out = []
    for row in by_id.values():
        open_opp = db.scalar(select(Opportunity.id).where(Opportunity.organization_id == row["organization_id"], Opportunity.stage.not_in(("won", "lost"))).limit(1))
        out.append(row | {"reason": ", ".join(row.pop("reasons")), "open_opportunity_id": open_opp})
    return sorted(out, key=lambda r: r["name"].casefold())


def create_prospect(db: Session, *, name: str, actor_id: str | None = None, **fields) -> Organization:
    oid = new_id()
    org = Organization(id=oid, organization_id=oid, name=name.strip()[:200], type=PROSPECT, status=PROSPECT, created_by=actor_id, updated_by=actor_id,
                       **{k: v for k, v in fields.items() if v not in (None, "")})
    db.add(org)
    db.flush()
    return org


def convert_to_client(db: Session, org: Organization) -> bool:
    """Prospect → `draft` client (spec §4.8 item 1). Returns whether it was a prospect. The R5 handoff calls this."""
    if not is_prospect(org):
        return False
    from app.tenancy.service import next_client_ref

    org.type, org.status = "client", "draft"
    if not org.client_ref:
        org.client_ref = next_client_ref(db)
    db.flush()
    return True
