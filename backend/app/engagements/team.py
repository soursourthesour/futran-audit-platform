"""The Futran team by person: one entry per person with every role they hold on the engagement.

A person can hold several roles (for example Chief Auditor and Auditor). Lists, documents and the conflict-of-interest
confirmation name each person once.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement, EngagementTeam
from app.tenancy.models import User

ROLE_ORDER = ("chief_auditor", "engagement_manager", "auditor", "qa_reviewer", "legal_reviewer")
ROLE_LABELS = {
    "chief_auditor": "Chief Auditor (Lead Auditor)",
    "engagement_manager": "Engagement Manager",
    "auditor": "Auditor",
    "qa_reviewer": "QA Reviewer",
    "legal_reviewer": "Legal / compliance reviewer",
}


def join_words(items: list[str]) -> str:
    """"A", "A and B", "A, B and C"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def order_roles(roles) -> list[str]:
    return sorted(dict.fromkeys(roles), key=lambda r: ROLE_ORDER.index(r) if r in ROLE_ORDER else len(ROLE_ORDER))


def roles_label(roles) -> str:
    return join_words([ROLE_LABELS.get(r, r) for r in order_roles(roles)])


def team_rows(db: Session, e: Engagement) -> list[tuple[EngagementTeam, User]]:
    return list(db.execute(
        select(EngagementTeam, User).join(User, User.id == EngagementTeam.user_id)
        .where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None)).order_by(EngagementTeam.created_at)
    ).tuples())


def team_by_person(db: Session, e: Engagement) -> list[dict]:
    """One entry per person, ordered by their most senior role on the engagement."""
    people: dict[str, dict] = {}
    for t, u in team_rows(db, e):
        p = people.setdefault(u.id, {"user_id": u.id, "name": u.name, "email": u.email, "roles": [], "confirmed": []})
        p["roles"].append(t.role)
        if t.conflict_confirmed_at is not None:
            p["confirmed"].append(t.role)
    out = []
    for p in people.values():
        roles = order_roles(p.pop("roles"))
        confirmed = set(p.pop("confirmed"))
        out.append(p | {
            "roles": roles, "role_label": roles_label(roles), "conflict_confirmed": confirmed >= set(roles),
            "unconfirmed_roles": [r for r in roles if r not in confirmed],
        })
    return sorted(out, key=lambda p: (ROLE_ORDER.index(p["roles"][0]) if p["roles"][0] in ROLE_ORDER else len(ROLE_ORDER), p["name"]))
