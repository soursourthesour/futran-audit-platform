"""Jurisdiction tree: supranational → country → state/province → city (schematic D4, §6)."""
import re
import unicodedata
from pathlib import Path

import pycountry
import yaml
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.reference.models import Jurisdiction, JurisdictionMembership

SEEDS = Path(__file__).resolve().parents[2] / "seeds"

# Built-in cities that carry their own laws. Admin can add more.
BUILTIN_CITIES = [
    {
        "code": "US-NYC",
        "name": "New York City",
        "parent": "US-NY",
        "aliases": ["New York", "New York City", "NYC", "Manhattan", "Brooklyn", "Queens", "Bronx", "The Bronx", "Staten Island"],
    },
]


def norm(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def seed_iso(db: Session) -> str:
    """Load every country and first-level subdivision from ISO 3166, plus the EU and built-in cities. Idempotent."""
    existing = set(db.scalars(select(Jurisdiction.code)))
    by_code: dict[str, str] = dict(db.execute(select(Jurisdiction.code, Jurisdiction.id)).all())
    rows = []

    def add(code, name, level, parent_code=None, iso=None, aliases=None):
        if code in existing:
            return
        jid = new_id()
        by_code[code] = jid
        existing.add(code)
        rows.append({"id": jid, "code": code, "name": name, "level": level, "parent_id": by_code.get(parent_code) if parent_code else None, "iso_code": iso, "aliases": aliases, "has_laws": False, "active": True})

    add("EU", "European Union", "supranational", aliases=["European Union", "EU"])
    for c in pycountry.countries:
        aliases = [getattr(c, "common_name", None), getattr(c, "official_name", None)]
        add(c.alpha_2, getattr(c, "common_name", None) or c.name, "country", iso=c.alpha_2, aliases=[a for a in aliases if a])
    # parents before children: top-level subdivisions first
    subs = sorted(pycountry.subdivisions, key=lambda s: (s.parent_code is not None, s.code))
    for s in subs:
        parent = s.parent_code if s.parent_code else s.country_code
        add(s.code, s.name, "state", parent_code=parent, iso=s.code)
    if rows:
        db.execute(insert(Jurisdiction), rows)
    for city in BUILTIN_CITIES:
        upsert_city(db, city["parent"], city["name"], code=city["code"], aliases=city["aliases"])
    eu_members = yaml.safe_load((SEEDS / "eu_members.yaml").read_text())["members"]
    eu_id = by_code["EU"]
    have = set(db.scalars(select(JurisdictionMembership.member_id).where(JurisdictionMembership.group_id == eu_id)))
    for code in eu_members:
        mid = by_code.get(code)
        if mid and mid not in have:
            db.add(JurisdictionMembership(member_id=mid, group_id=eu_id))
    db.flush()
    return f"{len(rows)} jurisdictions added"


def by_code(db: Session, code: str) -> Jurisdiction | None:
    return db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))


def upsert_city(db: Session, state_code: str, name: str, *, code: str | None = None, aliases: list[str] | None = None, actor_id: str | None = None) -> Jurisdiction:
    state = by_code(db, state_code)
    if state is None:
        raise ValueError(f"Unknown state or province {state_code}")
    code = code or f"{state_code}-{re.sub(r'[^A-Z0-9]+', '', norm(name).upper())}"
    j = by_code(db, code)
    if j is None:
        j = Jurisdiction(code=code, name=name, level="city", parent_id=state.id, aliases=aliases or [name], updated_by=actor_id)
        db.add(j)
    else:
        j.aliases = sorted(set((j.aliases or []) + (aliases or [])))
    db.flush()
    return j


def _find_subdivision(db: Session, country: Jurisdiction, subdivision: str | None) -> Jurisdiction | None:
    if not subdivision:
        return None
    j = by_code(db, subdivision.upper())
    if j is not None and j.level == "state":
        return j
    target = norm(subdivision)
    for s in db.scalars(select(Jurisdiction).where(Jurisdiction.level == "state", Jurisdiction.code.like(f"{country.code}-%"))):
        if norm(s.name) == target or target in {norm(a) for a in (s.aliases or [])}:
            return s
    return None


def _find_city(db: Session, state: Jurisdiction, city: str | None) -> Jurisdiction | None:
    if not city:
        return None
    target = norm(city)
    for c in db.scalars(select(Jurisdiction).where(Jurisdiction.level == "city", Jurisdiction.parent_id == state.id)):
        if norm(c.name) == target or target in {norm(a) for a in (c.aliases or [])}:
            return c
    return None


def resolve_jurisdictions(db: Session, country: str, subdivision: str | None = None, city: str | None = None) -> list[Jurisdiction]:
    """Every jurisdiction whose laws reach a site: city, state, country, then supranational groups."""
    c = by_code(db, (country or "").upper())
    if c is None:
        return []
    out: list[Jurisdiction] = []
    state = _find_subdivision(db, c, subdivision)
    if state is not None:
        # walk up nested subdivisions to the country
        chain = [state]
        while chain[-1].parent_id and chain[-1].parent_id != c.id:
            parent = db.get(Jurisdiction, chain[-1].parent_id)
            if parent is None:
                break
            chain.append(parent)
        city_j = _find_city(db, state, city)
        if city_j:
            out.append(city_j)
        out.extend(chain)
    out.append(c)
    groups = db.scalars(
        select(Jurisdiction).join(JurisdictionMembership, JurisdictionMembership.group_id == Jurisdiction.id).where(JurisdictionMembership.member_id == c.id)
    )
    out.extend(groups)
    return out
