"""The R6b demo clients: one Copilot readiness and one EU AI Act readiness engagement, idempotent, new tenants only."""
from sqlalchemy import func, select

from app.demo.r6b import seed_r6b
from app.engagements.models import Engagement, EngagementTeam
from app.register.models import RegisterSystem
from tests.factories import make_org, make_user


def test_seed_is_idempotent_and_staffs_the_engagements(db):
    f = make_org(db, type="futran", name="Futran Solutions")
    auditor = make_user(db, f, roles=["auditor"], email="auditor1@futran.demo")
    out = seed_r6b(db, None)
    again = seed_r6b(db, None)
    assert out == again
    types = {e.type: e for e in db.scalars(select(Engagement))}
    assert set(types) == {"copilot_readiness", "eu_ai_act_readiness"}
    eu_team = {t.role for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == types["eu_ai_act_readiness"].id))}
    assert eu_team == {"auditor", "legal_reviewer"}
    assert db.scalar(select(func.count()).select_from(RegisterSystem).where(RegisterSystem.organization_id == out["eu_client"])) == 4
    assert db.scalar(select(EngagementTeam.user_id).where(EngagementTeam.engagement_id == types["copilot_readiness"].id)) == auditor.id
