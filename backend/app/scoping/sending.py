"""Client links for the scoping questionnaire (SM-06, SM-07)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.scoping.models import QuestionnaireSend


def close_links(db: Session, q) -> None:
    """Locking a version closes its client links."""
    now = utcnow()
    for s in db.scalars(select(QuestionnaireSend).where(QuestionnaireSend.questionnaire_id == q.id, QuestionnaireSend.revoked_at.is_(None))):
        s.revoked_at = now
