"""Reminders to people who have not responded (spec §26.4 step 5), in the send's own delivery mode."""
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.clock import utcnow
from app.core.config import Settings
from app.mail import adminlog
from app.mail.models import DirectoryPerson, MailRecipient, MailSend, MailThread
from app.mail.sending import dispatch, next_subject_ref, responded_emails
from app.tenancy.models import User

WAITING = ("sent", "delivered", "opened")


def _done_emails(db: Session, s: MailSend) -> set[str]:
    done = responded_emails(db, (s.campaign_type, s.campaign_id)) if s.campaign_type and s.campaign_id else set()
    rows = db.scalars(select(MailRecipient.email).join(MailSend, MailSend.id == MailRecipient.send_id).where(
        (MailSend.id == s.id) | (MailSend.parent_send_id == s.id), MailRecipient.status == "completed"))
    return done | {e.lower() for e in rows}


def non_responders(db: Session, s: MailSend, *, due_index: int | None = None) -> list[MailRecipient]:
    """Recipients of `s` still waiting: not completed, not bounced, not left or opted out of reminders."""
    done = _done_emails(db, s)
    out = []
    for r in db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id, MailRecipient.status.in_(WAITING))):
        if r.email.lower() in done:
            continue
        if due_index is not None and (r.reminders_sent or 0) >= due_index:
            continue
        p = db.get(DirectoryPerson, r.person_id) if r.person_id else None
        if p is not None and (p.status != "active" or p.reminders_opt_out):
            continue
        out.append(r)
    return out


def _claim(db: Session, r: MailRecipient, due_index: int, now: datetime) -> bool:
    """Record the planned reminder on the recipient before it is sent, only if no other run has: a conditional update
    checked by its row count, so two scheduler runs that overlap remind each person once."""
    res = db.execute(update(MailRecipient).where(MailRecipient.id == r.id, func.coalesce(MailRecipient.reminders_sent, 0) < due_index)
                     .values(reminders_sent=due_index, last_reminded_at=now).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        db.refresh(r)
        return False
    set_committed_value(r, "reminders_sent", due_index)
    set_committed_value(r, "last_reminded_at", now)
    return True


def remind(db: Session, settings: Settings, s: MailSend, targets: list[MailRecipient], now: datetime, actor: User | None = None, due_index: int | None = None) -> MailSend | None:
    if due_index is not None:
        targets = [r for r in targets if _claim(db, r, due_index, now)]
    if not targets:
        return None
    rem = MailSend(organization_id=s.organization_id, engagement_id=s.engagement_id, kind="reminder", template_id=s.template_id, template_version=s.template_version,
                   template_key=s.template_key, template_name=s.template_name, subject=f"Reminder: {s.subject}" if s.subject else None, sender_connection_id=s.sender_connection_id,
                   sender_user_id=s.sender_user_id, sender_label=s.sender_label, channel=s.channel, groups=s.groups, exclusions=s.exclusions, mode=s.mode,
                   batch_size=s.batch_size, sent_by=actor.id if actor else None, sent_by_name=s.sent_by_name if actor is None else None, link_days=s.link_days,
                   campaign_type=s.campaign_type, campaign_id=s.campaign_id, context=s.context, recipient_count=len(targets), status="queued", parent_send_id=s.id,
                   expansion=[{"label": "Have not responded", "count": len(targets), "kind": "total"}], department_scope=s.department_scope,
                   retain_until=adminlog.retain_until(now), created_by=actor.id if actor else None)
    if actor is not None:
        from app.mail.sending import _who

        rem.sent_by_name = _who(db, actor)
    db.add(rem)
    db.flush()
    db.add(MailThread(organization_id=s.organization_id, send_id=rem.id, engagement_id=s.engagement_id, connection_id=s.sender_connection_id, subject_ref=next_subject_ref(db)))
    for i, r in enumerate(targets):
        db.add(MailRecipient(organization_id=s.organization_id, send_id=rem.id, person_id=r.person_id, email=r.email, name=r.name, status="queued",
                             batch_no=(i // (s.batch_size or 450)) + 1 if s.mode == "bcc" else None))
        if due_index is None:  # a reminder sent by hand; scheduled ones were claimed above
            r.reminders_sent = (r.reminders_sent or 0) + 1
            r.last_reminded_at = now
    db.flush()
    adminlog.write(db, organization_id=s.organization_id, category="send", action="reminder", actor=actor, engagement_id=s.engagement_id, send_id=rem.id,
                   summary=f"Reminder for {s.template_name or 'an email'} to {len(targets):,} {'person' if len(targets) == 1 else 'people'} who have not responded")
    dispatch(db, settings, rem, now)
    return rem


def run_reminders(db: Session, settings: Settings, now: datetime | None = None) -> int:
    """Scheduler: for every send with a reminder plan, remind non-responders once per planned day that has passed."""
    now = now or utcnow()
    n = 0
    for s in list(db.scalars(select(MailSend).where(MailSend.kind == "group", MailSend.reminder_plan.is_not(None), MailSend.sent_at.is_not(None)))):
        due = sum(1 for d in s.reminder_plan or [] if s.sent_at + timedelta(days=int(d)) <= now)
        if due == 0:
            continue
        rem = remind(db, settings, s, non_responders(db, s, due_index=due), now, due_index=due)
        if rem is not None:
            n += rem.recipient_count
    return n
