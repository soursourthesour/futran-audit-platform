"""The free-text guard for the website library API (review, 26 Nov).

The serializers in app.library.content leave out every field that ties a record to a client. Free text is another
matter: a staff member or a refresh reviewer can type a client's name into a version's change summary, a case's stage
note or a source address, and it would go to the website as typed. So before a response is served, every display
string in it is checked against the names of client and prospect organizations (name, legal name and trading name;
whole words, any case; spaces in a name also match hyphens, underscores, dots, plus signs and %20, as in web
addresses), and each match is replaced with "[client]". A warning names the record and field, never the text, so
staff can correct the record.

Machine values (ids, codes, enum values such as a stage or status) are not display text and are left alone, so filters
and links keep working.
"""
import logging
import re
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.tenancy.models import Organization

log = logging.getLogger("app.library")

PLACEHOLDER = "[client]"
ORG_TYPES = ("client", "prospect")
MIN_NAME = 3
NAMES_SECONDS = 60
SKIP_KEYS = {"id", "status", "stage", "type", "region", "kind", "level", "code", "role", "actor", "answer_type", "prefill_from", "committee_type",
             "needed_by_stage", "applies_to", "topics", "ai_types", "jurisdiction_code", "origin", "value", "sort", "in_scope_rule", "requirements",
             "regulation_ids", "requirement_ids", "control_ids", "question_ids"}
SEP = r"(?:[\s\-_+.]|%20)+"
_LOCK = threading.Lock()


def names_fingerprint(db: Session) -> tuple:
    return tuple(db.execute(select(func.count(Organization.id), func.max(Organization.updated_at), func.max(Organization.created_at))
                            .where(Organization.type.in_(ORG_TYPES))).one())


def _names(db: Session) -> list[str]:
    rows = db.execute(select(Organization.name, Organization.legal_name, Organization.trading_name)
                      .where(Organization.type.in_(ORG_TYPES), Organization.deleted_at.is_(None), Organization.is_internal.is_(False))).all()
    out = {n.strip() for row in rows for n in row if n and len(n.strip()) >= MIN_NAME}
    return sorted(out, key=lambda n: (-len(n), n.casefold()))  # longest first, so a full name wins over a shorter one inside it


def _pattern(names: list[str]) -> re.Pattern | None:
    if not names:
        return None
    alts = [SEP.join(re.escape(part) for part in n.split()) for n in names]
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE)


def pattern(state, db: Session) -> re.Pattern | None:
    """The compiled client-name pattern, kept on the app state until a client or prospect is added or changed, and at
    most NAMES_SECONDS in any case."""
    fp = names_fingerprint(db)
    now = time.monotonic()
    with _LOCK:
        hit = state.__dict__.get("_library_names")
    if hit is None or hit[0] != fp or now - hit[1] > NAMES_SECONDS:
        hit = (fp, now, _pattern(_names(db)))
        with _LOCK:
            state.__dict__["_library_names"] = hit
    return hit[2]


def scrub(body, rx: re.Pattern | None, endpoint: str):
    """Replace client names in every display string of a response body. Returns the body (changed in place)."""
    if rx is None:
        return body
    found: list[tuple[str | None, str]] = []

    def walk(value, key: str | None, path: str, record: str | None):
        if isinstance(value, dict):
            rec = value.get("id") if isinstance(value.get("id"), str) else record
            for k, v in value.items():
                value[k] = walk(v, k, f"{path}.{k}" if path else k, rec)
            return value
        if isinstance(value, list):
            for i, v in enumerate(value):
                value[i] = walk(v, key, f"{path}[{i}]", record)
            return value
        if isinstance(value, str) and key not in SKIP_KEYS and not (key or "").endswith(("_id", "_ids")):
            new, n = rx.subn(PLACEHOLDER, value)
            if n:
                found.append((record, path))
                return new
        return value

    walk(body, None, "", None)
    for record, path in found:
        log.warning("Website library API: a client name was replaced in %s, record %s, field %s. Correct the record in the platform.", endpoint, record or "-", path)
    return body
