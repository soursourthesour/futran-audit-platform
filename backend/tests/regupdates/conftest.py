import pytest
from sqlalchemy import select

from app.laws.publish import current_regulations
from app.reference.models import Jurisdiction
from app.regmaster.models import ClientGeography
from tests.factories import make_user
from tests.wsd_world import lit  # noqa: F401


@pytest.fixture
def world(db, lit):
    """ABC Corp operates in New York City, Northwind in Illinois. A Futran Legal Reviewer drafts updates."""
    j = {x.code: x for x in db.scalars(select(Jurisdiction).where(Jurisdiction.code.in_(["US", "US-NYC", "US-NY", "US-IL", "US-CA", "US-CO"])))}
    db.add_all([ClientGeography(organization_id=lit["abc"].id, jurisdiction_id=j["US-NYC"].id, basis="office"),
                ClientGeography(organization_id=lit["nw"].id, jurisdiction_id=j["US-IL"].id, basis="office")])
    from app.tenancy.models import Organization

    futran = db.get(Organization, lit["chief"].organization_id)
    lit["legal"] = make_user(db, futran, roles=["legal_reviewer"], name="Jordan Legal", email="jordan@futran.test")
    lit["legal2"] = make_user(db, futran, roles=["legal_reviewer"], name="Kim Legal", email="kim@futran.test")
    lit["screening"].risk_tier = 3
    lit["chatbot"].risk_tier = 1
    db.commit()
    lit["j"] = j
    lit["ll144"] = next(r for r in current_regulations(db) if r.short_name == "NYC Local Law 144")
    return lit


def nyc_enforcement(w, **kw):
    return {"change_type": "enforcement_action", "jurisdiction_id": w["j"]["US-NYC"].id, "law_name": "NYC Local Law 144",
            "title": "State Comptroller audit finds weak enforcement of the AI hiring law",
            "summary": "The audit (2024-N-6, 2 December 2025) found DCWP identified 1 issue of non-compliance among 32 companies; the auditors found at least 17.",
            "todo_text": "Confirm the bias audit is less than 12 months old\nCheck the published summary and candidate notice",
            "source_url": "https://www.osc.ny.gov/state-agencies/audits/2025/12/02/enforcement-local-law-144-automated-employment-decision-tools",
            "source_name": "Office of the New York State Comptroller", "affected_features": ["employment_hiring"]} | kw


def publish(client, db, w, body):
    from tests.factories import login_as

    login_as(client, db, w["legal"])
    r = client.post("/api/v1/reg/updates", json=body)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert client.post(f"/api/v1/reg/updates/{uid}/submit").status_code == 200
    login_as(client, db, w["chief"])
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "Checked against the audit report."})
    assert r.status_code == 200, r.text
    return r.json()
