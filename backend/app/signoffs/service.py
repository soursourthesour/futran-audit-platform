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


def create_sign_off(db: Session, e: Engagement, number: int, *, preparer_id: str | None, required_roles: list[str], document_id: str | None = None, scope_ref: str | None = None, excluded: list[str] | None = None, version: int = 1, supersedes_id: str | None = None) -> SignOff:
    so = SignOff(organization_id=e.client_id, engagement_id=e.id, number=number, title=SIGN_OFF_TITLES[number], scope_ref=scope_ref, preparer_id=preparer_id, excluded_signer_ids=list(dict.fromkeys([i for i in [preparer_id, *(excluded or [])] if i])), required_approver_roles=required_roles, approver_ids=[], document_version_id=document_id, status="pending", version=version, supersedes_id=supersedes_id)
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


def next_roles(db: Session, so: SignOff) -> list[str]:
    """Roles still to sign. A sequential sign-off offers only the next one (reviewer before approver)."""
    done = {s.role for s in signatures(db, so)}
    left = [r for r in so.required_approver_roles if r not in done]
    return left[:1] if so.sequential else left


def _holds(actor: Actor, so: SignOff, role: str) -> bool:
    if role == "dept_compliance_lead" and so.number == 2 and so.scope_ref:
        return actor.has_role(role, "department", so.scope_ref)
    return actor.has_role(role)


def signer_role(db: Session, actor: Actor, so: SignOff) -> str | None:
    """The still-unsigned required role this actor can sign for, if any. For a Futran role, the engagement team's
    holder signs; another holder of the role steps in only when the team's holder prepared the item."""
    for role in next_roles(db, so):
        if not _holds(actor, so, role):
            continue
        if is_excluded(so, actor.id) and not _fallback_self_sign(db, so, role):
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
        return hashlib.sha256(so.statement.encode()).hexdigest() if so.statement else None
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
    if so.status == "approved":
        raise Conflict("This sign-off is already complete.")
    if so.status == "returned" or _superseded(db, so):
        raise Conflict("This version is no longer open for signature.")
    role = signer_role(db, actor, so)
    if role is None:
        if is_excluded(so, actor.id):
            raise Forbidden("You prepared this item, so you cannot approve it. Another approver must sign it off.")
        if so.sequential and any(_holds(actor, so, r) for r in so.required_approver_roles):
            raise Conflict("It is not your turn to sign yet.")
        raise Forbidden("You are not one of the people who sign this.")
    if _norm(typed_name) != _norm(actor.user.name):
        raise Invalid("Type your name exactly as it appears on your account.", [{"field": "typed_name", "message": f"Type your full name: {actor.user.name}."}])
    unmet = [m for check in PRECONDITIONS.get(so.number, []) for m in check(db, db.get(Engagement, so.engagement_id), so.scope_ref)]
    if unmet:  # something changed since it was sent (spec §6): the signer must not approve what they have not seen
        raise Conflict("This can't be signed: things have changed since it was sent. Return it to the preparer.", [{"field": "precondition", "message": m} for m in unmet])
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
        for hook in ON_APPROVED.get(so.number, []):
            hook(db, settings, actor, so)
        _advance_if_ready(db, actor.user, e)
    else:
        _notify_next(db, settings, so)
    return sig


def _fallback_self_sign(db: Session, so: SignOff, role: str) -> bool:
    """A preparer may sign only as a stand-in role (DPO/Sponsor → CAICO) and only when nobody else holds that role."""
    if role not in (so.fallback_roles or []):
        return False
    return not [u for u in role_holders_for(db, so, role) if not is_excluded(so, u.id)]


def _superseded(db: Session, so: SignOff) -> bool:
    return db.scalar(select(SignOff.id).where(SignOff.supersedes_id == so.id, SignOff.deleted_at.is_(None))) is not None


def _advance_if_ready(db: Session, user: User, e: Engagement) -> None:
    from app.engagements.gates import advance_if_ready

    advance_if_ready(db, user, e)


