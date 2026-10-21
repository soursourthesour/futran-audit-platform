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
    assert db.scalar(select(Engagement.id).where(Engagement.client_id == demo["abc"], Engagement.status != "completed")) is None  # one engagement per client in v1
    assert db.scalar(select(Engagement.status).where(Engagement.client_id == demo["northwind"])) == "pending_approval"
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


def test_demo_abc_report_shows_scoring_and_references(db, demo):
    """Every ABC Corp finding carries real citations, and the final report explains the scoring and lists references."""
    from app.findings.models import Finding
    from app.reports.models import Report

    abc = db.scalar(select(Engagement).where(Engagement.client_id == demo["abc"]))
    findings = list(db.scalars(select(Finding).where(Finding.engagement_id == abc.id, Finding.deleted_at.is_(None), Finding.status == "approved")))
    assert len(findings) == 6
    for f in findings:
        assert f.control_refs, f.ref
        assert f.description and not f.description.startswith("Raised automatically"), f.ref
    bias = next(f for f in findings if f.title.startswith("No bias testing"))
    assert "NYC_LL144 Admin. Code § 20-871(a)(1)" in bias.control_refs and bias.use_case_ids
    md = db.scalar(select(Report.body_md).where(Report.engagement_id == abc.id, Report.version == "v1.1"))
    assert "## 2. How this report rates risk and maturity" in md
    assert "NYC Local Law 144, Admin. Code § 20-871(a)(1)" in md and "6.2.01" in md and "Bias testing performed" in md
    assert "High (4)" in md and "76.0 × (1 − 0.75 × (2.25 − 1) ÷ 4) = 58.2" in md
    assert "ER-001" in md
