"""In-app notifications, with an optional email (spec §14). Task 26 adds the event table and scheduled jobs."""
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement, EngagementTeam
from app.notifications.models import Notification
from app.tenancy.models import User


def notify(db: Session, users: Iterable[User], kind: str, title: str, body: str | None = None, link: str | None = None, *, engagement: Engagement | None = None, settings=None, email_template: str | None = None, context: dict | None = None) -> list[Notification]:
    """Write an in-app notification for each user. Events that §14 sends by email also get an email, through
    `email_template` when given, else the generic notification email."""
    from app.notifications.events import channels_for

    emailed = "email" in channels_for(kind) or email_template is not None
    out = []
    for u in {u.id: u for u in users if u is not None and u.status != "disabled"}.values():
        n = Notification(organization_id=u.organization_id, user_id=u.id, kind=kind, title=title[:300], body=body, link=link, engagement_id=engagement.id if engagement else None)
        db.add(n)
        out.append(n)
        if emailed and settings is not None:
            from app.mail.service import send

            send(db, settings, email_template or "notification", to=[u.email], organization_id=u.organization_id, related=n,
                 context={"name": u.name, "title": title, "body": body or "", "link": f"{settings.base_url}{link}" if link else None, **(context or {})})
    db.flush()
    return out


def futran_team(db: Session, e: Engagement) -> list[User]:
    """The engagement's Futran team (Chief Auditor, auditors, managers, reviewers)."""
    return list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None))))
