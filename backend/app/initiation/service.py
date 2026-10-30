"""Initiation package: generate, edit, approve and send (spec §7 stage 1, §12; schematic D7, D9)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.documents.csvsafe import to_csv
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


def _department_csv(ctx: dict) -> str:
    rows = [[d["name"], d.get("head_name"), d.get("head_email"), d.get("headcount")] for d in ctx["engagement"]["department_rows"]] or [["Human Resources", "", "", ""]]
    return to_csv(["department", "head_name", "head_email", "headcount"], rows)


def _user_csv(ctx: dict) -> str:
    return to_csv(
        ["first_name", "last_name", "email", "job_title", "department", "role", "location"],
        [["Priya", "Shah", "priya.shah@example.com", "Head of HR", "Human Resources", "Department Compliance Lead", "New York NY"],
         ["Tom", "Reyes", "tom.reyes@example.com", "Recruiter", "Human Resources", "Contributor", "New York NY"]],
    )


# CSV items are built in code, not from Markdown templates, so quoting and formula neutralising are always right.
CSV_BUILDERS = {"department_csv": _department_csv, "user_csv": _user_csv}


def _edited_documents(db: Session, prev: InitiationPackage | None) -> dict[tuple[str, int], str]:
    """Chief Auditor edits from the previous package, kept when the template has not changed since."""
    if prev is None:
        return {}
    return {(d.template_key, d.template_version): d.body_md for d in documents(db, prev) if d.edited}


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
    carried = _edited_documents(db, prev)
    for t in templates:
        builder = CSV_BUILDERS.get(t.key)
        body = builder(ctx) if builder else render_string(t.body, ctx)
        edited = carried.get((t.key, t.version))
        if edited is not None:
            body = edited
        doc = PackageDocument(
            organization_id=e.client_id, package_id=pkg.id, engagement_id=e.id, item=t.package_item, template_key=t.key, template_version=t.version,
            title=t.name, format=t.format or "md", requires_action=t.requires_action or "read", body_md=body, edited=edited is not None,
            merge_values={"has_ny": ctx["has_ny"], "has_eu": ctx["has_eu"], "governance_codes": [i["code"] for g in ctx["groups"] for i in g["items"]]} if t.package_item == 7 else None,
        )
        db.add(doc)
        db.flush()
        _write_files(db, settings, actor, e, doc)
    db.flush()
    from app.regmaster.letter import attach_to_package, latest_approved  # §25.8: the intro letter goes with the package

    intro = latest_approved(db, e.client_id)
    if intro is not None:
        attach_to_package(db, settings, actor, intro, pkg)
    audit.record(db, actor_id=actor.id if actor else None, action="package.generate", obj=pkg, summary=f"Generated initiation package v{pkg.version} for {e.audit_ref}")
    return pkg


def ensure_package(db: Session, settings: Settings, actor: User, e: Engagement) -> InitiationPackage | None:
    pkg = current_package(db, e)
    if pkg is None and e.status == "pending_approval":
        pkg = generate_package(db, settings, actor, e)
    return pkg


def document_signed(db: Session, doc: PackageDocument) -> bool:
    """True once anyone has signed a sign-off over this document (the engagement letter at sign-off 1)."""
    from app.signoffs.models import Signature, SignOff

    return db.scalar(select(Signature.id).join(SignOff, SignOff.id == Signature.sign_off_id).where(SignOff.document_version_id == doc.id, SignOff.deleted_at.is_(None)).limit(1)) is not None


def edit_block(db: Session, doc: PackageDocument) -> str | None:
    """Why this document cannot be edited now, or None. Editable: items in EDITABLE_ITEMS of the current package, while the
    Chief Auditor reviews the package or, once it is sent, while the engagement is live and nobody has signed the document."""
    pkg = db.get(InitiationPackage, doc.package_id)
    e = db.get(Engagement, doc.engagement_id)
    if doc.item not in EDITABLE_ITEMS or doc.format != "md":
        return "This document is generated from the engagement details. Change those instead."
    if pkg.status == "draft":
        if e.status != "pending_approval":
            return "Documents can be edited only while the engagement is awaiting your approval."
        return None
    if pkg.status != "sent":
        return "This package has been replaced. Documents can no longer be changed."
    if e.status not in ("initiated", "in_progress"):
        return "This engagement is closed. Its documents can no longer be changed."
    if document_signed(db, doc):
        return "This document has been signed, so it can't be edited. A change needs a sign-off correction."
    return None


def edit_document(db: Session, settings: Settings, actor: User, doc: PackageDocument, body_md: str) -> PackageDocument:
    block = edit_block(db, doc)
    if block:
        raise Conflict(block)
    if not body_md.strip():
        raise Invalid(errors=[{"field": "body_md", "message": "The document cannot be empty."}])
    pkg = db.get(InitiationPackage, doc.package_id)
    e = db.get(Engagement, doc.engagement_id)
    before = doc.body_md
    doc.body_md, doc.edited, doc.updated_by = body_md, True, actor.id
    _write_files(db, settings, actor, e, doc)
    audit.record(db, actor_id=actor.id, action="package.edit_document", obj=doc, before={"body_md": before[:2000]}, after={"body_md": body_md[:2000]},
                 summary=f"Edited {doc.title}" + (" after it was sent to the client" if pkg.status == "sent" else ""))
    if pkg.status == "sent" and before != body_md:
        _tell_client_document_changed(db, settings, e, doc)
    return doc


def _tell_client_document_changed(db: Session, settings: Settings, e: Engagement, doc: PackageDocument) -> None:
    """The client contacts who received the package see an in-app notice that the document changed."""
    from app.notifications.service import notify

    ids = [c.user_id for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None), ClientContact.user_id.is_not(None)))]
    users = list(db.scalars(select(User).where(User.id.in_(ids), User.deleted_at.is_(None)))) if ids else []
    notify(db, users, "document_changed", f"{doc.title} has been updated",
           f"Futran updated this document in your initiation package for {e.audit_ref}. The current version is on your getting started page.", "/start", engagement=e, settings=settings)


def _client_user(db: Session, org: Organization, contact: ClientContact, role: str, actor: User) -> tuple[User, bool]:
    """Find or create the client user for a contact and give them `role`. Returns (user, created)."""
    user = find_user_by_email(db, contact.email)
    created = False
    if user is None and db.scalar(select(User.id).where(func.lower(User.email) == contact.email.strip().lower())):
        raise Conflict(f"{contact.email} belonged to a user who was removed. Ask an administrator to restore that account, or use another email.")
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
    from app.engagements.service import preparers

    org = db.get(Organization, e.client_id)
    excluded = preparers(e)
    transition(db, actor, e, "initiated")  # compare-and-set; enforces approver ≠ anyone who prepared the draft
    pkg = current_package(db, e) or generate_package(db, settings, actor, e)
    letter = next((d for d in documents(db, pkg) if d.item == 1), None)
    if letter is None:
        raise Conflict("The package has no engagement letter. Check that the engagement letter template is active.")
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
    from app.governance.service import create_request

    codes = next((d.merge_values or {} for d in documents(db, pkg) if d.item == 7), {}).get("governance_codes")
    create_request(db, actor, e, codes)
    from app.systems.service import convert_planned

    convert_planned(db, actor, e)
    create_sign_off(db, e, 1, preparer_id=e.created_by, required_roles=["caico", "chief_auditor"], document_id=letter.id, excluded=excluded)
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
