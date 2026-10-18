"""Stage 4 client review: sign-offs 2 (each department), 3 and 4, the management representation and the snapshot lock."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement
from app.inventory.models import NamedUser, NamedUserLink, UseCase
from app.signoffs import service as so_svc
from app.tenancy.models import Department, Organization

STATUS_TEXT = {"draft": "is still a draft", "submitted": "is waiting for the Department Lead", "returned": "was returned to its author"}


def in_scope_departments(db: Session, e: Engagement) -> list[Department]:
    return list(db.scalars(select(Department).where(Department.organization_id == e.client_id, Department.deleted_at.is_(None), Department.in_scope.is_(True)).order_by(Department.name)))


def department_unmet(db: Session, e: Engagement, dept_id: str | None) -> list[str]:
    """Sign-off 2 for a department: every use case approved by the Department Lead; every named user without an account
    has confirmed, or the Lead has marked them unable to confirm with a reason (§8a)."""
    from app.inventory.service import effective_tier

    dept = db.get(Department, dept_id) if dept_id else None
    if dept is None or dept.organization_id != e.client_id or dept.deleted_at is not None or not dept.in_scope:
        return ["Choose a department in scope."]
    out = []
    for uc in db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.department_id == dept.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name)):
        if uc.status != "dept_approved":
            out.append(f"{uc.name} {STATUS_TEXT.get(uc.status, 'is not approved')}.")
            continue
        if (effective_tier(uc) or 1) < 2:
            continue
        for n in db.scalars(select(NamedUser).where(NamedUser.use_case_id == uc.id, NamedUser.deleted_at.is_(None), NamedUser.user_id.is_(None))):
            done = db.scalar(select(NamedUserLink.id).where(NamedUserLink.named_user_id == n.id, NamedUserLink.completed_at.is_not(None)).limit(1))
            if done is None and not n.unable_reason:
                out.append(f"{n.person_name} has not confirmed their use of {uc.name}. Wait for their answer, or mark them unable to confirm with a reason.")
    return out


def _departments_complete(db: Session, e: Engagement) -> list[str]:
    """Every department's sign-off 2 is approved and nothing was added or left in draft since."""
    out = []
    for d in in_scope_departments(db, e):
        cur = so_svc.current(db, e, 2, d.id)
        if cur is None or cur.status != "approved":
            out.append(f"Sign-off 2 for {d.name} is not approved yet.")
        out += [f"{d.name}: {m}" for m in department_unmet(db, e, d.id)]
    return out


def signoff3_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    return _departments_complete(db, e)


def signoff4_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    cur = so_svc.current(db, e, 3)
    out = [] if cur is not None and cur.status == "approved" else ["Sign-off 3 (data categories) is not approved yet."]
    return out + _departments_complete(db, e)


def representation_text(db: Session, e: Engagement) -> str:
    from app.reference.templates import render_template

    org = db.get(Organization, e.client_id)
    try:
        text = render_template(db, "management_representation", {"client": {"name": org.name}, "engagement": {"audit_ref": e.audit_ref}})
    except Exception:  # template missing or malformed: fall back to the spec wording
        text = ""
    return text.strip() or (f"To the best of our knowledge, the AI inventory submitted for {org.name} is complete and accurate for the audit period, "
                            "and we have disclosed all AI tools and use cases known to management in the departments in scope.")


def _lock(db: Session, settings, actor, so) -> None:
    from app.inventory.snapshot import lock_snapshot

    lock_snapshot(db, db.get(Engagement, so.engagement_id), so)


so_svc.PRECONDITIONS[2] = [department_unmet]
so_svc.PRECONDITIONS[3] = [signoff3_unmet]
so_svc.PRECONDITIONS[4] = [signoff4_unmet]
so_svc.ON_APPROVED[4] = [_lock]
so_svc.STATEMENTS[4] = representation_text


def _register_signoff5() -> None:
    from app.findings.service import _lock_on_signoff5, signoff5_unmet

    so_svc.PRECONDITIONS[5] = [signoff5_unmet]
    so_svc.ON_APPROVED[5] = [_lock_on_signoff5]


_register_signoff5()
