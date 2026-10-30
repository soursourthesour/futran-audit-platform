"""Security review: case matches show register detail only to people with access to that client's register. Everyone
else (Sales, an Auditor not on the client's engagement) sees the client name and system type only (§27.5)."""
from app.engagements.models import Engagement, EngagementTeam
from tests.factories import login_as
from tests.litigation.conftest import HIRING_CASE


def _case(client, db, lit) -> str:
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/litigation", json=HIRING_CASE)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _abc(out: dict) -> dict:
    return next(m for m in out["matches"] if m["organization_name"] == "ABC Corp")


def test_sales_sees_only_the_client_name_and_system_type(client, db, lit):
    cid = _case(client, db, lit)
    login_as(client, db, lit["sales"])
    m = _abc(client.get(f"/api/v1/litigation/{cid}").json())
    assert m["systems"] == [{"type": "vendor_app", "type_label": "Vendor AI app"}]
    assert "Résumé screening" not in str(m) and "Workday" not in str(m) and "live" not in str(m)
    assert m["restricted"] is True


def test_an_auditor_sees_register_detail_only_for_clients_they_audit(client, db, lit):
    cid = _case(client, db, lit)
    login_as(client, db, lit["aud"])
    assert _abc(client.get(f"/api/v1/litigation/{cid}").json())["systems"] == [{"type": "vendor_app", "type_label": "Vendor AI app"}]
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="AI audit", status="in_progress", stage=3, audit_ref="FSL-AI-AUD-2026-009")
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=lit["abc"].id, engagement_id=e.id, user_id=lit["aud"].id, role="auditor"))
    db.commit()
    m = _abc(client.get(f"/api/v1/litigation/{cid}").json())
    assert [s["name"] for s in m["systems"]] == ["Résumé screening"] and m["restricted"] is False
    nw = next(x for x in client.get(f"/api/v1/litigation/{cid}").json()["matches"] if x["organization_name"] == "Northwind Health")
    assert "name" not in nw["systems"][0]


def test_the_chief_auditor_sees_the_matched_systems(client, db, lit):
    cid = _case(client, db, lit)
    m = _abc(client.get(f"/api/v1/litigation/{cid}").json())
    assert m["systems"][0]["name"] == "Résumé screening" and m["systems"][0]["stage"] == "live" and m["restricted"] is False
