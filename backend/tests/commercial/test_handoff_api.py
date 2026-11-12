"""SM-13 screen API: the checklist, the delivery team and the independence confirmation."""
from app.commercial import handoff
from app.commercial.models import Handoff
from tests.commercial.conftest import STANDARD_LINES, line, proposal_for


def _won(cw, lines=None):
    p, a = proposal_for(cw, lines or STANDARD_LINES())
    h = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    return h


def _url(cw):
    return f"/api/v1/sales/opportunities/{cw.opp.id}/handoff"


def test_sales_officer_and_chief_auditor_see_the_checklist_auditors_do_not(cw, fake_catalog):
    _won(cw)
    for u in (cw.sales, cw.chief):
        cw.as_(u)
        r = cw.client.get(_url(cw))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["client_name"] == "Acme Staffing LLC" and d["year1_value"] == 105500
        assert [i["kind"] for i in d["items"]][:2] == ["client", "order"] and d["accepted_by"]["name"] == "Dana Diaz"
    for u in (cw.auditor, cw.caico):
        cw.as_(u)
        assert cw.client.get(_url(cw)).status_code in (403, 404)


def test_no_handoff_yet_is_not_found(cw):
    cw.as_(cw.sales)
    assert cw.client.get(_url(cw)).status_code == 404


def test_confirm_records_the_account_owner(cw, fake_catalog):
    _won(cw)
    cw.as_(cw.sales)
    r = cw.client.post(_url(cw) + "/confirm", json={"account_owner_id": cw.sales2.id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["team"]["account_owner_name"] == "Sue Seller"


def test_separate_team_lines_need_the_chief_auditor_first(cw, fake_catalog):
    _won(cw, [line("A-02b", 1, 35000), line("X-01", 1, 6000, value=72000)])
    cw.as_(cw.sales)
    r = cw.client.post(_url(cw) + "/confirm", json={})
    assert r.status_code == 409 and "Chief Auditor" in r.json()["detail"]
    assert cw.client.post(_url(cw) + "/independence", json={"separate_team_user_ids": [cw.sales2.id]}).status_code == 403
    cw.as_(cw.chief)
    r = cw.client.post(_url(cw) + "/independence", json={"separate_team_user_ids": [cw.sales2.id], "note": "Officer is Sue"})
    assert r.status_code == 200, r.text
    cw.as_(cw.sales)
    assert cw.client.post(_url(cw) + "/confirm", json={}).status_code == 200
    assert handoff.separate_team_user_ids(cw.db, cw.prospect.id) == {cw.sales2.id}


def test_separate_team_person_already_on_the_audit_team_is_refused(cw, fake_catalog):
    from sqlalchemy import select

    from app.engagements.models import Engagement, EngagementTeam

    h = _won(cw, [line("A-02b", 1, 35000), line("X-01", 1, 6000, value=72000)])
    e = cw.db.scalar(select(Engagement).where(Engagement.client_id == cw.prospect.id))
    cw.db.add(EngagementTeam(organization_id=e.client_id, engagement_id=e.id, user_id=cw.auditor.id, role="auditor"))
    cw.db.commit()
    cw.as_(cw.chief)
    r = cw.client.post(_url(cw) + "/independence", json={"separate_team_user_ids": [cw.auditor.id]})
    assert r.status_code == 409 and "Alex Auditor" in r.json()["detail"]
    assert cw.db.get(Handoff, h.id).independence_confirmed_by is None
