import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.passwords import hash_password, validate_password
from app.auth.sessions import hash_token
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid, NotFound
from app.invitations.models import Invitation
from app.mail.service import send
from app.policy.roles import role_label
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

INVITE_DAYS = 7


def invite_user(
    db: Session,
    settings: Settings,
    inviter: User | None,
    user: User,
    template_key: str = "invitation",
    extra_context: dict | None = None,
) -> Invitation:
    """Send a fresh single-use invitation; any earlier pending invitation stops working."""
    if user.status == "active" and user.password_hash:
        raise Conflict(f"{user.name} has already accepted an invitation.")
    if user.status == "disabled" or user.deleted_at is not None:
        raise Conflict(f"{user.name}'s account is disabled. Enable it before sending an invitation.")
    now = utcnow()
    for old in db.scalars(select(Invitation).where(Invitation.user_id == user.id, Invitation.status == "pending")):
        old.status = "revoked"
    raw = secrets.token_urlsafe(32)
    inv = Invitation(
        organization_id=user.organization_id,
        user_id=user.id,
        token_hash=hash_token(raw),
        sent_at=now,
        expires_at=now + timedelta(days=INVITE_DAYS),
        status="pending",
        template_key=template_key,
        created_by=inviter.id if inviter else None,
    )
    db.add(inv)
    org = db.get(Organization, user.organization_id)
    roles = [r.role for r in roles_of(db, user.id)]
    context = {
        "name": user.name,
        "organization_name": org.name,
        "inviter_name": inviter.name if inviter else "Futran Solutions",
        "role_label": ", ".join(role_label(r) for r in roles) if roles else "",
        "accept_url": f"{settings.base_url}/invite/{raw}",
        "mfa_required": settings.mfa_required,
        **(extra_context or {}),
    }
    send(
        db, settings, template_key, to=[user.email], context=context, organization_id=org.id, related=inv,
        actor_id=inviter.id if inviter else None, redact={"accept_url": "[secure link sent only to the recipient]"},
    )
    inv.raw_token = raw  # transient: for the caller (CLI) only; never stored
    audit.record(db, actor_id=inviter.id if inviter else None, action="invitation.sent", obj=inv, summary=f"Invitation sent to {user.email}")
    db.flush()
    return inv


def find_invitation(db: Session, raw: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(raw)))
    if inv is None:
        raise NotFound("This invitation link is not valid.")
    return inv


def invitation_state(inv: Invitation) -> dict:
    return {
        "expired": inv.status == "expired" or (inv.status == "pending" and utcnow() >= inv.expires_at),
        "used": inv.status in ("accepted", "revoked"),
    }


def accept_invitation(db: Session, settings: Settings, raw: str, password: str) -> User:
    inv = find_invitation(db, raw)
    if inv.status != "pending":
        raise Conflict("This invitation has already been used or replaced by a newer one. Ask for a new invitation.")
    if utcnow() >= inv.expires_at:
        inv.status = "expired"
        raise Conflict("This invitation has expired. Ask your contact at Futran to send a new one.")
    user = db.get(User, inv.user_id)
    if user is None or user.deleted_at is not None or user.status == "disabled":
        inv.status = "revoked"
        raise Conflict("This account is disabled. Contact your administrator.")
    errors = validate_password(password, user.email)
    if errors:
        raise Invalid("Choose a stronger password.", [{"field": "password", "message": e} for e in errors])
    user.password_hash = hash_password(password)
    user.status = "active"
    inv.status = "accepted"
    inv.accepted_at = utcnow()
    audit.record(db, actor_id=user.id, action="invitation.accepted", obj=inv, summary=f"{user.email} accepted the invitation")
    db.flush()
    return user


def revoke_pending_invitations(db: Session, user_id: str) -> int:
    n = 0
    for inv in db.scalars(select(Invitation).where(Invitation.user_id == user_id, Invitation.status == "pending")):
        inv.status = "revoked"
        n += 1
    return n


def decline_invitation(db: Session, settings: Settings, raw: str) -> Invitation:
    from app.notifications.service import notify

    inv = find_invitation(db, raw)
    if inv.status != "pending":
        raise Conflict("This invitation is no longer active.")
    inv.status = "revoked"
    user = db.get(User, inv.user_id)
    audit.record(db, actor_id=None, actor_name="Invitation recipient", action="invitation.declined", obj=inv, summary=f"The recipient of the invitation for {user.email} said it was not meant for them")
    inviter = db.get(User, inv.created_by) if inv.created_by else None
    if inviter is not None:
        notify(db, [inviter], "invitation_declined", f"Invitation for {user.name} cancelled", f"The person who opened the invitation sent to {user.email} said it was not for them. Check the email address and invite again.", None, settings=settings)
    return inv
