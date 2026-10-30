"""Dashboard (screen 1), client page (screen 9) and the client's initiation checklist (screen 10)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit_log.models import AuditLog
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.gates import STAGE_NAMES, gate_status
from app.engagements.models import ClientContact, ClientLocation, ClientRequirement, Engagement, EngagementTeam
from app.engagements.service import STATUS_LABELS
from app.engagements.wizard import INDUSTRIES
from app.engagements.wizard_router import _load
from app.initiation.context import TYPE_LABELS
from app.initiation.models import PackageDocument
from app.initiation.notice import counts as notice_counts
from app.initiation.service import current_package, documents, resend_invitation
from app.invitations.models import Invitation
from app.policy.actions import Action
from app.policy.authorize import assigned_engagement_ids, authorize, sees_all_engagements
from app.policy.roles import ROLE_LABELS
from app.reference.models import Jurisdiction
from app.signoffs.service import current as current_sign_off
from app.tenancy.models import Organization, User

router = APIRouter(tags=["clients"])
ACTIVITY_PREFIXES = ("engagement.", "package.", "signoff.")  # generated files are not news; uploads join with their own screens


def status_label(e: Engagement) -> str:
    return "Initiation sent" if e.status == "initiated" else STATUS_LABELS.get(e.status, e.status)


def stage_label(e: Engagement) -> str:
    if e.status in ("draft", "pending_approval"):
        return "Draft"
    if e.status in ("completed", "archived"):
        return "9 · Closed"
    return f"{e.stage} · {STAGE_NAMES.get(e.stage, '')}"


def _visible_engagements(db: Session, actor: Actor) -> list[Engagement]:
    stmt = select(Engagement).where(Engagement.deleted_at.is_(None))
    if not sees_all_engagements(actor):
        stmt = stmt.where(Engagement.id.in_(assigned_engagement_ids(db, actor.id)))
    return list(db.scalars(stmt.order_by(Engagement.updated_at.desc())))


def _chiefs(db: Session, ids: list[str]) -> dict[str, str]:
    rows = db.execute(select(EngagementTeam.engagement_id, User.name).join(User, User.id == EngagementTeam.user_id).where(EngagementTeam.engagement_id.in_(ids), EngagementTeam.role == "chief_auditor", EngagementTeam.deleted_at.is_(None)))
    return dict(rows.all())


FILTERS = {
    "all": lambda e: True,
    "in_progress": lambda e: e.status in ("initiated", "in_progress"),
    "completed": lambda e: e.status in ("completed", "archived"),
    "drafts": lambda e: e.status in ("draft", "pending_approval"),
}


@router.get("/engagements")
def dashboard(filter: str = "all", q: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_ENGAGEMENT, list_view=True)
    if not actor.is_futran:
        raise NotFound()
    es = _visible_engagements(db, actor)
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_([e.client_id for e in es])))}
    chiefs = _chiefs(db, [e.id for e in es])
    kpis = {
        "in_progress": sum(e.status == "in_progress" for e in es),
        "completed": sum(e.status in ("completed", "archived") for e in es),
        "awaiting_approval": sum(e.status == "pending_approval" for e in es),
        "awaiting_client": sum(e.status == "initiated" for e in es),
    }
    counts = {k: sum(1 for e in es if f(e)) for k, f in FILTERS.items()}
    pick = FILTERS.get(filter, FILTERS["all"])
    rows = []
    for e in es:
        org = orgs.get(e.client_id)
        if not pick(e) or (q and q.lower() not in f"{org.name if org else ''} {e.audit_ref} {e.name}".lower()):
            continue
        target = e.final_report_target or e.draft_report_target
        rows.append({
            "engagement_id": e.id, "client_id": e.client_id, "client_name": org.name if org else "", "audit_ref": e.audit_ref,
            "type_label": TYPE_LABELS.get(e.type, e.type), "stage": e.stage, "stage_label": stage_label(e), "status": e.status,
            "status_label": status_label(e), "chief_auditor": chiefs.get(e.id), "target_date": target.isoformat() if target else None,
        })
    return {"kpis": kpis, "counts": counts, "rows": rows}


@router.get("/clients")
def clients_list(q: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The Clients page: each client the Futran user can see, with its current engagement."""
    authorize(db, actor, Action.VIEW_ENGAGEMENT, list_view=True)
    if not actor.is_futran:
        raise NotFound()
    from app.engagements.models import ClientLocation
    from app.tenancy.models import User

    latest: dict[str, Engagement] = {}
    for e in _visible_engagements(db, actor):  # newest first; keep a live engagement over a later draft
        cur = latest.get(e.client_id)
        if cur is None or (cur.status in ("draft", "pending_approval") and e.status not in ("draft", "pending_approval")):
            latest[e.client_id] = e
    orgs = list(db.scalars(select(Organization).where(Organization.id.in_(list(latest)), Organization.deleted_at.is_(None)).order_by(Organization.name)))
    out = []
    for org in orgs:
        if q and q.lower() not in f"{org.name} {org.legal_name or ''} {org.hq_city or ''}".lower():
            continue
        e = latest[org.id]
        sites = db.scalar(select(func.count()).select_from(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None))) or 0
        people_n = db.scalar(select(func.count()).select_from(User).where(User.organization_id == org.id, User.deleted_at.is_(None))) or 0
        out.append({
            "id": org.id, "name": org.name, "industry": INDUSTRIES.get(org.industry or "", org.industry), "internal": org.is_internal,
            "headquarters": ", ".join(x for x in (org.hq_city, org.hq_state, org.hq_country) if x), "sites": sites, "people": people_n,
            "engagement": {"id": e.id, "audit_ref": e.audit_ref, "type_label": TYPE_LABELS.get(e.type, e.type), "stage_label": stage_label(e), "status": e.status, "status_label": status_label(e)},
        })
    return {"clients": out}


