"""Scheduled email work: continue paced sends, read replies, run due directory syncs and send reminders.
`run_mail_tick` runs every minute; each part decides for itself whether anything is due."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.mail import directory, reminders, replies, sending
from app.mail.models import MailConnection

log = logging.getLogger(__name__)


def _replies_due(db: Session, now: datetime) -> bool:
    for c in db.scalars(select(MailConnection).where(MailConnection.status == "connected", MailConnection.deleted_at.is_(None))):
        if (c.options or {}).get("sync_replies", True) and (c.last_sync_at is None or c.last_sync_at + timedelta(minutes=c.sync_interval_min or 15) <= now):
            return True
    return False


def run_mail_tick(db: Session, settings: Settings, now: datetime) -> dict[str, int]:
    out = {"dispatched": sending.dispatch_due(db, settings, now), "replies": 0, "directory_syncs": directory.run_due(db, settings, now),
           "reminders": reminders.run_reminders(db, settings, now)}
    if _replies_due(db, now):
        out["replies"] = replies.run_reply_sync(db, settings, now)
    return out
