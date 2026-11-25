"""EU AI Act risk level on engagement use cases (11-25 change): the client answers the screening in the use case form,
Futran can correct it after submission (same people who set the final tier), and the level shows beside the tier."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from tests.factories import login_as
from tests.inventory.test_named_users import _uc, inv  # noqa: F401
from tests.initiation.conftest import live, people, submitted  # noqa: F401

HR_SCREENING = {"art5": ["none"], "annex_iii_area": "employment", "annex_i": False, "art50": ["none"], "gpai": False}
NOTES_SCREENING = {"art5": ["none"], "annex_iii_area": "none", "annex_i": False, "art50": ["synthetic_content"], "gpai": False}


def test_screening_in_the_form_sets_the_eu_level_beside_the_tier(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], decision_impact="consequential", eu_screening=HR_SCREENING)
    assert uc["proposed_tier"] == 3
    assert uc["eu_risk_level"] == "high_risk" and uc["eu_risk_label"] == "High-risk"
    assert "Employment and workers management (point 4)" in uc["eu_risk_reason"]
    assert uc["eu_screening"]["annex_iii_area"] == "employment"


def test_no_screening_is_not_screened(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]])
    assert uc["eu_risk_level"] is None and uc["eu_risk_label"] == "Not screened"


def test_bad_screening_is_refused(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    body = {"name": "x", "department_id": hr.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none",
            "eu_screening": {"art5": ["mind_control"], "annex_iii_area": "employment", "art50": ["none"]}}
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "eu_screening.art5"


def test_inventory_counts_eu_levels_and_tier_preview_shows_the_level(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    _uc(client, cid, hr, [copilot["id"]], eu_screening=HR_SCREENING)
    _uc(client, cid, hr, [copilot["id"]], name="Meeting notes", eu_screening=NOTES_SCREENING)
    _uc(client, cid, hr, [copilot["id"]], name="Unscreened")
    body = client.get(f"/api/v1/clients/{cid}/inventory").json()
    assert body["eu_levels"] == {"prohibited": 0, "high_risk": 1, "limited": 1, "minimal": 0, "not_screened": 1}
    p = client.post(f"/api/v1/clients/{cid}/use-cases/tier-preview", json={"decision_impact": "none", "data_categories": ["none"], "tool_ids": [], "eu_screening": NOTES_SCREENING}).json()
    assert p["eu_risk_level"] == "limited" and p["eu_risk_label"] == "Limited risk"
    assert client.get(f"/api/v1/clients/{cid}/eu-screening-options").json()["levels"]["minimal"] == "Minimal risk"


def test_futran_corrects_the_screening_after_submission(client, db, people, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], eu_screening=NOTES_SCREENING)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/submit").json()["status"] == "submitted"
    # the client cannot change it once submitted, and cannot use the Futran route
    assert client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": "x"}).status_code == 403
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": ""})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "rationale"
    r = client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": "The tool ranks applicants."})
    assert r.status_code == 200 and r.json()["eu_risk_level"] == "high_risk"
    log = db.scalar(select(AuditLog).where(AuditLog.object_id == uc["id"], AuditLog.action == "inventory.eu_screening"))
    assert log is not None and "High-risk" in log.summary
    login_as(client, db, people["aud2"])  # not on the team
    assert client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": "x"}).status_code == 404


def test_tier3_reason_names_ll144_only_for_nyc_hiring(client, db, inv):
    """BUG-02 wiring: the API passes the use case's text and the client's NYC geography to tier_reason.
    The initiation wizard in this fixture already records a New York City office."""
    from app.core.clock import utcnow
    from app.reference.models import Jurisdiction
    from app.regmaster.models import ClientGeography

    cid, e, maria, hr, copilot, chatgpt = inv
    other = _uc(client, cid, hr, [copilot["id"]], name="Invoice approvals", purpose="Approves supplier invoices", decision_impact="consequential")
    hiring = _uc(client, cid, hr, [copilot["id"]], name="Résumé screening", purpose="Ranks applicants for interviews", decision_impact="consequential")
    assert "Local Law 144" in hiring["tier_reason"]
    assert "Local Law 144" not in other["tier_reason"]
    p = client.post(f"/api/v1/clients/{cid}/use-cases/tier-preview", json={"decision_impact": "consequential", "data_categories": ["none"], "tool_ids": [],
                                                                           "name": "Interview scheduling", "purpose": "Hiring for the NYC office"}).json()
    assert "Local Law 144" in p["reason"]
    nyc = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US-NYC"))
    for g in db.scalars(select(ClientGeography).where(ClientGeography.organization_id == cid, ClientGeography.jurisdiction_id == nyc.id)):
        g.deleted_at = utcnow()
    db.commit()
    assert "Local Law 144" not in client.get(f"/api/v1/use-cases/{hiring['id']}").json()["tier_reason"]


def test_futran_correction_survives_a_client_resave(client, db, people, inv):
    """Review 11-25 #5 and #8: Futran corrects only submitted use cases; once corrected, a client re-save after a
    return keeps Futran's answers, and the client's audit entry records the EU fields."""
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], eu_screening=NOTES_SCREENING)
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": "Ranks applicants."})
    assert r.status_code == 409  # still a client draft
    login_as(client, db, maria)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/submit").json()["status"] == "submitted"
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/eu-screening", json={"eu_screening": HR_SCREENING, "rationale": "Ranks applicants."})
    assert r.status_code == 200 and r.json()["eu_set_by_futran"] is True
    login_as(client, db, maria)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": False, "comment": "Add the purpose."}).json()["status"] == "returned"
    body = {"name": "Résumé screening", "department_id": hr.id, "purpose": "Ranks applicants", "tool_ids": [copilot["id"]], "data_categories": ["none"],
            "decision_impact": "none", "usage": [], "named_users": [], "eu_screening": NOTES_SCREENING}
    r = client.put(f"/api/v1/use-cases/{uc['id']}", json=body)
    assert r.status_code == 200 and r.json()["eu_risk_level"] == "high_risk"  # Futran's answers kept
    log = db.scalar(select(AuditLog).where(AuditLog.object_id == uc["id"], AuditLog.action == "inventory.use_case").order_by(AuditLog.at.desc()))
    assert "eu_risk_level" in (log.after or {})


def test_every_practice_ticked_saves_a_reason_within_the_column(client, db, inv):
    """BUG-K01: the use case path stored the reason uncut; on PostgreSQL the save was a server error."""
    from app.euaiact import risk
    from app.inventory.models import UseCase

    cid, e, maria, hr, copilot, chatgpt = inv
    scr = {"art5": list(risk.art5_practices()), "annex_iii_area": None, "art50": []}
    uc = _uc(client, cid, hr, [copilot["id"]], eu_screening=scr)
    assert uc["eu_risk_level"] == "prohibited" and len(uc["eu_risk_reason"]) <= 400
    assert len(db.get(UseCase, uc["id"]).eu_risk_reason) <= 400