def sign_off_out(db: Session, actor: Actor, so: SignOff) -> dict:
    from app.initiation.models import PackageDocument

    sigs = {s.role: s for s in signatures(db, so)}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_([s.user_id for s in sigs.values()])))} if sigs else {}
    doc = db.get(PackageDocument, so.document_version_id) if so.document_version_id else None
    preparer = db.get(User, so.preparer_id) if so.preparer_id else None
    return {
        "id": so.id, "number": so.number, "title": so.title, "status": so.status, "approved_at": so.approved_at.isoformat() if so.approved_at else None,
        "version": so.version, "scope_ref": so.scope_ref, "comment": so.comment, "statement": so.statement, "correction_reason": so.correction_reason,
        "preparer": preparer.name if preparer else None, "next_roles": next_roles(db, so) if so.status in ("pending", "in_review") else [],
        "parties": [
            {"role": r, "role_label": ROLE_LABELS.get(r, r), "signed": r in sigs, "signed_by": names.get(sigs[r].user_id) if r in sigs else None, "signed_at": sigs[r].signed_at.isoformat() if r in sigs else None}
            for r in so.required_approver_roles
        ],
        "document": {"id": doc.id, "title": doc.title, "pdf_file_id": doc.pdf_file_id, "docx_file_id": doc.docx_file_id} if doc else None,
        "can_sign": so.status in ("pending", "in_review") and actor.id not in (so.approver_ids or []) and signer_role(db, actor, so) is not None,
        "can_withdraw": so.status in ("pending", "in_review") and so.number != 1 and so.preparer_id == actor.id,
        "can_return": so.status in ("pending", "in_review") and so.number != 1 and actor.id not in (so.approver_ids or []) and signer_role(db, actor, so) is not None,
        "my_name": actor.user.name,
    }


# ---- sign-offs 2–8: who prepares and who signs (spec §8), with fallbacks for roles not appointed
from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class SignOffSpec:
    number: int
    preparer_roles: tuple[str, ...]
    signers: tuple[str, ...]  # reviewer, then approver
    per_department: bool = False


FALLBACKS = {"dpo": "caico", "exec_sponsor": "caico"}
SIGNOFF_SPECS: dict[int, SignOffSpec] = {
    2: SignOffSpec(2, ("contributor", "dept_compliance_lead", "caico"), ("dept_compliance_lead",), per_department=True),
    3: SignOffSpec(3, ("dept_compliance_lead", "caico"), ("dpo", "caico")),
    4: SignOffSpec(4, ("caico",), ("dpo", "exec_sponsor")),
    5: SignOffSpec(5, ("auditor", "chief_auditor"), ("chief_auditor",)),
    6: SignOffSpec(6, ("dept_compliance_lead", "caico"), ("caico", "exec_sponsor")),
    7: SignOffSpec(7, ("auditor", "chief_auditor"), ("chief_auditor",)),
    8: SignOffSpec(8, ("auditor", "chief_auditor"), ("caico",)),
}
# the last stage at which a signed item may still be reopened; later stages build on it (the snapshot, the released report)
CORRECTABLE_UNTIL = {2: 5, 3: 5, 4: 5, 5: 6, 6: 7, 7: 8, 8: 8}
ON_APPROVED: dict[int, list] = {}
PRECONDITIONS: dict[int, list] = {}
STATEMENTS: dict = {}  # number -> fn(db, engagement) -> the text signed when there is no package document


def resolve_signers(db: Session, e: Engagement, spec: SignOffSpec) -> tuple[list[str], list[str]]:
    """Signer roles in order, with DPO and Executive Sponsor replaced by the CAICO when nobody holds them."""
    from app.tenancy.models import Organization
    from app.tenancy.people import active_holders

    org = db.get(Organization, e.client_id)
    roles, fallback = [], []
    if all(r in FUTRAN_SIGNER_ROLES for r in spec.signers):
        return list(spec.signers), []
    for r in spec.signers:
        if r in FALLBACKS and not active_holders(db, org, r):
            r = FALLBACKS[r]
            fallback.append(r)
        if not roles or roles[-1] != r:
            roles.append(r)
    return roles, fallback


def _can_prepare(actor: Actor, spec: SignOffSpec, scope_ref: str | None) -> bool:
    if all(r in FUTRAN_SIGNER_ROLES for r in spec.preparer_roles) != actor.is_futran:
        return False
    for role in spec.preparer_roles:
        if spec.per_department and role in ("contributor", "dept_compliance_lead"):
            if actor.has_role(role, "department", scope_ref):
                return True
        elif actor.has_role(role):
            return True
    return False


