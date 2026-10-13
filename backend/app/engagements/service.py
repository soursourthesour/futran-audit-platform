"""Engagements: creation, client locations and the status state machine (spec §7)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid
from app.engagements.models import ClientLocation, Engagement
from app.policy.sod import assert_not_self_approval
from app.reference.jurisdictions import resolve_jurisdictions
from app.tenancy.models import Organization, User

STATUS_LABELS = {
    "draft": "Draft",
    "pending_approval": "Awaiting approval",
    "initiated": "Initiated",
    "in_progress": "In progress",
    "completed": "Completed",
    "archived": "Archived",
}
ALLOWED = {
    "draft": {"pending_approval"},
    "pending_approval": {"initiated", "draft"},  # approve, or return to the author with a comment
    "initiated": {"in_progress"},
    "in_progress": {"completed"},
    "completed": {"archived"},
    "archived": set(),
}
TYPES = ("initial_assessment", "ll144_bias_audit", "annual_review")


def next_audit_ref(db: Session) -> str:
    prefix = f"FSL-AI-AUD-{today().year}-"
    refs = db.scalars(select(Engagement.audit_ref).where(Engagement.audit_ref.like(f"{prefix}%"))).all()
    highest = max((int(r.rsplit("-", 1)[1]) for r in refs if r), default=0)
    return f"{prefix}{highest + 1:03d}"


def create_engagement(db: Session, actor: User, client: Organization, *, name: str, type: str = "initial_assessment", **fields) -> Engagement:
    if type not in TYPES:
        raise Invalid(errors=[{"field": "type", "message": "Choose an engagement type."}])
    e = Engagement(organization_id=client.id, client_id=client.id, name=name, type=type, audit_ref=next_audit_ref(db), status="draft", stage=1, created_by=actor.id, updated_by=actor.id, **fields)
    db.add(e)
    db.flush()
    audit.record(db, actor_id=actor.id, action="engagement.create", obj=e, summary=f"Started engagement {e.audit_ref} as a draft")
    return e


def add_location(
    db: Session,
    org: Organization,
    *,
    site_name: str,
    country_code: str,
    subdivision_code: str | None = None,
    city: str | None = None,
    street: str | None = None,
    employees_at_site: int | None = None,
    in_scope: bool = True,
    actor_id: str | None = None,
) -> ClientLocation:
    js = resolve_jurisdictions(db, country_code, subdivision_code, city)
    if not js:
        raise Invalid(errors=[{"field": "country_code", "message": "Choose a country."}])
    state = next((j for j in js if j.level == "state"), None)
    loc = ClientLocation(
        organization_id=org.id, site_name=site_name.strip(), street=street, city=city, country_code=country_code.upper(),
        subdivision_code=state.code if state else (subdivision_code or None), employees_at_site=employees_at_site,
        in_scope=in_scope, jurisdiction_ids=[j.id for j in js], created_by=actor_id,
    )
    db.add(loc)
    db.flush()
    return loc


def transition(db: Session, actor: User, engagement: Engagement, to_status: str, comment: str | None = None) -> Engagement:
    """Move an engagement along `draft → pending_approval → initiated → in_progress → completed → archived`.
    `pending_approval → draft` returns it to the author and needs a comment."""
    frm = engagement.status
    if to_status not in ALLOWED.get(frm, set()):
        raise Conflict(f"An engagement in {STATUS_LABELS.get(frm, frm)} cannot move to {STATUS_LABELS.get(to_status, to_status)}.")
    before = {"status": frm}
    if frm == "pending_approval" and to_status == "draft":
        if not (comment or "").strip():
            raise Invalid("Say what the author needs to change.", [{"field": "comment", "message": "Add a comment for the author."}])
        engagement.returned_comment = comment.strip()
    if to_status == "initiated":
        assert_not_self_approval(actor.id, engagement.created_by)
        engagement.approved_by, engagement.approved_at, engagement.returned_comment = actor.id, utcnow(), None
    if to_status == "completed":
        engagement.completed_at = utcnow()
    engagement.status = to_status
    engagement.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action=f"engagement.{to_status}", obj=engagement, before=before, after={"status": to_status, "comment": comment}, summary=f"{engagement.audit_ref}: {STATUS_LABELS[frm]} → {STATUS_LABELS[to_status]}")
    return engagement
