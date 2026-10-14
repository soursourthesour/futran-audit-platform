"""Document request register: issue, receive, not available, chase and escalate (spec §18.5)."""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today as _today
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.docrequests.models import DocumentChase, DocumentRequest
from app.engagements.models import ClientContact, Engagement, EngagementTeam
from app.engagements.wizard import TEAM_ROLES
from app.findings.models import Finding
from app.notifications.service import notify
from app.reference.models import DocumentCatalogItem
from app.systems.models import AISystem
from app.systems.service import systems_for
from app.tenancy.models import Organization, User

DUE_BUSINESS_DAYS = 5
ESCALATE_AFTER = 3


# ---- business days (Monday to Friday; no holiday calendar in v1)
def business_days_between(a: date, b: date) -> int:
    """Business days after `a` up to and including `b`."""
    if b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def subtract_business_days(d: date, n: int) -> date:
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


# ---- issuing
def _applies(item: DocumentCatalogItem, facts) -> bool:
    return not item.condition or bool(facts.get(f"{item.condition}_in_scope"))


def _caico(db: Session, e: Engagement) -> tuple[str | None, str | None]:
    c = db.scalar(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == "caico", ClientContact.deleted_at.is_(None)))
    return (c.name, c.email) if c else (None, None)


def _team(db: Session, e: Engagement, role: str) -> list[User]:
    return list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == role, EngagementTeam.deleted_at.is_(None))))


def requests_for(db: Session, e: Engagement) -> list[DocumentRequest]:
    rows = db.execute(
        select(DocumentRequest, DocumentCatalogItem.order).join(DocumentCatalogItem, DocumentCatalogItem.id == DocumentRequest.catalog_item_id)
        .where(DocumentRequest.engagement_id == e.id, DocumentRequest.deleted_at.is_(None))
    )
    systems = {s.id: s.reference_id for s in systems_for(db, e)}
    return [r for r, _ in sorted(rows, key=lambda x: (x[1], systems.get(x[0].ai_system_id or "", "")))]


def _missing(db: Session, e: Engagement) -> list[tuple[DocumentCatalogItem, AISystem | None]]:
    from app.questionnaire.service import facts_for

    facts = facts_for(db, e)
    have = {(r.catalog_item_id, r.ai_system_id) for r in requests_for(db, e)}
    systems = systems_for(db, e)
    out = []
    for item in db.scalars(select(DocumentCatalogItem).order_by(DocumentCatalogItem.order)):
        if not _applies(item, facts):
            continue
        for s in (systems if item.per_system else [None]):
            if (item.id, s.id if s else None) not in have:
                out.append((item, s))
    return out


def _due(e: Engagement) -> date:
    if e.fieldwork_start is None:
        raise Invalid("Set the fieldwork start date on the engagement first. Documents are due 5 business days before it.", [{"field": "fieldwork_start", "message": "Set the fieldwork start date."}])
    return subtract_business_days(e.fieldwork_start, DUE_BUSINESS_DAYS)


def email_context(db: Session, actor: User, e: Engagement, pairs: list[tuple[DocumentCatalogItem, AISystem | None]], due: date) -> dict:
    org = db.get(Organization, e.client_id)
    name, _ = _caico(db, e)
    cats: dict[int, dict] = {}
    for item, s in pairs:
        cats.setdefault(item.category, {"title": f"{item.category}. {item.category_title}", "requests": []})["requests"].append({"title": item.title, "system": f"{s.reference_id} {s.name}" if s else None})
    team_role = db.scalar(select(EngagementTeam.role).where(EngagementTeam.engagement_id == e.id, EngagementTeam.user_id == actor.id, EngagementTeam.deleted_at.is_(None)))
    return {
        "contacts": {"caico": {"name": name or "colleague"}}, "client": {"name": org.name}, "engagement": {"audit_ref": e.audit_ref},
        "due_date": f"{due.day} {due:%B %Y}", "categories": [cats[k] for k in sorted(cats)],
        "sender": {"name": actor.name, "role_label": TEAM_ROLES.get(team_role or "", "Auditor")},
    }


def render_email(db: Session, ctx: dict) -> tuple[str, str]:
    """The admin-editable request text, as Markdown and HTML."""
    from app.documents.render import render_markdown
    from app.reference.templates import render_template

    md = render_template(db, "document_request_email", ctx)
    return md, render_markdown(md)


