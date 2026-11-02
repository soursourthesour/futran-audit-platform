"""F19: SOC 2 readiness register and the platform's own AI features registered in Futran's organization (spec §21 F19,
rule 5 of §21: Futran governs its own AI)."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.platformtrust.models import SocControl
from app.platformtrust.seed import PLATFORM_AI, seed_controls, seed_platform_ai
from app.register.models import RegisterSystem
from tests.factories import login_as, make_org, make_user

API = "/api/v1"


def _world(db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Fran Admin", email="fran@futran.test")
    chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    org = make_org(db, name="ABC Corp")
    caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@abc.test")
    db.commit()
    return f, admin, chief, aud, org, caico


def test_starter_controls_cover_the_trust_services_criteria_once(db):
    f, *_ = _world(db)
    n = seed_controls(db)
    assert n >= 15
    assert seed_controls(db) == 0
    rows = list(db.scalars(select(SocControl).where(SocControl.organization_id == f.id)))
    codes = [r.code for r in rows]
    assert len(codes) == len(set(codes))
    assert {r.criterion for r in rows} == {"security", "availability", "confidentiality", "processing_integrity", "privacy"}
    assert all(r.status == "not_started" for r in rows)


def test_platform_ai_features_are_registered_in_futrans_organization_once(db):
    f, *_ , org, _ = _world(db)
    assert seed_platform_ai(db) == len(PLATFORM_AI)
    assert seed_platform_ai(db) == 0
    rows = list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == f.id).order_by(RegisterSystem.reference)))
    names = " | ".join(r.name for r in rows)
    for word in ("refresh", "Draft with Claude", "copilot", "questionnaire", "obligation"):
        assert word.lower() in names.lower(), word
    assert all(r.ai_provider == "anthropic" and r.sourcing == "in_house" and r.company_wide for r in rows)
    assert db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == org.id)) is None


def test_futrans_own_systems_stay_out_of_client_scans(db):
    from app.litigation.models import Case
    from app.litigation.service import match_case
    from app.sales.service import tracing_candidates

    f, *_ = _world(db)
    seed_platform_ai(db)
    own = db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == f.id))
    own.risk_tier, own.stage = 3, "live"
    db.commit()
    assert f.id not in tracing_candidates(db)
    case = Case(name="X v. Y", area="AI drafting", stage="filed", match_rule={"types": [own.type]})
    db.add(case)
    db.flush()
    assert all(m.organization_id != f.id for m in match_case(db, case))


def test_admin_keeps_the_register_and_others_read_or_see_nothing(client, db):
    f, admin, chief, aud, org, caico = _world(db)
    seed_controls(db)
    seed_platform_ai(db)
    db.commit()
    login_as(client, db, chief)
    page = client.get(f"{API}/staff/admin/trust")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["can_edit"] is False and len(body["ai_systems"]) == len(PLATFORM_AI) and body["summary"]["total"] >= 15
    cid = body["controls"][0]["id"]
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"status": "implemented"}).status_code == 403
    login_as(client, db, aud)
    assert client.get(f"{API}/staff/admin/trust").status_code == 403
    login_as(client, db, caico)
    assert client.get(f"{API}/staff/admin/trust").status_code == 404
    login_as(client, db, admin)
    r = client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"status": "implemented", "owner_id": chief.id, "evidence_link": "https://sharepoint.example/soc2/cc1-1",
                                                                     "last_reviewed_on": "2026-10-30", "notes": "Code of conduct signed by all staff."})
    assert r.status_code == 200, r.text
    assert r.json()["owner"] == "Cara Chief" and r.json()["next_review_on"] == "2027-10-30"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "platform_trust.control_edited")) is not None
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"status": "done"}).status_code == 422
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"owner_id": caico.id}).status_code == 422
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"evidence_link": "javascript:alert(1)"}).status_code == 422
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"evidence_link": "Architecture note: encryption at rest"}).status_code == 200
    assert client.patch(f"{API}/staff/admin/trust/controls/{cid}", json={"last_reviewed_on": "2099-01-01"}).status_code == 422
    new = client.post(f"{API}/staff/admin/trust/controls", json={"code": "CC9.9", "criterion": "security", "title": "Vendor SOC 2 reports reviewed each year"})
    assert new.status_code == 200 and new.json()["code"] == "CC9.9"
    assert client.post(f"{API}/staff/admin/trust/controls", json={"code": "CC9.9", "criterion": "security", "title": "Duplicate"}).status_code == 409