def _activity(db: Session, org_ids: list[str] | None, limit: int) -> list[dict]:
    stmt = select(AuditLog).where(or_(*[AuditLog.action.startswith(p) for p in ACTIVITY_PREFIXES]))
    if org_ids is not None:
        stmt = stmt.where(AuditLog.organization_id.in_(org_ids))
    entries = list(db.scalars(stmt.order_by(AuditLog.at.desc()).limit(limit)))
    names = dict(db.execute(select(Organization.id, Organization.name).where(Organization.id.in_({a.organization_id for a in entries}))).all())
    return [{"at": a.at.isoformat(), "actor": a.actor_name, "client": names.get(a.organization_id), "client_id": a.organization_id, "summary": a.summary, "action": a.action} for a in entries]


@router.get("/engagements/activity")
def activity(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_ENGAGEMENT, list_view=True)
    if not actor.is_futran:
        raise NotFound()
    org_ids = None if sees_all_engagements(actor) else list({e.client_id for e in _visible_engagements(db, actor)})
    return _activity(db, org_ids, 15)


def invite_status(db: Session, user: User | None) -> str:
    if user is None:
        return "Not invited yet"
    if user.status == "active":
        return "Active"
    if user.status == "disabled":
        return "Disabled"
    inv = db.scalar(select(Invitation).where(Invitation.user_id == user.id).order_by(Invitation.sent_at.desc()).limit(1))
    if inv is None:
        return "Not invited yet"
    if inv.status == "pending" and inv.expires_at < utcnow():
        return "Invitation expired"
    return "Invitation sent, not yet accepted" if inv.status == "pending" else "Invitation " + inv.status


