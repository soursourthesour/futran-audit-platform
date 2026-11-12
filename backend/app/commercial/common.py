"""Small shared helpers for the commercial package."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tenancy.models import Organization, RoleAssignment, User

SALES_ROLES = ("sales_team", "sales_manager", "pricing_approver")  # "sales_team" is the Sales Officer (R2 relabels it)
FEE_ROLES = ("chief_auditor", "engagement_manager", "admin", *SALES_ROLES)  # spec B2: never Auditors


def money(v) -> float:
    return round(float(v or 0), 2)


def users_with_roles(db: Session, roles, *, futran_only: bool = True) -> list[User]:
    q = (select(User).join(RoleAssignment, RoleAssignment.user_id == User.id)
         .where(RoleAssignment.role.in_(list(roles)), RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status != "disabled"))
    if futran_only:
        q = q.join(Organization, Organization.id == User.organization_id).where(Organization.type == "futran")
    return list({u.id: u for u in db.scalars(q)}.values())


def futran_org(db: Session) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.type == "futran", Organization.deleted_at.is_(None)).order_by(Organization.created_at).limit(1))


def engagement_types() -> tuple[str, ...]:
    """The engagement types the platform accepts now: R6a's list when it is installed, else the original three."""
    from app.engagements.service import TYPES

    try:
        from app.servicetemplates.types import ENGAGEMENT_TYPES  # R6a

        keys = tuple(ENGAGEMENT_TYPES.keys()) if isinstance(ENGAGEMENT_TYPES, dict) else tuple(ENGAGEMENT_TYPES)
    except ImportError:
        keys = ()
    return tuple(dict.fromkeys((*TYPES, *keys)))


def type_label(t: str) -> str:
    from app.initiation.context import TYPE_LABELS

    try:
        from app.servicetemplates.types import ENGAGEMENT_TYPES  # R6a

        if isinstance(ENGAGEMENT_TYPES, dict) and isinstance(ENGAGEMENT_TYPES.get(t), str):
            return ENGAGEMENT_TYPES[t]
    except ImportError:
        pass
    return TYPE_LABELS.get(t) or t.replace("_", " ").capitalize()


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