def role_holders_for(db: Session, so: SignOff, role: str) -> list[User]:
    from app.tenancy.models import Organization, RoleAssignment
    from app.tenancy.people import active_holders

    if role in FUTRAN_SIGNER_ROLES:
        return list(db.scalars(select(User).where(User.id.in_(_team_holders(db, so, role)))))
    users = active_holders(db, db.get(Organization, so.organization_id), role)
    if role == "dept_compliance_lead" and so.scope_ref:
        scoped = set(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role == role, RoleAssignment.scope_id == so.scope_ref, RoleAssignment.deleted_at.is_(None))))
        users = [u for u in users if u.id in scoped]
    return users


def _notify_next(db: Session, settings, so: SignOff) -> None:
    from app.notifications.service import notify

    e = db.get(Engagement, so.engagement_id)
    users = [u for r in next_roles(db, so) for u in role_holders_for(db, so, r) if not is_excluded(so, u.id) or _fallback_self_sign(db, so, r)]
    link = {2: "/review", 3: "/review", 4: "/review", 6: "/responses", 7: f"/clients/{so.organization_id}/report", 8: "/report"}.get(so.number, f"/clients/{so.organization_id}")
    notify(db, users, "sign_off_awaiting", f"Sign-off {so.number} is waiting for you: {so.title}", f"{e.audit_ref}. Prepared by {(db.get(User, so.preparer_id).name if so.preparer_id else 'the team')}.", link, engagement=e, settings=settings)


def submit_signoff(db: Session, settings, actor: Actor, e: Engagement, number: int, scope_ref: str | None = None, statement: str | None = None) -> SignOff:
    """The preparer sends a sign-off for signature. A returned one comes back as a new version."""
    spec = SIGNOFF_SPECS.get(number)
    if spec is None:
        raise Invalid(errors=[{"field": "number", "message": "This sign-off is not prepared this way."}])
    if spec.per_department and not scope_ref:
        raise Invalid(errors=[{"field": "scope_ref", "message": "Choose the department."}])
    if not _can_prepare(actor, spec, scope_ref):
        raise Forbidden("You are not one of the people who prepare this sign-off.")
    if e.stage < 3:
        raise Conflict("Client review sign-offs open once discovery has started.")
    unmet = [m for check in PRECONDITIONS.get(number, []) for m in check(db, e, scope_ref)]
    if unmet:
        raise Conflict(f"Sign-off {number} can't be sent yet.", [{"field": "precondition", "message": m} for m in unmet])
    cur = current(db, e, number, scope_ref)
    if cur is not None and cur.status in ("pending", "in_review"):
        raise Conflict("This sign-off is already waiting for signatures.")
    if cur is not None and cur.status == "approved":
        raise Conflict("This sign-off is approved. To change it, correct it with a reason.")
    roles, fallback = resolve_signers(db, e, spec)
    _assert_signable(db, e, roles, fallback, scope_ref, actor.id)
    so = create_sign_off(db, e, number, preparer_id=actor.id, required_roles=roles, scope_ref=scope_ref, version=cur.version + 1 if cur else 1, supersedes_id=cur.id if cur else None)
    so.status, so.sequential, so.fallback_roles, so.statement = "in_review", True, fallback, statement
    db.flush()
    audit.record(db, actor_id=actor.id, action="signoff.submit", obj=so, after={"version": so.version, "signers": roles}, summary=f"{actor.user.name} sent sign-off {number} ({so.title}) for signature")
    _notify_next(db, settings, so)
    return so


