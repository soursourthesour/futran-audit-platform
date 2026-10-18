"""Daily jobs (spec §14). Each is a plain function `run_<job>(db, settings, now)` so tests can call it with any date;
the scheduler runs `run_daily` once a day."""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.config import Settings
from app.engagements.models import ClientContact, Engagement, EngagementTeam
from app.invitations.models import Invitation
from app.notifications.service import futran_team, notify
from app.tenancy.models import Organization, RoleAssignment, User

log = logging.getLogger(__name__)
WARN_BEFORE = timedelta(hours=48)


def _dt(now: date | datetime) -> datetime:
    return now if isinstance(now, datetime) else datetime.combine(now, time(6, 0))


def _d(now: date | datetime) -> date:
    return now.date() if isinstance(now, datetime) else now


def _current_engagement(db: Session, org_id: str) -> Engagement | None:
    return db.scalar(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"])).order_by(Engagement.created_at.desc()).limit(1))


def _futran_contacts(db: Session, user: User) -> list[User]:
    """Who at Futran looks after this person's invitation: the engagement team for a client user, admins for Futran staff."""
    org = db.get(Organization, user.organization_id)
    if org.type == "client":
        e = _current_engagement(db, org.id)
        return futran_team(db, e) if e else []
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(User.organization_id == org.id, RoleAssignment.role == "admin", RoleAssignment.deleted_at.is_(None))))


# ---- invitations
def run_invitation_warnings(db: Session, settings: Settings, now) -> int:
    now = _dt(now)
    n = 0
    for inv in db.scalars(select(Invitation).where(Invitation.status == "pending", Invitation.warned_at.is_(None), Invitation.expires_at > now, Invitation.expires_at <= now + WARN_BEFORE)):
        user = db.get(User, inv.user_id)
        if user is None or user.status != "invited":
            continue
        from app.mail.service import send

        org = db.get(Organization, user.organization_id)
        sender = db.get(User, inv.created_by) if inv.created_by else None
        send(db, settings, "invitation_expiring", to=[user.email], organization_id=user.organization_id, related=inv,
             context={"name": user.name.split()[0], "organization": org.name, "expires": f"{inv.expires_at.day} {inv.expires_at:%B %Y}", "sent": f"{inv.sent_at.day} {inv.sent_at:%B}",
                      "contact": sender.name if sender else "your contact at Futran"})
        inv.warned_at = now
        n += 1
    db.flush()
    return n


def run_invitation_expiry(db: Session, settings: Settings, now) -> int:
    now = _dt(now)
    n = 0
    for inv in db.scalars(select(Invitation).where(Invitation.status == "pending", Invitation.expires_at <= now)):
        inv.status = "expired"
        user = db.get(User, inv.user_id)
        audit.record(db, actor_id=None, actor_name="Scheduler", action="invitation.expired", obj=inv, summary=f"The invitation for {user.email} expired unused")
        org = db.get(Organization, user.organization_id)
        notify(db, _futran_contacts(db, user), "invitation_expired", f"{org.name}: the invitation for {user.name} expired", f"{user.email} did not accept it within 7 days. Send a new invitation from the client page.",
               f"/clients/{org.id}" if org.type == "client" else "/admin/users", engagement=_current_engagement(db, org.id) if org.type == "client" else None, settings=settings)
        n += 1
    db.flush()
    return n


# ---- requests due soon (evidence and document requests)
DUE_SOON_SOURCES: list[Callable[[Session, Settings, date], int]] = []


def run_due_soon(db: Session, settings: Settings, now) -> int:
    today = _d(now)
    return sum(src(db, settings, today) for src in DUE_SOON_SOURCES)


def _document_requests_due(db: Session, settings: Settings, today: date) -> int:
    from app.docrequests.models import DocumentRequest
    from app.reference.models import DocumentCatalogItem

    by_engagement: dict[str, list[DocumentRequest]] = {}
    for r in db.scalars(select(DocumentRequest).where(DocumentRequest.status == "pending", DocumentRequest.deleted_at.is_(None), DocumentRequest.due_at == today + timedelta(days=3), DocumentRequest.due_warned_at.is_(None))):
        by_engagement.setdefault(r.engagement_id, []).append(r)
        r.due_warned_at = _dt(today)
    for eid, reqs in by_engagement.items():
        e = db.get(Engagement, eid)
        org = db.get(Organization, e.client_id)
        caico = db.scalar(select(User).join(ClientContact, ClientContact.user_id == User.id).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == "caico", ClientContact.deleted_at.is_(None)))
        titles = ", ".join(db.get(DocumentCatalogItem, r.catalog_item_id).title for r in reqs[:5]) + (f" and {len(reqs) - 5} more" if len(reqs) > 5 else "")
        notify(db, [caico], "evidence_request", f"{org.name}: {len(reqs)} requested document{'s' if len(reqs) != 1 else ''} due in 3 days", titles, "/documents", engagement=e, settings=settings)
    return sum(len(v) for v in by_engagement.values())


