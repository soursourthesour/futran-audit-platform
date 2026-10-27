"""The employee AI audit and data notice (package item 5, checklist item 6).

The Chief AI Compliance Officer may edit the notice and sends it to every person on People > Users. Sending completes
the checklist item, which is what opens the attestation campaign. Each person with a login then reads and acknowledges
the version sent, on a blocking page at their next sign-in. A new version sent later must be acknowledged again.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.documents.render import render_markdown
from app.engagements.models import Engagement
from app.initiation.models import NoticeAcknowledgement, NoticeRelease, PackageDocument
from app.initiation.service import _write_files, current_package
from app.tenancy.models import Organization, User

NOTICE_ITEM = 5
CLOSED = ("completed", "archived")


def notice_document(db: Session, e: Engagement) -> PackageDocument | None:
    pkg = current_package(db, e)
    if pkg is None or pkg.status != "sent":
        return None
    return db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == NOTICE_ITEM, PackageDocument.deleted_at.is_(None)))


def latest_release(db: Session, e: Engagement) -> NoticeRelease | None:
    return db.scalar(select(NoticeRelease).where(NoticeRelease.engagement_id == e.id, NoticeRelease.deleted_at.is_(None)).order_by(NoticeRelease.version.desc()).limit(1))


def recipients(db: Session, org_id: str) -> list[User]:
    """Everyone on People > Users: not removed and not deactivated."""
    return list(db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name)))


def acknowledgements(db: Session, release: NoticeRelease | None) -> dict[str, NoticeAcknowledgement]:
    if release is None:
        return {}
    return {a.user_id: a for a in db.scalars(select(NoticeAcknowledgement).where(NoticeAcknowledgement.release_id == release.id))}


def counts(db: Session, e: Engagement) -> dict | None:
    rel = latest_release(db, e)
    if rel is None:
        return None
    acks = acknowledgements(db, rel)
    people = recipients(db, e.client_id)
    done = sum(1 for u in people if u.id in acks)
    return {"acknowledged": done, "pending": len(people) - done, "version": rel.version}


def status_for(acks: dict[str, NoticeAcknowledgement], release: NoticeRelease | None, user: User) -> dict:
    if release is None:
        return {"status": "not_sent", "at": None, "version": None}
    a = acks.get(user.id)
    if a is not None:
        return {"status": "acknowledged", "at": a.acknowledged_at.isoformat(), "version": a.version}
    return {"status": "pending", "at": None, "version": release.version}


def _require_caico(user_roles: set[str]) -> None:
    if "caico" not in user_roles:
        raise Forbidden("Only the Chief AI Compliance Officer can change or send the employee data notice.")


def _require_open(e: Engagement) -> None:
    if e.status in CLOSED:
        raise Conflict("This engagement is closed. The notice can no longer be changed or sent.")


def edit(db: Session, settings: Settings, actor: User, roles: set[str], e: Engagement, body_md: str) -> PackageDocument:
    _require_caico(roles)
    _require_open(e)
    doc = notice_document(db, e)
    if doc is None:
        raise NotFound()
    if not (body_md or "").strip():
        raise Invalid(errors=[{"field": "body_md", "message": "The notice cannot be empty."}])
    if len(body_md) > 100_000:
        raise Invalid(errors=[{"field": "body_md", "message": "The notice is too long. Keep it under 100,000 characters."}])
    before = doc.body_md
    if body_md == before:
        return doc
    doc.body_md, doc.edited, doc.updated_by = body_md, True, actor.id
    _write_files(db, settings, actor, e, doc)
    audit.record(db, actor_id=actor.id, action="notice.edit", obj=doc, before={"body_md": before[:2000]}, after={"body_md": body_md[:2000]}, summary="Edited the employee AI audit and data notice")
    return doc


def _acknowledge(db: Session, user: User, release: NoticeRelease, summary: str) -> NoticeAcknowledgement:
    now = utcnow()
    a = NoticeAcknowledgement(organization_id=release.organization_id, release_id=release.id, engagement_id=release.engagement_id, user_id=user.id, version=release.version, acknowledged_at=now, created_by=user.id)
    db.add(a)
    db.flush()
    audit.record(db, actor_id=user.id, action="notice.acknowledge", obj=a, after={"user_id": user.id, "version": release.version, "release_id": release.id, "acknowledged_at": now.isoformat()}, summary=summary)
    return a


def send(db: Session, settings: Settings, actor: User, roles: set[str], e: Engagement) -> NoticeRelease:
    """Email the current notice to every person on People > Users and complete checklist item 6."""
    from app.mail.service import send as send_mail
    from app.policy.roles import ROLE_LABELS

    _require_caico(roles)
    _require_open(e)
    doc = notice_document(db, e)
    if doc is None:
        raise NotFound()
    prev = latest_release(db, e)
    version = (prev.version + 1) if prev else 1
    people = recipients(db, e.client_id)
    rel = NoticeRelease(organization_id=e.client_id, engagement_id=e.id, document_id=doc.id, version=version, title=doc.title, body_md=doc.body_md, sent_at=utcnow(), sent_by=actor.id, recipient_count=len(people), created_by=actor.id)
    db.add(rel)
    db.flush()
    org = db.get(Organization, e.client_id)
    notice_html = render_markdown(doc.body_md)
    for u in people:
        send_mail(db, settings, "employee_data_notice", to=[u.email], organization_id=e.client_id, related=rel, actor_id=actor.id, context={
            "name": u.name, "client": org.name, "sender": actor.name, "sender_role": ROLE_LABELS["caico"], "version": version,
            "has_login": bool(u.password_hash), "link": f"{settings.base_url}/login", "notice_html": notice_html, "notice_text": doc.body_md,
        })
    if doc.completed_at is None:
        doc.completed_at, doc.completed_by = utcnow(), actor.id
        audit.record(db, actor_id=actor.id, action="package.item_done", obj=doc, summary=f"{actor.name} completed: {doc.title}")
    audit.record(db, actor_id=actor.id, action="notice.send", obj=rel, after={"version": version, "recipients": len(people)},
                 summary=f"Sent version {version} of the employee AI audit and data notice to {len(people)} {'person' if len(people) == 1 else 'people'}")
    if actor.organization_id == e.client_id:
        _acknowledge(db, actor, rel, f"{actor.name} acknowledged version {version} of the employee data notice by sending it")
    return rel


def pending_for(db: Session, user: User) -> NoticeRelease | None:
    """The notice version this client user still has to acknowledge, if any."""
    from app.tenancy.people import current_engagement

    org = db.get(Organization, user.organization_id)
    if org is None or org.type != "client":
        return None
    e = current_engagement(db, org)
    if e is None or e.status in CLOSED:
        return None
    rel = latest_release(db, e)
    if rel is None:
        return None
    done = db.scalar(select(func.count()).select_from(NoticeAcknowledgement).where(NoticeAcknowledgement.release_id == rel.id, NoticeAcknowledgement.user_id == user.id))
    return None if done else rel


def acknowledge(db: Session, user: User, version: int, accepted: bool) -> NoticeAcknowledgement:
    if not accepted:
        raise Invalid(errors=[{"field": "accepted", "message": "Tick the box to confirm you have read and understood the notice."}])
    rel = pending_for(db, user)
    if rel is None:
        raise Conflict("There is no notice waiting for you to acknowledge.")
    if rel.version != version:
        raise Conflict("A newer version of the notice has been sent. Read the current version and acknowledge that.")
    return _acknowledge(db, user, rel, f"{user.name} read and acknowledged version {rel.version} of the employee data notice")
