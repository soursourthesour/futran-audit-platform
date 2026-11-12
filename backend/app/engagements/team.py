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


LEAD_ROLE = "chief_auditor"  # the team role shown as "Chief Auditor (Lead Auditor)"


def check_lead_independence(db: Session, client_id: str, user_id: str) -> None:
    """Independence rule (spec §21 F7, §21.1): a Futran person recorded as having written or tailored one of this client's
    policies cannot be Lead Auditor on a later engagement for the client. Raises Conflict naming the policy.
    Every path that puts someone on an engagement team as Lead Auditor calls this (the new-client wizard; an annual review
    that copies a team must call it too)."""
    from app.core.errors import Conflict
    from app.policies.service import tailored_by

    hits = tailored_by(db, client_id, user_id)
    if hits:
        u = db.get(User, user_id)
        titles = join_words(sorted({p.title for p in hits}))
        raise Conflict(f"{u.name if u else 'This person'} helped Futran write this client's {titles}, so they cannot be Lead Auditor on its audit. "
                       "Choose a different Lead Auditor.")


def check_separate_team(db: Session, client_id: str, user_id: str, *, engagement_id: str | None = None) -> None:
    """Independence rules I-3 and I-2 (Release 2 spec §4.7): the person who holds this client's Fractional AI Governance
    Officer role, or whom the Chief Auditor recorded as the separate delivery team for policy drafting, AgentWarden or
    Agent Assure, cannot be on the client's audit team in any role. Raises Conflict. Every path that puts someone on an
    engagement team calls this next to `check_lead_independence`. The records come from the hand-off (SM-13)."""
    from app.core.errors import Conflict

    try:
        from app.commercial.handoff import require_separate_team_named, separate_team_user_ids
    except ImportError:  # the commercial module is not installed: nothing has been handed off yet
        return
    if engagement_id is not None:  # R5: a hand-off's own drafts are not staffed until the Chief Auditor names the separate team
        require_separate_team_named(db, client_id, engagement_id)
    if user_id in separate_team_user_ids(db, client_id):
        u = db.get(User, user_id)
        raise Conflict(f"{u.name if u else 'This person'} delivers this client's governance work for Futran (Fractional AI Governance Officer or a "
                       "separate delivery team), so they cannot be on its audit team.")
