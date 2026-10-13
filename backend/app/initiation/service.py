"""Initiation package: generate, edit, approve and send (spec §7 stage 1, §12; schematic D7, D9)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.documents.docx import to_docx
from app.documents.pdf import to_pdf
from app.engagements.models import ClientContact, Engagement
from app.engagements.service import transition
from app.files.service import upload
from app.initiation.context import build_context
from app.initiation.models import InitiationPackage, PackageDocument
from app.invitations.service import invite_user
from app.reference.models import DocumentTemplate
from app.reference.templates import render_string
from app.signoffs.service import create_sign_off
from app.tenancy.models import Organization, User
from app.tenancy.service import assign_role, create_user, find_user_by_email, roles_of

ACTION_LABELS = {
    "sign": "Client signs · sign-off 1",
    "nominate": "Client nominates role holders",
    "upload": "Client uploads, or Client Admin adds them directly",
    "review": "Client reviews and circulates to staff",
    "read": "Client reads",
    "answer": "Client answers each item",
}
EDITABLE_ITEMS = {1, 2, 5, 6}
CHECKLIST = {
    "scope_ok": "Confirm the scope, laws and departments are right for this client.",
    "no_conflict": "Confirm the team has no conflict of interest.",
    "letter_previewed": "Preview the engagement letter before sending it.",
}


def current_package(db: Session, e: Engagement) -> InitiationPackage | None:
    return db.scalar(select(InitiationPackage).where(InitiationPackage.engagement_id == e.id, InitiationPackage.status != "superseded", InitiationPackage.deleted_at.is_(None)).order_by(InitiationPackage.version.desc()).limit(1))


def documents(db: Session, pkg: InitiationPackage) -> list[PackageDocument]:
    return list(db.scalars(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.deleted_at.is_(None)).order_by(PackageDocument.item)))


def _write_files(db: Session, settings: Settings, actor: User | None, e: Engagement, doc: PackageDocument) -> None:
    base = f"{e.audit_ref} {doc.title}".replace("/", "-")
    common = {"organization_id": e.client_id, "engagement_id": e.id, "linked_type": "package_document", "linked_id": doc.id}
    if doc.format == "csv":
        doc.csv_file_id = upload(db, settings, actor, data=doc.body_md.encode("utf-8"), filename=f"{base}.csv", content_type="text/csv", **common).id
        doc.docx_file_id = doc.pdf_file_id = None
        return
    meta = {"audit_ref": e.audit_ref}
    doc.docx_file_id = upload(db, settings, actor, data=to_docx(doc.body_md, doc.title, meta), filename=f"{base}.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", **common).id
    doc.pdf_file_id = upload(db, settings, actor, data=to_pdf(doc.body_md, doc.title, meta), filename=f"{base}.pdf", content_type="application/pdf", **common).id


def generate_package(db: Session, settings: Settings, actor: User | None, e: Engagement) -> InitiationPackage:
    """Render the seven package documents from the active templates, each to DOCX and PDF (CSV templates to CSV)."""
    prev = current_package(db, e)
    if prev is not None:
        prev.status = "superseded"
    ctx = build_context(db, settings, e)
    pkg = InitiationPackage(organization_id=e.client_id, engagement_id=e.id, version=(prev.version + 1) if prev else 1, status="draft", prepared_by=e.created_by, created_by=actor.id if actor else None)
    db.add(pkg)
    db.flush()
    templates = db.scalars(select(DocumentTemplate).where(DocumentTemplate.active.is_(True), DocumentTemplate.package_item.is_not(None)).order_by(DocumentTemplate.package_item))
    for t in templates:
        body = render_string(t.body, ctx)
        doc = PackageDocument(
            organization_id=e.client_id, package_id=pkg.id, engagement_id=e.id, item=t.package_item, template_key=t.key, template_version=t.version,
            title=t.name, format=t.format or "md", requires_action=t.requires_action or "read", body_md=body + ("\n" if t.format == "csv" else ""),
            merge_values={"has_ny": ctx["has_ny"], "has_eu": ctx["has_eu"], "governance_codes": [i["code"] for g in ctx["groups"] for i in g["items"]]} if t.package_item == 7 else None,
        )
        db.add(doc)
        db.flush()
        _write_files(db, settings, actor, e, doc)
    db.flush()
    audit.record(db, actor_id=actor.id if actor else None, action="package.generate", obj=pkg, summary=f"Generated initiation package v{pkg.version} for {e.audit_ref}")
    return pkg


def ensure_package(db: Session, settings: Settings, actor: User, e: Engagement) -> InitiationPackage | None:
    pkg = current_package(db, e)
    if pkg is None and e.status == "pending_approval":
        pkg = generate_package(db, settings, actor, e)
    return pkg


def edit_document(db: Session, settings: Settings, actor: User, doc: PackageDocument, body_md: str) -> PackageDocument:
    pkg = db.get(InitiationPackage, doc.package_id)
    if pkg.status != "draft":
        raise Conflict("This package has been sent. Documents can no longer be changed.")
    if doc.item not in EDITABLE_ITEMS:
        raise Conflict("This document is generated from the engagement details. Change those instead.")
    if not body_md.strip():
        raise Invalid(errors=[{"field": "body_md", "message": "The document cannot be empty."}])
    before = doc.body_md
    doc.body_md, doc.edited, doc.updated_by = body_md, True, actor.id
    _write_files(db, settings, actor, db.get(Engagement, doc.engagement_id), doc)
    audit.record(db, actor_id=actor.id, action="package.edit_document", obj=doc, before={"body_md": before[:2000]}, after={"body_md": body_md[:2000]}, summary=f"Edited {doc.title}")
    return doc


def _client_user(db: Session, org: Organization, contact: ClientContact, role: str, actor: User) -> tuple[User, bool]:
    """Find or create the client user for a contact and give them `role`. Returns (user, created)."""
    user = find_user_by_email(db, contact.email)
    created = False
    if user is None:
        user = create_user(db, org, name=contact.name, email=contact.email, job_title=contact.title, phone=contact.phone)
        created = True
    elif user.organization_id != org.id:
        raise Conflict(f"{contact.email} belongs to a user in another organization. Return the engagement so the contact can be corrected.")
    if role not in {r.role for r in roles_of(db, user.id)}:
        assign_role(db, user, role, actor_id=actor.id)
    contact.user_id = user.id
    return user, created


def approve_and_send(db: Session, settings: Settings, actor: User, e: Engagement, client_message: str | None, checklist: dict) -> InitiationPackage:
    missing = [{"field": f"checklist.{k}", "message": msg} for k, msg in CHECKLIST.items() if not checklist.get(k)]
    if missing:
        raise Invalid("Confirm each item in the approval checklist.", missing)
    if e.status != "pending_approval":
        raise Conflict("Only an engagement awaiting approval can be approved.")
    pkg = ensure_package(db, settings, actor, e)
    org = db.get(Organization, e.client_id)
    transition(db, actor, e, "initiated")  # enforces approver ≠ preparer
    contacts = {c.contact_role: c for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None)))}
    to_invite: dict[str, User] = {}
    for role in ("caico", "client_admin"):
        c = contacts.get(role)
        if c is None or not c.email:
            continue
        user, _ = _client_user(db, org, c, role, actor)
        to_invite[user.id] = user
    for user in to_invite.values():  # one invitation per person, even when they hold both roles
        if user.status != "active":
            invite_user(db, settings, actor, user, template_key="client_invitation", extra_context={"client_message": client_message, "chief_name": actor.name})
    org.status = "active"
    now = utcnow()
    pkg.status, pkg.approved_by, pkg.approved_at, pkg.sent_at = "sent", actor.id, now, now
    pkg.client_message, pkg.approval_checklist = client_message, {k: True for k in CHECKLIST}
    letter = next(d for d in documents(db, pkg) if d.item == 1)
    create_sign_off(db, e, 1, preparer_id=e.created_by, required_roles=["caico", "chief_auditor"], document_id=letter.id)
    audit.record(db, actor_id=actor.id, action="package.send", obj=pkg, summary=f"Approved {e.audit_ref} and sent the initiation package (7 items) to {', '.join(u.name for u in to_invite.values())}")
    return pkg


def resend_invitation(db: Session, settings: Settings, actor: User, e: Engagement, role: str) -> User:
    c = db.scalar(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == role, ClientContact.deleted_at.is_(None)))
    if c is None or c.user_id is None:
        raise Conflict("This person has not been invited yet.")
    user = db.get(User, c.user_id)
    pkg = current_package(db, e)
    invite_user(db, settings, actor, user, template_key="client_invitation", extra_context={"client_message": pkg.client_message if pkg else None, "chief_name": actor.name})
    return user
