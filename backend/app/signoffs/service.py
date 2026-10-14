"""Sign-offs and click-to-sign signatures (spec §8, schematic D8)."""
import hashlib

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid
from app.engagements.models import Engagement
from app.policy.roles import ROLE_LABELS
from app.signoffs.models import SIGN_OFF_TITLES, Signature, SignOff
from app.tenancy.models import User

FUTRAN_SIGNER_ROLES = {"chief_auditor", "auditor", "qa_reviewer"}


def create_sign_off(db: Session, e: Engagement, number: int, *, preparer_id: str | None, required_roles: list[str], document_id: str | None = None, scope_ref: str | None = None, excluded: list[str] | None = None) -> SignOff:
    so = SignOff(organization_id=e.client_id, engagement_id=e.id, number=number, title=SIGN_OFF_TITLES[number], scope_ref=scope_ref, preparer_id=preparer_id, excluded_signer_ids=list(dict.fromkeys([i for i in [preparer_id, *(excluded or [])] if i])), required_approver_roles=required_roles, approver_ids=[], document_version_id=document_id, status="pending")
    db.add(so)
    db.flush()
    return so


def current(db: Session, e: Engagement, number: int, scope_ref: str | None = None) -> SignOff | None:
    stmt = select(SignOff).where(SignOff.engagement_id == e.id, SignOff.number == number, SignOff.deleted_at.is_(None))
    if scope_ref is not None:
        stmt = stmt.where(SignOff.scope_ref == scope_ref)
    return db.scalar(stmt.order_by(SignOff.version.desc(), SignOff.created_at.desc()).limit(1))


def is_approved(db: Session, e: Engagement, number: int) -> bool:
    so = current(db, e, number)
    return so is not None and so.status == "approved"


def signatures(db: Session, so: SignOff) -> list[Signature]:
    return list(db.scalars(select(Signature).where(Signature.sign_off_id == so.id).order_by(Signature.signed_at)))


def _team_holders(db: Session, so: SignOff, role: str) -> set[str]:
    from app.engagements.models import EngagementTeam

    return set(db.scalars(select(EngagementTeam.user_id).where(EngagementTeam.engagement_id == so.engagement_id, EngagementTeam.role == role, EngagementTeam.deleted_at.is_(None))))


def is_excluded(so: SignOff, user_id: str) -> bool:
    return user_id == so.preparer_id or user_id in (so.excluded_signer_ids or [])


def signer_role(db: Session, actor: Actor, so: SignOff) -> str | None:
    """The still-unsigned required role this actor can sign for, if any. For a Futran role, the engagement team's
    holder signs; another holder of the role steps in only when the team's holder prepared the item."""
    done = {s.role for s in signatures(db, so)}
    for role in so.required_approver_roles:
        if role in done or not actor.has_role(role):
            continue
        if role in FUTRAN_SIGNER_ROLES:
            if not actor.is_futran:
                continue
            holders = {h for h in _team_holders(db, so, role) if not is_excluded(so, h)}
            if not holders or actor.id in holders:
                return role
        elif not actor.is_futran and actor.organization.id == so.organization_id:
            return role
    return None


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def document_hash(db: Session, so: SignOff, settings) -> str | None:
    if not so.document_version_id:
        return None
    from app.files.models import FileObject
    from app.files.service import read
    from app.initiation.models import PackageDocument

    doc = db.get(PackageDocument, so.document_version_id)
    if doc is None:
        return None
    f = db.get(FileObject, doc.pdf_file_id) if doc.pdf_file_id else None
    return hashlib.sha256(read(settings, f)).hexdigest() if f else hashlib.sha256(doc.body_md.encode()).hexdigest()


def sign(db: Session, settings, actor: Actor, so: SignOff, typed_name: str, request=None) -> Signature:
    # take the row lock first so two signers cannot both miss each other's signature
    db.execute(update(SignOff).where(SignOff.id == so.id).values(updated_at=utcnow()))
    db.refresh(so)
    if not any(actor.has_role(r) for r in so.required_approver_roles):
        raise Forbidden("You are not one of the people who sign this.")
    if any(s.user_id == actor.id for s in signatures(db, so)):
        raise Conflict("You have already signed this.")
    if is_excluded(so, actor.id):
        raise Forbidden("You prepared this item, so you cannot approve it. Another approver must sign it off.")
    if so.status == "approved":
        raise Conflict("This sign-off is already complete.")
    role = signer_role(db, actor, so)
    if role is None:
        raise Forbidden("You are not one of the people who sign this.")
    if _norm(typed_name) != _norm(actor.user.name):
        raise Invalid("Type your name exactly as it appears on your account.", [{"field": "typed_name", "message": f"Type your full name: {actor.user.name}."}])
    sig = Signature(
        organization_id=so.organization_id, sign_off_id=so.id, user_id=actor.id, role=role, typed_name=" ".join(typed_name.split()),
        signed_at=utcnow(), ip=request.client.host if request is not None and request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:300] if request is not None else None, document_sha256=document_hash(db, so, settings),
    )
    db.add(sig)
    so.approver_ids = [*(so.approver_ids or []), actor.id]
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise Conflict("This has just been signed. Reload the page.") from None
    e = db.get(Engagement, so.engagement_id)
    audit.record(db, actor_id=actor.id, action="signoff.sign", obj=so, request=request, after={"role": role, "document_sha256": sig.document_sha256}, summary=f"{actor.user.name} signed sign-off {so.number} ({so.title}) as {ROLE_LABELS.get(role, role)}")
    if {s.role for s in signatures(db, so)} >= set(so.required_approver_roles):
        so.status, so.approved_at = "approved", utcnow()
        audit.record(db, actor_id=actor.id, action="signoff.approved", obj=so, summary=f"Sign-off {so.number} ({so.title}) approved for {e.audit_ref}")
        _advance_if_ready(db, actor.user, e)
    return sig


def _advance_if_ready(db: Session, user: User, e: Engagement) -> None:
    from app.engagements.gates import advance_stage, gate_status

    if gate_status(db, e).ready:
        advance_stage(db, user, e)


def sign_off_out(db: Session, actor: Actor, so: SignOff) -> dict:
    from app.initiation.models import PackageDocument

    sigs = {s.role: s for s in signatures(db, so)}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_([s.user_id for s in sigs.values()])))} if sigs else {}
    doc = db.get(PackageDocument, so.document_version_id) if so.document_version_id else None
    return {
        "id": so.id, "number": so.number, "title": so.title, "status": so.status, "approved_at": so.approved_at.isoformat() if so.approved_at else None,
        "parties": [
            {"role": r, "role_label": ROLE_LABELS.get(r, r), "signed": r in sigs, "signed_by": names.get(sigs[r].user_id) if r in sigs else None, "signed_at": sigs[r].signed_at.isoformat() if r in sigs else None}
            for r in so.required_approver_roles
        ],
        "document": {"id": doc.id, "title": doc.title, "pdf_file_id": doc.pdf_file_id, "docx_file_id": doc.docx_file_id} if doc else None,
        "can_sign": so.status != "approved" and not is_excluded(so, actor.id) and actor.id not in (so.approver_ids or []) and signer_role(db, actor, so) is not None,
        "my_name": actor.user.name,
    }