DUE_SOON_SOURCES.append(_document_requests_due)


def _evidence_requests_due(db: Session, settings: Settings, today: date) -> int:
    from app.docrequests.evidence_requests import due_soon

    return due_soon(db, settings, today)


DUE_SOON_SOURCES.append(_evidence_requests_due)


def run_escalations(db: Session, settings: Settings, now) -> int:
    from app.docrequests.service import escalate_due

    return escalate_due(db, settings, _d(now))


# ---- weekly overdue digest
@dataclass
class OverdueItem:
    organization_id: str
    engagement_id: str
    owner: str
    description: str
    due: date
    kind: str  # commitment | remediation


DIGEST_SOURCES: list[Callable[[Session, date], list[OverdueItem]]] = []


def _overdue_commitments(db: Session, today: date) -> list[OverdueItem]:
    from app.governance.models import Commitment

    rows = db.scalars(select(Commitment).where(Commitment.deleted_at.is_(None), Commitment.status.in_(["open", "in_progress", "reopened"]), Commitment.target_date < today))
    return [OverdueItem(c.organization_id, c.engagement_id, c.owner, c.description, c.target_date, "commitment") for c in rows]


DIGEST_SOURCES.append(_overdue_commitments)


def run_weekly_digest(db: Session, settings: Settings, now) -> int:
    """Mondays only: one email per person per client, items grouped by owner (CAICO and the assigned auditors)."""
    today = _d(now)
    if today.weekday() != 0:
        return 0
    items = [i for src in DIGEST_SOURCES for i in src(db, today)]
    by_org: dict[str, list[OverdueItem]] = {}
    for i in items:
        by_org.setdefault(i.organization_id, []).append(i)
    sent = 0
    from app.mail.service import send

    for org_id, its in by_org.items():
        org = db.get(Organization, org_id)
        groups: dict[str, list[dict]] = {}
        for i in sorted(its, key=lambda x: (x.owner.casefold(), x.due)):
            groups.setdefault(i.owner, []).append({"description": i.description, "due": f"{i.due.day} {i.due:%b %Y}", "kind": i.kind})
        engagement_ids = {i.engagement_id for i in its}
        recipients: dict[str, User] = {}
        for eid in engagement_ids:
            for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == eid, ClientContact.contact_role == "caico", ClientContact.deleted_at.is_(None))):
                u = db.get(User, c.user_id) if c.user_id else None
                if u is not None:
                    recipients[u.id] = u
            for u in db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == eid, EngagementTeam.role.in_(["auditor", "chief_auditor"]), EngagementTeam.deleted_at.is_(None))):
                recipients[u.id] = u
        for u in recipients.values():
            if u.status == "disabled":
                continue
            link = f"{settings.base_url}/clients/{org.id}" if db.get(Organization, u.organization_id).type == "futran" else f"{settings.base_url}/start"
            send(db, settings, "overdue_digest", to=[u.email], organization_id=org.id,
                 context={"name": u.name.split()[0], "organization": org.name, "count": len(its), "groups": [{"owner": k, "items": v} for k, v in groups.items()], "link": link})
            sent += 1
    db.flush()
    return sent


# ---- the daily run
JOBS = {
    "invitation_warnings": run_invitation_warnings, "invitation_expiry": run_invitation_expiry, "due_soon": run_due_soon,
    "escalations": run_escalations, "weekly_digest": run_weekly_digest,
}


def run_daily(db: Session, settings: Settings, now) -> dict[str, int | str]:
    out: dict[str, int | str] = {}
    for name, job in JOBS.items():
        try:
            with db.begin_nested():
                out[name] = job(db, settings, now)
        except Exception as exc:  # one failing job must not stop the others
            log.exception("Daily job %s failed", name)
            out[name] = f"failed: {exc.__class__.__name__}"
    db.commit()
    return out


def start_scheduler(app) -> None:
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.core.clock import utcnow

    settings = app.state.settings

    def tick():
        db = app.state.sessionmaker()
        try:
            log.info("Daily jobs: %s", run_daily(db, settings, utcnow()))
        finally:
            db.close()

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(tick, "cron", hour=10, minute=0, id="daily", replace_existing=True)  # 06:00 New York
    sched.start()
    app.state.scheduler = sched
