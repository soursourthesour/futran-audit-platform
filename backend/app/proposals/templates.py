"""Proposal section templates (SM-14 Proposal templates tab, maintained by the Futran Admin; spec §4.6 "template
sections, editable").

The starter wording is plain and short; nothing in it is a price or a promise beyond the spec. Each new proposal copies
the current wording into its own sections, so later template edits never change a proposal already drafted."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Invalid, NotFound
from app.proposals.independence import STATEMENT
from app.proposals.models import ProposalTemplate

# key, title, starter body. Order is the document's order.
STARTER = [
    ("cover", "Cover", "Prepared for [Company] by [Rep name], Futran Solutions."),
    ("situation", "Your situation",
     "What you told us during scoping. We use it to size the work below; tell us if anything has changed."),
    ("services", "What we'll do", "Each service below says what you receive. The wording is written for [Company]."),
    ("deliverables", "Deliverables and timeline", "Timings are typical durations from the start of each service."),
    ("pricing", "Pricing", "Prices are in US dollars."),
    ("assumptions", "Assumptions",
     "This proposal is based on what you told us during scoping. If the scope changes, we agree the change in writing before the work changes."),
    ("terms", "Terms", "This proposal is valid until [Valid until]."),
    ("independence", "Independence statement", STATEMENT),
    ("acceptance", "Acceptance",
     "To accept, use the personal link in the email that came with this proposal. You can also request changes there. "
     "Questions? Reply to [Rep name]."),
]
KEYS = [k for k, _, _ in STARTER]
MERGE_FIELDS = ("Company", "Rep name", "Valid until", "Version", "Date")


def ensure(db: Session) -> None:
    have = {t.key for t in db.scalars(select(ProposalTemplate))}
    for i, (key, title, body) in enumerate(STARTER):
        if key not in have:
            db.add(ProposalTemplate(key=key, title=title, body=body, sort=i, is_starter=True))
    db.flush()


def all_templates(db: Session) -> list[ProposalTemplate]:
    ensure(db)
    return list(db.scalars(select(ProposalTemplate).order_by(ProposalTemplate.sort)))


def by_key(db: Session) -> dict[str, ProposalTemplate]:
    return {t.key: t for t in all_templates(db)}


def update(db: Session, actor, key: str, body: dict) -> ProposalTemplate:
    t = by_key(db).get(key)
    if t is None:
        raise NotFound()
    title = " ".join((body.get("title") if body.get("title") is not None else t.title).split())
    text = (body.get("body") if body.get("body") is not None else t.body).replace("\r\n", "\n").strip()
    if not title:
        raise Invalid(errors=[{"field": "title", "message": "Give the section a title."}])
    if len(text) > 8000:
        raise Invalid(errors=[{"field": "body", "message": "Keep the wording under 8,000 characters."}])
    unknown = sorted({m for m in re.findall(r"\[([A-Za-z ]+)\]", text) if m not in MERGE_FIELDS})
    if unknown:
        raise Invalid(errors=[{"field": "body", "message": f"Unknown merge field{'s' if len(unknown) != 1 else ''}: {', '.join('[' + u + ']' for u in unknown)}. "
                                                           f"Use {', '.join('[' + f + ']' for f in MERGE_FIELDS)}."}])
    if key in ("cover", "pricing", "acceptance", "independence") and body.get("active") is False:
        raise Invalid(errors=[{"field": "active", "message": "This section is always in the proposal."}])
    old = (t.title, t.body, t.active)
    t.title, t.body = title[:120], text
    if body.get("active") is not None:
        t.active = bool(body["active"])
    t.is_starter, t.updated_by, t.updated_at = False, actor.id, utcnow()
    db.flush()
    from app.audit_log import service as audit

    if old != (t.title, t.body, t.active):
        audit.record(db, actor_id=actor.id, action="proposal_template.update", organization_id=actor.organization_id, object_type="ProposalTemplate",
                     object_id=t.id, summary=f"Proposal template \"{t.title}\" changed")
    return t


def out(t: ProposalTemplate, names: dict | None = None) -> dict:
    return {"key": t.key, "title": t.title, "body": t.body, "sort": t.sort, "active": t.active, "is_starter": t.is_starter,
            "always": t.key in ("cover", "pricing", "acceptance", "independence"), "auto": AUTO.get(t.key),
            "updated_by": (names or {}).get(t.updated_by), "updated_at": t.updated_at.isoformat() if t.updated_at else None}


AUTO = {
    "cover": "Title, company, date and validity are added.",
    "situation": "Pre-filled for each proposal from the locked scoping questionnaire (trigger, locations, AI footprint).",
    "services": "One block per line, from each item's deliverables in the master price list; the rep can tailor it per proposal.",
    "deliverables": "A table of each service, what the client receives and the typical duration.",
    "pricing": "The pricing table: one-time, recurring year 1, discount, year-1 total, annual recurring after year 1, and optional roadmap items with no price.",
    "assumptions": "Added automatically: unknown answers, what each line includes, roadmap items excluded, manual-delivery notes.",
    "terms": "Validity, payment terms, contract term, SLA and data residency from the builder.",
    "independence": "Only when the opportunity's independence flag is set (rule I-4). Fixed wording.",
    "acceptance": "The acceptance block with the client's name and the authority statement.",
}