@router.get("/clients/{client_id}")
def client_page(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _load(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    if not actor.is_futran:
        raise NotFound()
    gate = gate_status(db, e)
    jnames = dict(db.execute(select(Jurisdiction.id, Jurisdiction.name)).all())
    from app.laws.publish import current_version_of

    laws = []
    for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None), ClientRequirement.in_scope.is_(True)).order_by(ClientRequirement.created_at)):
        reg = current_version_of(db, r.regulation_id) if r.regulation_id else None  # the current text of the law
        laws.append({"label": reg.short_name if reg else r.free_text, "jurisdiction": jnames.get(reg.jurisdiction_id) if reg else None, "type": reg.type if reg else None,
                     "citation": reg.citation if reg else None, "effective_date": reg.effective_date_text if reg else None})
    contacts = []
    for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None))):
        if not c.name and not c.not_appointed:
            continue
        user = db.get(User, c.user_id) if c.user_id else None
        contacts.append({"role": c.contact_role, "role_label": ROLE_LABELS.get(c.contact_role, c.contact_role.replace("_", " ").capitalize()), "name": c.name, "email": c.email, "phone": c.phone, "not_appointed": c.not_appointed, "invite_status": invite_status(db, user) if c.contact_role in ("caico", "client_admin") else None})
    from app.engagements.team import team_by_person

    team = [{"name": p["name"], "role_label": p["role_label"]} for p in team_by_person(db, e)]  # one line per person
    pkg = current_package(db, e)
    so1 = current_sign_off(db, e, 1)
    sites = [{"site_name": loc.site_name, "city": loc.city, "jurisdictions": [jnames.get(j) for j in loc.jurisdiction_ids or []]} for loc in db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True)))]
    return {
        "client": {"id": org.id, "name": org.name, "legal_name": org.legal_name, "client_ref": org.client_ref, "industry": INDUSTRIES.get(org.industry or "", org.industry), "employee_band": org.employee_band, "hq": ", ".join(x for x in (org.hq_street, org.hq_city, org.hq_state, org.hq_country) if x), "status": org.status},
        "engagement": {"id": e.id, "audit_ref": e.audit_ref, "name": e.name, "type_label": TYPE_LABELS.get(e.type, e.type), "status": e.status, "status_label": status_label(e), "stage": e.stage, "stage_label": stage_label(e), "returned_comment": e.returned_comment},
        "gate": {"ready": gate.ready, "unmet": gate.unmet},
        "sites": sites,
        "laws": laws,
        "contacts": contacts,
        "team": team,
        "package": package_documents_out(db, actor, e, pkg) if pkg else None,
        "sign_off_1": {"id": so1.id, "status": so1.status} if so1 else None,
        "activity": _activity(db, [org.id], 20),
    }


def package_documents_out(db: Session, actor: Actor, e: Engagement, pkg) -> dict:
    """The initiation package documents with what this user may do with each: view always; edit for the Chief Auditor
    while the document is editable (see initiation.service.edit_block)."""
    from app.core.errors import Forbidden
    from app.initiation.service import EDITABLE_ITEMS, document_signed, edit_block

    try:
        authorize(db, actor, Action.APPROVE_ENGAGEMENT, engagement_id=e.id)
        may_edit = True
    except (Forbidden, NotFound):
        may_edit = False
    out = []
    for d in documents(db, pkg):
        block = edit_block(db, d)
        out.append({
            "id": d.id, "item": d.item, "title": d.title, "pdf_file_id": d.pdf_file_id, "docx_file_id": d.docx_file_id, "csv_file_id": d.csv_file_id,
            "completed_at": d.completed_at.isoformat() if d.completed_at else None, "edited": d.edited, "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "editable": d.item in EDITABLE_ITEMS and d.format == "md", "signed": document_signed(db, d), "can_edit": may_edit and block is None,
            "edit_note": block if d.item in EDITABLE_ITEMS and d.format == "md" else None,
        })
    return {"id": pkg.id, "status": pkg.status, "sent_at": pkg.sent_at.isoformat() if pkg.sent_at else None, "documents": out}