def preview(db: Session, actor: User, e: Engagement) -> dict:
    pairs = _missing(db, e) or [(db.get(DocumentCatalogItem, r.catalog_item_id), db.get(AISystem, r.ai_system_id) if r.ai_system_id else None) for r in requests_for(db, e) if r.status == "pending"]
    md, _ = render_email(db, email_context(db, actor, e, pairs, _due(e)))
    name, email = _caico(db, e)
    return {"to": email, "cc": [u.email for u in _team(db, e, "engagement_manager")], "markdown": md, "new_items": len(_missing(db, e))}


def issue_register(db: Session, settings: Settings, actor: User, e: Engagement) -> list[DocumentRequest]:
    """Request every catalog document that applies (per-system items once per system) and email the client."""
    pairs = _missing(db, e)
    if not pairs:
        raise Conflict("Every document has already been requested.")
    due = _due(e)
    name, email = _caico(db, e)
    if not email:
        raise Conflict("The client has no Chief AI Compliance Officer email to send the request to.")
    now = utcnow()
    for item, s in pairs:
        db.add(DocumentRequest(organization_id=e.client_id, engagement_id=e.id, catalog_item_id=item.id, ai_system_id=s.id if s else None, requested_at=now, due_at=due, status="pending", evidence_ids=[], created_by=actor.id))
    db.flush()
    md, html = render_email(db, email_context(db, actor, e, pairs, due))
    from app.mail.service import send

    org = db.get(Organization, e.client_id)
    send(db, settings, "document_request", to=[email], cc=[u.email for u in _team(db, e, "engagement_manager")] or None, organization_id=e.client_id, related=e, actor_id=actor.id,
         context={"client": org.name, "audit_ref": e.audit_ref, "body_html": html, "body_text": md})
    audit.record(db, actor_id=actor.id, action="documents.issue", obj=e, after={"count": len(pairs), "due": due.isoformat()}, summary=f"Requested {len(pairs)} documents from {org.name}, due {due.isoformat()}")
    return requests_for(db, e)


# ---- client actions
def _withdraw_finding(db: Session, req: DocumentRequest) -> None:
    f = db.get(Finding, req.finding_id) if req.finding_id else None
    if f is not None and f.deleted_at is None and f.status == "draft" and f.confirmed_at is None:
        f.deleted_at = utcnow()
        req.finding_id = None


def receive(db: Session, actor: User, req: DocumentRequest, file_ids: list[str]) -> DocumentRequest:
    if not file_ids:
        raise Invalid(errors=[{"field": "file", "message": "Upload the document."}])
    req.evidence_ids = list(dict.fromkeys([*(req.evidence_ids or []), *file_ids]))
    before = req.status
    req.status, req.received_at, req.received_by, req.not_available_note = "received", req.received_at or utcnow(), actor.id, None
    _withdraw_finding(db, req)
    item = db.get(DocumentCatalogItem, req.catalog_item_id)
    audit.record(db, actor_id=actor.id, action="documents.receive", obj=req, before={"status": before}, after={"status": "received", "files": len(req.evidence_ids)}, summary=f"Received {item.title}")
    return req


def mark_not_available(db: Session, actor: User, req: DocumentRequest, note: str | None) -> DocumentRequest:
    """"Missing documents = findings": a document that does not exist raises a draft finding for the auditor."""
    note = " ".join(str(note or "").split())
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say why the document is not available."}])
    if req.status == "received":
        raise Conflict("This document has already been received.")
    from app.questionnaire.service import next_finding_ref

    e = db.get(Engagement, req.engagement_id)
    item = db.get(DocumentCatalogItem, req.catalog_item_id)
    s = db.get(AISystem, req.ai_system_id) if req.ai_system_id else None
    req.status, req.not_available_note = "not_available", note[:4000]
    if req.finding_id is None or (f := db.get(Finding, req.finding_id)) is None or f.deleted_at is not None:
        f = Finding(organization_id=e.client_id, engagement_id=e.id, ref=next_finding_ref(db, e), ai_system_id=s.id if s else None, template_section=item.template_section,
                    source_question_ids=[], title=f"Document not available: {item.title}"[:300], severity="medium", status="draft", origin="document_request",
                    description=f"The client confirmed that this document does not exist: {item.title}{f' ({s.reference_id} {s.name})' if s else ''}. Client note: {note}",
                    use_case_ids=list(s.use_case_ids or []) if s else [], control_refs=[], created_by=actor.id)
        db.add(f)
        db.flush()
        req.finding_id = f.id
    audit.record(db, actor_id=actor.id, action="documents.not_available", obj=req, after={"note": note, "finding": f.ref}, summary=f"Marked {item.title} not available; draft finding {f.ref}")
    return req


