"""The monthly AI model list check with no real AI provider sends the reminder (review R6)."""
from datetime import datetime

from sqlalchemy import select

from tests.factories import make_org, make_user


def test_monthly_check_with_the_demonstration_model_sends_the_reminder(db, reg):
    from app.ai.models import AIInteraction
    from app.core.config import Settings
    from app.notifications.models import Notification
    from app.register import catalogue
    from app.register.models import ModelCatalogueRun

    fo = make_org(db, type="futran")
    adm = make_user(db, fo, roles=["admin"], name="Fran Admin", email="fran3@futran.test")
    db.commit()
    settings = Settings(_env_file=None, email_mode="outbox", ai_client="auto", anthropic_api_key=None)
    assert settings.test_mode
    assert catalogue.run_monthly(db, settings, datetime(2026, 12, 1, 10)) == 1
    assert db.query(AIInteraction).count() == 0
    assert db.scalar(select(ModelCatalogueRun.mode)) == "reminder"
    n = db.scalars(select(Notification).where(Notification.user_id == adm.id)).all()
    assert len(n) == 1 and "No AI provider is connected" in n[0].body