def _assert_signable(db: Session, e: Engagement, roles: list[str], fallback: list[str], scope_ref: str | None, preparer_id: str) -> None:
    """Every signer role needs someone other than the preparer, or the sign-off could never be completed (spec §6 rule 2)."""
    from app.tenancy.models import Organization, RoleAssignment
    from app.tenancy.people import active_holders

    for role in roles:
        if role in fallback:
            continue  # a stand-in CAICO may sign what they prepared when nobody holds the role
        if role in FUTRAN_SIGNER_ROLES:
            org = db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False)))
            users = active_holders(db, org, role) if org else []
        else:
            users = active_holders(db, db.get(Organization, e.client_id), role)
            if role == "dept_compliance_lead" and scope_ref:
                scoped = set(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role == role, RoleAssignment.scope_id == scope_ref, RoleAssignment.deleted_at.is_(None))))
                users = [u for u in users if u.id in scoped]
        if not [u for u in users if u.id != preparer_id]:
            label = ROLE_LABELS.get(role, role)
            raise Conflict(f"You are the only {label} who could sign this, and you can't sign what you prepared. Ask someone else to prepare it, or appoint another {label}.")


def withdraw(db: Session, actor: Actor, so: SignOff) -> SignOff:
    """The preparer takes back a sign-off still waiting for signatures; it is kept as returned and can be sent again."""
    if so.preparer_id != actor.id or so.number == 1:
        raise Forbidden("Only the person who prepared this sign-off can withdraw it.")
    if so.status not in ("pending", "in_review"):
        raise Conflict("Only a sign-off waiting for signatures can be withdrawn.")
    so.status, so.comment = "returned", "Withdrawn by the preparer."
    audit.record(db, actor_id=actor.id, action="signoff.withdrawn", obj=so, summary=f"{actor.user.name} withdrew sign-off {so.number} ({so.title})")
    return so


def return_signoff(db: Session, settings, actor: Actor, so: SignOff, comment: str | None) -> SignOff:
    comment = " ".join(str(comment or "").split())
    if not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say what needs to change."}])
    if so.status not in ("pending", "in_review") or signer_role(db, actor, so) is None:
        raise Forbidden("Only the person whose signature is next can return this.")
    so.status, so.comment = "returned", comment[:2000]
    audit.record(db, actor_id=actor.id, action="signoff.returned", obj=so, after={"comment": so.comment}, summary=f"{actor.user.name} returned sign-off {so.number} ({so.title})")
    from app.notifications.service import notify

    notify(db, [db.get(User, so.preparer_id)] if so.preparer_id else [], "sign_off_returned", f"Sign-off {so.number} was returned: {so.title}", comment,
           {5: f"/clients/{so.organization_id}/findings", 7: f"/clients/{so.organization_id}/report", 8: f"/clients/{so.organization_id}/report", 6: "/responses"}.get(so.number, "/review"), engagement=db.get(Engagement, so.engagement_id), settings=settings)
    return so


def correct(db: Session, settings, actor: Actor, so: SignOff, reason: str | None) -> SignOff:
    """Changing a signed item: a new version with a reason, the signed one is kept unchanged."""
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Give the reason for the correction."}])
    spec = SIGNOFF_SPECS.get(so.number)
    if spec is None or not _can_prepare(actor, spec, so.scope_ref):
        raise Forbidden("You are not one of the people who prepare this sign-off.")
    if so.status != "approved" or _superseded(db, so):
        raise Conflict("Only the current approved version can be corrected.")
    e = db.get(Engagement, so.engagement_id)
    last = CORRECTABLE_UNTIL.get(so.number, 0)
    if e.status not in ("initiated", "in_progress") or e.stage > last:
        raise Conflict(f"Sign-off {so.number} can no longer be corrected: later work relies on it (corrections are possible up to stage {last}).")
    roles, fallback = resolve_signers(db, e, spec)
    _assert_signable(db, e, roles, fallback, so.scope_ref, actor.id)
    new = create_sign_off(db, e, so.number, preparer_id=actor.id, required_roles=roles, scope_ref=so.scope_ref, version=so.version + 1, supersedes_id=so.id)
    new.status, new.sequential, new.fallback_roles, new.statement = "in_review", True, fallback, so.statement
    new.correction_reason = reason[:2000]
    db.flush()
    if so.number == 4:
        e.client_answers_locked_at = None  # the client may update its answers; re-approval locks a new snapshot version
    audit.record(db, actor_id=actor.id, action="signoff.corrected", obj=new, before={"version": so.version}, after={"version": new.version, "reason": new.correction_reason},
                 summary=f"{actor.user.name} reopened sign-off {so.number} as version {new.version}: {reason[:120]}")
    _notify_next(db, settings, new)
    return new
