"""Task 32: demo tenants, created through the real API and services."""
import pytest
from sqlalchemy import select

from app.engagements.models import ClientRequirement, Engagement
from app.laws.models import Regulation
from app.systems.models import AISystem
from app.tenancy.models import Organization


@pytest.fixture
def demo(client, db, matrix, settings, tmp_path):
    from app.demo.seed_demo import run
    from app.reference import LOADERS

    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    for name, loader in LOADERS:
        if name != "Law matrix" and not name.startswith("Jurisdictions"):
            loader(db)
    db.commit()
    return run(db, settings, client=client)


def test_demo_abc_completed_and_sys001_high(db, demo):
    from app.scoring.service import latest

    abc = db.scalar(select(Engagement).where(Engagement.client_id == demo["abc"], Engagement.status == "completed"))
    assert abc is not None and abc.stage == 9
    s = db.scalar(select(AISystem).where(AISystem.engagement_id == abc.id, AISystem.reference_id == "SYS-001"))
    row = latest(db, s)
    assert (row.inherent, row.maturity, row.residual, row.final_rating) == (76.0, 2.25, 58.2, "high")
    assert {x.reference_id for x in db.scalars(select(AISystem).where(AISystem.engagement_id == abc.id))} == {"SYS-001", "SYS-002", "SYS-003", "SYS-004"}
    pending = db.scalar(select(Engagement).where(Engagement.client_id == demo["abc"], Engagement.status == "pending_approval"))
    assert pending is not None and pending.name == "Annual review 2027"
    internal = db.get(Organization, demo["internal"])
    assert internal.is_internal and db.scalar(select(Engagement.stage).where(Engagement.client_id == internal.id)) == 2


def test_demo_meridian_suggests_eu_ai_act_gdpr_dpdp(db, demo):
    e = db.scalar(select(Engagement).where(Engagement.client_id == demo["meridian"]))
    assert e.stage == 3
    names = " | ".join(db.scalars(select(Regulation.short_name).join(ClientRequirement, ClientRequirement.regulation_id == Regulation.id).where(ClientRequirement.engagement_id == e.id)))
    assert "EU AI Act" in names or "Artificial Intelligence Act" in names
    assert "GDPR" in names or "General Data Protection" in names
    assert "DPDP" in names or "Digital Personal Data Protection" in names


def test_demo_refused_outside_test_mode(db, settings):
    from app.demo.seed_demo import run

    live = settings.model_copy(update={"mfa_required": True, "email_mode": "smtp"})
    with pytest.raises(PermissionError):
        run(db, live)