@router.post("/clients/{client_id}/contacts/{role}/resend")
def resend(client_id: str, role: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _, e = _load(db, actor, client_id, Action.CREATE_CLIENT_ENGAGEMENT)
    if role not in ("caico", "client_admin"):
        raise NotFound()
    user = resend_invitation(db, request.app.state.settings, actor.user, e, role)
    return {"sent_to": user.email}


# ---- client side: initiation checklist (screen 10, mockup ClientWelcome)
CHECKLIST = [
    ("guide", 6, "Read the getting started guide", "Sign-in, MFA, timeline and your Futran contacts"),
    ("sign", 1, "Sign the engagement letter and scope", "Confirms the audit period, laws, sites and departments in scope · sign-off 1"),
    ("nominate", 2, "Nominate role holders", "Executive Sponsor, Data Protection Officer and Department Compliance Leads; see the roles note"),
    ("departments", 4, "Confirm departments", "Pre-filled from the scope. Correct, add or upload them on People > Departments, then confirm the list."),
    ("users", 3, "Add employees", "Add the people who need a login on People > Users, one by one or from a CSV. All other staff are reached later through the attestation link."),
    ("notice", 5, "Review employee AI audit and data notice and kick off audit", "The Chief AI Compliance Officer reviews the notice and sends it to everyone on the user list. Each person with a login reads and acknowledges it."),
    ("governance", 7, "Describe your AI governance structure", "Charter, committees and named owners for bias, explainability and accountability. Not in place yet? Choose \"Will constitute\"."),
]
SELF_COMPLETE = {"guide", "notice"}  # the rest complete through their own screens


def _client_engagement(db: Session, actor: Actor) -> Engagement:
    if actor.is_futran:
        raise NotFound()
    e = db.scalar(select(Engagement).where(Engagement.client_id == actor.organization.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"])).order_by(Engagement.created_at.desc()).limit(1))
    if e is None:
        raise NotFound("There is no engagement to show yet.")
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    return e


from app.mail.onboarding import getting_started_items  # noqa: E402  (email onboarding, spec §26.1)


@router.get("/me/initiation")
def my_initiation(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _client_engagement(db, actor)
    pkg = current_package(db, e)
    docs = {d.item: d for d in documents(db, pkg)} if pkg else {}
    so1 = current_sign_off(db, e, 1)
    from app.signoffs.service import signatures

    signed = so1 is not None and any(s.role == "caico" for s in signatures(db, so1))
    chief = db.scalar(select(User.name).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == "chief_auditor", EngagementTeam.deleted_at.is_(None)))
    from app.tenancy.people import role_holders

    holders = role_holders(db, db.get(Organization, e.client_id))
    named = all(holders[r]["user"] or holders[r]["not_appointed"] for r in ("exec_sponsor", "dpo"))
    leads_ok = e.stage > 2 or (e.stage == 2 and gate_status(db, e).ready)
    items = []
    for key, n, title, desc in CHECKLIST:
        d = docs.get(n)
        if key == "sign":
            done = signed
        elif key == "nominate":
            done = named and leads_ok
        else:
            done = bool(d and d.completed_at)
        item = {"key": key, "title": title, "description": desc, "done": done, "document": {"id": d.id, "pdf_file_id": d.pdf_file_id, "docx_file_id": d.docx_file_id, "csv_file_id": d.csv_file_id} if d else None, "self_complete": key in SELF_COMPLETE}
        if key == "notice":
            item["acknowledgements"] = notice_counts(db, e)
        items.append(item)
    return {
        "engagement": {"id": e.id, "audit_ref": e.audit_ref, "name": e.name, "stage": e.stage},
        "items": items, "done": sum(i["done"] for i in items), "total": len(items),
        "requested_by": e.letter_due.isoformat() if e.letter_due else None, "sign_off_1_id": so1.id if so1 else None, "chief_auditor": chief,
        "extra_items": getting_started_items(db, actor),
    }


@router.post("/me/initiation/items/{key}/done")
def mark_done(key: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _client_engagement(db, actor)
    if key not in SELF_COMPLETE:
        raise Invalid("This item is completed by doing it, not by ticking it off.")
    if key == "notice" and not actor.has_role("caico"):
        raise Conflict("The Chief AI Compliance Officer reviews and sends the employee data notice.")
    if key == "notice":  # completing item 6 means sending the notice to staff
        from app.initiation import notice

        rel = notice.send(db, request.app.state.settings, actor.user, actor.role_names, e)
        return {"key": key, "done": True, "version": rel.version}
    n = dict((k, n) for k, n, *_ in CHECKLIST)[key]
    pkg = current_package(db, e)
    d = db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == n)) if pkg else None
    if d is None:
        raise NotFound()
    if d.completed_at is None:
        d.completed_at, d.completed_by = utcnow(), actor.id
        from app.audit_log import service as audit

        audit.record(db, actor_id=actor.id, action="package.item_done", obj=d, summary=f"{actor.user.name} completed: {d.title}")
    return {"key": key, "done": True}