# ---- chasing and escalation
def chase(db: Session, actor: User, req: DocumentRequest, note: str | None, now: datetime | None = None) -> DocumentChase:
    if req.status != "pending":
        raise Conflict("Only pending requests can be chased.")
    c = DocumentChase(organization_id=req.organization_id, document_request_id=req.id, chased_at=now or utcnow(), chased_by=actor.id, note=" ".join(str(note or "").split())[:2000] or None, created_by=actor.id)
    db.add(c)
    db.flush()
    item = db.get(DocumentCatalogItem, req.catalog_item_id)
    audit.record(db, actor_id=actor.id, action="documents.chase", obj=req, after={"note": c.note}, summary=f"Chased {item.title}")
    return c


def chase_all(db: Session, settings: Settings, actor: User, e: Engagement, note: str | None) -> int:
    """Chase every pending request and send the client one reminder listing them."""
    pending = [r for r in requests_for(db, e) if r.status == "pending"]
    if not pending:
        raise Conflict("Nothing is pending.")
    for r in pending:
        chase(db, actor, r, note)
    pairs = [(db.get(DocumentCatalogItem, r.catalog_item_id), db.get(AISystem, r.ai_system_id) if r.ai_system_id else None) for r in pending]
    md, html = render_email(db, email_context(db, actor, e, pairs, pending[0].due_at or _due(e)))
    name, email = _caico(db, e)
    if email:
        from app.mail.service import send

        org = db.get(Organization, e.client_id)
        send(db, settings, "document_request", to=[email], cc=[u.email for u in _team(db, e, "engagement_manager")] or None, organization_id=e.client_id, related=e, actor_id=actor.id,
             context={"client": org.name, "audit_ref": e.audit_ref, "body_html": html, "body_text": md, "reminder": True})
    return len(pending)


def last_chase(db: Session, req: DocumentRequest) -> DocumentChase | None:
    return db.scalar(select(DocumentChase).where(DocumentChase.document_request_id == req.id, DocumentChase.deleted_at.is_(None)).order_by(DocumentChase.chased_at.desc()).limit(1))


def escalations_due(db: Session, today: date | None = None) -> list[DocumentRequest]:
    """Pending requests chased 3 or more business days ago with nothing received."""
    today = today or _today()
    out = []
    for req in db.scalars(select(DocumentRequest).where(DocumentRequest.status == "pending", DocumentRequest.deleted_at.is_(None)).order_by(DocumentRequest.created_at)):
        c = last_chase(db, req)
        if c is not None and business_days_between(c.chased_at.date(), today) >= ESCALATE_AFTER:
            out.append(req)
    return out


def escalate_due(db: Session, settings: Settings, today: date | None = None) -> int:
    """Tell each engagement's Lead Auditor (Chief Auditor) once per chase. Called by the daily scheduler."""
    n = 0
    by_engagement: dict[str, list[DocumentRequest]] = {}
    for req in escalations_due(db, today):
        c = last_chase(db, req)
        if req.escalated_chase_id == c.id:
            continue
        req.escalated_at, req.escalated_chase_id = utcnow(), c.id
        by_engagement.setdefault(req.engagement_id, []).append(req)
        n += 1
    for eid, reqs in by_engagement.items():
        e = db.get(Engagement, eid)
        org = db.get(Organization, e.client_id)
        titles = ", ".join(db.get(DocumentCatalogItem, r.catalog_item_id).title for r in reqs[:5]) + (f" and {len(reqs) - 5} more" if len(reqs) > 5 else "")
        notify(db, _team(db, e, "chief_auditor"), "document_escalation", f"{org.name}: {len(reqs)} document{'s' if len(reqs) != 1 else ''} still missing after a chase", titles, f"/clients/{org.id}/documents", engagement=e, settings=settings)
    db.flush()
    return n


def kpis(db: Session, rows: list[DocumentRequest], today: date | None = None) -> dict:
    today = today or _today()
    pending = [r for r in rows if r.status == "pending"]
    overdue = [r for r in pending if (c := last_chase(db, r)) is not None and business_days_between(c.chased_at.date(), today) >= ESCALATE_AFTER]
    na = [r for r in rows if r.status == "not_available"]
    return {"requested": len(rows), "received": sum(r.status == "received" for r in rows), "pending": len(pending), "past_escalation": len(overdue),
            "not_available": len(na), "findings": sum(1 for r in na if r.finding_id)}
